"""Progress events for a running review: stage changes plus the agents' own messages and tool calls."""

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel

from app.schemas import SourceName

ProgressStage = Literal["prepare", "extraction", "rules", "narrative"]
ProgressKind = Literal[
    "stage_started",
    "stage_finished",
    "agent_message",
    "tool_call",
    "tool_result",
]


class ProgressEvent(BaseModel):
    kind: ProgressKind
    stage: ProgressStage
    source: SourceName | None = None
    label: str
    status: str | None = None
    tool: str | None = None
    # Model text, tool arguments (JSON) or tool output; `truncated` when clipped.
    detail: str | None = None
    truncated: bool = False


ProgressSink = Callable[[ProgressEvent], None]


def emit(sink: ProgressSink | None, event: ProgressEvent) -> None:
    if sink is not None:
        sink(event)
