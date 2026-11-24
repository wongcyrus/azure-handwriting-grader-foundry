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
