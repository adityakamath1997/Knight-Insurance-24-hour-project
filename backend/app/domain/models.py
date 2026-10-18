from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class FieldName(StrEnum):
    BUSINESS_NAME = "business_name"
    REQUESTED_EFFECTIVE_DATE = "requested_effective_date"
    GARAGING_STATE = "garaging_state"
    OPERATIONS_DESCRIPTION = "operations_description"
    DECLARED_VEHICLE_COUNT = "declared_vehicle_count"
    OPERATING_RADIUS_MILES = "operating_radius_miles"
    HAZARDOUS_MATERIALS = "hazardous_materials"
    LOSS_RUNS_PRESENT = "loss_runs_present"
    SCHEDULE_VEHICLE_COUNT = "schedule_vehicle_count"


class FieldState(StrEnum):
    KNOWN = "KNOWN"
    MISSING = "MISSING"
    CONFLICT = "CONFLICT"
    INVALID = "INVALID"


# Dates are ISO `YYYY-MM-DD` strings, matching the field contract.
FieldValue = str | int | float | bool | None

RuleStatus = Literal["PASS", "FLAG", "UNKNOWN"]
OverallStatus = Literal["READY_FOR_REVIEW", "NEEDS_REVIEW"]


class Evidence(BaseModel):
    source_file: str
    locator: str
    excerpt_or_observation: str


class Candidate(BaseModel):
    source: str
    source_file: str
    raw_value: str | None
    state: FieldState
    value: FieldValue = None
    evidence: list[Evidence] = Field(default_factory=list)


class Override(BaseModel):
    value: FieldValue
    note: str | None = None
    created_at: str
    original_state: FieldState
    original_value: FieldValue


class ReviewedField(BaseModel):
    name: FieldName
    state: FieldState
    value: FieldValue = None
    candidates: list[Candidate] = Field(default_factory=list)
    inspected_sources: list[str] = Field(default_factory=list)
    attachment_inventory: list[str] = Field(default_factory=list)
    override: Override | None = None


class RuleInput(BaseModel):
    state: FieldState
    value: FieldValue
    overridden: bool


class RuleResult(BaseModel):
    id: str
    name: str
    status: RuleStatus
    reason: str
    inputs: dict[str, RuleInput]


class RuleEvaluation(BaseModel):
    rules: list[RuleResult]
    overall_status: OverallStatus
