"""Packet processing and override-driven deterministic reevaluation."""

from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

from app.agents.narrative import NarrativeService
from app.domain.models import (
    BUSINESS_FIELDS,
    Candidate,
    Evidence,
    FieldName,
    FieldState,
    Override,
    ReviewedField,
)
from app.domain.normalization import (
    normalize_value,
    reconcile_candidates,
    validate_override,
)
from app.domain.rules import evaluate_rules
from app.persistence.database import DocumentRow, SourceRunRow
from app.persistence.repository import SubmissionRepository
from app.progress import ProgressEvent, ProgressSink, emit
from app.schemas import (
    RunStatus,
    SortField,
    SortOrder,
    SourceName,
    SubmissionDetail,
    SubmissionListItem,
)
from app.services.documents import (
    APPLICATION_FILE_NAME,
    PreparedDocument,
    PreparedPacket,
    UploadInput,
    prepare_submission_documents,
)

SOURCE_FIELDS: dict[SourceName, tuple[FieldName, ...]] = {
    "email": BUSINESS_FIELDS,
    "pdf": BUSINESS_FIELDS,
    "attachments": (FieldName.LOSS_RUNS_PRESENT,),
}


class SourceRun(BaseModel):
    """One extraction source's outcome; candidates carry verbatim raw values."""

    source: SourceName
    status: RunStatus
    attempts: int = 0
    error: str | None = None
    candidates: dict[FieldName, list[Candidate]] = Field(default_factory=dict)
    detected_types: dict[str, str] = Field(default_factory=dict)


class Extractor(Protocol):
    def __call__(
        self, packet: PreparedPacket, progress: ProgressSink | None = None
    ) -> list[SourceRun]: ...


def source_documents(
    packet: PreparedPacket, source: SourceName
) -> list[PreparedDocument]:
    if source == "email":
        return [packet.email] if packet.email else []
    wants_application = source == "pdf"
    return [
        doc
        for doc in packet.attachments
        if (doc.file_name.casefold() == APPLICATION_FILE_NAME) == wants_application
        and (wants_application or doc is not packet.schedule_document)
    ]


def _normalized(field: FieldName, candidate: Candidate) -> Candidate:
    if candidate.raw_value is None:
        return candidate.model_copy(update={"value": None})
    state, value = normalize_value(field, candidate.raw_value)
    return candidate.model_copy(update={"state": state, "value": value})


def _failure(run: SourceRun, documents: list[PreparedDocument]) -> Candidate:
    source_file = ", ".join(doc.file_name for doc in documents)
    return Candidate(
        source=run.source,
        source_file=source_file,
        raw_value=None,
        state=FieldState.INVALID,
        evidence=[
            Evidence(
                source_file=source_file,
                locator=f"{run.source} extraction",
                excerpt_or_observation=f"{run.status} after {run.attempts} attempts: {run.error}",
            )
        ],
    )


def _unreadable(source: SourceName, unreadable: list[PreparedDocument]) -> Candidate:
    source_file = ", ".join(doc.file_name for doc in unreadable)
    return Candidate(
        source=source,
        source_file=source_file,
        raw_value=None,
        state=FieldState.INVALID,
        evidence=[
            Evidence(
                source_file=source_file,
                locator="uploaded attachment inventory",
                excerpt_or_observation=f"Could not be read, so absence cannot be concluded: {source_file}",
            )
        ],
    )


def _no_attachments() -> Candidate:
    # Absence of any attachment is observed directly, so it is a known "No".
    return Candidate(
        source="attachments",
        source_file="attachment inventory",
        raw_value="No",
        state=FieldState.KNOWN,
        value=False,
        evidence=[
            Evidence(
                source_file="attachment inventory",
                locator="uploaded attachment inventory",
                excerpt_or_observation="No attachment besides the application and the vehicle schedule was supplied, so no loss run report is present.",
            )
        ],
    )


def _reconcile(
    packet: PreparedPacket, runs: list[SourceRun]
) -> dict[FieldName, ReviewedField]:
    fields: dict[FieldName, ReviewedField] = {}
    for name in FieldName:
        if name == FieldName.SCHEDULE_VEHICLE_COUNT:
            fields[name] = packet.schedule
            continue
        if name == FieldName.LOSS_RUNS_PRESENT and not source_documents(
            packet, "attachments"
        ):
            fields[name] = reconcile_candidates(name, [_no_attachments()], [])
            continue

        candidates: list[Candidate] = []
        inspected: list[str] = []
        for run in runs:
            if name not in SOURCE_FIELDS[run.source]:
                continue
            # Skipped sources had only unreadable files; they are still inspected.
            documents = source_documents(packet, run.source)
            inspected += [doc.describe() for doc in documents]
            unreadable = [doc for doc in documents if not doc.readable]
            if run.status == "SUCCEEDED":
                candidates += [
                    _normalized(name, c) for c in run.candidates.get(name, [])
                ]
                # An unreadable file may be the loss runs report; only a found one passes.
                found = any(c.value is True for c in candidates)
                if name == FieldName.LOSS_RUNS_PRESENT and unreadable and not found:
                    candidates.append(_unreadable(run.source, unreadable))
            elif run.status == "SKIPPED":
                if unreadable:
                    candidates.append(_unreadable(run.source, unreadable))
            else:
                candidates.append(_failure(run, documents))
        fields[name] = reconcile_candidates(name, candidates, inspected)

    fields[
        FieldName.LOSS_RUNS_PRESENT
    ].attachment_inventory = packet.attachment_inventory
    return fields


class ReviewService:
    def __init__(
        self,
        repository: SubmissionRepository,
        extractor: Extractor,
        narrative: NarrativeService,
    ) -> None:
        self._repository = repository
        self._extractor = extractor
        self._narrative = narrative

    def create_submission(
        self,
        email_text: str | None,
        uploads: list[UploadInput],
        progress: ProgressSink | None = None,
    ) -> SubmissionDetail:
        emit(
            progress,
            ProgressEvent(
                kind="stage_started", stage="prepare", label="Reading the packet"
            ),
        )
        packet = prepare_submission_documents(email_text, uploads)
        count = len(packet.attachments) + (1 if packet.email else 0)
        emit(
            progress,
            ProgressEvent(
                kind="stage_finished",
                stage="prepare",
                label=f"Read {count} document{'' if count == 1 else 's'}",
            ),
        )
        runs = self._extractor(packet, progress)
        submission_id = str(uuid4())
        documents = ([packet.email] if packet.email else []) + packet.attachments
        self._repository.create(
            submission_id,
            [
                DocumentRow(
                    submission_id=submission_id,
                    file_name=doc.file_name,
                    kind=doc.kind,
                    content=doc.content,
                    readable=doc.readable,
                )
                for doc in documents
            ],
        )

        emit(
            progress,
            ProgressEvent(
                kind="stage_started", stage="rules", label="Evaluating rules R1-R5"
            ),
        )
        fields = _reconcile(packet, runs)
        detected = {
            name: kind for run in runs for name, kind in run.detected_types.items()
        }

        self._repository.record_extraction(
            submission_id,
            fields,
            evaluate_rules(fields),
            [
                SourceRunRow(
                    submission_id=submission_id,
                    source=run.source,
                    status=run.status,
                    attempts=run.attempts,
                    error=run.error,
                )
                for run in runs
            ],
            detected,
        )
        detail = self.get_submission(submission_id)
        emit(
            progress,
            ProgressEvent(
                kind="stage_finished",
                stage="rules",
                label="Rules evaluated",
                status=detail.overall_status,
            ),
        )
        emit(
            progress,
            ProgressEvent(
                kind="stage_started",
                stage="narrative",
                label="Drafting summary and email",
            ),
        )
        narrative = self._narrative.generate(submission_id, progress=progress)
        emit(
            progress,
            ProgressEvent(
                kind="stage_finished",
                stage="narrative",
                label="Summary and draft ready"
                if narrative.status == "SUCCEEDED"
                else "Summary and draft failed",
                status=narrative.status,
                detail=narrative.error,
            ),
        )
        return self.get_submission(submission_id)

    def apply_override(
        self, submission_id: str, field_name: FieldName, value: object, note: str | None
    ) -> SubmissionDetail:
        fields = self._repository.get_fields(submission_id)
        typed = validate_override(field_name, value)
        field = fields[field_name]
        # Repeated overrides keep the original extraction result, not the previous override.
        original = field.override
        field.override = Override(
            value=typed,
            note=note,
            created_at=datetime.now(UTC).isoformat(),
            original_state=original.original_state if original else field.state,
            original_value=original.original_value if original else field.value,
        )
        field.state = FieldState.MISSING if typed is None else FieldState.KNOWN
        field.value = typed
        self._repository.save_review(
            submission_id,
            fields,
            evaluate_rules(fields),
            f"override:{field_name.value}",
        )
        return self.get_submission(submission_id)

    def list_submissions(
        self, query: str, sort: SortField, order: SortOrder, limit: int
    ) -> list[SubmissionListItem]:
        return self._repository.list_submissions(query, sort, order, limit)

    def get_submission(self, submission_id: str) -> SubmissionDetail:
        return self._repository.get(submission_id)
