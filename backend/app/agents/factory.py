"""Deep Agent construction: StateBackend VFS, no checkpointer, no general-purpose subagent."""

from collections.abc import Sequence
from typing import Any

from deepagents import (
    FilesystemPermission,
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from deepagents.backends import StateBackend
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelFallbackMiddleware,
    ModelRetryMiddleware,
)
from langchain.agents.structured_output import ToolStrategy
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import ToolMessage
from pydantic import BaseModel, SecretStr

from app.settings import Settings

MAX_SCHEMA_RETRIES = 2


class StructuredOutputRetriesExhausted(RuntimeError):
    pass


class _StructuredOutputRetryLimit(AgentMiddleware):
    """Fails the run once the final answer has been rejected more than `MAX_SCHEMA_RETRIES` times."""

    def __init__(self, tool_name: str) -> None:
        super().__init__()
        self._tool_name = tool_name

    def before_model(self, state: Any, runtime: Any) -> None:
        # Every answer-tool message before the model call is a rejection; success ends the run.
        rejections = [
            m.content
            for m in state["messages"]
            if isinstance(m, ToolMessage) and m.name == self._tool_name
        ]
        if len(rejections) > MAX_SCHEMA_RETRIES:
            raise StructuredOutputRetriesExhausted(str(rejections[-1]))


def answer_attempts(state: dict[str, Any]) -> int:
    name = type(state["structured_response"]).__name__
    return sum(
        1 for m in state["messages"] if isinstance(m, ToolMessage) and m.name == name
    )


def _chat_model(
    spec: str, base_url: str | None, api_key: SecretStr | None
) -> BaseChatModel:
    kwargs: dict[str, Any] = {}
    if base_url:
        kwargs["base_url"] = base_url
    if api_key:
        kwargs["api_key"] = api_key.get_secret_value()
    register_harness_profile(
        spec,
        HarnessProfile(
            # Agents only read their inputs; permissions below also deny writes.
            excluded_tools=frozenset({"write_file", "edit_file", "delete", "execute"}),
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        ),
    )
    return init_chat_model(spec, **kwargs)


def build_chat_models(settings: Settings) -> list[BaseChatModel]:
    """Primary model, then the optional fallback. Specs are `provider:model`."""
    if not settings.llm_model:
        raise RuntimeError("LLM_MODEL is not configured")
    models = [
        _chat_model(settings.llm_model, settings.llm_base_url, settings.llm_api_key)
    ]
    if settings.llm_fallback_model:
        models.append(
            _chat_model(
                settings.llm_fallback_model,
                settings.llm_fallback_base_url,
                settings.llm_fallback_api_key,
            )
        )
    return models


def build_agent(
    models: Sequence[BaseChatModel],
    root: str,
    system_prompt: str,
    response_format: type[BaseModel],
) -> Any:
    primary, *fallbacks = models
    # Fallback is outermost, so each model gets its own retries first.
    middleware: list[Any] = [ModelFallbackMiddleware(*fallbacks)] if fallbacks else []
    middleware.append(ModelRetryMiddleware(max_retries=2, on_failure="error"))
    middleware.append(_StructuredOutputRetryLimit(response_format.__name__))
    return create_deep_agent(
        model=primary,
        system_prompt=system_prompt,
        backend=StateBackend(),
        # First match wins: read-only inside root, nothing elsewhere.
        permissions=[
            FilesystemPermission(operations=["read"], paths=[root, f"{root}/**"]),
            FilesystemPermission(
                operations=["read", "write"], paths=["/**"], mode="deny"
            ),
        ],
        # A rejected answer goes back to the model as a tool error in the same run.
        response_format=ToolStrategy(response_format, handle_errors=True),
        middleware=middleware,
    )
