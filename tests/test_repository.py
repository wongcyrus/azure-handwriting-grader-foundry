import hashlib
import sqlite3
from uuid import uuid4

import pytest
from conftest import TEACHER

from handwriting_grader_cloud.errors import ApplicationError
from handwriting_grader_cloud.models import CreateExam, ExamSettings


def test_compare_and_swap_conflict_rolls_back_artifact(service):
    document = service.create(
        TEACHER, CreateExam(title="Synthetic", settings=ExamSettings(pages_per_student=2))
    )
    stale = service.repository.get(document["id"])
    changed = service.repository.get(document["id"])
    changed["version"] = 2
    service.repository.save(changed, 1)
    stale["version"] = 2
    artifact = str(uuid4())
    with pytest.raises(ApplicationError):
        service.repository.save(stale, 1, (artifact, b"synthetic"))
    with pytest.raises(ApplicationError):
        service.repository.content(document["id"], artifact)
    assert service.repository.get(document["id"]) == changed


def test_multi_artifact_failure_rolls_back_manifest_and_all_images(service):
    document = service.create(
        TEACHER, CreateExam(title="Synthetic", settings=ExamSettings(pages_per_student=2))
    )
    changed = {**document, "version": 2, "regions": {"prepared": True}}
    artifact_id = str(uuid4())
    with pytest.raises(sqlite3.IntegrityError):
        service.repository.save(
            changed, 1, artifacts=[(artifact_id, b"first"), (artifact_id, b"duplicate")]
        )
    assert service.repository.get(document["id"]) == document
    with pytest.raises(ApplicationError):
        service.repository.content(document["id"], artifact_id)


@pytest.mark.parametrize("kind", ["missing", "corrupt"])
def test_checkpoint_failure_rolls_back_all_new_artifacts(service, kind):
    document = service.create(
        TEACHER, CreateExam(title="Synthetic", settings=ExamSettings(pages_per_student=2))
    )
    artifact_id = str(uuid4())
    manifest = {
        "files": {
            "synthetic.json": {
                "artifact_id": artifact_id if kind == "corrupt" else str(uuid4()),
                "size": 9,
                "sha256": hashlib.sha256(b"synthetic").hexdigest(),
            }
        }
    }
    checkpoint_id = str(uuid4())
    with pytest.raises(ApplicationError):
        service.repository.save_checkpoint(
            document["id"], 1, checkpoint_id, manifest, [(artifact_id, b"wrong")]
        )
    with pytest.raises(ApplicationError):
        service.repository.checkpoint(document["id"], checkpoint_id)
    with pytest.raises(ApplicationError):
        service.repository.content(document["id"], artifact_id)


def test_existing_checkpoint_cannot_be_replaced(service):
    document = service.create(
        TEACHER, CreateExam(title="Synthetic", settings=ExamSettings(pages_per_student=2))
    )
    checkpoint_id = str(uuid4())
    manifest = {"files": {}}
    digest = service.repository.save_checkpoint(document["id"], 1, checkpoint_id, manifest, [])
    artifact_id = str(uuid4())
    with pytest.raises(sqlite3.IntegrityError):
        service.repository.save_checkpoint(
            document["id"], 1, checkpoint_id, manifest, [(artifact_id, b"synthetic")]
        )
    assert service.repository.checkpoint(document["id"], checkpoint_id) == (manifest, digest)
    with pytest.raises(ApplicationError):
        service.repository.content(document["id"], artifact_id)
