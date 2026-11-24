import hashlib
import json
import shutil
import stat
from copy import deepcopy

import pytest
from conftest import ADMIN, OTHER_TEACHER, OTHER_TENANT, TEACHER, WORKER
from test_attendance import approve as approve_inputs
from test_attendance import attendance_files
from test_engine_preflight import send_for_review, synthetic_files
from test_region_review import approve as approve_regions
from test_region_review import prepare, save_draft

from handwriting_grader_cloud.errors import ApplicationError
from handwriting_grader_cloud.repository import SQLiteRepository
from handwriting_grader_cloud.service import ExamService
from handwriting_grader_cloud.workspace import WorkspaceBridge

pytestmark = pytest.mark.engine


def approved_review(client, attendance=False):
    files = attendance_files() if attendance else synthetic_files()
    _, _, response = send_for_review(client, files)
    assert response.status_code == 200, response.text
    response = approve_inputs(client, response, attendance_confirmed=attendance)
    assert response.status_code == 200, response.text
    response = prepare(client, response)
    assert response.status_code == 200, response.text
    response = save_draft(client, response)
    assert response.status_code == 200, response.text
    response = approve_regions(client, response)
    assert response.status_code == 200, response.text
    return response


@pytest.fixture
def reviewed(client):
    return approved_review(client)


def file_bytes(path):
    return {
        str(file.relative_to(path)): file.read_bytes() for file in path.rglob("*") if file.is_file()
    }


@pytest.mark.parametrize("attendance", [False, True])
def test_approved_workspace_survives_replacement_without_invented_approvals(
    client, service, tmp_path, attendance
):
    from handwriting_grader.cli import check_exam
    from handwriting_grader.regions import approval_is_current, verify_run

    document = approved_review(client, attendance).json()
    bridge = WorkspaceBridge(service, tmp_path / "first-worker")
    first = bridge.hydrate(TEACHER, document["id"], document["version"])
    original = file_bytes(first.path)
    manifest, digest = service.repository.checkpoint(document["id"], first.checkpoint_id)
    assert digest == first.manifest_sha256
    for kind, artifact in document["artifacts"].items():
        path = next(name for name in original if name.startswith(f"inputs/{kind}."))
        assert manifest["files"][path]["artifact_id"] == artifact["id"]
    for index, page in enumerate(document["regions"]["pages"]):
        assert (
            manifest["files"][f"output/regions/images/{index}.jpg"]["artifact_id"]
            == page["artifact_id"]
        )
    shutil.rmtree(first.path)
    replacement = WorkspaceBridge(
        ExamService(SQLiteRepository(service.repository.path)), tmp_path / "replacement-worker"
    )
    restored = replacement.restore(
        TEACHER, document["id"], document["version"], first.checkpoint_id
    )
    assert restored.path != first.path
    assert restored.manifest_sha256 == first.manifest_sha256
    assert file_bytes(restored.path) == original
    config_path = restored.path / "exam.config.json"
    config = json.loads(config_path.read_bytes())
    root, engine_manifest = verify_run(config, restored.path, config_path)
    draft = json.loads((root / "draft.json").read_bytes())
    assert draft["annotations"] == document["regions"]["annotations"]
    issues, summary = check_exam(config, restored.path)
    assert not issues
    assert summary["students"] == (1 if attendance else 2)
    assert summary["absent"] == (1 if attendance else 0)
    assert not approval_is_current(root, engine_manifest, draft)
    assert not list(restored.path.rglob("approval.json"))
    assert "models" not in config and "azure_openai" not in config
    assert service.repository.get(document["id"]) == document
    assert stat.S_IMODE(restored.path.stat().st_mode) == 0o700
    assert all(
        stat.S_IMODE(file.stat().st_mode) == 0o600
        for file in restored.path.rglob("*")
        if file.is_file()
    )


@pytest.mark.parametrize(
    "principal,status",
    [(OTHER_TEACHER, 404), (OTHER_TENANT, 404), (WORKER, 403), (ADMIN, 403)],
)
def test_workspace_hydration_and_recovery_are_owner_scoped(
    service, reviewed, tmp_path, principal, status
):
    document = reviewed.json()
    bridge = WorkspaceBridge(service, tmp_path / "workspaces")
    checkpoint = bridge.hydrate(TEACHER, document["id"], document["version"])
    paths = set(bridge.root.iterdir())
    for operation in (
        lambda: bridge.hydrate(principal, document["id"], document["version"]),
        lambda: bridge.restore(
            principal, document["id"], document["version"], checkpoint.checkpoint_id
        ),
    ):
        with pytest.raises(ApplicationError) as error:
            operation()
        assert error.value.status == status
    assert set(bridge.root.iterdir()) == paths


@pytest.mark.parametrize(
    "change",
    [
        "missing_input",
        "missing_region",
        "wrong_actor",
        "wrong_pin",
        "changed_geometry",
        "duplicate",
    ],
)
def test_hydration_rejects_missing_or_incompatible_attestations(
    service, reviewed, tmp_path, change
):
    document = reviewed.json()
    if change == "missing_input":
        document["current_approval"] = None
    elif change == "missing_region":
        document["current_region_approval"] = None
    elif change == "wrong_actor":
        document["approvals"][0]["actor_id"] = "teacher-b"
    elif change == "wrong_pin":
        document["approvals"][0]["preflight_engine_commit"] = "0" * 40
    elif change == "changed_geometry":
        document["approvals"][-1]["reviewed_regions"]["annotations"]["0"][0]["x"] = 1
    else:
        document["approvals"].append(deepcopy(document["approvals"][0]))
    service.repository.save(document, document["version"])
    bridge = WorkspaceBridge(service, tmp_path / "workspaces")
    with pytest.raises(ApplicationError) as error:
        bridge.hydrate(TEACHER, document["id"], document["version"])
    assert error.value.status == 409
    assert not bridge.root.exists()


def test_explicit_attendance_needs_its_separate_current_attestation(client, service, tmp_path):
    document = approved_review(client, attendance=True).json()
    document["current_attendance_approval"] = None
    service.repository.save(document, document["version"])
    with pytest.raises(ApplicationError) as error:
        WorkspaceBridge(service, tmp_path / "workspaces").hydrate(
            TEACHER, document["id"], document["version"]
        )
    assert error.value.code == "APPROVAL_REQUIRED"


def test_changed_inputs_and_reapproved_geometry_cannot_restore_old_checkpoint(
    client, service, reviewed, tmp_path
):
    document = reviewed.json()
    bridge = WorkspaceBridge(service, tmp_path / "workspaces")
    checkpoint = bridge.hydrate(TEACHER, document["id"], document["version"])
    changed = approve_regions(client, save_draft(client, reviewed))
    assert changed.status_code == 200, changed.text
    current = changed.json()
    with pytest.raises(ApplicationError) as error:
        bridge.restore(TEACHER, document["id"], current["version"], checkpoint.checkpoint_id)
    assert error.value.code == "WORKSPACE_INTEGRITY"
    with pytest.raises(ApplicationError) as error:
        bridge.restore(TEACHER, document["id"], document["version"], checkpoint.checkpoint_id)
    assert error.value.code == "STALE_REVIEW"
    current = service.settings(TEACHER, current["id"], current["version"], current["settings"])
    with pytest.raises(ApplicationError) as error:
        bridge.restore(TEACHER, document["id"], current["version"], checkpoint.checkpoint_id)
    assert error.value.code == "APPROVAL_REQUIRED"
    assert len(list(bridge.root.iterdir())) == 1


@pytest.mark.parametrize("kind", ["input", "image", "config"])
def test_corrupt_input_image_or_checkpoint_file_cannot_be_restored(
    service, reviewed, tmp_path, kind
):
    document = reviewed.json()
    bridge = WorkspaceBridge(service, tmp_path / "workspaces")
    checkpoint = bridge.hydrate(TEACHER, document["id"], document["version"])
    manifest, _ = service.repository.checkpoint(document["id"], checkpoint.checkpoint_id)
    artifact_id = {
        "input": document["artifacts"]["scans"]["id"],
        "image": document["regions"]["pages"][0]["artifact_id"],
        "config": manifest["files"]["exam.config.json"]["artifact_id"],
    }[kind]
    with service.repository.connection() as connection:
        connection.execute("UPDATE artifacts SET content=? WHERE id=?", (b"corrupt", artifact_id))
    with pytest.raises(ApplicationError) as error:
        bridge.restore(TEACHER, document["id"], document["version"], checkpoint.checkpoint_id)
    assert error.value.status == 409
    assert len(list(bridge.root.iterdir())) == 1


@pytest.mark.parametrize("change", ["path", "owner", "pin", "hash"])
def test_corrupt_checkpoint_metadata_is_rejected_before_filesystem_writes(
    service, reviewed, tmp_path, change
):
    document = reviewed.json()
    bridge = WorkspaceBridge(service, tmp_path / "workspaces")
    checkpoint = bridge.hydrate(TEACHER, document["id"], document["version"])
    manifest, digest = service.repository.checkpoint(document["id"], checkpoint.checkpoint_id)
    if change == "path":
        manifest["files"]["../outside"] = manifest["files"].pop("exam.config.json")
    elif change == "owner":
        manifest["binding"]["owner_id"] = "teacher-b"
    elif change == "pin":
        manifest["engine_commit"] = "0" * 40
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    if change != "hash":
        digest = hashlib.sha256(encoded.encode()).hexdigest()
    else:
        digest = "0" * 64
    with service.repository.connection() as connection:
        connection.execute(
            "UPDATE workspace_checkpoints SET manifest=?, manifest_sha256=? WHERE id=?",
            (encoded, digest, checkpoint.checkpoint_id),
        )
    with pytest.raises(ApplicationError) as error:
        bridge.restore(TEACHER, document["id"], document["version"], checkpoint.checkpoint_id)
    assert error.value.code == "WORKSPACE_INTEGRITY"
    assert not (bridge.root / "outside").exists()
    assert len(list(bridge.root.iterdir())) == 1


def test_checkpoint_cannot_be_replayed_against_another_owned_exam(
    client, service, reviewed, tmp_path
):
    document = reviewed.json()
    bridge = WorkspaceBridge(service, tmp_path / "workspaces")
    checkpoint = bridge.hydrate(TEACHER, document["id"], document["version"])
    other = approved_review(client).json()
    with pytest.raises(ApplicationError) as error:
        bridge.restore(TEACHER, other["id"], other["version"], checkpoint.checkpoint_id)
    assert error.value.status == 404
    assert len(list(bridge.root.iterdir())) == 1


def test_hydration_race_publishes_neither_checkpoint_nor_partial_workspace(
    service, reviewed, tmp_path, monkeypatch
):
    document = reviewed.json()
    original = service.repository.save_checkpoint

    def changed_before_publish(*args, **kwargs):
        service.settings(TEACHER, document["id"], document["version"], document["settings"])
        return original(*args, **kwargs)

    monkeypatch.setattr(service.repository, "save_checkpoint", changed_before_publish)
    bridge = WorkspaceBridge(service, tmp_path / "workspaces")
    with service.repository.connection() as connection:
        count = connection.execute("SELECT count(*) FROM artifacts").fetchone()[0]
    with pytest.raises(ApplicationError) as error:
        bridge.hydrate(TEACHER, document["id"], document["version"])
    assert error.value.code == "STALE_REVIEW"
    assert not list(bridge.root.iterdir())
    with service.repository.connection() as connection:
        assert connection.execute("SELECT count(*) FROM workspace_checkpoints").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM artifacts").fetchone()[0] == count


def test_restore_race_removes_only_the_new_workspace(service, reviewed, tmp_path, monkeypatch):
    document = reviewed.json()
    bridge = WorkspaceBridge(service, tmp_path / "workspaces")
    checkpoint = bridge.hydrate(TEACHER, document["id"], document["version"])
    original_files = file_bytes(checkpoint.path)
    original = service.repository.assert_version

    def changed_before_return(*args, **kwargs):
        service.settings(TEACHER, document["id"], document["version"], document["settings"])
        return original(*args, **kwargs)

    monkeypatch.setattr(service.repository, "assert_version", changed_before_return)
    with pytest.raises(ApplicationError) as error:
        bridge.restore(TEACHER, document["id"], document["version"], checkpoint.checkpoint_id)
    assert error.value.code == "STALE_REVIEW"
    assert list(bridge.root.iterdir()) == [checkpoint.path]
    assert file_bytes(checkpoint.path) == original_files


@pytest.mark.parametrize("kind", ["shared", "symlink"])
def test_workspace_root_must_be_private_and_not_a_symlink(service, reviewed, tmp_path, kind):
    root = tmp_path / "workspaces"
    if kind == "shared":
        root.mkdir(mode=0o755)
        root.chmod(0o755)
    else:
        target = tmp_path / "other-directory"
        target.mkdir(mode=0o700)
        root.symlink_to(target, target_is_directory=True)
    document = reviewed.json()
    with pytest.raises(ApplicationError) as error:
        WorkspaceBridge(service, root).hydrate(TEACHER, document["id"], document["version"])
    assert error.value.code == "UNSAFE_WORKSPACE"
    assert not list(root.iterdir())
