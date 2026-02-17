from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from backend.agent_v3.prompts import load_chat_prompt
from backend.agent_v3.responding import completed_step_payloads, failed_step_payloads
from backend.agent_v3.state import AgentV3State, AnswerFeedback
from backend.agent_v3.utils import build_prompt_messages
from backend.logger import logprint
from backend.llm import get_llm_model

REWRITER_RECENT_WINDOW = 16


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


def answer_rewriter_node(state: AgentV3State, config: RunnableConfig) -> dict[str, Any]:
    _ = config

    draft_answer = str(state.draft_answer or "")
    feedback = state.last_answer_feedback or AnswerFeedback(
        decision="rewrite",
        reason="Missing validator feedback.",
        issues=["No validator feedback provided."],
        rewrite_instructions=(
            "Rewrite for clarity and completeness using completed outputs only."
        ),
        confidence=None,
    )

    llm = get_llm_model()
    prompt = load_chat_prompt("answer_rewriter").invoke(
        {
            "messages": build_prompt_messages(
                state.messages,
                conversation_summary=state.conversation_summary,
                recent_window=REWRITER_RECENT_WINDOW,
            ),
            "draft_answer": draft_answer,
            "feedback_reason": feedback.reason,
            "issues": json.dumps(feedback.issues, default=str),
            "rewrite_instructions": feedback.rewrite_instructions or "",
            "completed_step_outputs": json.dumps(
                completed_step_payloads(state), default=str
            ),
            "failed_steps": json.dumps(failed_step_payloads(state), default=str),
            "conversation_summary": state.conversation_summary or "(none)",
        }
    )

    ai_msg = llm.invoke(prompt)
    rewritten = _content_to_text(getattr(ai_msg, "content", "")).strip()
    if not rewritten:
        rewritten = draft_answer

    logprint(
        "answer_rewrite_applied",
        reason=feedback.reason,
        chars_before=len(draft_answer),
        chars_after=len(rewritten),
    )

    return {
        "draft_answer": rewritten,
        "answer_revision_attempts": state.answer_revision_attempts + 1,
        "messages": [
            AIMessage(
                content=rewritten,
                additional_kwargs={"ephemeral_node_output": "answer_rewriter"},
            )
        ],
    }


__all__ = ["answer_rewriter_node"]
