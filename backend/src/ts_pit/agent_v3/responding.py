from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage
from langchain_core.runnables import RunnableConfig

from ts_pit.config import get_config
from ts_pit.agent_v3.prompts import load_chat_prompt
from ts_pit.agent_v3.state import AgentV3State
from ts_pit.agent_v3.utils import build_prompt_messages
from ts_pit.llm import get_llm_model

RESPOND_RECENT_WINDOW = 16
_response_quality_cfg = get_config().get_agent_response_quality_config()
_response_quality_enabled = bool(_response_quality_cfg.get("enabled", True))


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


def _safe_json_loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {"raw": raw}
    except Exception:
        return {"raw": str(raw)}


def _latest_user_question(messages: list[AnyMessage]) -> str:
    for message in reversed(messages):
        msg_type = str(getattr(message, "type", "")).lower()
        if msg_type not in {"human", "user"}:
            continue
        content = _content_to_text(getattr(message, "content", ""))
        if "[USER QUESTION]" in content:
            parts = content.split("[USER QUESTION]", 1)
            if len(parts) > 1:
                return parts[1].strip()
        return content.strip()
    return ""


def _step_plan_version(step_id: str) -> int | None:
    text = str(step_id or "")
    if not text.startswith("v"):
        return None
    marker = "_s"
    if marker not in text:
        return None
    try:
        return int(text[1 : text.index(marker)])
    except Exception:
        return None


def _is_near_empty(answer: str) -> bool:
    compact = " ".join(str(answer or "").split()).strip()
    if not compact:
        return True
    if len(compact) < 24:
        return True
    return compact.lower() in {
        "no data",
        "no results",
        "not sure",
        "i don't know",
        "unable to answer",
    }


def _has_limitation_note(answer: str) -> bool:
    lowered = str(answer or "").lower()
    markers = (
        "limitation",
        "could not",
        "unable",
        "partial",
        "incomplete",
        "not available",
    )
    return any(marker in lowered for marker in markers)


def _table_opportunity_exists(completed: list[dict[str, Any]]) -> bool:
    for item in completed:
        result = item.get("result") if isinstance(item, dict) else None
        if not isinstance(result, dict):
            continue
        data = result.get("data")
        if not isinstance(data, list) or len(data) < 3:
            continue
        if all(isinstance(row, dict) for row in data[:3]):
            return True
    return False


def _quality_issues(answer: str, completed: list[dict[str, Any]], failed: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    if _is_near_empty(answer):
        issues.append("Answer is empty or near-empty.")
    if failed and not _has_limitation_note(answer):
        issues.append("Answer omits a concise limitation note despite failed steps.")
    if _table_opportunity_exists(completed) and "|" not in answer:
        issues.append("Likely table opportunity missed for comparable rows.")
    return issues


def completed_step_payloads(state: AgentV3State) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for step in state.steps:
        if step.status != "done":
            continue
        payloads.append(
            {
                "id": step.id,
                "instruction": step.instruction,
                "tool": step.selected_tool,
                "attempts": step.attempts,
                "result": step.result_payload or _safe_json_loads(step.result_summary),
            }
        )
    return payloads


def failed_step_payloads(state: AgentV3State) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for step in state.steps:
        if step.status != "failed":
            continue
        version = _step_plan_version(step.id)
        if version is not None and version != state.plan_version:
            continue
        payloads.append(
            {
                "id": step.id,
                "instruction": step.instruction,
                "tool": step.selected_tool,
                "attempts": step.attempts,
                "error_code": step.last_error_code,
                "error": step.error,
            }
        )
    return payloads


def respond_node(state: AgentV3State, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    ephemeral_marker = "respond" if _response_quality_enabled else None

    # Guardrail responses are already complete user-facing answers.
    if state.guardrail_response:
        answer_text = str(state.guardrail_response).strip()
        guardrail_msg = AIMessage(content=answer_text)
        if ephemeral_marker:
            guardrail_msg = AIMessage(
                content=answer_text,
                additional_kwargs={"ephemeral_node_output": ephemeral_marker},
            )
        return {
            "draft_answer": answer_text,
            "guardrail_response": None,
            "terminal_error": None,
            "messages": [guardrail_msg],
        }

    llm = get_llm_model()
    user_question = _latest_user_question(state.messages)
    completed = completed_step_payloads(state)
    failed = failed_step_payloads(state)
    quality_hint = (
        "Before finalizing, ensure the answer is concrete and not generic. "
        "If failed steps exist, include one short limitation note. "
        "If comparable multi-row data exists, use a markdown table."
    )

    prompt = load_chat_prompt("respond").invoke(
        {
            "messages": build_prompt_messages(
                state.messages,
                conversation_summary=state.conversation_summary,
                recent_window=RESPOND_RECENT_WINDOW,
            ),
            "query": user_question or "(missing user request)",
            "completed_step_outputs": json.dumps(completed, default=str),
            "failed_steps": json.dumps(failed, default=str),
            "current_alert": state.current_alert.model_dump_json(),
            "terminal_error": state.terminal_error or "",
            "conversation_summary": state.conversation_summary or "(none)",
            "quality_hint": quality_hint,
        }
    )

    ai_msg = llm.invoke(prompt)
    answer_text = _content_to_text(getattr(ai_msg, "content", "")).strip()
    issues = _quality_issues(answer_text, completed, failed)
    if issues:
        repair_prompt = load_chat_prompt("respond").invoke(
            {
                "messages": build_prompt_messages(
                    state.messages,
                    conversation_summary=state.conversation_summary,
                    recent_window=RESPOND_RECENT_WINDOW,
                ),
                "query": user_question or "(missing user request)",
                "completed_step_outputs": json.dumps(completed, default=str),
                "failed_steps": json.dumps(failed, default=str),
                "current_alert": state.current_alert.model_dump_json(),
                "terminal_error": state.terminal_error or "",
                "conversation_summary": state.conversation_summary or "(none)",
                "quality_hint": (
                    quality_hint
                    + " Fix these issues now: "
                    + " ".join(f"- {issue}" for issue in issues)
                ),
            }
        )
        repaired = llm.invoke(repair_prompt)
        repaired_text = _content_to_text(getattr(repaired, "content", "")).strip()
        if repaired_text:
            answer_text = repaired_text

    msg = AIMessage(content=answer_text)
    if ephemeral_marker:
        msg = AIMessage(
            content=answer_text,
            additional_kwargs={"ephemeral_node_output": ephemeral_marker},
        )
    return {"draft_answer": answer_text, "messages": [msg], "last_answer_feedback": None}


__all__ = [
    "respond_node",
    "completed_step_payloads",
    "failed_step_payloads",
]
