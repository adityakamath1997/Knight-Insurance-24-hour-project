from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.domain.models import FieldName, OverallStatus, ReviewedField, RuleResult
from app.services.documents import DocumentKind

SourceName = Literal["email", "pdf", "attachments"]
RunStatus = Literal["SUCCEEDED", "MODEL_FAILED", "VALIDATION_FAILED", "SKIPPED"]


class DocumentSummary(BaseModel):
    file_name: str
    kind: DocumentKind
    readable: bool
    detected_type: str | None


class SourceRunSummary(BaseModel):
    source: SourceName
    status: RunStatus
    attempts: int
    error: str | None


class Snapshot(BaseModel):
    created_at: datetime
    trigger: str
    overall_status: OverallStatus
    rules: list[RuleResult]


class Draft(BaseModel):
    body: str = ""
    edited: bool = False
    stale: bool = False


class Message(BaseModel):
    role: Literal["reviewer", "assistant"]
    content: str
    created_at: datetime


class Narrative(BaseModel):
    status: Literal["SUCCEEDED", "FAILED", "NOT_RUN"] = "NOT_RUN"
    error: str | None = None
    summary: str | None = None
    draft: Draft = Draft()
    messages: list[Message] = []


class SubmissionDetail(BaseModel):
    id: str
    created_at: datetime
    documents: list[DocumentSummary]
    source_runs: list[SourceRunSummary]
    fields: dict[FieldName, ReviewedField]
    rules: list[RuleResult]
    overall_status: OverallStatus
    snapshots: list[Snapshot]
    narrative: Narrative = Narrative()
