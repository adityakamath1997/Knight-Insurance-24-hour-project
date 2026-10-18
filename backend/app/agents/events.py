"""Turns new agent messages into progress events: model text, tool calls with arguments, tool output."""

import json
from typing import Any, Literal

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from app.progress import ProgressEvent, ProgressStage
from app.schemas import SourceName

# Caps one event's payload; the full text is still what the agent saw.
MAX_DETAIL_CHARS = 8000


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )


def _detail(text: str) -> dict[str, Any]:
    if not text:
        return {}
    return {
        "detail": text[:MAX_DETAIL_CHARS],
        "truncated": len(text) > MAX_DETAIL_CHARS,
    }


def message_events(
    message: BaseMessage,
    stage: ProgressStage,
    source: SourceName | None,
    answer_tool: str,
) -> list[ProgressEvent]:
    """Events for one new message; `answer_tool` is the structured-output tool's name."""

    def event(
        kind: Literal["agent_message", "tool_call", "tool_result"],
        label: str,
        text: str = "",
        **extra: Any,
    ) -> ProgressEvent:
        return ProgressEvent(
            kind=kind, stage=stage, source=source, label=label, **_detail(text), **extra
        )

    if isinstance(message, AIMessage):
        events = []
        text = _text(message.content).strip()
        if text:
            events.append(event("agent_message", "Model message", text))
        for call in message.tool_calls:
            if call["name"] == answer_tool:
                label = "Submitting answer"
            elif call["name"] == "read_file":
                label = f"Reading {_read_name(call['args'])}"
            else:
                label = f"Calling {call['name']}"
            args = json.dumps(call["args"], indent=2, ensure_ascii=False, default=str)
            events.append(event("tool_call", label, args, tool=call["name"]))
        return events
    if isinstance(message, ToolMessage):
        ok = message.status != "error"
        if message.name == answer_tool:
            label = "Answer accepted" if ok else "Answer rejected, retrying"
        else:
            label = "Read ok" if ok else "Tool error"
        return [
            event(
                "tool_result",
                label,
                _text(message.content),
                tool=message.name,
                status="ok" if ok else "error",
            )
        ]
    return []


def _read_name(args: dict[str, Any]) -> str:
    name = str(args.get("file_path", "")).rsplit("/", 1)[-1]
    # PDF text is stored under a .txt path; show the original file name.
    return name.removesuffix(".txt") if name.endswith(".pdf.txt") else name
