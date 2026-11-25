from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

ArtifactKind = Literal["scans", "roster", "rubric", "attendance"]


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
    attendance_confirmed: StrictBool = False


class RegionBox(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    x: StrictInt = Field(ge=0)
    y: StrictInt = Field(ge=0)
    width: StrictInt = Field(gt=0)
    height: StrictInt = Field(gt=0)
    label: StrictStr = Field(min_length=1, max_length=64)


class RegionDraft(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    annotations: dict[str, Annotated[list[RegionBox], Field(max_length=500)]] = Field(max_length=20)
    reviewed_pages: list[StrictInt] = Field(max_length=20)


class RegionApproval(StrictModel):
    snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    regions_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: StrictBool


class OfflineValidationRequest(StrictModel):
    checkpoint_id: UUID
    request_id: UUID
    confirmed: StrictBool


class OfflineActionConfirmation(StrictModel):
    confirmed: StrictBool
