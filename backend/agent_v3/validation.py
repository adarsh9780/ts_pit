from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from backend.agent_v3.prompts import load_chat_prompt
from backend.agent_v3.responding import completed_step_payloads, failed_step_payloads
from backend.agent_v3.state import AgentV3State, AnswerFeedback
from backend.logger import logprint
from backend.llm import get_llm_model

VALIDATOR_SCHEMA: dict[str, Any] = {
    "title": "AnswerFeedback",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["accept", "rewrite", "escalate"],
        },
        "reason": {"type": "string"},
        "issues": {
            "type": "array",
            "items": {"type": "string"},
        },
        "rewrite_instructions": {"type": ["string", "null"]},
        "confidence": {"type": ["number", "null"]},
    },
    "required": ["decision", "reason", "issues", "rewrite_instructions", "confidence"],
}


def _is_near_empty(answer: str) -> bool:
    compact = re.sub(r"\s+", " ", str(answer or "")).strip()
    if not compact:
        return True
    # Reject boilerplate or extremely short placeholders.
    if len(compact) < 24:
        return True
    return compact.lower() in {
        "no data",
        "no results",
        "not sure",
        "i don't know",
        "unable to answer",
    }


def _seems_generic(answer: str) -> bool:
    lowered = str(answer or "").lower()
    generic_markers = (
        "please provide more",
        "cannot assist",
        "need more context",
        "i can help with",
        "let me know if",
    )
    return any(marker in lowered for marker in generic_markers)


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


def _append_fallback_note(answer: str, feedback: AnswerFeedback) -> str:
    base = str(answer or "").strip()
    limitation = (
        "\n\nLimitation: I may not have enough reliable evidence to improve this "
        "response further automatically in this turn."
    )
    if base:
        return base + limitation
    reason = feedback.reason or "Response quality checks could not produce a stronger answer."
    return (
        "I could not produce a confident final answer in this turn. "
        f"Reason: {reason}."
        "\n\nLimitation: Please rephrase with a narrower scope or request one specific output table."
    )


def _deterministic_feedback(state: AgentV3State, draft_answer: str) -> AnswerFeedback | None:
    completed = completed_step_payloads(state)
    failed = failed_step_payloads(state)

    issues: list[str] = []
    if _is_near_empty(draft_answer):
        issues.append("Answer is empty or near-empty.")

    if completed and _seems_generic(draft_answer):
        issues.append("Answer is generic despite available completed outputs.")

    if failed and not _has_limitation_note(draft_answer):
        issues.append("Answer omits a concise limitation note despite failed steps.")

    if _table_opportunity_exists(completed) and "|" not in draft_answer:
        issues.append("Likely table opportunity missed for comparable rows.")

    if not issues:
        return None

    decision = "rewrite"
    if state.answer_revision_attempts >= state.max_answer_revision_attempts:
        decision = "escalate"

    return AnswerFeedback(
        decision=decision,
        reason="Deterministic response quality checks failed.",
        issues=issues,
        rewrite_instructions=(
            "Address all listed issues. Keep facts faithful to completed tool outputs only. "
            "Use a markdown table for comparable multi-row data when applicable. "
            "Include one concise limitation sentence if any failed steps exist."
        ),
        confidence=0.95,
    )


def _llm_feedback(state: AgentV3State, draft_answer: str) -> AnswerFeedback:
    completed = completed_step_payloads(state)
    failed = failed_step_payloads(state)
    model = get_llm_model().with_structured_output(VALIDATOR_SCHEMA)

    prompt = load_chat_prompt("answer_validator").invoke(
        {
            "messages": [],
            "draft_answer": draft_answer,
            "completed_step_outputs": json.dumps(completed, default=str),
            "failed_steps": json.dumps(failed, default=str),
            "answer_revision_attempts": state.answer_revision_attempts,
            "max_answer_revision_attempts": state.max_answer_revision_attempts,
            "master_escalations_from_validation": state.master_escalations_from_validation,
            "max_master_escalations_from_validation": state.max_master_escalations_from_validation,
        }
    )

    raw = model.invoke(prompt)
    if not isinstance(raw, dict):
        raise ValueError("Validator output is not a dict")
    return AnswerFeedback.model_validate(raw)


def _finalize_accept(state: AgentV3State, answer_text: str, feedback: AnswerFeedback) -> dict[str, Any]:
    return {
        "last_answer_feedback": feedback,
        "messages": [AIMessage(content=answer_text)],
        "draft_answer": None,
    }


def answer_validator_node(state: AgentV3State, config: RunnableConfig) -> dict[str, Any]:
    _ = config

    draft_answer = str(state.draft_answer or "").strip()

    deterministic = _deterministic_feedback(state, draft_answer)
    if deterministic is not None:
        feedback = deterministic
    else:
        try:
            feedback = _llm_feedback(state, draft_answer)
        except Exception as exc:
            # Safe fallback: avoid loops when validator is unavailable.
            feedback = AnswerFeedback(
                decision="accept",
                reason="Validator model unavailable; accepted via fallback.",
                issues=[str(exc)],
                rewrite_instructions=None,
                confidence=None,
            )

    can_rewrite = state.answer_revision_attempts < state.max_answer_revision_attempts
    can_escalate = (
        state.master_escalations_from_validation
        < state.max_master_escalations_from_validation
    )

    if feedback.decision == "rewrite" and not can_rewrite:
        feedback = feedback.model_copy(
            update={
                "decision": "escalate",
                "reason": "Rewrite budget exhausted; escalating once to master.",
            }
        )

    updates: dict[str, Any] = {"last_answer_feedback": feedback}

    if feedback.decision == "escalate":
        if can_escalate:
            updates["master_escalations_from_validation"] = (
                state.master_escalations_from_validation + 1
            )
        else:
            fallback_feedback = feedback.model_copy(
                update={
                    "decision": "accept",
                    "reason": "Escalation budget exhausted; finalizing with best effort.",
                }
            )
            fallback_answer = _append_fallback_note(draft_answer, fallback_feedback)
            updates.update(_finalize_accept(state, fallback_answer, fallback_feedback))
            feedback = fallback_feedback
            logprint(
                "answer_quality_fallback_finalize",
                decision=fallback_feedback.decision,
                issues_count=len(fallback_feedback.issues),
                revision_attempts=state.answer_revision_attempts,
                escalation_count=state.master_escalations_from_validation,
            )

    if feedback.decision == "accept":
        final_answer = draft_answer
        if _is_near_empty(final_answer):
            final_answer = _append_fallback_note(final_answer, feedback)
        updates.update(_finalize_accept(state, final_answer, feedback))

    logprint(
        "answer_validation_decision",
        decision=feedback.decision,
        reason=feedback.reason,
        issues_count=len(feedback.issues),
        confidence=feedback.confidence,
        revision_attempts=state.answer_revision_attempts,
        escalation_count=updates.get(
            "master_escalations_from_validation",
            state.master_escalations_from_validation,
        ),
    )

    return updates


__all__ = ["answer_validator_node"]
