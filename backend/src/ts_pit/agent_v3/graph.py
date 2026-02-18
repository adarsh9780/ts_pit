from __future__ import annotations

import ast
import re
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langchain_core.messages import AnyMessage, SystemMessage, HumanMessage, AIMessage

from ts_pit.agent_v3.state import AgentV3State, AgentInputSchema
from ts_pit.agent_v3.planning import planner
from ts_pit.agent_v3.prompts import load_chat_prompt
from ts_pit.agent_v3.execution import executioner
from ts_pit.agent_v3.responding import respond_node
from ts_pit.agent_v3.validation import answer_validator_node
from ts_pit.agent_v3.rewriting import answer_rewriter_node
from ts_pit.agent_v3.utils import build_prompt_messages
from ts_pit.config import get_config
from ts_pit.llm import get_llm_model

MAX_REPLAN_ATTEMPTS = 1
SUMMARY_TRIGGER_TOKENS = 50_000
SUMMARY_RECENT_MESSAGE_WINDOW = 16
SUMMARY_TEXT_LIMIT = 2500
_response_quality_cfg = get_config().get_agent_response_quality_config()
RESPONSE_QUALITY_ENABLED = bool(_response_quality_cfg.get("enabled", True))
MAX_ANSWER_REVISION_ATTEMPTS = int(
    _response_quality_cfg.get("max_answer_revision_attempts", 1)
)
MAX_MASTER_ESCALATIONS_FROM_VALIDATION = int(
    _response_quality_cfg.get("max_master_escalations_from_validation", 1)
)
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
    "title": "IntentRoutingDecision",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "intent_class": {
            "type": "string",
            "enum": [
                "task",
                "meta_help",
                "blocked_user_code",
                "blocked_safety",
                "analyze_current_alert",
                "analyze_other_alert",
                "needs_clarification",
            ],
        },
        "target_scope": {
            "type": "string",
            "enum": ["current_alert", "explicit_alert_id", "other_alert_unknown", "none"],
        },
        "target_alert_id": {"type": ["string", "null"]},
        "confidence": {"type": ["number", "null"]},
        "assumption_risk": {"type": "string", "enum": ["low", "medium", "high"]},
        "ambiguities": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
    "required": [
        "intent_class",
        "target_scope",
        "target_alert_id",
        "confidence",
        "assumption_risk",
        "ambiguities",
        "reason",
    ],
}

ALERT_ANALYSIS_PATTERNS = (
    "analyze alert",
    "analyse alert",
    "analyze this alert",
    "analyse this alert",
    "analyze current alert",
    "analyse current alert",
    "analyze the current alert",
    "analyse the current alert",
    "investigate this alert",
    "review this alert",
    "explain this alert",
    "explain the alert",
)
ANOTHER_ALERT_PATTERNS = (
    "another alert",
    "other alert",
    "different alert",
)
PRICE_ANALYSIS_PATTERNS = (
    "analyze price data",
    "analyse price data",
    "price analysis",
    "analyze prices",
    "analyse prices",
)
PRICE_METHOD_HINTS = (
    "daily change",
    "candle",
    "rolling mean",
    "moving average",
    "volatility",
    "drawdown",
    "returns",
)

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
    return _looks_like_user_code(question) and (
        "run" in lowered or "execute" in lowered
    )


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
    return any(
        token in lowered
        for token in (
            "run",
            "execute",
            "command",
            "script",
            "code",
            "analyze",
            "analyse",
            "review",
            "investigate",
            "price",
            "alert",
        )
    )


def _extract_alert_ids(text: str) -> list[int]:
    ids = re.findall(r"\balert\s*#?\s*(\d+)\b", str(text or "").lower())
    out: list[int] = []
    for item in ids:
        try:
            out.append(int(item))
        except Exception:
            continue
    return out


def _deterministic_ambiguity_and_intent(state: AgentV3State, question: str) -> dict[str, Any]:
    lowered = str(question or "").strip().lower()
    current_id = getattr(state.current_alert, "alert_id", None)
    mentioned_ids = _extract_alert_ids(lowered)
    ambiguities: list[str] = []
    intent_class = "task"
    target_scope = "none"
    target_alert_id: int | None = None
    assumption_risk: Literal["low", "medium", "high"] = "low"
    reason = "No deterministic ambiguity detected."
    assumption_candidate: str | None = None

    if any(p in lowered for p in ALERT_ANALYSIS_PATTERNS):
        intent_class = "analyze_current_alert" if current_id is not None else "needs_clarification"
        target_scope = "current_alert" if current_id is not None else "other_alert_unknown"
        if current_id is None:
            ambiguities.append("missing_current_alert_context")
            assumption_risk = "high"
            reason = "User asked to analyze current alert, but no current alert is bound."
        else:
            reason = "Deterministic current-alert analysis intent matched."

    if any(p in lowered for p in ANOTHER_ALERT_PATTERNS):
        intent_class = "analyze_other_alert"
        target_scope = "other_alert_unknown"
        assumption_risk = "high"
        ambiguities.append("other_alert_missing_id")
        if current_id is not None:
            assumption_candidate = f"default_to_current_alert:{current_id}"
        reason = "User referenced another/other alert without clear target id."

    if mentioned_ids:
        if len(mentioned_ids) > 1:
            intent_class = "needs_clarification"
            target_scope = "other_alert_unknown"
            assumption_risk = "high"
            ambiguities.append("multiple_alert_ids")
            reason = "Multiple alert IDs were provided."
        else:
            target_alert_id = int(mentioned_ids[0])
            target_scope = "explicit_alert_id"
            if current_id is not None and target_alert_id != int(current_id):
                intent_class = "needs_clarification"
                assumption_risk = "high"
                ambiguities.append("target_mismatch_current_vs_requested")
                assumption_candidate = f"default_to_current_alert:{current_id}"
                reason = "Requested alert id differs from current selected alert."
            elif intent_class in {"task", "needs_clarification"}:
                intent_class = "analyze_other_alert"
                reason = "Explicit alert id target detected."

    if any(p in lowered for p in PRICE_ANALYSIS_PATTERNS):
        if not any(h in lowered for h in PRICE_METHOD_HINTS):
            ambiguities.append("price_method_ambiguous")
            if assumption_risk == "low":
                assumption_risk = "medium"
            if intent_class == "task":
                intent_class = "needs_clarification"
            reason = "Price analysis request does not specify method."

    if "review this" in lowered and current_id is None:
        ambiguities.append("review_scope_ambiguous")
        assumption_risk = "high"
        intent_class = "needs_clarification"
        reason = "Scope is ambiguous and no current alert context is available."

    if intent_class == "analyze_other_alert" and target_scope != "explicit_alert_id":
        intent_class = "needs_clarification"

    return {
        "intent_class": intent_class,
        "target_scope": target_scope,
        "target_alert_id": target_alert_id,
        "assumption_risk": assumption_risk,
        "ambiguities": ambiguities,
        "reason": reason,
        "assumption_candidate": assumption_candidate,
    }


def _llm_guard_intent(question: str) -> dict[str, Any] | None:
    model = get_llm_model().with_structured_output(INTENT_CLASSIFIER_SCHEMA)
    raw = model.invoke(
        [
            SystemMessage(
                content=(
                    "Classify user request for trade-surveillance routing.\n"
                    "blocked_user_code: asks to run shell/python/sql code directly.\n"
                    "blocked_safety: harmful/sexual dangerous request.\n"
                    "meta_help: asks about capabilities/help.\n"
                    "analyze_current_alert: asks to analyze currently selected alert.\n"
                    "analyze_other_alert: asks to analyze a different alert and id is explicit.\n"
                    "needs_clarification: ambiguity likely to cause wrong analysis.\n"
                    "task: normal task with safe assumptions.\n"
                    "Return strict structured output only."
                )
            ),
            HumanMessage(content=f"User request:\n{question}"),
        ]
    )
    if not isinstance(raw, dict):
        return None
    return raw


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


def context_metrics(state: AgentV3State, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    return {"token_estimate": _estimate_history_tokens(state)}


def intent_guard(state: AgentV3State, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    question = _latest_user_question(state.messages)
    if not question:
        return {
            "intent_class": "task",
            "guardrail_response": None,
            "needs_clarification": False,
            "clarification_resolved": True,
        }

    deterministic = _deterministic_ambiguity_and_intent(state, question)
    ambiguity_signature = "|".join(sorted(deterministic.get("ambiguities") or []))
    asked_turns = int(state.clarification_asked_turns or 0)
    max_turns = int(state.max_clarification_turns or 1)
    same_signature_repeat = (
        bool(ambiguity_signature)
        and state.clarification_signature == ambiguity_signature
        and asked_turns >= 1
    )

    if _is_harmful_question(question):
        return {
            "intent_class": "blocked_safety",
            "guardrail_response": (
                "I can't help with harmful, sexual, or dangerous requests. "
                "I can still help with alert analysis, SQL/data queries, and "
                "investigation summaries for this case."
            ),
            "needs_clarification": False,
        }

    if _is_code_run_question(question):
        return {
            "intent_class": "blocked_user_code",
            "guardrail_response": (
                "I can't run user-submitted arbitrary shell/Python/SQL code directly. "
                "Please describe the analysis goal in plain language and I will "
                "use approved tools/workflows to help."
            ),
            "needs_clarification": False,
        }

    if _looks_like_user_code(question):
        return {
            "intent_class": "blocked_user_code",
            "guardrail_response": (
                "I can't process submitted shell/Python/SQL code directly. "
                "Please describe your objective in plain language and I will "
                "help using approved analysis tools."
            ),
            "needs_clarification": False,
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
            "needs_clarification": False,
        }

    confidence = None
    if _needs_llm_guard_check(question):
        try:
            llm_intent = _llm_guard_intent(question)
        except Exception:
            llm_intent = None
        llm_class = (
            str((llm_intent or {}).get("intent_class") or "").strip()
            if isinstance(llm_intent, dict)
            else ""
        )
        if llm_class == "blocked_safety":
            return {
                "intent_class": "blocked_safety",
                "guardrail_response": (
                    "I can't help with harmful, sexual, or dangerous requests. "
                    "I can still help with alert analysis, SQL/data queries, and "
                    "investigation summaries for this case."
                ),
                "needs_clarification": False,
            }
        if llm_class == "blocked_user_code":
            # Only honor model-only blocked_user_code if deterministic code signals exist.
            if _looks_like_user_code(question) or _is_code_run_question(question):
                return {
                    "intent_class": "blocked_user_code",
                    "guardrail_response": (
                        "I can't run user-submitted arbitrary shell/Python/SQL code directly. "
                        "Please describe the analysis goal in plain language and I will "
                        "use approved tools/workflows to help."
                    ),
                    "needs_clarification": False,
                }
        if llm_class == "meta_help":
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
                "needs_clarification": False,
            }
        if isinstance(llm_intent, dict):
            # Keep deterministic high-risk ambiguity decisions authoritative.
            det_class = str(deterministic.get("intent_class") or "")
            det_risk = str(deterministic.get("assumption_risk") or "low")
            if (
                det_class in {"task"}
                and det_risk in {"low", "medium"}
                and llm_class not in {"blocked_user_code", "blocked_safety"}
            ):
                deterministic["intent_class"] = llm_class or deterministic["intent_class"]
                deterministic["reason"] = str(llm_intent.get("reason") or deterministic["reason"])
            confidence_val = llm_intent.get("confidence")
            try:
                confidence = float(confidence_val) if confidence_val is not None else None
            except Exception:
                confidence = None

    should_clarify = False
    risk = str(deterministic.get("assumption_risk") or "low")
    if deterministic.get("intent_class") == "needs_clarification":
        if risk == "high":
            should_clarify = True
        elif risk == "medium":
            should_clarify = deterministic.get("assumption_candidate") is None

    if should_clarify and ambiguity_signature and asked_turns < max_turns and not same_signature_repeat:
        return {
            "intent_class": "needs_clarification",
            "guardrail_response": None,
            "needs_clarification": True,
            "clarification_resolved": False,
            "clarification_reason": str(deterministic.get("reason") or ""),
            "clarification_signature": ambiguity_signature,
            "assumption_risk": risk,
            "assumption_candidate": deterministic.get("assumption_candidate"),
            "clarify_decision_reason": "Ambiguity risk is high enough to reduce user satisfaction.",
            "intent_confidence": confidence,
            "intent_reason": str(deterministic.get("reason") or ""),
            "intent_target_alert_id": deterministic.get("target_alert_id"),
        }

    if should_clarify and (asked_turns >= max_turns or same_signature_repeat):
        current_alert_id = getattr(state.current_alert, "alert_id", None)
        if current_alert_id is not None:
            return {
                "intent_class": "analyze_current_alert",
                "guardrail_response": None,
                "needs_clarification": False,
                "clarification_resolved": True,
                "clarification_reason": (
                    "Clarification budget exhausted; defaulted to current alert."
                ),
                "assumption_candidate": f"default_to_current_alert:{current_alert_id}",
                "clarify_decision_reason": "Fallback assumption applied after unresolved ambiguity.",
                "intent_target_alert_id": int(current_alert_id),
                "intent_confidence": confidence,
                "intent_reason": str(deterministic.get("reason") or ""),
            }
        return {
            "intent_class": "task",
            "guardrail_response": (
                "I need one concrete target before I can run analysis. "
                "Please provide an alert ID."
            ),
            "needs_clarification": False,
            "clarification_resolved": False,
            "clarify_decision_reason": "Unable to assume target alert because no current alert is selected.",
        }

    intent_class = str(deterministic.get("intent_class") or "task")
    if intent_class not in {
        "task",
        "meta_help",
        "blocked_user_code",
        "blocked_safety",
        "analyze_current_alert",
        "analyze_other_alert",
        "needs_clarification",
    }:
        intent_class = "task"
    return {
        "intent_class": intent_class,
        "guardrail_response": None,
        "needs_clarification": False,
        "clarification_resolved": True,
        "clarification_reason": None,
        "clarification_signature": ambiguity_signature or None,
        "assumption_risk": risk if risk in {"low", "medium", "high"} else "low",
        "assumption_candidate": deterministic.get("assumption_candidate"),
        "intent_confidence": confidence,
        "intent_reason": str(deterministic.get("reason") or ""),
        "intent_target_alert_id": deterministic.get("target_alert_id"),
    }


CLARIFY_OPTIONS_SCHEMA: dict[str, Any] = {
    "title": "ClarificationOptions",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "why": {"type": "string"},
        "options": {"type": "array", "items": {"type": "string"}},
        "ask": {"type": "string"},
    },
    "required": ["why", "options", "ask"],
}


def _llm_method_options(question: str) -> list[str]:
    model = get_llm_model().with_structured_output(CLARIFY_OPTIONS_SCHEMA)
    raw = model.invoke(
        [
            SystemMessage(
                content=(
                    "User asked for analysis but method is ambiguous. "
                    "Generate concise options with practical trade-offs. "
                    "Return strict structured output only."
                )
            ),
            HumanMessage(content=f"Query:\n{question}"),
        ]
    )
    if not isinstance(raw, dict):
        return []
    options = raw.get("options")
    if not isinstance(options, list):
        return []
    clean = [str(x).strip() for x in options if str(x).strip()]
    return clean[:3]


def clarify_node(state: AgentV3State, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    question = _latest_user_question(state.messages)
    reason = str(state.clarification_reason or "The request has high-impact ambiguity.")
    current_alert_id = getattr(state.current_alert, "alert_id", None)
    signature = str(state.clarification_signature or "")
    options: list[str] = []

    if "target_mismatch_current_vs_requested" in signature and current_alert_id is not None:
        requested = state.intent_target_alert_id
        options = [
            f"Analyze current alert {current_alert_id}.",
            f"Analyze requested alert {requested}." if requested is not None else "Analyze the requested alert id you intended.",
            "Compare both alerts side-by-side.",
        ]
    elif "other_alert_missing_id" in signature:
        options = [
            f"Analyze current alert {current_alert_id}." if current_alert_id is not None else "Provide an alert ID to analyze.",
            "Provide another alert ID for analysis.",
            "Compare current alert with another alert ID you provide.",
        ]
    elif "price_method_ambiguous" in signature:
        try:
            options = _llm_method_options(question)
        except Exception:
            options = []
        if not options:
            options = [
                "Calculate daily candle change (open-close, day-by-day).",
                "Calculate 7-day rolling mean and trend direction.",
                "Calculate volatility and drawdown summary.",
            ]
    else:
        options = [
            "Proceed with current alert baseline analysis.",
            "Provide explicit alert ID and desired analysis target.",
            "Specify exact analysis method/output you want.",
        ]

    questions = [f"{i+1}. {opt}" for i, opt in enumerate(options[:3])]
    ask_line = "Reply with one option number (and alert ID if needed)."
    content = (
        "**Why I'm asking**\n"
        f"- {reason}\n\n"
        "**What I can do**\n"
        + "\n".join(f"- {line}" for line in questions)
        + "\n\n"
        "**What I need from you**\n"
        f"- {ask_line}"
    )

    return {
        "messages": [AIMessage(content=content)],
        "needs_clarification": True,
        "clarification_questions": options[:3],
        "clarification_question": ask_line,
        "clarification_asked_turns": int(state.clarification_asked_turns or 0) + 1,
        "clarification_resolved": False,
        "next_step": "respond",
    }


def master(state: AgentV3State, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    latest_question = _latest_user_question(state.messages)

    if latest_question and latest_question != (state.last_user_question or ""):
        reset_clarify_count = (
            0
            if not state.needs_clarification
            or state.clarification_resolved
            else int(state.clarification_asked_turns or 0)
        )
        return {
            "next_step": "plan",
            "failed_step_index": None,
            "terminal_error": None,
            "draft_answer": None,
            "last_answer_feedback": None,
            "answer_revision_attempts": 0,
            "master_escalations_from_validation": 0,
            "max_answer_revision_attempts": MAX_ANSWER_REVISION_ATTEMPTS,
            "max_master_escalations_from_validation": MAX_MASTER_ESCALATIONS_FROM_VALIDATION,
            "clarification_asked_turns": reset_clarify_count,
            "needs_clarification": False,
            "clarification_resolved": True,
            "clarification_reason": None,
            "clarification_question": None,
            "clarification_questions": [],
        }

    if state.needs_clarification and not state.clarification_resolved:
        return {"next_step": "respond"}

    if state.terminal_error:
        return {"next_step": "respond"}

    pending_idx = _first_pending_index(state)
    failed_idx = _first_failed_index(state)
    if (
        failed_idx is not None
        and state.plan_requires_execution
        and pending_idx < len(state.steps)
    ):
        return {
            "next_step": "execute",
            "current_step_index": pending_idx,
            "failed_step_index": failed_idx,
        }

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

    if pending_idx >= len(state.steps):
        return {"next_step": "respond", "current_step_index": pending_idx}

    return {
        "next_step": "execute",
        "current_step_index": pending_idx,
    }


def router(state: AgentV3State) -> str:
    mapping = {
        "plan": "planner",
        "respond": "respond",
        "execute": "executioner",
    }
    return mapping[state.next_step]


def intent_router(state: AgentV3State) -> str:
    if state.intent_class == "needs_clarification" or state.needs_clarification:
        return "clarify"
    if state.intent_class in {"blocked_safety", "blocked_user_code", "meta_help"}:
        return "respond"
    return "master"


def route_after_respond(
    state: AgentV3State,
) -> Literal["answer_validator", "__end__"]:
    if RESPONSE_QUALITY_ENABLED:
        return "answer_validator"
    return "__end__"


def route_after_validation(
    state: AgentV3State,
) -> Literal["answer_rewriter", "master", "__end__"]:
    feedback = state.last_answer_feedback
    decision = str(getattr(feedback, "decision", "accept") or "accept")
    if decision == "rewrite":
        return "answer_rewriter"
    if decision == "escalate":
        return "master"
    return "__end__"


def build_graph():
    workflow = StateGraph(state_schema=AgentV3State, input_schema=AgentInputSchema)
    workflow.add_node("ensure_system_prompt", ensure_system_prompt)
    workflow.add_node("context_manager", context_manager)
    workflow.add_node("context_metrics", context_metrics)
    workflow.add_node("intent_guard", intent_guard)
    workflow.add_node("clarify", clarify_node)
    workflow.add_node("master", master)
    workflow.add_node("planner", planner)
    workflow.add_node("respond", respond_node)
    workflow.add_node("answer_validator", answer_validator_node)
    workflow.add_node("answer_rewriter", answer_rewriter_node)
    workflow.add_node("executioner", executioner)

    workflow.add_edge(START, "ensure_system_prompt")
    workflow.add_edge("ensure_system_prompt", "context_manager")
    workflow.add_edge("context_manager", "intent_guard")
    workflow.add_conditional_edges(
        "intent_guard",
        intent_router,
        {
            "master": "master",
            "respond": "context_metrics",
            "clarify": "clarify",
        },
    )
    workflow.add_edge("clarify", END)
    workflow.add_conditional_edges(
        "master",
        router,
        {
            "planner": "planner",
            "respond": "context_metrics",
            "executioner": "executioner",
        },
    )
    workflow.add_edge("planner", "master")
    workflow.add_edge("executioner", "master")
    workflow.add_edge("context_metrics", "respond")
    workflow.add_conditional_edges("respond", route_after_respond)
    workflow.add_conditional_edges("answer_validator", route_after_validation)
    workflow.add_edge("answer_rewriter", "answer_validator")

    return workflow


workflow = build_graph()
