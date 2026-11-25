import hashlib
import json
import shutil
from datetime import datetime
from uuid import UUID

import pytest
from conftest import ADMIN, OTHER_TEACHER, OTHER_TENANT, TEACHER, WORKER
from test_workspace import approved_review, file_bytes

from handwriting_grader_cloud.errors import ApplicationError
from handwriting_grader_cloud.repository import SQLiteRepository
from handwriting_grader_cloud.service import ExamService
from handwriting_grader_cloud.workspace import WorkspaceBridge, json_bytes

pytestmark = pytest.mark.engine


@pytest.fixture(autouse=True)
def forbid_engine_approval_actions(monkeypatch):
    from handwriting_grader import attendance, grading, regions, rubric

    def forbidden(*_args, **_kwargs):
        pytest.fail("Mapping must preserve API approvals, not approve or grade through the engine.")

    for module, name in (
        (attendance, "approve_attendance"),
        (regions, "approve_regions"),
        (rubric, "approve_rubric"),
        (grading, "grade_exam"),
    ):
        monkeypatch.setattr(module, name, forbidden)


@pytest.mark.parametrize("attendance", [False, True])
def test_explicit_engine_input_mapping_preserves_api_authority_and_recovery(
    client, service, tmp_path, attendance
):
    from handwriting_grader.attendance import approved_attendance, present_roster
    from handwriting_grader.grading import approved_inputs

    document = approved_review(client, attendance).json()
    bridge = WorkspaceBridge(service, tmp_path / "first-process")
    review = bridge.hydrate(TEACHER, document["id"], document["version"])
    review_files = file_bytes(review.path)
    prepared = bridge.prepare_engine_inputs(TEACHER, document["id"], document["version"])
    original = file_bytes(prepared.path)
    config_path = prepared.path / "exam.config.json"
    config = json.loads(config_path.read_bytes())
    questions, _, _, boxes = approved_inputs(config, prepared.path, config_path)
    assert questions == document["preflight"]["rubric_review"]
    assert set(boxes) == {"ID", "NAME", "CLASS", "1"}
    input_approval = next(
        item for item in document["approvals"] if item["id"] == document["current_approval"]
    )
    region_approval = next(
        item for item in document["approvals"] if item["id"] == document["current_region_approval"]
    )
    rubric = json.loads(original["output/rubric/approval.json"])
    regions = json.loads(original["output/regions/approval.json"])
    assert rubric["approved_at"] == input_approval["at"]
    assert regions["approved_at"] == region_approval["at"]
    assert regions["revision"] == document["regions"]["revision"]
    assert original["output/rubric/rubric.xlsx"] == original["inputs/rubric.xlsx"]
    manifest, _ = service.repository.checkpoint(document["id"], prepared.checkpoint_id)
    assert (
        manifest["files"]["output/rubric/rubric.xlsx"]["artifact_id"]
        == document["artifacts"]["rubric"]["id"]
    )
    mapping = json.loads(original["engine-input-context.json"])
    assert mapping["binding"] == json.loads(original["review-context.json"])["binding"]
    assert mapping["mapped_approvals"]["rubric"]["api_approval_id"] == input_approval["id"]
    assert mapping["mapped_approvals"]["regions"]["api_approval_id"] == region_approval["id"]
    for item in mapping["mapped_approvals"].values():
        assert item["actor_id"] == TEACHER.object_id
        assert item["tenant_id"] == TEACHER.tenant_id
        assert item["sha256"] == hashlib.sha256(original[item["path"]]).hexdigest()
    attendance_result = approved_attendance(config, prepared.path, config_path)
    if attendance:
        attestation = next(
            item
            for item in document["approvals"]
            if item["id"] == document["current_attendance_approval"]
        )
        pointer = json.loads(original["output/attendance/current.json"])
        assert pointer["review_id"] == UUID(attestation["id"]).hex
        assert attendance_result[0]["students"] == document["preflight"]["attendance_review"]
        assert set(present_roster(config, prepared.path, config_path)) == {"001"}
        assert mapping["mapped_approvals"]["attendance"]["api_approval_id"] == attestation["id"]
        assert mapping["mapped_approvals"]["attendance"]["approved_at"] == attestation["at"]
    else:
        assert attendance_result is None
        assert set(present_roster(config, prepared.path, config_path)) == {"001", "002"}
        assert "attendance" not in mapping["mapped_approvals"]
        assert not any(name.startswith("output/attendance/") for name in original)
    assert "azure_openai" not in config and "models" not in config
    assert service.repository.get(document["id"]) == document
    assert file_bytes(review.path) == review_files
    shutil.rmtree(prepared.path)
    replacement = WorkspaceBridge(
        ExamService(SQLiteRepository(service.repository.path)), tmp_path / "replacement-process"
    )
    restored = replacement.restore(
        TEACHER, document["id"], document["version"], prepared.checkpoint_id
    )
    assert restored.manifest_sha256 == prepared.manifest_sha256
    assert file_bytes(restored.path) == original
    restored_config = json.loads((restored.path / "exam.config.json").read_bytes())
    approved_inputs(restored_config, restored.path, restored.path / "exam.config.json")
    restored_review = replacement.restore(
        TEACHER, document["id"], document["version"], review.checkpoint_id
    )
    assert file_bytes(restored_review.path) == review_files
    assert not list(restored_review.path.rglob("approval.json"))


@pytest.mark.parametrize(
    "principal,status",
    [(OTHER_TEACHER, 404), (OTHER_TENANT, 404), (WORKER, 403), (ADMIN, 403)],
)
def test_engine_input_mapping_and_recovery_require_the_owner(
    client, service, tmp_path, principal, status
):
    document = approved_review(client).json()
    bridge = WorkspaceBridge(service, tmp_path / "workspaces")
    prepared = bridge.prepare_engine_inputs(TEACHER, document["id"], document["version"])
    for operation in (
        lambda: bridge.prepare_engine_inputs(principal, document["id"], document["version"]),
        lambda: bridge.restore(
            principal, document["id"], document["version"], prepared.checkpoint_id
        ),
    ):
        with pytest.raises(ApplicationError) as error:
            operation()
        assert error.value.status == status
    assert list(bridge.root.iterdir()) == [prepared.path]


@pytest.mark.parametrize(
    "change",
    ["input", "region", "attendance", "naive_time", "invalid_time", "invalid_id"],
)
def test_mapping_cannot_invent_missing_approval_identity_or_time(client, service, tmp_path, change):
    document = approved_review(client, attendance=True).json()
    pointers = {
        "input": "current_approval",
        "region": "current_region_approval",
        "attendance": "current_attendance_approval",
    }
    if change in pointers:
        document[pointers[change]] = None
    elif change == "naive_time":
        document["approvals"][0]["at"] = (
            datetime.fromisoformat(document["approvals"][0]["at"]).replace(tzinfo=None).isoformat()
        )
    elif change == "invalid_time":
        document["approvals"][0]["at"] = "not-an-approval-time"
    else:
        attestation = next(
            item
            for item in document["approvals"]
            if item["id"] == document["current_attendance_approval"]
        )
        attestation["id"] = "../not-an-approval-id"
        document["current_attendance_approval"] = attestation["id"]
    service.repository.save(document, document["version"])
    bridge = WorkspaceBridge(service, tmp_path / "workspaces")
    with pytest.raises(ApplicationError) as error:
        bridge.prepare_engine_inputs(TEACHER, document["id"], document["version"])
    assert error.value.status == 409
    assert not bridge.root.exists()


@pytest.mark.parametrize("kind", ["rubric", "regions", "attendance"])
def test_rehashed_engine_approval_tampering_cannot_replace_api_provenance(
    client, service, tmp_path, kind
):
    document = approved_review(client, attendance=True).json()
    bridge = WorkspaceBridge(service, tmp_path / "workspaces")
    prepared = bridge.prepare_engine_inputs(TEACHER, document["id"], document["version"])
    manifest, _ = service.repository.checkpoint(document["id"], prepared.checkpoint_id)
    mapping = json.loads((prepared.path / "engine-input-context.json").read_bytes())
    reference = manifest["files"][mapping["mapped_approvals"][kind]["path"]]
    content = json.loads(service.repository.content(document["id"], reference["artifact_id"]))
    if kind == "attendance":
        content["review_id"] = "0" * 32
    else:
        content["approved_at"] = "2000-01-01T00:00:00+00:00"
    altered = json_bytes(content)
    reference["sha256"] = hashlib.sha256(altered).hexdigest()
    reference["size"] = len(altered)
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    with service.repository.connection() as connection:
        connection.execute(
            "UPDATE artifacts SET content=? WHERE id=?", (altered, reference["artifact_id"])
        )
        connection.execute(
            "UPDATE workspace_checkpoints SET manifest=?, manifest_sha256=? WHERE id=?",
            (encoded, hashlib.sha256(encoded.encode()).hexdigest(), prepared.checkpoint_id),
        )
    with pytest.raises(ApplicationError) as error:
        bridge.restore(TEACHER, document["id"], document["version"], prepared.checkpoint_id)
    assert error.value.code == "WORKSPACE_INTEGRITY"
    assert list(bridge.root.iterdir()) == [prepared.path]


def test_review_checkpoint_cannot_be_upgraded_by_changing_its_kind(client, service, tmp_path):
    from handwriting_grader_cloud.workspace import ENGINE_INPUT_WORKSPACE

    document = approved_review(client).json()
    bridge = WorkspaceBridge(service, tmp_path / "workspaces")
    review = bridge.hydrate(TEACHER, document["id"], document["version"])
    manifest, _ = service.repository.checkpoint(document["id"], review.checkpoint_id)
    manifest["kind"] = ENGINE_INPUT_WORKSPACE
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    with service.repository.connection() as connection:
        connection.execute(
            "UPDATE workspace_checkpoints SET manifest=?, manifest_sha256=? WHERE id=?",
            (encoded, hashlib.sha256(encoded.encode()).hexdigest(), review.checkpoint_id),
        )
    with pytest.raises(ApplicationError) as error:
        bridge.restore(TEACHER, document["id"], document["version"], review.checkpoint_id)
    assert error.value.code == "WORKSPACE_INTEGRITY"
    assert not list(review.path.rglob("approval.json"))


def test_engine_validators_reject_bad_mapping_before_checkpoint_publication(
    client, service, tmp_path, monkeypatch
):
    document = approved_review(client).json()
    bridge = WorkspaceBridge(service, tmp_path / "workspaces")
    original = bridge._engine_files

    def bad_mapping(document, files):
        mapped = original(document, files)
        approval = json.loads(mapped["output/rubric/approval.json"])
        approval["source_sha256"] = "0" * 64
        mapped["output/rubric/approval.json"] = json_bytes(approval)
        return mapped

    monkeypatch.setattr(bridge, "_engine_files", bad_mapping)
    with pytest.raises(ApplicationError) as error:
        bridge.prepare_engine_inputs(TEACHER, document["id"], document["version"])
    assert error.value.code == "WORKSPACE_INTEGRITY"
    assert not list(bridge.root.iterdir())
    with service.repository.connection() as connection:
        assert connection.execute("SELECT count(*) FROM workspace_checkpoints").fetchone()[0] == 0
