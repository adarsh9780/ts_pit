from __future__ import annotations

import re
import json
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from .tools import (
    TOOL_REGISTRY,
)
from ..llm import get_llm_model
from ..config import get_config
from .prompts import AGENT_V2_SYSTEM_PROMPT
from .state import AgentV2State

ALL_TOOLS = list(TOOL_REGISTRY.values())
SUMMARY_TRIGGER_TOKENS_EST = 7000
RECENT_MESSAGES_WINDOW = 14
TOOL_ERROR_RETRY_MSG_ID_PREFIX = "agent-v2-tool-error-retry-"
CORRECTABLE_ERROR_CODES = {
    "READ_ONLY_ENFORCED",
    "INVALID_INPUT",
    "TABLE_NOT_FOUND",
    "DB_ERROR",
}


def ensure_system_prompt(state: AgentV2State, config: RunnableConfig) -> dict:
    _ = config
    messages = state.get("messages", [])
    has_system = any(
        isinstance(m, SystemMessage) and getattr(m, "id", None) == "agent-v2-system-prompt"
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
            latest_error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
            break
        return None

    if not failed_tool_call_id:
        return None

    for message in reversed(messages):
        if getattr(message, "type", "") != "ai":
            continue
        for call in (getattr(message, "tool_calls", None) or []):
            call_id = str(call.get("id") if isinstance(call, dict) else getattr(call, "id", "") or "")
            if call_id != failed_tool_call_id:
                continue
            name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
            args = call.get("args") if isinstance(call, dict) else getattr(call, "args", None)
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
                signature = f"{name}:{json.dumps(args, sort_keys=True, separators=(',', ':'))}"
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


def _is_correctable_tool_error(error_code: str | None) -> bool:
    return str(error_code or "").strip().upper() in CORRECTABLE_ERROR_CODES


def _ai_first_tool_call_signature(message) -> str | None:
    if getattr(message, "type", "") != "ai":
        return None
    calls = getattr(message, "tool_calls", None) or []
    if not calls:
        return None
    call = calls[0]
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
    for call in (getattr(message, "tool_calls", None) or []):
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
    pending_tool_ids: set[str] = set()
    for message in messages:
        msg_type = getattr(message, "type", "")
        if msg_type == "ai":
            pending_tool_ids = _ai_tool_call_ids(message)
            sanitized.append(message)
            continue
        if msg_type == "tool":
            tool_call_id = getattr(message, "tool_call_id", None)
            if not pending_tool_ids or not tool_call_id:
                continue
            tool_call_id = str(tool_call_id)
            if tool_call_id not in pending_tool_ids:
                continue
            sanitized.append(message)
            pending_tool_ids.discard(tool_call_id)
            continue
        pending_tool_ids = set()
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

    summary_text = str(state.get("summary") or "").strip()
    if summary_text:
        selected.append(
            SystemMessage(
                content=(
                    "Conversation memory summary (older context):\n"
                    f"{summary_text}"
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
    if re.search(r"^\s*(with|select|insert|update|delete|create|drop|alter)\b", lowered):
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
    return any(re.search(pattern, txt, flags=re.IGNORECASE | re.MULTILINE) for pattern in py_patterns)


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
        ("analyze", "analysis", "trend", "correlation", "distribution", "z score", "z-score", "compare", "summary"),
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


def route_after_intent(state: AgentV2State) -> Literal["reject_execute_code", "summarize_and_trim"]:
    return "reject_execute_code" if state.get("disallow_execute_code") else "summarize_and_trim"


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
        ("alert", "article", "sql", "database", "table", "ticker", "isin", "status", "count"),
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
    active_tool_names: list[str] = [] if direct_smalltalk else list(TOOL_REGISTRY.keys())

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
        loaded_context["db"] = "DB querying is available and schema reference docs are available in artifacts."
        context_lines.append("- DB context is available.")

    if state.get("needs_kb"):
        loaded_context["kb"] = "Filesystem tools are available within configured allowed directories."
        context_lines.append("- Document context is available.")

    if state.get("needs_web"):
        loaded_context["web"] = "Web/news search and scraping tools are available."
        context_lines.append("- Web context is available.")

    # Automatically expose Python runtime capabilities from config so the model
    # knows what libraries/imports are actually allowed.
    py_cfg = get_config().get_agent_v2_safe_py_runner_config()
    py_enabled = bool(py_cfg.get("enabled", False))
    if py_enabled:
        blocked_imports = [str(x).strip() for x in py_cfg.get("blocked_imports", []) if str(x).strip()]
        blocked_builtins = [str(x).strip() for x in py_cfg.get("blocked_builtins", []) if str(x).strip()]
        loaded_context["python"] = (
            "Python execution is available with policy constraints."
        )
        context_lines.append(
            "- Python runtime is enabled."
        )
        context_lines.append(
            "- Blocked python imports: " + (", ".join(blocked_imports) if blocked_imports else "(none)")
        )
        context_lines.append(
            "- Blocked python builtins: " + (", ".join(blocked_builtins) if blocked_builtins else "(none)")
        )
    else:
        context_lines.append("- Python runtime is disabled in config.")

    if not context_lines:
        context_lines.append("- No extra context preloaded for this request.")

    runtime_context = (
        "Planner summary:\n"
        f"{state.get('planner_reason', '')}\n"
        "Runtime context:\n"
        + "\n".join(context_lines)
    )

    return {
        "loaded_context": loaded_context,
        "messages": [SystemMessage(content=runtime_context, id="agent-v2-runtime-context")],
    }


def route_after_plan(state: AgentV2State) -> Literal["direct_answer", "agent"]:
    return "direct_answer" if state.get("route") == "direct" else "agent"


def direct_answer_node(state: AgentV2State, config: RunnableConfig):
    _ = config
    llm = get_llm_model()
    response = llm.invoke(_messages_for_model(state))
    return {"messages": [response]}


def agent_node(state: AgentV2State, config: RunnableConfig):
    _ = config
    llm = get_llm_model()
    model_messages = _messages_for_model(state)
    active_names = state.get("active_tool_names") or []
    selected_tools = [TOOL_REGISTRY[name] for name in active_names if name in TOOL_REGISTRY]
    if selected_tools:
        response = llm.bind_tools(selected_tools).invoke(model_messages)
    else:
        response = llm.invoke(model_messages)
    return {"messages": [response]}


def should_continue(state: AgentV2State) -> Literal["tools", "retry_after_tool_error", "__end__"]:
    messages = state["messages"]
    if not messages:
        return "__end__"
    last_message = messages[-1]
    failed_call = _latest_failed_tool_call(messages)
    latest_error = _latest_tool_error(messages) or {}
    error_code = latest_error.get("code")
    can_correct = _is_correctable_tool_error(error_code)
    if getattr(last_message, "tool_calls", None):
        if failed_call and can_correct:
            attempts = _tool_error_retry_attempts(messages)
            if attempts < _max_tool_error_retries():
                new_sig = _ai_first_tool_call_signature(last_message)
                if new_sig and new_sig == failed_call.get("signature"):
                    return "retry_after_tool_error"
        return "tools"
    if failed_call and can_correct:
        attempts = _tool_error_retry_attempts(messages)
        if attempts < _max_tool_error_retries():
            return "retry_after_tool_error"
    return "__end__"


def retry_after_tool_error_node(state: AgentV2State, config: RunnableConfig):
    _ = config
    messages = state.get("messages", [])
    failed_call = _latest_failed_tool_call(messages)
    if not failed_call:
        return {}

    attempts = _tool_error_retry_attempts(messages)
    next_attempt = attempts + 1
    error_code = failed_call.get("error_code") or "UNKNOWN_ERROR"
    error_message = failed_call.get("error_message") or "Tool returned an error payload."
    return {
        "messages": [
            SystemMessage(
                content=(
                    "The previous tool call failed with a correctable error. "
                    f"Error code: {error_code}. Error message: {error_message}. "
                    "Issue a corrected tool call with revised inputs. "
                    "Do not repeat the exact same tool call arguments."
                ),
                id=f"{TOOL_ERROR_RETRY_MSG_ID_PREFIX}{next_attempt}",
            ),
        ]
    }


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
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)
    workflow.add_node("retry_after_tool_error", retry_after_tool_error_node)

    workflow.add_edge(START, "ensure_system_prompt")
    workflow.add_edge("ensure_system_prompt", "classify_intent")
    workflow.add_conditional_edges("classify_intent", route_after_intent)
    workflow.add_edge("reject_execute_code", END)
    workflow.add_edge("summarize_and_trim", "plan_request")
    workflow.add_edge("plan_request", "load_context")
    workflow.add_conditional_edges("load_context", route_after_plan)
    workflow.add_edge("direct_answer", END)
    workflow.add_conditional_edges("agent", should_continue)
    workflow.add_edge("tools", "agent")
    workflow.add_edge("retry_after_tool_error", "agent")

    return workflow


workflow = build_graph()
