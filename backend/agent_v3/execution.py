from __future__ import annotations

import json
from typing import Any, cast

from backend.agent_v3.prompts import load_chat_prompt
from backend.agent_v3.state import AgentV3State
from backend.agent_v3.tools import TOOL_REGISTRY
from backend.config import get_config
from backend.llm import get_llm_model


from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

tool_descriptions_dict = {
    name: structured_tool.description for name, structured_tool in TOOL_REGISTRY.items()
}

tool_descriptions = "\n".join(
    f"- {name}: {structured_tool.description}"
    for name, structured_tool in TOOL_REGISTRY.items()
)

retry_cfg = get_config().get_agent_retry_config()
MAX_RETRIES = int(retry_cfg.get("max_tool_error_retries", 1))
MAX_EXECUTION_ATTEMPTS = MAX_RETRIES + 1


class ToolCallArgs(BaseModel):
    instruction: str
    kwargs: dict[str, str]


class ProposedToolArgs(BaseModel):
    tool_args: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None


def _normalize_tool_args(tool_name: str, tool_args: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(tool_args, dict):
        return tool_args
    normalized = dict(tool_args)

    # Common model output shape issue:
    # execute_sql expects {"query": "..."} but model sometimes returns
    # {"kwargs": {"query": "..."}}.
    if tool_name == "execute_sql":
        query = normalized.get("query")
        if isinstance(query, str) and query.strip():
            return normalized
        kwargs = normalized.get("kwargs")
        if isinstance(kwargs, dict):
            kw_query = kwargs.get("query")
            if isinstance(kw_query, str) and kw_query.strip():
                normalized["query"] = kw_query
                normalized.pop("kwargs", None)
    return normalized


def _attempt_signature(tool_name: str, tool_args: dict[str, object]) -> str:
    try:
        args_key = json.dumps(tool_args, sort_keys=True, separators=(",", ":"))
    except Exception:
        args_key = str(tool_args)
    return f"{tool_name}:{args_key}"


def _propose_tool_args(
    state: AgentV3State,
    instruction: str,
    tool_name: str,
    tool_description: str,
    current_tool_args: dict[str, Any] | None,
    error_code: str = "",
    error_message: str = "",
) -> ProposedToolArgs:
    prompt_template = load_chat_prompt("execution")
    prompt = prompt_template.invoke(
        {
            "messages": state.messages,
            "instruction": instruction,
            "tool_name": tool_name,
            "tool_description": tool_description,
            "current_tool_args": json.dumps(current_tool_args or {}, default=str),
            "error_code": error_code,
            "error_message": error_message,
        }
    )
    model = get_llm_model().with_structured_output(ProposedToolArgs)
    return cast(ProposedToolArgs, model.invoke(prompt))


async def executioner(state: AgentV3State, config: RunnableConfig) -> dict:
    _ = config

    # 1) Pick current step
    idx = state.current_step_index
    if idx >= len(state.steps):
        return {}

    steps = list(state.steps)
    step = steps[idx]

    # 2) Validate tool
    tool_name = step.tool
    tool = TOOL_REGISTRY.get(tool_name)
    if tool is None:
        step.status = "failed"
        step.attempts += 1
        step.last_error_code = "INVALID_INPUT"
        step.error = f"Unknown tool: {tool_name}"
        steps[idx] = step
        return {"steps": steps, "failed_step_index": idx}

    # Build args at execution time from latest context. This prevents stale
    # planner-time SQL args (e.g., before schema file read) from being reused.
    if step.status == "pending" and step.correction_attempts == 0:
        proposed = _propose_tool_args(
            state=state,
            instruction=step.instruction,
            tool_name=step.tool,
            tool_description=tool.description,
            current_tool_args=step.tool_args,
        )
        if proposed.tool_args:
            step.tool_args = proposed.tool_args

    step.tool_args = _normalize_tool_args(tool_name, step.tool_args)
    tool_args = step.tool_args
    signature = _attempt_signature(tool_name, tool_args or {})
    step.last_attempt_signature = signature
    if tool_args is None:
        step.status = "failed"
        step.attempts += 1
        step.last_error_code = "INVALID_INPUT"
        step.error = f"Unknown tool: {tool_name} or tool arguments: {tool_args}"
        steps[idx] = step
        return {"steps": steps, "failed_step_index": idx}

    if step.attempts >= MAX_EXECUTION_ATTEMPTS:
        step.status = "failed"
        step.last_error_code = "MAX_RETRIES_EXCEEDED"
        step.error = f"Max execution attempts reached for tool '{tool_name}'"
        steps[idx] = step
        return {"steps": steps, "failed_step_index": idx}

    step.status = "running"
    step.attempts += 1
    steps[idx] = step

    try:
        # 5) Execute tool
        if hasattr(tool, "ainvoke"):
            tool_output = await tool.ainvoke(tool_args)
        else:
            tool_output = tool.invoke(tool_args)
        tool_output = json.loads(tool_output)
        # 6) Summarize/store result
        if tool_output.get("ok"):
            step.status = "done"
            step.last_error_code = None
            step.result_summary = json.dumps(tool_output, default=str)
            step.error = None
            current_step_index = idx + 1
            failed_step_index = None
        else:
            step.status = "failed"
            step.result_summary = ""
            err = tool_output.get("error")
            step.last_error_code = (
                err.get("code") if isinstance(err, dict) else "TOOL_ERROR"
            )
            step.error = str(err)
            current_step_index = idx
            failed_step_index = idx

        # 7) Advance pointer
        steps[idx] = step
        return {
            "steps": steps,
            "current_step_index": current_step_index,
            "failed_step_index": failed_step_index,
        }

    except Exception as e:
        # 8) Failure path
        step.status = "failed"
        step.last_error_code = "EXECUTION_EXCEPTION"
        step.error = str(e)
        steps[idx] = step
        return {"steps": steps, "failed_step_index": idx}
