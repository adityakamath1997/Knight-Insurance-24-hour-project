"""Deterministic packet preparation: no model calls, unreadable content is recorded, never guessed."""

import csv
import io
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel
from pypdf import PdfReader

from app.domain.models import Candidate, Evidence, FieldName, FieldState, ReviewedField

PASTED_EMAIL = "pasted broker email"
APPLICATION_FILE_NAME = "application.pdf"
EMAIL_FILE_NAME = "broker_email.txt"
RESERVED_FILE_NAMES = ("manifest.txt",)
SCHEDULE_HEADER = ["vehicle_id", "vin", "year", "make", "model"]

DocumentKind = Literal["email", "pdf", "csv", "other"]


class PacketError(ValueError):
    pass


class UploadInput(BaseModel):
    file_name: str
    content: bytes


class PreparedDocument(BaseModel):
    file_name: str
    kind: DocumentKind
    content: bytes
    text: str | None

    @property
    def readable(self) -> bool:
        return self.text is not None

    def describe(self) -> str:
        return (
            f"{self.file_name} ({self.kind}{'' if self.readable else ', unreadable'})"
        )


class PreparedPacket(BaseModel):
    email: PreparedDocument | None
    attachments: list[PreparedDocument]
    schedule: ReviewedField

    @property
    def attachment_inventory(self) -> list[str]:
        return [doc.describe() for doc in self.attachments]

    @property
    def schedule_document(self) -> PreparedDocument | None:
        """The single readable CSV with the schedule header; code counts it, no agent reads it."""
        csvs = [doc for doc in self.attachments if doc.kind == "csv"]
        if (
            len(csvs) == 1
            and csvs[0].text is not None
            and _count_vehicle_rows(csvs[0].text) is not None
        ):
            return csvs[0]
        return None


def _decode(content: bytes) -> str | None:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def _pdf_text(content: bytes) -> str | None:
    try:
        pages = [
            page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages
        ]
    except Exception:  # noqa: BLE001 - pypdf raises many exception types for corrupt uploads
        return None
    if not any(page.strip() for page in pages):
        return None  # no selectable text; OCR is out of scope
    return "\n\n".join(
        f"[Page {number}]\n{page}" for number, page in enumerate(pages, 1)
    )


def _prepare(upload: UploadInput) -> PreparedDocument:
    name = upload.file_name.casefold()
    suffix = PurePosixPath(name).suffix
    if name == EMAIL_FILE_NAME:
        kind, text = "email", _decode(upload.content)
    elif suffix == ".pdf":
        kind, text = "pdf", _pdf_text(upload.content)
    elif suffix == ".csv":
        kind, text = "csv", _decode(upload.content)
    else:
        kind, text = "other", _decode(upload.content)
    return PreparedDocument(
        file_name=upload.file_name, kind=kind, content=upload.content, text=text
    )


def _count_vehicle_rows(text: str) -> int | None:
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error:
        return None
    if not rows or [cell.strip() for cell in rows[0]] != SCHEDULE_HEADER:
        return None
    return sum(1 for row in rows[1:] if any(cell.strip() for cell in row))


def _invalid_schedule(
    source_file: str, observation: str, inspected: list[str]
) -> ReviewedField:
    return ReviewedField(
        name=FieldName.SCHEDULE_VEHICLE_COUNT,
        state=FieldState.INVALID,
        candidates=[
            Candidate(
                source="schedule",
                source_file=source_file,
                raw_value=None,
                state=FieldState.INVALID,
                evidence=[
                    Evidence(
                        source_file=source_file,
                        locator=source_file,
                        excerpt_or_observation=observation,
                    )
                ],
            )
        ],
        inspected_sources=inspected,
    )


def _schedule_field(attachments: Sequence[PreparedDocument]) -> ReviewedField:
    csvs = [doc for doc in attachments if doc.kind == "csv"]
    if not csvs:
        return ReviewedField(
            name=FieldName.SCHEDULE_VEHICLE_COUNT,
            state=FieldState.MISSING,
            inspected_sources=[doc.describe() for doc in attachments],
        )
    if len(csvs) > 1:
        names = ", ".join(doc.file_name for doc in csvs)
        return _invalid_schedule(
            names,
            f"More than one vehicle schedule was supplied ({names}); the count is ambiguous.",
            [doc.describe() for doc in csvs],
        )

    doc = csvs[0]
    count = _count_vehicle_rows(doc.text) if doc.text is not None else None
    if count is None:
        return _invalid_schedule(
            doc.file_name,
            f"Unreadable, or header is not {','.join(SCHEDULE_HEADER)}.",
            [doc.describe()],
        )
    return ReviewedField(
        name=FieldName.SCHEDULE_VEHICLE_COUNT,
        state=FieldState.KNOWN,
        value=count,
        candidates=[
            Candidate(
                source="schedule",
                source_file=doc.file_name,
                raw_value=str(count),
                state=FieldState.KNOWN,
                value=count,
                evidence=[
                    Evidence(
                        source_file=doc.file_name,
                        locator=f"{doc.file_name}, data rows 1-{count} (header excluded)",
                        excerpt_or_observation=f"{count} nonblank vehicle rows after the header.",
                    )
                ],
            )
        ],
        inspected_sources=[doc.describe()],
    )


def prepare_submission_documents(
    email_text: str | None, uploads: Sequence[UploadInput]
) -> PreparedPacket:
    documents = [_prepare(upload) for upload in uploads]
    names = [doc.file_name.casefold() for doc in documents]
    if len(set(names)) != len(names):
        raise PacketError("File names must be unique within a packet.")
    if reserved := [n for n in names if n in RESERVED_FILE_NAMES]:
        raise PacketError(f"{reserved[0]} is a reserved file name.")
    attachments = [doc for doc in documents if doc.kind != "email"]
    pasted = (email_text or "").strip()
    if not pasted and not documents:
        raise PacketError("Provide broker email text or at least one file.")

    emails = [doc for doc in documents if doc.kind == "email"]
    if len(emails) + bool(pasted) > 1:
        raise PacketError(
            f"Provide one broker email: pasted text or {EMAIL_FILE_NAME}, not both."
        )
    email = emails[0] if emails else None
    if pasted:
        email = PreparedDocument(
            file_name=PASTED_EMAIL, kind="email", content=pasted.encode(), text=pasted
        )
    return PreparedPacket(
        email=email, attachments=attachments, schedule=_schedule_field(attachments)
    )
