from __future__ import annotations

import ast
import json
import re
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langchain_core.messages import AnyMessage, SystemMessage, HumanMessage, AIMessage

from backend.agent_v3.state import AgentV3State, AgentInputSchema
from backend.agent_v3.planning import planner
from backend.agent_v3.prompts import load_chat_prompt
from backend.agent_v3.execution import executioner
from backend.agent_v3.utilis import build_prompt_messages
from backend.llm import get_llm_model

MAX_REPLAN_ATTEMPTS = 1
SUMMARY_TRIGGER_TOKENS = 50_000
SUMMARY_RECENT_MESSAGE_WINDOW = 16
SUMMARY_TEXT_LIMIT = 2500
META_HELP_PATTERNS = (
    "what can you do",
    "help",
    "capabilities",
    "how can you help",
    "what do you do",
)
CODE_RUN_PATTERNS = (
    "run this code",
    "execute this code",
    "can you run this code",
    "execute my code",
)
HARMFUL_PATTERNS = (
    "how to make bomb",
    "make a bomb",
    "build a bomb",
    "kill someone",
    "murder",
    "sexual content involving minors",
    "child sexual",
)
SHELL_COMMAND_PREFIXES = (
    "rm ",
    "rm\t",
    "sudo ",
    "chmod ",
    "chown ",
    "mv ",
    "cp ",
    "curl ",
    "wget ",
    "bash ",
    "sh ",
    "zsh ",
    "powershell ",
    "cmd ",
    "del ",
    "rmdir ",
)
SHELL_META_PATTERNS = (
    "&&",
    "||",
    ";",
    "|",
    "$(",
    "`",
    ">",
    "<",
)
INTENT_CLASSIFIER_SCHEMA: dict[str, Any] = {
    "title": "IntentGuardDecision",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "intent_class": {
            "type": "string",
            "enum": ["task", "meta_help", "blocked_user_code", "blocked_safety"],
        },
        "reason": {"type": "string"},
    },
    "required": ["intent_class", "reason"],
}

try:
    import tiktoken  # type: ignore
except Exception:  # pragma: no cover - optional dependency runtime
    tiktoken = None  # type: ignore


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


def _message_role(message: AnyMessage) -> str:
    msg_type = str(getattr(message, "type", "")).lower()
    if msg_type in {"human", "user"}:
        return "user"
    if msg_type in {"ai", "assistant"}:
        return "assistant"
    if msg_type == "system":
        return "system"
    return msg_type or "message"


def _messages_to_transcript(messages: list[AnyMessage]) -> str:
    lines: list[str] = []
    for message in messages:
        text = _content_to_text(getattr(message, "content", "")).strip()
        if not text:
            continue
        lines.append(f"{_message_role(message)}: {text}")
    return "\n".join(lines)


def _estimate_tokens(text: str) -> int:
    txt = str(text or "")
    if not txt:
        return 0
    if tiktoken is not None:
        try:
            enc = tiktoken.encoding_for_model("gpt-4o-mini")
        except Exception:
            enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(txt))
    # fallback heuristic
    return max(1, len(txt) // 4)


def _estimate_history_tokens(state: AgentV3State) -> int:
    transcript = _messages_to_transcript(state.messages)
    summary = str(state.conversation_summary or "").strip()
    if summary:
        transcript = f"[summary]\n{summary}\n\n{transcript}"
    return _estimate_tokens(transcript)


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


def _latest_user_question(messages: list[AnyMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage) or getattr(message, "type", "") in {
            "human",
            "user",
        }:
            content = _content_to_text(getattr(message, "content", ""))
            if "[USER QUESTION]" in content:
                parts = content.split("[USER QUESTION]", 1)
                if len(parts) > 1:
                    return parts[1].strip()
            return content.strip()
    return ""


def _looks_like_user_code(question: str) -> bool:
    text = str(question or "").strip()
    lowered = text.lower()
    if "```" in text:
        return True
    if re.search(r"\bselect\b[\s\S]{0,240}\bfrom\b", lowered):
        return True
    if _looks_like_python_code(text):
        return True
    if _looks_like_shell_command(text):
        return True
    return False


def _is_meta_help_question(question: str) -> bool:
    lowered = str(question or "").strip().lower()
    if not lowered:
        return False
    return any(pattern in lowered for pattern in META_HELP_PATTERNS)


def _is_code_run_question(question: str) -> bool:
    lowered = str(question or "").strip().lower()
    if any(pattern in lowered for pattern in CODE_RUN_PATTERNS):
        return True
    if _looks_like_shell_command(question):
        return True
    return _looks_like_user_code(question) and ("run" in lowered or "execute" in lowered)


def _is_harmful_question(question: str) -> bool:
    lowered = str(question or "").strip().lower()
    return any(pattern in lowered for pattern in HARMFUL_PATTERNS)


def _strip_code_fences(text: str) -> str:
    txt = str(text or "").strip()
    if txt.startswith("```") and txt.endswith("```"):
        lines = txt.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return txt


def _looks_like_python_code(question: str) -> bool:
    text = _strip_code_fences(question)
    lowered = text.lower()
    if re.search(r"^\s*(def|class|import|from|print|for|while|if)\b", lowered):
        return True
    if re.search(r"[=:()\[\]{}]", text) is None and "\n" not in text:
        return False
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False
    substantial_nodes = (
        ast.Call,
        ast.Assign,
        ast.AnnAssign,
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
        ast.Import,
        ast.ImportFrom,
        ast.For,
        ast.While,
        ast.If,
        ast.With,
        ast.Try,
        ast.Subscript,
        ast.Attribute,
        ast.BinOp,
        ast.Compare,
    )
    return any(isinstance(node, substantial_nodes) for node in ast.walk(tree))


def _looks_like_shell_command(question: str) -> bool:
    text = _strip_code_fences(question)
    lowered = text.lower().strip()
    if not lowered:
        return False
    if any(lowered.startswith(prefix) for prefix in SHELL_COMMAND_PREFIXES):
        return True
    if lowered.startswith("./") or lowered.startswith("~/"):
        return True
    if "bash -c" in lowered or "sh -c" in lowered or "powershell -command" in lowered:
        return True
    if any(meta in lowered for meta in SHELL_META_PATTERNS):
        if re.search(r"\b(rm|curl|wget|bash|sh|chmod|chown|mv|cp)\b", lowered):
            return True
    return False


def _needs_llm_guard_check(question: str) -> bool:
    lowered = str(question or "").lower()
    if _looks_like_user_code(question):
        return False
    return any(token in lowered for token in ("run", "execute", "command", "script", "code"))


def _llm_guard_intent(question: str) -> str | None:
    model = get_llm_model().with_structured_output(INTENT_CLASSIFIER_SCHEMA)
    raw = model.invoke(
        [
            SystemMessage(
                content=(
                    "Classify user request intent for guardrail routing.\n"
                    "blocked_user_code: asks to run shell/python/sql code directly.\n"
                    "blocked_safety: harmful/sexual dangerous request.\n"
                    "meta_help: asks about capabilities/help.\n"
                    "task: normal business/analysis task.\n"
                    "Return strict structured output only."
                )
            ),
            HumanMessage(content=f"User request:\n{question}"),
        ]
    )
    if not isinstance(raw, dict):
        return None
    value = str(raw.get("intent_class") or "").strip()
    if value in {"task", "meta_help", "blocked_user_code", "blocked_safety"}:
        return value
    return None


def _safe_json_loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {"raw": str(raw)}


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


def _is_current_plan_step(state: AgentV3State, step_id: str) -> bool:
    version = _step_plan_version(step_id)
    if version is None:
        # Backward compatibility for legacy step IDs without vN prefix.
        return True
    return version == state.plan_version


def _completed_step_payloads(state: AgentV3State) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for step in state.steps:
        if step.status != "done":
            continue
        if not _is_current_plan_step(state, step.id):
            continue
        payloads.append(
            {
                "id": step.id,
                "instruction": step.instruction,
                "tool": step.selected_tool,
                "attempts": step.attempts,
                "result": step.result_payload
                or _safe_json_loads(step.result_summary),
            }
        )
    return payloads


def _failed_step_payloads(state: AgentV3State) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for step in state.steps:
        if step.status != "failed":
            continue
        if not _is_current_plan_step(state, step.id):
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


def _first_pending_index(state: AgentV3State) -> int:
    for idx, step in enumerate(state.steps):
        if step.status in {"pending", "running"}:
            return idx
    return len(state.steps)


def _first_failed_index(state: AgentV3State) -> int | None:
    for idx, step in enumerate(state.steps):
        if step.status == "failed":
            return idx
    return None


def ensure_system_prompt(state: AgentV3State, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    existing = state.messages

    system_prompt = load_chat_prompt("agent").invoke({"messages": []}).to_messages()[0]

    if _has_system_message(existing, expected=_content_to_text(system_prompt.content)):
        return {}

    return {"messages": [system_prompt]}


def context_manager(state: AgentV3State, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    token_estimate = _estimate_history_tokens(state)
    updates: dict[str, Any] = {"token_estimate": token_estimate}
    if token_estimate < SUMMARY_TRIGGER_TOKENS:
        return updates

    cutoff = max(0, len(state.messages) - SUMMARY_RECENT_MESSAGE_WINDOW)
    start = min(max(0, state.last_summarized_message_index), cutoff)
    if cutoff <= start:
        return updates

    chunk = state.messages[start:cutoff]
    chunk_transcript = _messages_to_transcript(chunk)
    if not chunk_transcript.strip():
        updates["last_summarized_message_index"] = cutoff
        return updates

    llm = get_llm_model()
    ai_msg = llm.invoke(
        [
            SystemMessage(
                content=(
                    "You are a conversation memory compressor for an agent graph.\n"
                    "Write a compact, factual memory with these sections:\n"
                    "1) User Objectives\n2) Retrieved Facts\n3) Decisions/Outcomes\n"
                    "4) Open Items\n"
                    "Do not include chain-of-thought. Keep critical entities exact "
                    "(alert ids, tickers, dates, quantities). Keep it concise."
                )
            ),
            HumanMessage(
                content=(
                    f"Existing summary:\n{state.conversation_summary or '(none)'}\n\n"
                    "New conversation chunk to merge:\n"
                    f"{chunk_transcript}\n\n"
                    f"Return updated summary under {SUMMARY_TEXT_LIMIT} characters."
                )
            ),
        ]
    )
    summary_text = _content_to_text(getattr(ai_msg, "content", "")).strip()
    if summary_text:
        if len(summary_text) > SUMMARY_TEXT_LIMIT:
            summary_text = summary_text[:SUMMARY_TEXT_LIMIT].rstrip() + "..."
        updates["conversation_summary"] = summary_text
        updates["summary_version"] = state.summary_version + 1
    updates["last_summarized_message_index"] = cutoff
    updates["token_estimate"] = _estimate_tokens(
        _messages_to_transcript(
            build_prompt_messages(
                state.messages,
                conversation_summary=summary_text or state.conversation_summary,
                recent_window=SUMMARY_RECENT_MESSAGE_WINDOW,
            )
        )
    )
    return updates


def intent_guard(state: AgentV3State, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    question = _latest_user_question(state.messages)
    if not question:
        return {"intent_class": "task", "guardrail_response": None}

    if _is_harmful_question(question):
        return {
            "intent_class": "blocked_safety",
            "guardrail_response": (
                "I can't help with harmful, sexual, or dangerous requests. "
                "I can still help with alert analysis, SQL/data queries, and "
                "investigation summaries for this case."
            ),
        }

    if _is_code_run_question(question):
        return {
            "intent_class": "blocked_user_code",
            "guardrail_response": (
                "I can't run user-submitted arbitrary shell/Python/SQL code directly. "
                "Please describe the analysis goal in plain language and I will "
                "use approved tools/workflows to help."
            ),
        }

    if _looks_like_user_code(question):
        return {
            "intent_class": "blocked_user_code",
            "guardrail_response": (
                "I can't process submitted shell/Python/SQL code directly. "
                "Please describe your objective in plain language and I will "
                "help using approved analysis tools."
            ),
        }

    if _is_meta_help_question(question):
        return {
            "intent_class": "meta_help",
            "guardrail_response": (
                "I can help with this alert workflow: \n"
                "1. Read schema/methodology artifacts.\n"
                "2. Retrieve backend data with SQL (preferred).\n"
                "3. Run bounded Python analysis when needed.\n"
                "4. Summarize findings and draft disposition/report text.\n"
                "Ask me a concrete objective and I will create/continue the plan."
            ),
            "plan_requires_execution": False,
        }

    if _needs_llm_guard_check(question):
        try:
            llm_intent = _llm_guard_intent(question)
        except Exception:
            llm_intent = None
        if llm_intent == "blocked_safety":
            return {
                "intent_class": "blocked_safety",
                "guardrail_response": (
                    "I can't help with harmful, sexual, or dangerous requests. "
                    "I can still help with alert analysis, SQL/data queries, and "
                    "investigation summaries for this case."
                ),
            }
        if llm_intent == "blocked_user_code":
            return {
                "intent_class": "blocked_user_code",
                "guardrail_response": (
                    "I can't run user-submitted arbitrary shell/Python/SQL code directly. "
                    "Please describe the analysis goal in plain language and I will "
                    "use approved tools/workflows to help."
                ),
            }
        if llm_intent == "meta_help":
            return {
                "intent_class": "meta_help",
                "guardrail_response": (
                    "I can help with this alert workflow: \n"
                    "1. Read schema/methodology artifacts.\n"
                    "2. Retrieve backend data with SQL (preferred).\n"
                    "3. Run bounded Python analysis when needed.\n"
                    "4. Summarize findings and draft disposition/report text.\n"
                    "Ask me a concrete objective and I will create/continue the plan."
                ),
                "plan_requires_execution": False,
            }

    return {
        "intent_class": "task",
        "guardrail_response": None,
    }


def master(state: AgentV3State, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    latest_question = _latest_user_question(state.messages)

    if latest_question and latest_question != (state.last_user_question or ""):
        return {
            "next_step": "plan",
            "failed_step_index": None,
            "terminal_error": None,
        }

    if state.terminal_error:
        return {"next_step": "respond"}

    failed_idx = _first_failed_index(state)
    if failed_idx is not None:
        if state.replan_attempts < MAX_REPLAN_ATTEMPTS:
            return {
                "next_step": "plan",
                "failed_step_index": failed_idx,
                "replan_attempts": state.replan_attempts + 1,
            }
        failed_step = state.steps[failed_idx]
        return {
            "next_step": "respond",
            "terminal_error": failed_step.error or "Task failed after retries.",
            "failed_step_index": failed_idx,
        }

    if not state.plan_requires_execution:
        return {"next_step": "respond"}

    if not state.steps:
        if latest_question and latest_question == (state.last_user_question or ""):
            return {
                "next_step": "respond",
                "terminal_error": (
                    "Planner returned no actionable steps for the current request."
                ),
            }
        return {"next_step": "plan"}

    pending_idx = _first_pending_index(state)
    if pending_idx >= len(state.steps):
        return {"next_step": "respond", "current_step_index": pending_idx}

    return {
        "next_step": "execute",
        "current_step_index": pending_idx,
    }


def respond(state: AgentV3State, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    if state.guardrail_response:
        return {
            "messages": [AIMessage(content=state.guardrail_response)],
            "guardrail_response": None,
            "terminal_error": None,
        }
    llm = get_llm_model()
    user_question = _latest_user_question(state.messages)
    completed = _completed_step_payloads(state)
    failed = _failed_step_payloads(state)

    ai_msg = llm.invoke(
        [
            SystemMessage(
                content=(
                    "You are generating the final user-facing answer. "
                    "Answer the user's request directly using completed tool outputs. "
                    "Do not include internal reasoning or debug traces. "
                    "If there are rows/data results, present them clearly. "
                    "If partial failure occurred, include one concise limitation note."
                )
            ),
            HumanMessage(
                content=(
                    "User request:\n"
                    f"{user_question or '(missing user request)'}\n\n"
                    "Completed step outputs (JSON):\n"
                    f"{json.dumps(completed, default=str)}\n\n"
                    "Failed steps (JSON):\n"
                    f"{json.dumps(failed, default=str)}\n\n"
                    "Current alert context (JSON):\n"
                    f"{state.current_alert.model_dump_json()}\n\n"
                    "Terminal error (if any):\n"
                    f"{state.terminal_error or ''}"
                )
            ),
        ]
    )
    return {"messages": [ai_msg]}


def router(state: AgentV3State) -> str:
    mapping = {
        "plan": "planner",
        "respond": "respond",
        "execute": "executioner",
    }
    return mapping[state.next_step]


def intent_router(state: AgentV3State) -> str:
    if state.intent_class in {"blocked_safety", "blocked_user_code", "meta_help"}:
        return "respond"
    return "master"


def build_graph():
    workflow = StateGraph(state_schema=AgentV3State, input_schema=AgentInputSchema)
    workflow.add_node("ensure_system_prompt", ensure_system_prompt)
    workflow.add_node("context_manager", context_manager)
    workflow.add_node("intent_guard", intent_guard)
    workflow.add_node("master", master)
    workflow.add_node("planner", planner)
    workflow.add_node("respond", respond)
    workflow.add_node("executioner", executioner)

    workflow.add_edge(START, "ensure_system_prompt")
    workflow.add_edge("ensure_system_prompt", "context_manager")
    workflow.add_edge("context_manager", "intent_guard")
    workflow.add_conditional_edges(
        "intent_guard",
        intent_router,
        {
            "master": "master",
            "respond": "respond",
        },
    )
    workflow.add_conditional_edges(
        "master",
        router,
        {
            "planner": "planner",
            "respond": "respond",
            "executioner": "executioner",
        },
    )
    workflow.add_edge("planner", "master")
    workflow.add_edge("executioner", "master")
    workflow.add_edge("respond", END)

    return workflow


workflow = build_graph()
