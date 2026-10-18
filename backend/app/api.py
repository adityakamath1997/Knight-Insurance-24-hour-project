from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from app.agents.narrative import NarrativeService
from app.domain.models import FieldName
from app.schemas import SubmissionDetail
from app.services.documents import PacketError, UploadInput
from app.services.review import ReviewService


def _review(request: Request) -> ReviewService:
    return request.app.state.review


def _narrative(request: Request) -> NarrativeService:
    return request.app.state.narrative


ReviewDep = Annotated[ReviewService, Depends(_review)]
NarrativeDep = Annotated[NarrativeService, Depends(_narrative)]


class OverrideRequest(BaseModel):
    # Evidence, rules and statuses are read-only, so any other key is rejected.
    model_config = ConfigDict(extra="forbid")

    value: str | int | float | bool | None
    note: str | None = None


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str


class MessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1)


router = APIRouter(prefix="/submissions", tags=["submissions"])


# Sync handlers run in the threadpool; extraction starts its own event loop.
@router.post("", status_code=201)
def create_submission(
    review: ReviewDep,
    email_text: Annotated[str | None, Form()] = None,
    files: Annotated[list[UploadFile] | None, File()] = None,
) -> SubmissionDetail:
    uploads = [
        UploadInput(
            file_name=PurePosixPath(
                (file.filename or "upload").replace("\\", "/")
            ).name,
            content=file.file.read(),
        )
        for file in files or []
    ]
    try:
        return review.create_submission(email_text, uploads)
    except PacketError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/{submission_id}")
def get_submission(review: ReviewDep, submission_id: str) -> SubmissionDetail:
    return review.get_submission(submission_id)


@router.patch("/{submission_id}/fields/{field_name}")
def override_field(
    review: ReviewDep,
    submission_id: str,
    field_name: FieldName,
    request: OverrideRequest,
) -> SubmissionDetail:
    try:
        return review.apply_override(
            submission_id, field_name, request.value, request.note
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.patch("/{submission_id}/draft")
def edit_draft(
    review: ReviewDep,
    narrative: NarrativeDep,
    submission_id: str,
    request: DraftRequest,
) -> SubmissionDetail:
    narrative.edit_draft(submission_id, request.body)
    return review.get_submission(submission_id)


@router.post("/{submission_id}/narrative/regenerate")
def regenerate_narrative(
    review: ReviewDep, narrative: NarrativeDep, submission_id: str
) -> SubmissionDetail:
    narrative.generate(submission_id)
    return review.get_submission(submission_id)


@router.post("/{submission_id}/narrative/messages")
def reply(
    review: ReviewDep,
    narrative: NarrativeDep,
    submission_id: str,
    request: MessageRequest,
) -> SubmissionDetail:
    narrative.reply(submission_id, request.message)
    return review.get_submission(submission_id)
