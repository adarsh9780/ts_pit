from typing import Any
from langchain_core.messages import AnyMessage, SystemMessage


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""


def _has_system_message(
    messages: list[AnyMessage], expected: str | None = None
) -> bool:
    expected_norm = expected.strip() if isinstance(expected, str) else None

    for m in messages:
        if isinstance(m, SystemMessage):
            current = _content_to_text(m.content).strip()
            if expected_norm is None or current == expected_norm:
                return True
    return False


def build_prompt_messages(
    messages: list[AnyMessage],
    *,
    conversation_summary: str | None = None,
    recent_window: int = 16,
) -> list[AnyMessage]:
    recent = list(messages[-max(1, recent_window) :]) if messages else []
    summary = str(conversation_summary or "").strip()
    if not summary:
        return recent
    summary_msg = SystemMessage(
        content=(
            "[CONVERSATION SUMMARY]\n"
            "Use this as compact memory from older turns.\n"
            f"{summary}"
        )
    )
    return [summary_msg] + recent
