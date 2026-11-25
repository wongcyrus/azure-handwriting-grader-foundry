import hashlib
import json
import os
import shutil
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from .auth import Principal
from .errors import ApplicationError
from .preflight import ENGINE_COMMIT, EngineInputValidator, engine_functions
from .region_review import validate_regions
from .service import ExamService, snapshot

INPUT_PATHS = {
    "scans": "inputs/scans.pdf",
    "roster": "inputs/roster.xlsx",
    "rubric": "inputs/rubric.xlsx",
    "attendance": "inputs/attendance.csv",
}
REVIEW_WORKSPACE = "offline_review_workspace"
ENGINE_INPUT_WORKSPACE = "offline_engine_input_workspace"


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def integrity_error() -> ApplicationError:
    return ApplicationError(
        "WORKSPACE_INTEGRITY", "The workspace does not match current approved inputs.", 409
    )


@dataclass(frozen=True)
class Workspace:
    path: Path
    checkpoint_id: str
    manifest_sha256: str


class WorkspaceBridge:
    """Owner-scoped offline input workspaces; never model config or job authority."""

    def __init__(self, service: ExamService, root: Path):
        self.service = service
        self.root = root.absolute()

    def _attestation(self, document: dict, pointer: str, kind: str) -> dict:
        matches = [item for item in document["approvals"] if item["id"] == document.get(pointer)]
        if len(matches) != 1 or matches[0]["kind"] != kind:
            raise ApplicationError("APPROVAL_REQUIRED", "Current review approval is required.", 409)
        approval = matches[0]
        if (
            approval["actor_id"] != document["owner_id"]
            or approval["tenant_id"] != document["tenant_id"]
            or approval["snapshot_sha256"] != snapshot(document)
            or approval["preflight_engine_commit"] != ENGINE_COMMIT
            or not approval["at"]
        ):
            raise integrity_error()
        return approval

    def _source(
        self, principal: Principal, exam_id: str, expected: int
    ) -> tuple[dict, dict[str, bytes], dict[str, str], dict]:
        document = self.service.current(principal, exam_id, expected)
        if document["state"] != "REGIONS_REVIEWED":
            raise ApplicationError(
                "APPROVAL_REQUIRED", "Approve inputs and regions before workspace hydration.", 409
            )
        document = self.service.region_document(principal, exam_id, expected)
        try:
            if (
                document["snapshot_sha256"] != snapshot(document)
                or not {"scans", "roster", "rubric"}.issubset(document["artifacts"])
                or not set(document["artifacts"]).issubset(INPUT_PATHS)
                or document["settings"]["scan_order_confirmed"] is not True
                or document["settings"]["same_layout_for_all"] is not True
            ):
                raise integrity_error()
            inputs = self._attestation(document, "current_approval", "input_review_attestation")
            regions = self._attestation(
                document, "current_region_approval", "regions_review_attestation"
            )
            if (
                inputs["input_revision"] != document["input_revision"]
                or inputs["preflight_policy_version"] != 2
                or regions["region_policy_version"] != 1
                or regions["regions_sha256"] != document["regions"]["review_sha256"]
                or regions["reviewed_regions"] != document["regions"]
            ):
                raise integrity_error()
            approvals = {"inputs": inputs, "regions": regions}
            if "attendance" in document["artifacts"]:
                attendance = self._attestation(
                    document, "current_attendance_approval", "attendance_review_attestation"
                )
                if (
                    attendance["input_revision"] != document["input_revision"]
                    or attendance["preflight_policy_version"] != 2
                    or attendance["attendance_sha256"]
                    != document["artifacts"]["attendance"]["sha256"]
                    or attendance["roster_sha256"] != document["artifacts"]["roster"]["sha256"]
                ):
                    raise integrity_error()
                approvals["attendance"] = attendance
            elif document["current_attendance_approval"] is not None:
                raise integrity_error()
            contents = self.service.input_contents(document)
            validated = EngineInputValidator().validate(document, contents)
            preflight = document["preflight"]
            if preflight["snapshot_sha256"] != snapshot(document) or any(
                preflight.get(key) != value for key, value in validated.items()
            ):
                raise integrity_error()
            validate_regions(document["regions"], complete=True)
            binding = {
                "exam_id": exam_id,
                "tenant_id": document["tenant_id"],
                "owner_id": document["owner_id"],
                "exam_version": expected,
                "snapshot_sha256": snapshot(document),
                "regions_sha256": document["regions"]["review_sha256"],
                "approval_ids": {key: value["id"] for key, value in approvals.items()},
            }
            files, references = self._files(document, contents, approvals, binding)
        except (KeyError, TypeError, ValueError) as error:
            raise integrity_error() from error
        return binding, files, references, document

    def _files(self, document, contents, approvals, binding):
        engine_functions()
        from handwriting_grader.regions import config_hash

        config = {
            "exam": {
                "name": document["title"],
                "scanned_pdf": INPUT_PATHS["scans"],
                "roster": INPUT_PATHS["roster"],
                "roster_sheet": document["settings"]["roster_sheet"],
                "marking_scheme": INPUT_PATHS["rubric"],
                "output_dir": "output",
            },
            "layout": {
                "pages_per_student": document["settings"]["pages_per_student"],
                "same_layout_for_all": True,
            },
        }
        if "attendance" in contents:
            config["exam"]["attendance"] = INPUT_PATHS["attendance"]
        regions = document["regions"]
        files = {INPUT_PATHS[kind]: content for kind, content in contents.items()}
        references = {
            INPUT_PATHS[kind]: artifact["id"] for kind, artifact in document["artifacts"].items()
        }
        files["exam.config.json"] = json_bytes(config)
        files["review-context.json"] = json_bytes({"binding": binding, "approvals": approvals})
        files["output/regions/manifest.json"] = json_bytes(
            {
                "version": 1,
                "config_sha256": config_hash(config),
                "pdf_sha256": regions["source_pdf_sha256"],
                "pages": [
                    {key: page[key] for key in ("width", "height", "sha256")}
                    for page in regions["pages"]
                ],
            }
        )
        files["output/regions/draft.json"] = json_bytes(
            {
                "revision": regions["revision"],
                "annotations": regions["annotations"],
                "reviewed": regions["reviewed_pages"],
            }
        )
        files["output/regions/annotations.json"] = json_bytes(regions["annotations"])
        for index, page in enumerate(regions["pages"]):
            path = f"output/regions/images/{index}.jpg"
            files[path] = self.service.repository.content(document["id"], page["artifact_id"])
            if hashlib.sha256(files[path]).hexdigest() != page["sha256"]:
                raise integrity_error()
            references[path] = page["artifact_id"]
        return files, references

    @staticmethod
    def _engine_files(document: dict, base_files: dict[str, bytes]) -> dict[str, bytes]:
        engine_functions()
        from handwriting_grader.regions import config_hash

        files = dict(base_files)
        config = json.loads(files["exam.config.json"])
        context = json.loads(files["review-context.json"])
        approvals = context["approvals"]
        try:
            for approval in approvals.values():
                UUID(approval["id"])
                if datetime.fromisoformat(approval["at"]).tzinfo is None:
                    raise integrity_error()
            config_digest = config_hash(config)
            rubric_digest = hashlib.sha256(files[INPUT_PATHS["rubric"]]).hexdigest()
            files["output/rubric/rubric.xlsx"] = files[INPUT_PATHS["rubric"]]
            files["output/rubric/manifest.json"] = json_bytes(
                {
                    "version": 1,
                    "exam_config_sha256": config_digest,
                    "source_sha256": rubric_digest,
                    "origin": "xlsx",
                }
            )
            files["output/rubric/approval.json"] = json_bytes(
                {
                    "version": 1,
                    "rubric_sha256": rubric_digest,
                    "exam_config_sha256": config_digest,
                    "source_sha256": rubric_digest,
                    "approved_at": approvals["inputs"]["at"],
                }
            )
            region_manifest = json.loads(files["output/regions/manifest.json"])
            region_draft = json.loads(files["output/regions/draft.json"])
            files["output/regions/approval.json"] = json_bytes(
                {
                    "annotations_sha256": hashlib.sha256(
                        files["output/regions/annotations.json"]
                    ).hexdigest(),
                    "config_sha256": config_digest,
                    "pdf_sha256": region_manifest["pdf_sha256"],
                    "revision": region_draft["revision"],
                    "approved_at": approvals["regions"]["at"],
                }
            )
            mapped = {
                "rubric": ("inputs", "output/rubric/approval.json"),
                "regions": ("regions", "output/regions/approval.json"),
            }
            if "attendance" in approvals:
                review_id = UUID(approvals["attendance"]["id"]).hex
                root = f"output/attendance/versions/{review_id}"
                review = {
                    "version": 1,
                    "config_sha256": config_digest,
                    "attendance_sha256": hashlib.sha256(
                        files[INPUT_PATHS["attendance"]]
                    ).hexdigest(),
                    "roster_sha256": hashlib.sha256(files[INPUT_PATHS["roster"]]).hexdigest(),
                    "students": document["preflight"]["attendance_review"],
                }
                files[f"{root}/review.json"] = json_bytes(review)
                files["output/attendance/current.json"] = json_bytes(
                    {"version": 1, "review_id": review_id}
                )
                files[f"{root}/approval.json"] = json_bytes(
                    {
                        "version": 1,
                        "review_sha256": hashlib.sha256(files[f"{root}/review.json"]).hexdigest(),
                        "review_id": review_id,
                    }
                )
                mapped["attendance"] = ("attendance", f"{root}/approval.json")
            files["engine-input-context.json"] = json_bytes(
                {
                    "version": 1,
                    "engine_commit": ENGINE_COMMIT,
                    "scope": "offline_approved_inputs_only",
                    "binding": context["binding"],
                    "mapped_approvals": {
                        kind: {
                            "api_approval_id": approvals[source]["id"],
                            "actor_id": approvals[source]["actor_id"],
                            "tenant_id": approvals[source]["tenant_id"],
                            "approved_at": approvals[source]["at"],
                            "path": path,
                            "sha256": hashlib.sha256(files[path]).hexdigest(),
                        }
                        for kind, (source, path) in mapped.items()
                    },
                }
            )
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise integrity_error() from error
        return files

    def _write(self, files: dict[str, bytes], *, engine_inputs: bool = False) -> Path:
        if any(path.is_symlink() for path in (self.root, *self.root.parents)):
            raise ApplicationError("UNSAFE_WORKSPACE", "Use a private non-symlink workspace root.")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        mode = self.root.stat().st_mode
        if not stat.S_ISDIR(mode) or stat.S_IMODE(mode) & 0o077:
            raise ApplicationError("UNSAFE_WORKSPACE", "The workspace root must be private.")
        target = self.root / str(uuid4())
        target.mkdir(mode=0o700)
        try:
            for name, content in files.items():
                path = target / name
                path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with path.open("xb") as file:
                    path.chmod(0o600)
                    file.write(content)
                    file.flush()
                    os.fsync(file.fileno())
            self._verify_engine(target, engine_inputs=engine_inputs)
        except BaseException:
            shutil.rmtree(target)
            raise
        return target

    @staticmethod
    def _verify_engine(target: Path, *, engine_inputs: bool = False) -> None:
        engine_functions()
        from handwriting_grader.regions import verify_run

        config_path = target / "exam.config.json"
        config = json.loads(config_path.read_bytes())
        try:
            verify_run(config, target, config_path)
            if engine_inputs:
                from handwriting_grader.grading import approved_inputs

                approved_inputs(config, target, config_path)
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise integrity_error() from error

    def hydrate(self, principal: Principal, exam_id: str, expected: int) -> Workspace:
        binding, files, references, _ = self._source(principal, exam_id, expected)
        return self._publish(exam_id, expected, binding, files, references, REVIEW_WORKSPACE)

    def prepare_engine_inputs(self, principal: Principal, exam_id: str, expected: int) -> Workspace:
        binding, files, references, document = self._source(principal, exam_id, expected)
        files = self._engine_files(document, files)
        references["output/rubric/rubric.xlsx"] = references[INPUT_PATHS["rubric"]]
        return self._publish(exam_id, expected, binding, files, references, ENGINE_INPUT_WORKSPACE)

    def _publish(self, exam_id, expected, binding, files, references, kind) -> Workspace:
        checkpoint_id = str(uuid4())
        metadata, artifacts = {}, []
        for name, content in files.items():
            artifact_id = references.get(name) or str(uuid4())
            metadata[name] = {
                "artifact_id": artifact_id,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
            }
            if name not in references:
                artifacts.append((artifact_id, content))
        manifest = {
            "version": 1,
            "kind": kind,
            "engine_commit": ENGINE_COMMIT,
            "binding": binding,
            "files": metadata,
        }
        target = self._write(files, engine_inputs=kind == ENGINE_INPUT_WORKSPACE)
        try:
            digest = self.service.repository.save_checkpoint(
                exam_id, expected, checkpoint_id, manifest, artifacts
            )
        except BaseException:
            shutil.rmtree(target)
            raise
        return Workspace(target, checkpoint_id, digest)

    def _load_checkpoint(
        self, principal: Principal, exam_id: str, expected: int, checkpoint_id: str
    ) -> tuple[dict, str, dict[str, bytes], bool]:
        binding, expected_files, _, document = self._source(principal, exam_id, expected)
        manifest, digest = self.service.repository.checkpoint(exam_id, checkpoint_id)
        try:
            if (
                set(manifest) != {"version", "kind", "engine_commit", "binding", "files"}
                or manifest["version"] != 1
                or manifest["kind"] not in {REVIEW_WORKSPACE, ENGINE_INPUT_WORKSPACE}
                or manifest["engine_commit"] != ENGINE_COMMIT
                or manifest["binding"] != binding
            ):
                raise integrity_error()
            engine_inputs = manifest["kind"] == ENGINE_INPUT_WORKSPACE
            if engine_inputs:
                expected_files = self._engine_files(document, expected_files)
            if set(manifest["files"]) != set(expected_files):
                raise integrity_error()
            files = {}
            for name, expected_content in expected_files.items():
                reference = manifest["files"][name]
                if (
                    set(reference) != {"artifact_id", "sha256", "size"}
                    or type(reference["size"]) is not int
                    or reference["size"] != len(expected_content)
                    or reference["sha256"] != hashlib.sha256(expected_content).hexdigest()
                ):
                    raise integrity_error()
                content = self.service.repository.content(exam_id, reference["artifact_id"])
                if content != expected_content:
                    raise integrity_error()
                files[name] = content
        except (KeyError, ValueError, TypeError) as error:
            raise integrity_error() from error
        return manifest, digest, files, engine_inputs

    def validated_checkpoint(
        self, principal: Principal, exam_id: str, expected: int, checkpoint_id: str
    ) -> tuple[dict, str]:
        manifest, digest, _, _ = self._load_checkpoint(principal, exam_id, expected, checkpoint_id)
        self.service.repository.assert_version(exam_id, expected)
        return manifest, digest

    def restore(
        self, principal: Principal, exam_id: str, expected: int, checkpoint_id: str
    ) -> Workspace:
        _, digest, files, engine_inputs = self._load_checkpoint(
            principal, exam_id, expected, checkpoint_id
        )
        target = self._write(files, engine_inputs=engine_inputs)
        try:
            self.service.repository.assert_version(exam_id, expected)
        except BaseException:
            shutil.rmtree(target)
            raise
        return Workspace(target, checkpoint_id, digest)
