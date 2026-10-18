"""Structured outputs the agents must return; a rejected answer is sent back to the model to fix."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import Evidence, FieldName, FieldState


class EvidenceItem(Evidence):
    model_config = ConfigDict(extra="forbid")

    source_file: str = Field(description="Exact file name as listed in manifest.txt.")
    locator: str = Field(
        description='Where in the file: "email body", "PDF page N" or '
        '"uploaded attachment inventory".'
    )
    excerpt_or_observation: str = Field(
        description="Verbatim excerpt that states the value, or for inventory "
        "evidence an observation naming the files checked."
    )


class ExtractedField(BaseModel):
    """One value one file states for one field."""

    model_config = ConfigDict(extra="forbid")

    name: FieldName
    # Agents report what a file states; CONFLICT/INVALID are decided in code.
    state: Literal[FieldState.KNOWN, FieldState.MISSING] = Field(
        description="KNOWN when the file states a value; MISSING when the file "
        'explicitly says it is not provided (e.g. "Not provided", "N/A", "TBD").'
    )
    raw_value: str | None = Field(
        description="KNOWN: the value text copied verbatim, never converted or "
        "normalized. MISSING: null."
    )
    evidence: list[EvidenceItem] = Field(min_length=1)

    @model_validator(mode="after")
    def _value_matches_state(self) -> Self:
        if self.state == FieldState.KNOWN and not (self.raw_value or "").strip():
            raise ValueError("KNOWN requires a raw_value")
        if self.state == FieldState.MISSING and self.raw_value is not None:
            raise ValueError("MISSING must have raw_value null")
        return self


class DetectedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_name: str = Field(description="Exact file name as listed in manifest.txt.")
    document_type: Literal["application", "loss_runs", "vehicle_schedule", "other"] = (
        Field(
            description="application: commercial auto application form. loss_runs: "
            "a loss runs or loss history report, including one reporting zero losses. "
            "vehicle_schedule: a vehicle list. other: anything else."
        )
    )


class SourceExtractionResult(BaseModel):
    """Final answer. Call once, after reading the files your instructions require."""

    model_config = ConfigDict(extra="forbid")

    fields: list[ExtractedField] = Field(
        description="One entry per value a file states; omit fields no file mentions."
    )
    documents: list[DetectedDocument] = Field(
        default=[],
        description="Document type of each file you read (attachments source only).",
    )


class NarrativeOutput(BaseModel):
    """Final answer. Call once, after reading the review report."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(
        description="Concise underwriter summary: the applicant, each rule's status "
        "with the values and evidence behind it, conflicts and human overrides."
    )
    draft_email: str = Field(
        description="Editable draft to the broker requesting every entry in "
        "items_to_request. Never sent."
    )
    reply: str = Field(
        default="", description="Answer to the reviewer's latest message, if any."
    )
