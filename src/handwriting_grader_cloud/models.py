from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

ArtifactKind = Literal["scans", "roster", "rubric"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ExamSettings(StrictModel):
    pages_per_student: StrictInt = Field(ge=1, le=20)
    scan_order_confirmed: StrictBool = False
    same_layout_for_all: StrictBool = False
    roster_sheet: str = Field(default="Roster", min_length=1, max_length=31)


class CreateExam(StrictModel):
    title: str = Field(min_length=1, max_length=160)
    settings: ExamSettings


class ReviewApproval(StrictModel):
    snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: StrictBool
