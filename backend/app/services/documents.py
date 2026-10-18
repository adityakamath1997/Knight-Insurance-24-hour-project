"""Deterministic packet preparation: no model calls, unreadable content is recorded, never guessed."""

import csv
import io
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel
from pypdf import PdfReader

from app.domain.models import Candidate, Evidence, FieldName, FieldState, ReviewedField

PASTED_EMAIL = "pasted broker email"
EMAIL_SUFFIXES = (".txt", ".eml")
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
    suffix = upload.file_name.lower().rsplit(".", 1)[-1]
    if suffix == "pdf":
        kind, text = "pdf", _pdf_text(upload.content)
    elif suffix == "csv":
        kind, text = "csv", _decode(upload.content)
    elif f".{suffix}" in EMAIL_SUFFIXES:
        kind, text = "email", _decode(upload.content)
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


def _schedule_field(attachments: Sequence[PreparedDocument]) -> ReviewedField:
    doc = next((doc for doc in attachments if doc.kind == "csv"), None)
    if doc is None:
        return ReviewedField(
            name=FieldName.SCHEDULE_VEHICLE_COUNT,
            state=FieldState.MISSING,
            inspected_sources=[doc.describe() for doc in attachments],
        )

    count = _count_vehicle_rows(doc.text) if doc.text is not None else None
    if count is None:
        observation = f"Unreadable, or header is not {','.join(SCHEDULE_HEADER)}."
        return ReviewedField(
            name=FieldName.SCHEDULE_VEHICLE_COUNT,
            state=FieldState.INVALID,
            candidates=[
                Candidate(
                    source="schedule",
                    source_file=doc.file_name,
                    raw_value=None,
                    state=FieldState.INVALID,
                    evidence=[
                        Evidence(
                            source_file=doc.file_name,
                            locator=doc.file_name,
                            excerpt_or_observation=observation,
                        )
                    ],
                )
            ],
            inspected_sources=[doc.describe()],
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
    attachments = [doc for doc in documents if doc.kind != "email"]
    pasted = (email_text or "").strip()
    if not pasted and not documents:
        raise PacketError("Provide broker email text or at least one file.")

    # A packet has one email: pasted text, else the uploaded .txt/.eml file.
    email = next((doc for doc in documents if doc.kind == "email"), None)
    if pasted:
        email = PreparedDocument(
            file_name=PASTED_EMAIL, kind="email", content=pasted.encode(), text=pasted
        )
    return PreparedPacket(
        email=email, attachments=attachments, schedule=_schedule_field(attachments)
    )
