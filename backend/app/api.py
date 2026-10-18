import asyncio
from pathlib import PurePosixPath
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, ConfigDict

from app.agents.narrative import NarrativeService
from app.domain.models import FieldName
from app.schemas import SortField, SortOrder, SubmissionDetail, SubmissionListItem
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


router = APIRouter(prefix="/submissions", tags=["submissions"])


@router.get("")
def list_submissions(
    review: ReviewDep,
    q: str = "",
    sort: SortField = "created_at",
    order: SortOrder = "desc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[SubmissionListItem]:
    return review.list_submissions(q, sort, order, limit)


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


# Review runs keep going if the client disconnects, so hold references until done.
_running: set[asyncio.Task[None]] = set()


async def _read_uploads(files: list[UploadFile] | None) -> list[UploadInput]:
    return [
        UploadInput(
            file_name=PurePosixPath(
                (file.filename or "upload").replace("\\", "/")
            ).name,
            content=await file.read(),
        )
        for file in files or []
    ]


@router.post("/stream", response_class=EventSourceResponse)
async def stream_submission(
    review: ReviewDep,
    email_text: Annotated[str | None, Form()] = None,
    files: Annotated[list[UploadFile] | None, File()] = None,
):
    """Same as POST /submissions, but streams `progress` events and ends with one
    `result` or `error` event."""
    uploads = await _read_uploads(files)
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    def push(item: tuple[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, item)

    def work() -> None:
        # Progress and the final event share one thread, so their order is preserved.
        try:
            detail = review.create_submission(
                email_text, uploads, lambda event: push(("progress", event))
            )
            push(("result", detail))
        except PacketError as error:
            push(("error", {"detail": str(error)}))
        except Exception:  # noqa: BLE001 - never leave the stream hanging
            push(("error", {"detail": "The review failed unexpectedly."}))

    task = asyncio.create_task(asyncio.to_thread(work))
    _running.add(task)
    task.add_done_callback(_running.discard)

    while True:
        name, data = await queue.get()
        yield ServerSentEvent(data=data, event=name)
        if name != "progress":
            return


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
