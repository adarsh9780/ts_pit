from __future__ import annotations

import re
import json
from uuid import uuid4
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from sqlalchemy import text as sa_text

from .tools import (
    TOOL_REGISTRY,
)
from ..llm import get_llm_model
from ..config import get_config
from ..db import get_engine
from .prompts import AGENT_V2_SYSTEM_PROMPT
from .state import AgentV2State

ALL_TOOLS = list(TOOL_REGISTRY.values())
SUMMARY_TRIGGER_TOKENS_EST = 7000
RECENT_MESSAGES_WINDOW = 14
TOOL_ERROR_RETRY_MSG_ID_PREFIX = "agent-v2-tool-error-retry-"
ANSWER_REWRITE_MSG_ID_PREFIX = "agent-v2-answer-format-rewrite-"
SCHEMA_PREFLIGHT_PATH = "artifacts/DB_SCHEMA_REFERENCE.yaml"
CORRECTABLE_ERROR_CODES = {
    "READ_ONLY_ENFORCED",
    "INVALID_INPUT",
    "TABLE_NOT_FOUND",
    "DB_ERROR",
    "PYTHON_EXEC_ERROR",
}


def ensure_system_prompt(state: AgentV2State, config: RunnableConfig) -> dict:
    _ = config
    messages = state.get("messages", [])
    has_system = any(
        isinstance(m, SystemMessage)
        and getattr(m, "id", None) == "agent-v2-system-prompt"
        for m in messages
    )
    if has_system:
        return {}
    return {
        "messages": [
            SystemMessage(content=AGENT_V2_SYSTEM_PROMPT, id="agent-v2-system-prompt")
        ]
    }


def _latest_user_text(messages: list) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage) or getattr(message, "type", "") == "human":
            return str(getattr(message, "content", "") or "").strip()
    if messages:
        return str(getattr(messages[-1], "content", "") or "").strip()
    return ""


def _contains_any(text_value: str, tokens: tuple[str, ...]) -> bool:
    lowered = text_value.lower()
    return any(token in lowered for token in tokens)


def _message_text(message) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, list):
        text_parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict) and "text" in part:
                text_parts.append(str(part["text"]))
        return " ".join(text_parts).strip()
    return str(content or "").strip()


def _estimate_tokens(text: str) -> int:
    # Practical approximation for English-heavy prompts.
    return max(1, len(text) // 4)


def _message_content_as_text(message) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and "text" in part:
                parts.append(str(part["text"]))
        return " ".join(parts).strip()
    return str(content or "")


def _parse_tool_payload(message) -> dict | None:
    text_value = _message_content_as_text(message).strip()
    if not text_value:
        return None
    try:
        payload = json.loads(text_value)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _latest_tool_error(messages: list) -> dict | None:
    """
    Return latest tool error payload, or None if latest tool result is success/unknown.
    """
    for message in reversed(messages):
        if getattr(message, "type", "") != "tool":
            continue
        payload = _parse_tool_payload(message)
        if isinstance(payload, dict) and payload.get("ok") is False:
            err = payload.get("error") or {}
            code = err.get("code") if isinstance(err, dict) else None
            msg = err.get("message") if isinstance(err, dict) else str(err)
            return {"code": code, "message": msg}
        return None
    return None


def _latest_failed_tool_call(messages: list) -> dict | None:
    """
    Return the most recent failed tool call details (name/args), if recoverable.
    """
    failed_tool_call_id = None
    latest_error = None
    for message in reversed(messages):
        if getattr(message, "type", "") != "tool":
            continue
        payload = _parse_tool_payload(message)
        if isinstance(payload, dict) and payload.get("ok") is False:
            failed_tool_call_id = str(getattr(message, "tool_call_id", "") or "")
            latest_error = (
                payload.get("error") if isinstance(payload.get("error"), dict) else {}
            )
            break
        return None

    if not failed_tool_call_id:
        return None

    for message in reversed(messages):
        if getattr(message, "type", "") != "ai":
            continue
        for call in getattr(message, "tool_calls", None) or []:
            call_id = str(
                call.get("id")
                if isinstance(call, dict)
                else getattr(call, "id", "") or ""
            )
            if call_id != failed_tool_call_id:
                continue
            name = (
                call.get("name")
                if isinstance(call, dict)
                else getattr(call, "name", None)
            )
            args = (
                call.get("args")
                if isinstance(call, dict)
                else getattr(call, "args", None)
            )
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            if not isinstance(args, dict):
                args = {}
            if not name:
                return None
            try:
                signature = (
                    f"{name}:{json.dumps(args, sort_keys=True, separators=(',', ':'))}"
                )
            except Exception:
                signature = f"{name}:{str(args)}"
            return {
                "name": name,
                "args": args,
                "error_code": (latest_error or {}).get("code"),
                "error_message": (latest_error or {}).get("message"),
                "signature": signature,
            }
    return None


def _is_empty_success_payload(payload: dict) -> bool:
    if payload.get("ok") is not True:
        return False
    data = payload.get("data")
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}

    # Explicit count-based hints returned by many tools.
    for key in (
        "row_count",
        "item_count",
        "url_count",
        "combined_count",
        "web_count",
        "news_count",
    ):
        if key in meta:
            try:
                if int(meta.get(key)) == 0:
                    return True
            except Exception:
                pass

    # Generic emptiness fallback.
    if data is None:
        return True
    if isinstance(data, (list, tuple, set)):
        if len(data) == 0:
            return True
    if isinstance(data, dict):
        if not data:
            return True
        # For structured containers like {"combined": [], "web": [], "news": []}
        vals = list(data.values())
        if vals and all(
            (
                v is None
                or (isinstance(v, (list, tuple, set, dict, str)) and len(v) == 0)
            )
            for v in vals
        ):
            return True
    if isinstance(data, str):
        return data.strip() == ""
    if (
        isinstance(data, list)
        and data
        and _looks_like_zero_aggregate_sql_payload(payload)
    ):
        return True
    return False


def _is_zero_like_scalar(value) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return value is False
    if isinstance(value, (int, float)):
        return float(value) == 0.0
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized in {"", "0", "0.0", "0.00", "null", "none"}
    return False


def _looks_like_zero_aggregate_sql_payload(payload: dict) -> bool:
    """
    Detect aggregate-style SQL responses that return only zero-like values.
    This catches COUNT/SUM style rows like [{"n": 0}] that often indicate an
    over-filtered query and should be retried once before concluding no data.
    """
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    query = str(meta.get("executed_query") or "").lower()
    if not query:
        return False
    if not any(fn in query for fn in ("count(", "sum(", "avg(", "min(", "max(")):
        return False

    data = payload.get("data")
    if not isinstance(data, list) or len(data) != 1:
        return False
    row = data[0]
    if not isinstance(row, dict) or not row:
        return False
    return all(_is_zero_like_scalar(v) for v in row.values())


def _latest_empty_success_tool_call(messages: list) -> dict | None:
    """
    Return latest tool call details when the tool succeeded but returned empty data.
    """
    empty_tool_call_id = None
    for message in reversed(messages):
        if getattr(message, "type", "") != "tool":
            continue
        payload = _parse_tool_payload(message)
        if not isinstance(payload, dict):
            return None
        if _is_empty_success_payload(payload):
            empty_tool_call_id = str(getattr(message, "tool_call_id", "") or "")
            break
        return None

    if not empty_tool_call_id:
        return None

    for message in reversed(messages):
        if getattr(message, "type", "") != "ai":
            continue
        for call in getattr(message, "tool_calls", None) or []:
            call_id = str(
                call.get("id")
                if isinstance(call, dict)
                else getattr(call, "id", "") or ""
            )
            if call_id != empty_tool_call_id:
                continue
            name, args = _tool_call_name_and_args(call)
            if not name:
                return None
            try:
                signature = (
                    f"{name}:{json.dumps(args, sort_keys=True, separators=(',', ':'))}"
                )
            except Exception:
                signature = f"{name}:{str(args)}"
            return {
                "name": name,
                "args": args,
                "signature": signature,
            }
    return None


def _is_correctable_tool_error(error_code: str | None) -> bool:
    return str(error_code or "").strip().upper() in CORRECTABLE_ERROR_CODES


def _ai_first_tool_call_signature(message) -> str | None:
    if getattr(message, "type", "") != "ai":
        return None
    calls = getattr(message, "tool_calls", None) or []
    if not calls:
        return None
    call = calls[0]
    name, args = _tool_call_name_and_args(call)
    if not name:
        return None
    try:
        return f"{name}:{json.dumps(args, sort_keys=True, separators=(',', ':'))}"
    except Exception:
        return f"{name}:{str(args)}"


def _latest_human_index(messages: list) -> int:
    for idx in range(len(messages) - 1, -1, -1):
        if getattr(messages[idx], "type", "") in {"human", "user"}:
            return idx
    return -1


def _messages_since_latest_human(messages: list) -> list:
    start = _latest_human_index(messages) + 1
    return list(messages[start:])


def _normalize_rel_path(value: str) -> str:
    return str(value or "").strip().lstrip("./").lower()


def _tool_call_name_and_args(call) -> tuple[str | None, dict]:
    if isinstance(call, dict):
        name = call.get("name")
        args = call.get("args")
    else:
        name = getattr(call, "name", None)
        args = getattr(call, "args", None)
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = {}
    if not isinstance(args, dict):
        args = {}
    return name, args


def _turn_has_schema_reference_read(messages: list) -> bool:
    expected = _normalize_rel_path(SCHEMA_PREFLIGHT_PATH)
    for message in _messages_since_latest_human(messages):
        if getattr(message, "type", "") != "ai":
            continue
        for call in getattr(message, "tool_calls", None) or []:
            name, args = _tool_call_name_and_args(call)
            if name != "read_file":
                continue
            path_value = _normalize_rel_path(str(args.get("path", "")))
            if path_value.endswith(expected):
                return True
    return False


def _turn_used_any_tools(messages: list, names: set[str]) -> bool:
    for message in _messages_since_latest_human(messages):
        if getattr(message, "type", "") != "ai":
            continue
        for call in getattr(message, "tool_calls", None) or []:
            name, _ = _tool_call_name_and_args(call)
            if name in names:
                return True
    return False


def _answer_rewrite_attempts(messages: list) -> int:
    attempts = 0
    for message in _messages_since_latest_human(messages):
        if getattr(message, "type", "") != "system":
            continue
        msg_id = str(getattr(message, "id", "") or "")
        if msg_id.startswith(ANSWER_REWRITE_MSG_ID_PREFIX):
            attempts += 1
    return attempts


def _tool_error_retry_attempts(messages: list) -> int:
    start_idx = _latest_human_index(messages) + 1
    attempts = 0
    for message in messages[start_idx:]:
        if getattr(message, "type", "") != "system":
            continue
        msg_id = str(getattr(message, "id", "") or "")
        if msg_id.startswith(TOOL_ERROR_RETRY_MSG_ID_PREFIX):
            attempts += 1
    return attempts


def _diagnostic_exists_since_last_tool(messages: list) -> bool:
    """Check if a diagnostic SystemMessage was already injected since the
    last ToolMessage.  Walk backwards from the end of the message list."""
    for msg in reversed(messages):
        msg_type = getattr(msg, "type", "")
        if msg_type == "tool":
            # Reached the last tool result without finding a diagnostic
            return False
        if msg_type == "system":
            msg_id = str(getattr(msg, "id", "") or "")
            if msg_id.startswith(TOOL_ERROR_RETRY_MSG_ID_PREFIX):
                return True
    return False


def _max_tool_error_retries() -> int:
    cfg = get_config().get_agent_v2_retry_config()
    try:
        return max(0, int(cfg.get("max_tool_error_retries", 1)))
    except Exception:
        return 1


def _conversation_messages(state: AgentV2State, include_tool: bool = False) -> list:
    messages = state.get("messages", [])
    excluded = {"system"} if include_tool else {"system", "tool"}
    return [m for m in messages if getattr(m, "type", "") not in excluded]


def _ai_tool_call_ids(message) -> set[str]:
    ids: set[str] = set()
    for call in getattr(message, "tool_calls", None) or []:
        if isinstance(call, dict):
            call_id = call.get("id")
        else:
            call_id = getattr(call, "id", None)
        if call_id:
            ids.add(str(call_id))
    return ids


def _sanitize_tool_sequence(messages: list) -> list:
    """
    Ensure tool messages are only kept when paired with a preceding AI tool_calls message.
    This prevents API contract violations when context trimming cuts message boundaries.
    """
    sanitized: list = []
    pending_ai = None
    pending_tool_ids: set[str] = set()
    pending_tool_messages: list = []
    for message in messages:
        msg_type = getattr(message, "type", "")
        if msg_type == "ai":
            # Drop prior dangling assistant(tool_calls) blocks.
            pending_ai = None
            pending_tool_ids = set()
            pending_tool_messages = []

            tool_ids = _ai_tool_call_ids(message)
            if tool_ids:
                pending_ai = message
                pending_tool_ids = set(tool_ids)
            else:
                sanitized.append(message)
            continue
        if msg_type == "tool":
            tool_call_id = getattr(message, "tool_call_id", None)
            if not pending_ai or not pending_tool_ids or not tool_call_id:
                continue
            tool_call_id = str(tool_call_id)
            if tool_call_id not in pending_tool_ids:
                continue
            pending_tool_messages.append(message)
            pending_tool_ids.discard(tool_call_id)
            if not pending_tool_ids:
                sanitized.append(pending_ai)
                sanitized.extend(pending_tool_messages)
                pending_ai = None
                pending_tool_messages = []
            continue
        # Non-tool message breaks a pending tool-call block; drop that block.
        pending_ai = None
        pending_tool_ids = set()
        pending_tool_messages = []
        sanitized.append(message)
    return sanitized


def _recent_dialogue(messages: list, window: int = RECENT_MESSAGES_WINDOW) -> list:
    if len(messages) <= window:
        return _sanitize_tool_sequence(list(messages))

    start_idx = len(messages) - window
    # Do not start the slice at a tool message; pull left to include its parent AI tool_calls message.
    while start_idx > 0 and getattr(messages[start_idx], "type", "") == "tool":
        start_idx -= 1
    return _sanitize_tool_sequence(list(messages[start_idx:]))


def _messages_for_model(state: AgentV2State) -> list:
    all_messages = state.get("messages", [])
    # IMPORTANT: include tool messages so every assistant tool_call has
    # corresponding tool responses in subsequent model invocations.
    dialogue = _conversation_messages(state, include_tool=True)
    selected: list = []

    # Keep the latest base/runtime system guidance.
    latest_by_id: dict[str, object] = {}
    for message in all_messages:
        if getattr(message, "type", "") != "system":
            continue
        msg_id = getattr(message, "id", None)
        if msg_id in {"agent-v2-system-prompt", "agent-v2-runtime-context"}:
            latest_by_id[msg_id] = message
    if "agent-v2-system-prompt" in latest_by_id:
        selected.append(latest_by_id["agent-v2-system-prompt"])
    if "agent-v2-runtime-context" in latest_by_id:
        selected.append(latest_by_id["agent-v2-runtime-context"])

    # Keep per-turn control directives (retry/answer rewrite) so the next model
    # invocation can actually follow them.
    latest_human_idx = _latest_human_index(all_messages)
    for message in all_messages[latest_human_idx + 1 :]:
        if getattr(message, "type", "") != "system":
            continue
        msg_id = str(getattr(message, "id", "") or "")
        if msg_id.startswith(TOOL_ERROR_RETRY_MSG_ID_PREFIX) or msg_id.startswith(
            ANSWER_REWRITE_MSG_ID_PREFIX
        ):
            selected.append(message)

    summary_text = str(state.get("summary") or "").strip()
    if summary_text:
        selected.append(
            SystemMessage(
                content=(
                    f"Conversation memory summary (older context):\n{summary_text}"
                ),
                id="agent-v2-memory-summary",
            )
        )

    selected.extend(_recent_dialogue(dialogue))
    return selected


def _looks_like_code_submission(text_value: str) -> bool:
    txt = (text_value or "").strip()
    if not txt:
        return False
    lowered = txt.lower()

    if "```python" in lowered or "```py" in lowered or "```sql" in lowered:
        return True

    if re.search(r"\bselect\b[\s\S]{0,240}\bfrom\b", lowered):
        return True
    if re.search(
        r"^\s*(with|select|insert|update|delete|create|drop|alter)\b", lowered
    ):
        return True

    py_patterns = [
        r"^\s*import\s+[a-zA-Z_][\w.]*",
        r"^\s*from\s+[a-zA-Z_][\w.]*\s+import\s+",
        r"^\s*def\s+[a-zA-Z_]\w*\s*\(",
        r"^\s*class\s+[A-Z][A-Za-z0-9_]*\s*[:(]",
        r"^\s*for\s+.+\s+in\s+.+:",
        r"^\s*while\s+.+:",
        r"^\s*if\s+.+:",
        r"^\s*print\s*\(",
    ]
    return any(
        re.search(pattern, txt, flags=re.IGNORECASE | re.MULTILINE)
        for pattern in py_patterns
    )


def classify_intent(state: AgentV2State, config: RunnableConfig) -> dict:
    _ = config
    text_value = _latest_user_text(state.get("messages", []))
    lowered = text_value.lower()

    intent_labels: list[str] = []
    disallow_execute_code = _looks_like_code_submission(text_value)
    if disallow_execute_code:
        intent_labels.append("execute_code")

    if _contains_any(
        lowered,
        (
            "analyze",
            "analysis",
            "trend",
            "correlation",
            "distribution",
            "z score",
            "z-score",
            "compare",
            "summary",
        ),
    ):
        intent_labels.append("data_analysis")

    if _contains_any(
        lowered,
        ("alert", "ticker", "isin", "trade type", "status", "news item", "article"),
    ):
        intent_labels.append("alert_analysis")

    if _contains_any(
        lowered,
        ("methodology", "method", "framework", "definition", "explain score", "how is"),
    ):
        intent_labels.append("methodology_discussion")

    if not intent_labels:
        intent_labels.append("other")
    elif len(intent_labels) > 1:
        intent_labels.append("mixed")

    # Preserve first occurrence order and remove duplicates.
    deduped_labels = list(dict.fromkeys(intent_labels))
    return {
        "intent_labels": deduped_labels,
        "disallow_execute_code": disallow_execute_code,
    }


def route_after_intent(
    state: AgentV2State,
) -> Literal["reject_execute_code", "summarize_and_trim"]:
    return (
        "reject_execute_code"
        if state.get("disallow_execute_code")
        else "summarize_and_trim"
    )


def reject_execute_code_node(state: AgentV2State, config: RunnableConfig):
    _ = config
    _ = state
    return {
        "messages": [
            AIMessage(
                content=(
                    "I can't process submitted SQL or Python code. "
                    "Please describe your objective in plain language, and I can help with analysis steps or findings."
                )
            )
        ],
        "route": "direct",
    }


def summarize_and_trim_node(state: AgentV2State, config: RunnableConfig) -> dict:
    _ = config
    dialogue = _conversation_messages(state)
    if len(dialogue) <= RECENT_MESSAGES_WINDOW:
        return {}

    total_est_tokens = sum(_estimate_tokens(_message_text(m)) for m in dialogue)
    if total_est_tokens < SUMMARY_TRIGGER_TOKENS_EST:
        return {}

    older_messages = dialogue[:-RECENT_MESSAGES_WINDOW]
    if not older_messages:
        return {}

    existing_summary = str(state.get("summary") or "").strip()
    transcript = "\n".join(
        f"{getattr(m, 'type', 'message').upper()}: {_message_text(m)}"
        for m in older_messages
        if _message_text(m)
    )
    if not transcript.strip():
        return {}

    llm = get_llm_model()
    summary_response = llm.invoke(
        [
            SystemMessage(
                content=(
                    "Summarize the older conversation context for memory compression. "
                    "Keep only durable facts: user goals, constraints, key findings, assumptions, "
                    "and unresolved questions. Omit small talk and verbosity. "
                    "Return concise markdown bullet points."
                )
            ),
            HumanMessage(
                content=(
                    "Existing summary:\n"
                    f"{existing_summary or '(none)'}\n\n"
                    "Older transcript to fold into summary:\n"
                    f"{transcript}"
                )
            ),
        ]
    )
    new_summary = _message_text(summary_response)
    if not new_summary:
        return {}
    return {"summary": new_summary}


def plan_request(state: AgentV2State, config: RunnableConfig) -> dict:
    _ = config
    text_value = _latest_user_text(state.get("messages", []))

    needs_web = _contains_any(
        text_value,
        ("web", "internet", "online", "external", "latest news", "search"),
    )
    needs_kb = _contains_any(
        text_value,
        ("methodology", "method", "framework", "definition", "explain score", "why"),
    )
    needs_db = _contains_any(
        text_value,
        (
            "alert",
            "article",
            "sql",
            "database",
            "table",
            "ticker",
            "isin",
            "status",
            "count",
        ),
    )
    needs_report = _contains_any(
        text_value,
        ("report", "download", "export", "pdf", "artifact"),
    )
    needs_compute = _contains_any(
        text_value,
        ("calculate", "compute", "correlation", "regression", "python", "simulate"),
    )

    direct_smalltalk = _contains_any(
        text_value,
        ("hello", "hi", "thanks", "thank you", "who are you"),
    ) and not (needs_db or needs_kb or needs_web or needs_report or needs_compute)

    # Temporary simplification: for non-smalltalk requests, expose full toolset.
    # This disables dynamic tool gating and makes planner failures less likely.
    active_tool_names: list[str] = (
        [] if direct_smalltalk else list(TOOL_REGISTRY.keys())
    )

    active_tool_names = [
        name for name in dict.fromkeys(active_tool_names) if name in TOOL_REGISTRY
    ]

    route = "direct" if direct_smalltalk else "agent"
    reason = (
        f"needs_db={needs_db}, needs_kb={needs_kb}, needs_web={needs_web}, "
        f"needs_compute={needs_compute}, needs_report={needs_report}, "
        f"route={route}, tool_mode={'all_tools' if not direct_smalltalk else 'direct'}"
    )
    return {
        "route": route,
        "planner_reason": reason,
        "needs_db": needs_db,
        "needs_kb": needs_kb,
        "needs_web": needs_web,
        "active_tool_names": active_tool_names,
    }


def load_context(state: AgentV2State, config: RunnableConfig) -> dict:
    _ = config
    loaded_context: dict[str, str] = {}
    context_lines: list[str] = []

    if state.get("needs_db"):
        loaded_context["db"] = (
            "DB querying is available and schema reference docs are available in artifacts."
        )
        context_lines.append("- DB context is available.")

    if state.get("needs_kb"):
        loaded_context["kb"] = (
            "Filesystem tools are available within configured allowed directories."
        )
        context_lines.append("- Document context is available.")

    if state.get("needs_web"):
        loaded_context["web"] = "Web/news search and scraping tools are available."
        context_lines.append("- Web context is available.")

    # Automatically expose Python runtime capabilities from config so the model
    # knows what libraries/imports are actually allowed.
    py_cfg = get_config().get_agent_v2_safe_py_runner_config()
    py_enabled = bool(py_cfg.get("enabled", False))
    if py_enabled:
        blocked_imports = [
            str(x).strip() for x in py_cfg.get("blocked_imports", []) if str(x).strip()
        ]
        blocked_builtins = [
            str(x).strip() for x in py_cfg.get("blocked_builtins", []) if str(x).strip()
        ]
        loaded_context["python"] = (
            "Python execution is available with policy constraints."
        )
        context_lines.append("- Python runtime is enabled.")
        context_lines.append(
            "- Blocked python imports: "
            + (", ".join(blocked_imports) if blocked_imports else "(none)")
        )
        context_lines.append(
            "- Blocked python builtins: "
            + (", ".join(blocked_builtins) if blocked_builtins else "(none)")
        )
    else:
        context_lines.append("- Python runtime is disabled in config.")

    if not context_lines:
        context_lines.append("- No extra context preloaded for this request.")

    runtime_context = (
        "Planner summary:\n"
        f"{state.get('planner_reason', '')}\n"
        "Runtime context:\n" + "\n".join(context_lines)
    )

    return {
        "loaded_context": loaded_context,
        "messages": [
            SystemMessage(content=runtime_context, id="agent-v2-runtime-context")
        ],
    }


def route_after_plan(
    state: AgentV2State,
) -> Literal["direct_answer", "schema_preflight"]:
    return "direct_answer" if state.get("route") == "direct" else "schema_preflight"


def direct_answer_node(state: AgentV2State, config: RunnableConfig):
    _ = config
    llm = get_llm_model()
    response = llm.invoke(_messages_for_model(state))
    return {"messages": [response]}


def schema_preflight_node(state: AgentV2State, config: RunnableConfig):
    _ = config
    messages = state.get("messages", [])
    if not state.get("needs_db"):
        return {"needs_schema_preflight": False}
    if _turn_has_schema_reference_read(messages):
        return {"needs_schema_preflight": False}

    return {
        "needs_schema_preflight": True,
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": f"call_{uuid4().hex[:12]}",
                        "name": "read_file",
                        "args": {"path": SCHEMA_PREFLIGHT_PATH},
                    }
                ],
            )
        ],
    }


def route_after_schema_preflight(state: AgentV2State) -> Literal["tools", "agent"]:
    return "tools" if state.get("needs_schema_preflight") else "agent"


def agent_node(state: AgentV2State, config: RunnableConfig):
    _ = config
    llm = get_llm_model()
    model_messages = _messages_for_model(state)
    active_names = state.get("active_tool_names") or []
    selected_tools = [
        TOOL_REGISTRY[name] for name in active_names if name in TOOL_REGISTRY
    ]
    if selected_tools:
        response = llm.bind_tools(selected_tools).invoke(model_messages)
    else:
        response = llm.invoke(model_messages)
    return {"messages": [response]}


def should_continue(
    state: AgentV2State,
) -> Literal["tools", "diagnose_empty_result", "validate_answer", "__end__"]:
    messages = state["messages"]
    if not messages:
        return "__end__"
    last_message = messages[-1]
    failed_call = _latest_failed_tool_call(messages)
    empty_call = _latest_empty_success_tool_call(messages)
    latest_error = _latest_tool_error(messages) or {}
    error_code = latest_error.get("code")
    can_correct = _is_correctable_tool_error(error_code)
    attempts = _tool_error_retry_attempts(messages)
    if getattr(last_message, "tool_calls", None):
        if failed_call and can_correct:
            if attempts < _max_tool_error_retries():
                new_sig = _ai_first_tool_call_signature(last_message)
                if new_sig and new_sig == failed_call.get("signature"):
                    return "diagnose_empty_result"
        if empty_call and attempts < _max_tool_error_retries():
            new_sig = _ai_first_tool_call_signature(last_message)
            if new_sig and new_sig == empty_call.get("signature"):
                return "diagnose_empty_result"
        return "tools"
    # -- Text-only response (LLM did NOT issue tool calls) ----------------
    # Only route to diagnose if the LLM has NOT already seen a diagnostic
    # message for this empty/error result.  If a diagnostic was injected
    # and the LLM still responded with text, it means it won't comply –
    # accept the answer instead of looping.
    diagnostic_already_given = _diagnostic_exists_since_last_tool(messages)
    if not diagnostic_already_given:
        if failed_call and can_correct and attempts < _max_tool_error_retries():
            return "diagnose_empty_result"
        if empty_call and attempts < _max_tool_error_retries():
            return "diagnose_empty_result"
    if failed_call:
        return "__end__"
    return "validate_answer"


# ---------------------------------------------------------------------------
#  Diagnostic helpers for empty / error tool results
# ---------------------------------------------------------------------------


def _extract_sql_filters(query: str) -> list[dict]:
    """Extract table names and WHERE-clause column/value pairs from SQL."""
    filters: list[dict] = []
    table_match = re.search(r'\bFROM\s+["\']?([\w]+)["\']?', query, re.IGNORECASE)
    if not table_match:
        return filters
    table_name = table_match.group(1)

    where_match = re.search(
        r"\bWHERE\b(.+?)(?:\bGROUP\b|\bORDER\b|\bLIMIT\b|\bHAVING\b|$)",
        query,
        re.IGNORECASE | re.DOTALL,
    )
    if not where_match:
        return filters

    where_clause = where_match.group(1)
    # Match: col = 'val', "col" = 'val', col LIKE 'val%', etc.
    pattern = (
        r"(?:^|\bAND\b|\bOR\b)\s*"
        r'["\']?([a-zA-Z_][a-zA-Z0-9_ ]*?[a-zA-Z0-9_]|[a-zA-Z_][a-zA-Z0-9_]*)["\']?'
        r"\s*(?:=|LIKE|>=|<=|>|<)\s*"
        r"'([^']*)'"
    )
    for match in re.finditer(pattern, where_clause, re.IGNORECASE):
        col_name = match.group(1).strip().strip("\"'")
        value = match.group(2).strip()
        filters.append({"table": table_name, "column": col_name, "value": value})
    return filters


def _resolve_physical_column(table_name: str, col_name: str) -> str:
    """Resolve a column name to its physical DB column name via config."""
    try:
        cfg = get_config()
        tables_cfg = cfg._config.get("tables", {})
        for key, table_info in tables_cfg.items():
            if not isinstance(table_info, dict):
                continue
            actual_table = table_info.get("name", key)
            if (
                actual_table.lower() != table_name.lower()
                and key.lower() != table_name.lower()
            ):
                continue
            columns = table_info.get("columns", {})
            for logical, physical in columns.items():
                if (
                    logical.lower() == col_name.lower()
                    or str(physical).lower() == col_name.lower()
                ):
                    return str(physical) if physical else col_name
            break
    except Exception:
        pass
    return col_name


def _run_sample_query(table_name: str, column_name: str, limit: int = 5) -> list[str]:
    """Run SELECT DISTINCT to discover actual data formats."""
    try:
        engine = get_engine()
        quoted_col = f'"{column_name}"'
        quoted_table = f'"{table_name}"'
        sql = (
            f"SELECT DISTINCT {quoted_col} FROM {quoted_table} "
            f"WHERE {quoted_col} IS NOT NULL "
            f"ORDER BY {quoted_col} DESC LIMIT {limit}"
        )
        with engine.connect() as conn:
            result = conn.execute(sa_text(sql))
            return [str(row[0]) for row in result.fetchall()]
    except Exception:
        return []


def _diagnose_empty_sql(call_info: dict) -> str:
    """Analyse an empty SQL result by inspecting the DB for format hints."""
    query = (call_info.get("args") or {}).get("query", "")
    if not query:
        return (
            "The SQL query returned no results. "
            "You MUST issue a corrected execute_sql tool call with adjusted filters."
        )

    filters = _extract_sql_filters(query)
    if not filters:
        return (
            f"The SQL query returned no results: `{query}`. "
            "Try broadening filters, changing date formats (DATE() or LIKE), "
            "or removing restrictive conditions. "
            "You MUST issue a corrected execute_sql tool call."
        )

    hints: list[str] = []
    for f in filters:
        physical_col = _resolve_physical_column(f["table"], f["column"])
        samples = _run_sample_query(f["table"], physical_col)
        if not samples and physical_col != f["column"]:
            samples = _run_sample_query(f["table"], f["column"])
        if samples:
            sample_str = ", ".join(f"`{s}`" for s in samples[:5])
            hints.append(
                f"Column `{f['column']}` (DB name: `{physical_col}`) "
                f"has sample values: [{sample_str}]. "
                f"Your filter used `{f['value']}`."
            )

    if hints:
        hint_text = " | ".join(hints)
        return (
            f"The SQL query returned no results. Diagnostic: {hint_text}. "
            "Adjust your query to match the actual data format "
            "(e.g. DATE() function, LIKE with wildcards, or different value). "
            "You MUST issue a corrected execute_sql tool call — do NOT respond with text only."
        )

    return (
        f"The SQL query returned no results: `{query}`. "
        "Try DATE() for date comparisons, LIKE for partial matches, "
        "or relax the filters. "
        "You MUST issue a corrected execute_sql tool call — do NOT respond with text only."
    )


def _diagnose_tool_error(call_info: dict) -> str:
    """Provide specific fix guidance for tool errors."""
    error_code = call_info.get("error_code") or "UNKNOWN_ERROR"
    error_message = call_info.get("error_message") or "Tool returned an error."
    tool_name = call_info.get("name") or "tool"

    extra = ""
    if tool_name == "execute_python":
        low = error_message.lower()
        if "keyerror" in low:
            extra = (
                " This is a KeyError — the key/column you accessed does not exist "
                "in the data. Check the actual keys in input_data before accessing them."
            )
        elif "typeerror" in low:
            extra = (
                " This is a TypeError — check your data types and add explicit "
                "type conversions (int(), float(), str()) where needed."
            )
        elif "modulenotfounderror" in low or "import" in low:
            extra = (
                " An import failed — check get_python_capabilities to see which "
                "modules are available in the sandbox."
            )
        elif "nameerror" in low:
            extra = (
                " A variable name was not defined — ensure all variables are "
                "assigned before use and that you read inputs from `input_data`."
            )

    return (
        f"The previous `{tool_name}` call failed. "
        f"Error code: {error_code}. Error: {error_message}.{extra} "
        "Issue a corrected tool call with revised inputs. "
        "Do NOT repeat the exact same arguments."
    )


def _diagnose_empty_python(call_info: dict, messages: list) -> str:
    """Provide guidance when execute_python returned empty/None result."""
    code = (call_info.get("args") or {}).get("code", "")
    code_preview = code[:200] + "..." if len(code) > 200 else code
    return (
        f"The previous execute_python call returned an empty result. "
        f"Code preview: `{code_preview}`. "
        "Common causes: the `result` variable was not assigned, "
        "or the data filtering produced an empty DataFrame/list. "
        "Verify the input data structure, check column names, and ensure "
        "`result` is assigned a value. "
        "You MUST issue a corrected execute_python tool call — do NOT respond with text only."
    )


def _diagnose_empty_generic(call_info: dict) -> str:
    """Fallback guidance for other tools returning empty results."""
    tool_name = call_info.get("name") or "tool"
    return (
        f"The previous `{tool_name}` call returned an empty result. "
        "Try adjusting your query/inputs with different terms or relaxed filters. "
        "You MUST issue a corrected tool call — do NOT respond with text only."
    )


def diagnose_empty_result_node(state: AgentV2State, config: RunnableConfig):
    """Inspect empty/error tool results, run diagnostics, and give the LLM
    concrete, data-driven retry instructions."""
    _ = config
    messages = state.get("messages", [])
    failed_call = _latest_failed_tool_call(messages)
    empty_call = _latest_empty_success_tool_call(messages)
    if not failed_call and not empty_call:
        return {}

    attempts = _tool_error_retry_attempts(messages)
    next_attempt = attempts + 1

    if failed_call:
        content = _diagnose_tool_error(failed_call)
    else:
        tool_name = (empty_call or {}).get("name", "")
        if tool_name == "execute_sql":
            content = _diagnose_empty_sql(empty_call)
        elif tool_name == "execute_python":
            content = _diagnose_empty_python(empty_call, messages)
        else:
            content = _diagnose_empty_generic(empty_call)

    return {
        "messages": [
            SystemMessage(
                content=content,
                id=f"{TOOL_ERROR_RETRY_MSG_ID_PREFIX}{next_attempt}",
            ),
        ]
    }


def validate_answer_node(state: AgentV2State, config: RunnableConfig):
    _ = config
    messages = state.get("messages", [])
    if not messages:
        return {"needs_answer_rewrite": False}
    last_message = messages[-1]
    if getattr(last_message, "type", "") != "ai":
        return {"needs_answer_rewrite": False}
    if getattr(last_message, "tool_calls", None):
        return {"needs_answer_rewrite": False}
    if not _turn_used_any_tools(messages, {"execute_sql", "execute_python"}):
        return {"needs_answer_rewrite": False}

    # Skip validation if the last tool call returned empty — the answer
    # is inherently "no data" and rewriting won't add value.
    if _latest_empty_success_tool_call(messages):
        return {"needs_answer_rewrite": False}

    text_value = _message_content_as_text(last_message).lower()
    required_markers = [
        "method",
        "schema/data assumption",
        "data-type",
        "check",
        "limitation",
    ]
    has_all = all(marker in text_value for marker in required_markers)
    if has_all:
        return {"needs_answer_rewrite": False}

    attempts = _answer_rewrite_attempts(messages)
    if attempts >= 1:
        return {"needs_answer_rewrite": False}

    return {
        "needs_answer_rewrite": True,
        "messages": [
            SystemMessage(
                content=(
                    "Revise the previous answer to include explicit sections with short headings: "
                    "Method Used, Schema/Data Assumptions, Data-Type Handling, Checks Performed, Limitations. "
                    "Keep it concise and evidence-based."
                ),
                id=f"{ANSWER_REWRITE_MSG_ID_PREFIX}{attempts + 1}",
            )
        ],
    }


def route_after_validate_answer(state: AgentV2State) -> Literal["agent", "__end__"]:
    return "agent" if state.get("needs_answer_rewrite") else "__end__"


def build_graph():
    tool_node = ToolNode(ALL_TOOLS)

    workflow = StateGraph(AgentV2State)
    workflow.add_node("ensure_system_prompt", ensure_system_prompt)
    workflow.add_node("classify_intent", classify_intent)
    workflow.add_node("reject_execute_code", reject_execute_code_node)
    workflow.add_node("summarize_and_trim", summarize_and_trim_node)
    workflow.add_node("plan_request", plan_request)
    workflow.add_node("load_context", load_context)
    workflow.add_node("direct_answer", direct_answer_node)
    workflow.add_node("schema_preflight", schema_preflight_node)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)
    workflow.add_node("diagnose_empty_result", diagnose_empty_result_node)
    workflow.add_node("validate_answer", validate_answer_node)

    workflow.add_edge(START, "ensure_system_prompt")
    workflow.add_edge("ensure_system_prompt", "classify_intent")
    workflow.add_conditional_edges("classify_intent", route_after_intent)
    workflow.add_edge("reject_execute_code", END)
    workflow.add_edge("summarize_and_trim", "plan_request")
    workflow.add_edge("plan_request", "load_context")
    workflow.add_conditional_edges("load_context", route_after_plan)
    workflow.add_edge("direct_answer", END)
    workflow.add_conditional_edges("schema_preflight", route_after_schema_preflight)
    workflow.add_conditional_edges("agent", should_continue)
    workflow.add_edge("tools", "agent")
    workflow.add_edge("diagnose_empty_result", "agent")
    workflow.add_conditional_edges("validate_answer", route_after_validate_answer)

    return workflow


workflow = build_graph()
