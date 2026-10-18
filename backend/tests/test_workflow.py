from pathlib import Path

import pytest
from sqlalchemy import text
from sqlmodel import Session

from app.agents.narrative import NarrativeService
from app.agents.schemas import NarrativeOutput
from app.domain.models import Candidate, Evidence, FieldName, FieldState
from app.persistence.database import DocumentRow, SubmissionRow, create_db_engine
from app.persistence.repository import SubmissionNotFoundError, SubmissionRepository
from app.services.documents import (
    PacketError,
    PreparedPacket,
    UploadInput,
    prepare_submission_documents,
)
from app.services.review import Extractor, ReviewService, SourceRun
from app.settings import Settings

F = FieldName

SAMPLES = Path(__file__).parents[2] / (
    "Knight_Insurance_24_Hour_Project/candidate_materials/sample_submissions"
)
HEADER = "vehicle_id,vin,year,make,model"


def upload(name: str, content: bytes | str) -> UploadInput:
    data = content.encode() if isinstance(content, str) else content
    return UploadInput(file_name=name, content=data)


def write_narrative(report: dict, history: list, draft: str) -> NarrativeOutput:
    return NarrativeOutput(summary="summary", draft_email="draft")


def review_service(path: Path, extractor: Extractor) -> ReviewService:
    repository = SubmissionRepository(create_db_engine(path))
    narrative = NarrativeService(repository, write_narrative)
    return ReviewService(repository, extractor, narrative)


def test_settings_uses_local_sqlite_path(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    assert settings.database_path == tmp_path / "knight-review.sqlite3"


def test_database_configures_sqlite_and_survives_new_engine(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "knight-review.sqlite3"
    engine = create_db_engine(path)
    with Session(engine) as session:
        assert session.exec(text("PRAGMA journal_mode")).one()[0] == "wal"
        assert session.exec(text("PRAGMA foreign_keys")).one()[0] == 1
        session.add(SubmissionRow(id="s1", reviewed_fields={"a": 1}))
        session.flush()
        session.add(
            DocumentRow(
                submission_id="s1",
                file_name="a.pdf",
                kind="pdf",
                content=b"\x00raw",
                readable=False,
            )
        )
        session.commit()

    with Session(create_db_engine(path)) as session:
        assert session.get(SubmissionRow, "s1").reviewed_fields == {"a": 1}
        assert session.get(DocumentRow, 1).content == b"\x00raw"


def test_pasted_email_and_page_labelled_pdf_text() -> None:
    pdf = (SAMPLES / "SUB-A" / "application.pdf").read_bytes()
    packet = prepare_submission_documents("Hello", [upload("application.pdf", pdf)])

    assert packet.email is not None
    assert (packet.email.file_name, packet.email.text) == (
        "pasted broker email",
        "Hello",
    )
    [doc] = packet.attachments
    assert doc.kind == "pdf" and doc.readable
    assert doc.text.startswith("[Page 1]\n") and "Business name" in doc.text


def test_unreadable_pdf_is_recorded_not_guessed() -> None:
    packet = prepare_submission_documents("", [upload("loss_runs.pdf", b"not a pdf")])
    [doc] = packet.attachments
    assert not doc.readable
    assert packet.attachment_inventory == ["loss_runs.pdf (pdf, unreadable)"]


def test_uploaded_txt_is_the_email_body() -> None:
    packet = prepare_submission_documents(None, [upload("broker_email.txt", "Hi")])
    assert packet.email is not None and packet.email.text == "Hi"
    assert packet.attachments == []


def test_only_broker_email_txt_is_the_email() -> None:
    packet = prepare_submission_documents(
        None,
        [
            upload("Broker_Email.TXT", "Hi"),
            upload("notes.txt", "x"),
            upload("a.eml", "y"),
        ],
    )
    assert packet.email is not None and packet.email.text == "Hi"
    assert [(d.file_name, d.kind) for d in packet.attachments] == [
        ("notes.txt", "other"),
        ("a.eml", "other"),
    ]


def test_empty_packet_is_rejected() -> None:
    with pytest.raises(PacketError):
        prepare_submission_documents("  ", [])


def test_schedule_count_excludes_header_and_blank_rows_with_bom_and_crlf() -> None:
    csv = f"\ufeff {HEADER} \r\nA,V1,2022,M,X\r\n , , , , \r\n\r\nB,V2,2023,M,Y\r\n"
    field = prepare_submission_documents("Hi", [upload("vehicles.csv", csv)]).schedule

    assert (field.state, field.value) == (FieldState.KNOWN, 2)
    [candidate] = field.candidates
    assert (
        candidate.evidence[0].locator == "vehicles.csv, data rows 1-2 (header excluded)"
    )


def test_schedule_with_zero_rows_is_known_zero() -> None:
    field = prepare_submission_documents(
        "Hi", [upload("v.csv", HEADER + "\r\n")]
    ).schedule
    assert (field.state, field.value) == (FieldState.KNOWN, 0)


@pytest.mark.parametrize(
    "uploads",
    [
        [upload("v.csv", "id,vin\r\n1,2\r\n")],
        [upload("v.csv", b"\xff\xfe\x00")],
    ],
)
def test_malformed_or_duplicate_schedule_is_invalid(uploads: list[UploadInput]) -> None:
    field = prepare_submission_documents("Hi", uploads).schedule
    assert field.state == FieldState.INVALID and field.value is None
    assert all(c.evidence for c in field.candidates)


def test_no_schedule_is_missing_with_attachment_inventory() -> None:
    packet = prepare_submission_documents("Hi", [upload("loss_runs.pdf", b"bad")])
    field = packet.schedule
    assert field.state == FieldState.MISSING
    assert field.inspected_sources == ["loss_runs.pdf (pdf, unreadable)"]


EMAIL_RAW = {
    F.BUSINESS_NAME: "Acme LLC",
    F.REQUESTED_EFFECTIVE_DATE: "2026-11-01",
    F.GARAGING_STATE: "CA",
    F.OPERATIONS_DESCRIPTION: "Retail goods.",
    F.DECLARED_VEHICLE_COUNT: "3",
    F.OPERATING_RADIUS_MILES: "180",
    F.HAZARDOUS_MATERIALS: "No",
}
PDF_RAW = EMAIL_RAW | {F.GARAGING_STATE: "California", F.OPERATING_RADIUS_MILES: "80"}
PACKET = [
    upload("application.pdf", (SAMPLES / "SUB-A" / "application.pdf").read_bytes()),
    upload(
        "vehicles.csv",
        f"{HEADER}\r\nA,V1,2022,M,X\r\nB,V2,2022,M,X\r\nC,V3,2022,M,X\r\n",
    ),
]


def candidates(source: str, file: str, raws: dict[FieldName, str]) -> dict:
    return {
        field: [
            Candidate(
                source=source,
                source_file=file,
                raw_value=raw,
                state=FieldState.KNOWN,
                evidence=[
                    Evidence(
                        source_file=file, locator="line 1", excerpt_or_observation=raw
                    )
                ],
            )
        ]
        for field, raw in raws.items()
    }


def fake_extractor(pdf_status: str = "SUCCEEDED"):
    def extract(packet: PreparedPacket) -> list[SourceRun]:
        assert packet.email is not None and len(packet.attachments) == 2
        return [
            SourceRun(
                source="email",
                status="SUCCEEDED",
                attempts=1,
                candidates=candidates("email", "pasted broker email", EMAIL_RAW),
            ),
            SourceRun(
                source="pdf",
                status=pdf_status,
                attempts=3 if pdf_status != "SUCCEEDED" else 1,
                error=None if pdf_status == "SUCCEEDED" else "model timed out",
                candidates=candidates("pdf", "application.pdf", PDF_RAW)
                if pdf_status == "SUCCEEDED"
                else {},
            ),
            SourceRun(
                source="attachments",
                status="SUCCEEDED",
                attempts=1,
                candidates=candidates(
                    "attachments", "vehicles.csv", {F.LOSS_RUNS_PRESENT: "false"}
                ),
                detected_types={"vehicles.csv": "vehicle schedule"},
            ),
        ]

    return extract


def test_submission_reconciles_sources_and_persists_across_engines(
    tmp_path: Path,
) -> None:
    path = tmp_path / "db.sqlite3"
    detail = review_service(path, fake_extractor()).create_submission(
        "Broker email", PACKET
    )

    fields = detail.fields
    assert (fields[F.GARAGING_STATE].state, fields[F.GARAGING_STATE].value) == (
        FieldState.KNOWN,
        "CA",
    )
    assert fields[F.OPERATIONS_DESCRIPTION].state == FieldState.KNOWN
    radius = fields[F.OPERATING_RADIUS_MILES]
    assert (radius.state, radius.value) == (FieldState.CONFLICT, None)
    assert [c.value for c in radius.candidates] == [180.0, 80.0]
    assert fields[F.SCHEDULE_VEHICLE_COUNT].value == 3
    assert fields[F.LOSS_RUNS_PRESENT].attachment_inventory == [
        "application.pdf (pdf)",
        "vehicles.csv (csv)",
    ]
    assert [r.status for r in detail.rules] == [
        "PASS",
        "PASS",
        "UNKNOWN",
        "PASS",
        "FLAG",
    ]
    assert detail.overall_status == "NEEDS_REVIEW"
    assert [(d.file_name, d.kind, d.detected_type) for d in detail.documents] == [
        ("pasted broker email", "email", None),
        ("application.pdf", "pdf", None),
        ("vehicles.csv", "csv", "vehicle schedule"),
    ]
    assert [s.trigger for s in detail.snapshots] == ["initial"]

    reloaded = review_service(path, fake_extractor())
    assert reloaded.get_submission(detail.id) == detail
    with Session(create_db_engine(path)) as session:
        stored = session.get(DocumentRow, 2)
        assert stored.content == PACKET[0].content


def test_failed_source_stays_visible_and_makes_its_fields_invalid(
    tmp_path: Path,
) -> None:
    service = review_service(tmp_path / "db.sqlite3", fake_extractor("MODEL_FAILED"))
    detail = service.create_submission("Broker email", PACKET)

    run = next(r for r in detail.source_runs if r.source == "pdf")
    assert (run.status, run.attempts, run.error) == (
        "MODEL_FAILED",
        3,
        "model timed out",
    )
    name = detail.fields[F.BUSINESS_NAME]
    assert name.state == FieldState.INVALID
    failure = next(c for c in name.candidates if c.source == "pdf")
    assert "model timed out" in failure.evidence[0].excerpt_or_observation
    assert detail.rules[0].status == "UNKNOWN"


def test_override_resolves_conflict_and_keeps_original_evidence(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite3"
    service = review_service(path, fake_extractor())
    submission_id = service.create_submission("Broker email", PACKET).id

    detail = service.apply_override(
        submission_id, F.OPERATING_RADIUS_MILES, 120, "Broker confirmed"
    )
    radius = detail.fields[F.OPERATING_RADIUS_MILES]
    assert (radius.state, radius.value) == (FieldState.KNOWN, 120.0)
    assert radius.override.original_state == FieldState.CONFLICT
    assert radius.override.note == "Broker confirmed"
    assert [c.value for c in radius.candidates] == [180.0, 80.0]
    assert (
        detail.rules[2].status == "PASS"
        and detail.rules[2].inputs[F.OPERATING_RADIUS_MILES].overridden
    )
    assert [s.trigger for s in detail.snapshots] == [
        "initial",
        "override:operating_radius_miles",
    ]
    assert detail.snapshots[0].rules[2].status == "UNKNOWN"

    cleared = service.apply_override(
        submission_id, F.OPERATING_RADIUS_MILES, None, None
    )
    radius = cleared.fields[F.OPERATING_RADIUS_MILES]
    assert (radius.state, radius.override.original_state) == (
        FieldState.MISSING,
        FieldState.CONFLICT,
    )
    assert cleared.rules[2].status == "UNKNOWN"
    assert (
        review_service(path, fake_extractor()).get_submission(submission_id) == cleared
    )


def test_override_rejects_wrong_type_and_unknown_submission(tmp_path: Path) -> None:
    service = review_service(tmp_path / "db.sqlite3", fake_extractor())
    submission_id = service.create_submission("Broker email", PACKET).id
    with pytest.raises(ValueError):
        service.apply_override(submission_id, F.DECLARED_VEHICLE_COUNT, "three", None)
    with pytest.raises(SubmissionNotFoundError):
        service.get_submission("missing")
