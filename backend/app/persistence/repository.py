"""All database reads and writes for submissions."""

from collections import Counter
from collections.abc import Sequence

from sqlalchemy import Engine
from sqlmodel import Session, select

from app.domain.models import FieldName, ReviewedField, RuleEvaluation
from app.persistence.database import (
    DocumentRow,
    NarrativeRow,
    SnapshotRow,
    SourceRunRow,
    SubmissionRow,
)
from app.schemas import (
    DocumentSummary,
    Draft,
    Narrative,
    Snapshot,
    SortField,
    SortOrder,
    SourceRunSummary,
    SubmissionDetail,
    SubmissionListItem,
)

Fields = dict[FieldName, ReviewedField]


class SubmissionNotFoundError(LookupError):
    pass


def _get_submission(session: Session, submission_id: str) -> SubmissionRow:
    submission = session.get(SubmissionRow, submission_id)
    if submission is None:
        raise SubmissionNotFoundError(submission_id)
    return submission


def _load_fields(submission: SubmissionRow) -> Fields:
    return {
        FieldName(name): ReviewedField.model_validate(payload)
        for name, payload in submission.reviewed_fields.items()
    }


def _write_review(
    session: Session,
    submission: SubmissionRow,
    fields: Fields,
    evaluation: RuleEvaluation,
    trigger: str,
) -> None:
    submission.reviewed_fields = {
        name.value: field.model_dump(mode="json") for name, field in fields.items()
    }
    session.add(
        SnapshotRow(
            submission_id=submission.id,
            trigger=trigger,
            overall_status=evaluation.overall_status,
            rules=[rule.model_dump(mode="json") for rule in evaluation.rules],
        )
    )


class SubmissionRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create(self, submission_id: str, documents: Sequence[DocumentRow]) -> None:
        with Session(self._engine) as session:
            session.add(SubmissionRow(id=submission_id))
            session.flush()  # FKs are enforced and inserts are not ordered without relationships
            session.add_all(documents)
            session.commit()

    def record_extraction(
        self,
        submission_id: str,
        fields: Fields,
        evaluation: RuleEvaluation,
        runs: Sequence[SourceRunRow],
        detected_types: dict[str, str],
    ) -> None:
        with Session(self._engine) as session:
            submission = _get_submission(session, submission_id)
            documents = session.exec(
                select(DocumentRow).where(DocumentRow.submission_id == submission_id)
            )
            for document in documents:
                document.detected_type = detected_types.get(document.file_name)
            session.add_all(runs)
            _write_review(session, submission, fields, evaluation, "initial")
            session.commit()

    def get_fields(self, submission_id: str) -> Fields:
        with Session(self._engine) as session:
            return _load_fields(_get_submission(session, submission_id))

    def save_review(
        self,
        submission_id: str,
        fields: Fields,
        evaluation: RuleEvaluation,
        trigger: str,
    ) -> None:
        with Session(self._engine) as session:
            submission = _get_submission(session, submission_id)
            _write_review(session, submission, fields, evaluation, trigger)
            session.commit()

    def save_narrative(self, narrative: NarrativeRow) -> None:
        with Session(self._engine) as session:
            _get_submission(session, narrative.submission_id)
            session.merge(narrative)
            session.commit()

    def list_submissions(
        self, query: str, sort: SortField, order: SortOrder, limit: int
    ) -> list[SubmissionListItem]:
        """Reviewed submissions only. Filtering and sorting happen here, not in SQL, so
        `query` is always a literal substring and business name comes from the JSON."""
        with Session(self._engine) as session:
            statuses = {
                submission_id: status
                for submission_id, status in session.exec(
                    select(
                        SnapshotRow.submission_id, SnapshotRow.overall_status
                    ).order_by(SnapshotRow.id)  # the last snapshot per submission wins
                )
            }
            counts = Counter(session.exec(select(DocumentRow.submission_id)))
            items = [
                SubmissionListItem(
                    id=row.id,
                    created_at=row.created_at,
                    business_name=(row.reviewed_fields.get("business_name") or {}).get(
                        "value"
                    ),
                    overall_status=statuses[row.id],
                    document_count=counts[row.id],
                )
                for row in session.exec(select(SubmissionRow))
                if row.id in statuses
            ]
        needle = query.strip().lower()
        if needle:
            items = [
                i
                for i in items
                if needle in i.id.lower() or needle in (i.business_name or "").lower()
            ]
        reverse = order == "desc"
        if sort == "business_name":
            named = sorted(
                (i for i in items if i.business_name),
                key=lambda i: ((i.business_name or "").lower(), i.id),
                reverse=reverse,
            )
            return (named + [i for i in items if not i.business_name])[:limit]
        keys = {
            "created_at": lambda i: (i.created_at, i.id),
            "id": lambda i: i.id,
            "status": lambda i: (i.overall_status, i.id),
        }
        return sorted(items, key=keys[sort], reverse=reverse)[:limit]

    def get(self, submission_id: str) -> SubmissionDetail:
        with Session(self._engine) as session:
            submission = _get_submission(session, submission_id)
            documents = session.exec(
                select(DocumentRow)
                .where(DocumentRow.submission_id == submission_id)
                .order_by(DocumentRow.id)
            )
            runs = session.exec(
                select(SourceRunRow)
                .where(SourceRunRow.submission_id == submission_id)
                .order_by(SourceRunRow.id)
            )
            snapshots = [
                Snapshot.model_validate(row, from_attributes=True)
                for row in session.exec(
                    select(SnapshotRow)
                    .where(SnapshotRow.submission_id == submission_id)
                    .order_by(SnapshotRow.id)
                )
            ]
            narrative = session.get(NarrativeRow, submission_id)
            return SubmissionDetail(
                id=submission.id,
                created_at=submission.created_at,
                documents=[
                    DocumentSummary.model_validate(d, from_attributes=True)
                    for d in documents
                ],
                source_runs=[
                    SourceRunSummary.model_validate(r, from_attributes=True)
                    for r in runs
                ],
                fields=_load_fields(submission),
                rules=snapshots[-1].rules,
                overall_status=snapshots[-1].overall_status,
                snapshots=snapshots,
                narrative=Narrative(
                    status=narrative.status,
                    error=narrative.error,
                    summary=narrative.summary,
                    draft=Draft(
                        body=narrative.draft_body,
                        edited=narrative.draft_edited,
                        stale=narrative.draft_stale,
                    ),
                )
                if narrative
                else Narrative(),
            )
