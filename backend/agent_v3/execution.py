from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal, cast

import yaml
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel

from backend.agent_v3.prompts import load_chat_prompt
from backend.agent_v3.state import AgentV3State, CorrectionAttempt
from backend.agent_v3.tools import TOOL_REGISTRY
from backend.config import get_config
from backend.llm import get_llm_model


SCHEMA_REFERENCE_PATH = Path("artifacts/DB_SCHEMA_REFERENCE.yaml")
QUOTED_SEGMENT_RE = r"(\".*?\"|'.*?')"
RETRYABLE_ERROR_CODES = {
    "READ_ONLY_ENFORCED",
    "INVALID_INPUT",
    "TABLE_NOT_FOUND",
    "DB_ERROR",
    "PYTHON_EXEC_ERROR",
    "TOOL_ERROR",
    "EXECUTION_EXCEPTION",
}
TABLE_ALIAS_OVERRIDES: dict[str, dict[str, str]] = {
    "alerts": {
        "alert_id": "id",
        "created_at": "alert_date",
        "created_date": "alert_date",
        "creation_date": "alert_date",
        "generated_at": "alert_date",
        "generated_date": "alert_date",
        "investigation_window_start": "start_date",
        "investigation_window_end": "end_date",
        "window_start": "start_date",
        "window_end": "end_date",
    },
    "articles": {
        "created_at": "created_date",
        "published_at": "created_date",
        "published_date": "created_date",
    },
}

retry_cfg = get_config().get_agent_retry_config()
MAX_RETRIES = int(retry_cfg.get("max_tool_error_retries", 1))
MAX_EXECUTION_ATTEMPTS = MAX_RETRIES + 1


tool_descriptions = "\n".join(
    f"- {name}: {structured_tool.description}"
    for name, structured_tool in TOOL_REGISTRY.items()
)


class ExecutionProposal(BaseModel):
    tool_name: str
    tool_args_json: str = "{}"
    reason: str | None = None


def _has_no_data_retry(step: Any) -> bool:
    return any(
        str(item.error_code or "").upper() == "NO_DATA"
        for item in (step.retry_history or [])
    )


def _is_empty_sql_success(tool_name: str, result: dict[str, Any]) -> bool:
    if tool_name != "execute_sql":
        return False
    if not bool(result.get("ok")):
        return False
    data = result.get("data")
    if isinstance(data, list):
        return len(data) == 0
    if isinstance(data, dict):
        row_count = (result.get("meta") or {}).get("row_count")
        if isinstance(row_count, int):
            return row_count == 0
    row_count = (result.get("meta") or {}).get("row_count")
    return isinstance(row_count, int) and row_count == 0


def _first_pending_index(steps: list[Any]) -> int:
    for idx, step in enumerate(steps):
        if step.status in {"pending", "running"}:
            return idx
    return len(steps)


def _safe_json_loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {"raw": raw}
    except Exception:
        return {"raw": str(raw)}


def _parse_tool_args_json(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return {}


def _attempt_signature(tool_name: str, tool_args: dict[str, Any]) -> str:
    try:
        key = json.dumps(tool_args, sort_keys=True, separators=(",", ":"))
    except Exception:
        key = str(tool_args)
    return f"{tool_name}:{key}"


def _norm_identifier(value: str) -> str:
    txt = str(value or "").strip().lower()
    txt = re.sub(r"[^a-z0-9]+", "_", txt)
    return re.sub(r"_+", "_", txt).strip("_")


def _quote_identifier(value: str) -> str:
    escaped = str(value).replace('"', '""')
    return f'"{escaped}"'


def _extract_table_name(query: str) -> str | None:
    match = re.search(r"\bfrom\s+([A-Za-z_][\w]*)", query, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip().lower()


def _extract_missing_column(error_text: str) -> str | None:
    match = re.search(r"no such column:\s*([A-Za-z_][\w]*)", error_text, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip()


def _load_table_alias_map(table_name: str) -> dict[str, str]:
    if not SCHEMA_REFERENCE_PATH.exists():
        return {}
    try:
        with open(SCHEMA_REFERENCE_PATH, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except Exception:
        return {}

    tables = raw.get("tables") if isinstance(raw, dict) else {}
    if not isinstance(tables, dict):
        return {}
    table_info = tables.get(table_name)
    if not isinstance(table_info, dict):
        return {}
    columns = table_info.get("columns")
    if not isinstance(columns, dict):
        return {}

    alias_map: dict[str, str] = {}
    logical_to_db: dict[str, str] = {}
    for logical_name, meta in columns.items():
        if not isinstance(meta, dict):
            continue
        db_column = str(meta.get("db_column") or "").strip()
        logical = str(logical_name or "").strip()
        if not db_column or not logical:
            continue
        logical_to_db[logical] = db_column
        aliases = {
            logical,
            _norm_identifier(logical),
            db_column,
            _norm_identifier(db_column),
        }
        for alias in aliases:
            norm = _norm_identifier(alias)
            if norm:
                alias_map[norm] = db_column

    for alias, logical_key in TABLE_ALIAS_OVERRIDES.get(table_name, {}).items():
        db_column = logical_to_db.get(logical_key)
        if db_column:
            alias_map[_norm_identifier(alias)] = db_column
    return alias_map


def _replace_aliases_with_physical(query: str, alias_map: dict[str, str]) -> tuple[str, bool]:
    if not alias_map:
        return query, False

    def _replace_outside_quotes(
        text: str, pattern: re.Pattern[str], replacement: str
    ) -> tuple[str, bool]:
        parts = re.split(QUOTED_SEGMENT_RE, text)
        changed_local = False
        for i in range(0, len(parts), 2):
            updated = pattern.sub(replacement, parts[i])
            if updated != parts[i]:
                changed_local = True
                parts[i] = updated
        return "".join(parts), changed_local

    changed = False
    rewritten = query
    aliases = sorted(alias_map.keys(), key=len, reverse=True)
    for alias in aliases:
        physical = _quote_identifier(alias_map[alias])
        pattern = re.compile(rf"\b{re.escape(alias)}\b", flags=re.IGNORECASE)
        rewritten, changed_local = _replace_outside_quotes(rewritten, pattern, physical)
        changed = changed or changed_local
    return rewritten, changed


def _rewrite_missing_column(
    query: str, missing_col: str | None, alias_map: dict[str, str]
) -> tuple[str, bool]:
    if not missing_col or not alias_map:
        return query, False

    missing_norm = _norm_identifier(missing_col)
    if not missing_norm:
        return query, False

    if missing_norm in alias_map:
        replacement = _quote_identifier(alias_map[missing_norm])
        pattern = re.compile(rf"\b{re.escape(missing_col)}\b", flags=re.IGNORECASE)
        parts = re.split(QUOTED_SEGMENT_RE, query)
        changed = False
        for i in range(0, len(parts), 2):
            updated = pattern.sub(replacement, parts[i])
            if updated != parts[i]:
                changed = True
                parts[i] = updated
        return "".join(parts), changed

    return query, False


def _deterministic_sql_correction(query: str, error_text: str) -> tuple[str, str] | None:
    table_name = _extract_table_name(query)
    if not table_name:
        return None
    alias_map = _load_table_alias_map(table_name)
    if not alias_map:
        return None

    rewritten, changed = _replace_aliases_with_physical(query, alias_map)
    missing_col = _extract_missing_column(error_text)
    rewritten2, changed2 = _rewrite_missing_column(rewritten, missing_col, alias_map)
    if not (changed or changed2):
        return None

    return (
        rewritten2,
        "Applied deterministic SQL identifier rewrite using DB schema physical columns.",
    )


def _normalize_tool_args(tool_name: str, tool_args: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(tool_args, dict):
        return {}
    normalized = dict(tool_args)

    if tool_name == "execute_sql":
        query = normalized.get("query")
        if isinstance(query, str) and query.strip():
            return normalized
        kwargs = normalized.get("kwargs")
        if isinstance(kwargs, dict):
            kw_query = kwargs.get("query")
            if isinstance(kw_query, str) and kw_query.strip():
                return {"query": kw_query.strip()}
    return normalized


def _completed_outputs(state: AgentV3State) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for step in state.steps:
        if step.status != "done":
            continue
        rows.append(
            {
                "id": step.id,
                "instruction": step.instruction,
                "tool": step.selected_tool,
                "result": step.result_payload,
            }
        )
    return rows


def _propose_execution(
    state: AgentV3State,
    *,
    instruction: str,
    goal: str,
    success_criteria: str,
    constraints: list[str],
    current_tool_name: str,
    current_tool_args: dict[str, Any],
    error_code: str,
    error_message: str,
    allowed_tool_switch: bool,
    force_tool_name: str,
) -> ExecutionProposal:
    prompt_template = load_chat_prompt("execution")
    prompt = prompt_template.invoke(
        {
            "query": instruction,
            "messages": state.messages,
            "instruction": instruction,
            "goal": goal,
            "success_criteria": success_criteria,
            "constraints": json.dumps(constraints, default=str),
            "tool_descriptions": tool_descriptions,
            "completed_step_outputs": json.dumps(_completed_outputs(state), default=str),
            "current_alert": state.current_alert.model_dump_json(),
            "current_tool_name": current_tool_name,
            "current_tool_args": json.dumps(current_tool_args, default=str),
            "error_code": error_code,
            "error_message": error_message,
            "allowed_tool_switch": str(bool(allowed_tool_switch)).lower(),
            "force_tool_name": force_tool_name,
        }
    )
    model = get_llm_model().with_structured_output(ExecutionProposal)
    return cast(ExecutionProposal, model.invoke(prompt))


async def _invoke_tool(tool_name: str, tool_args: dict[str, Any]) -> dict[str, Any]:
    tool = TOOL_REGISTRY.get(tool_name)
    if tool is None:
        return {
            "ok": False,
            "error": {
                "code": "INVALID_INPUT",
                "message": f"Unknown tool: {tool_name}",
            },
        }

    try:
        if hasattr(tool, "ainvoke"):
            raw_output = await tool.ainvoke(tool_args)
        else:
            raw_output = tool.invoke(tool_args)
    except Exception as exc:
        return {
            "ok": False,
            "error": {
                "code": "EXECUTION_EXCEPTION",
                "message": str(exc),
            },
        }

    if isinstance(raw_output, str):
        try:
            parsed = json.loads(raw_output)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {"ok": True, "data": raw_output, "message": "raw tool output"}
    if isinstance(raw_output, dict):
        return raw_output
    return {"ok": True, "data": raw_output}


async def executioner(state: AgentV3State, config: RunnableConfig) -> dict[str, Any]:
    _ = config

    idx = _first_pending_index(state.steps)
    if idx >= len(state.steps):
        return {"current_step_index": idx}

    steps = list(state.steps)
    step = steps[idx]

    seen_signatures: set[str] = set()
    last_error_code = str(step.last_error_code or "")
    last_error_message = str(step.error or "")
    allowed_tool_switch = False
    forced_tool_name = str(step.selected_tool or "")

    while step.attempts < MAX_EXECUTION_ATTEMPTS:
        proposal = _propose_execution(
            state,
            instruction=step.instruction,
            goal=step.goal or step.instruction,
            success_criteria=step.success_criteria or "Complete the step successfully.",
            constraints=step.constraints,
            current_tool_name=str(step.selected_tool or ""),
            current_tool_args=step.tool_args or {},
            error_code=last_error_code,
            error_message=last_error_message,
            allowed_tool_switch=allowed_tool_switch,
            force_tool_name=forced_tool_name,
        )

        tool_name = str(proposal.tool_name or "").strip() or forced_tool_name
        if forced_tool_name and not allowed_tool_switch:
            tool_name = forced_tool_name
        if tool_name not in TOOL_REGISTRY:
            step.attempts += 1
            last_error_code = "INVALID_INPUT"
            last_error_message = f"Unknown proposed tool: {tool_name}"
            allowed_tool_switch = True
            continue

        tool_args = _normalize_tool_args(tool_name, _parse_tool_args_json(proposal.tool_args_json))
        signature = _attempt_signature(tool_name, tool_args)
        signature_repeated = signature in seen_signatures
        seen_signatures.add(signature)

        step.status = "running"
        step.selected_tool = tool_name
        step.tool_args = tool_args
        step.last_attempt_signature = signature
        step.attempts += 1

        result = await _invoke_tool(tool_name, tool_args)
        ok = bool(result.get("ok"))

        if ok:
            # Retry once for empty SQL results before finalizing as done.
            if _is_empty_sql_success(tool_name, result) and not _has_no_data_retry(step):
                history = list(step.retry_history)
                history.append(
                    CorrectionAttempt(
                        attempt=len(history) + 1,
                        error_code="NO_DATA",
                        error_message="SQL returned 0 rows.",
                        old_args=tool_args,
                        new_args={},
                        reason=(
                            "Retrying once with revised SQL to handle possible "
                            "overly restrictive filters."
                        ),
                    )
                )
                step.retry_history = history
                step.status = "pending"
                step.error = None
                step.last_error_code = None
                last_error_code = "NO_DATA"
                last_error_message = (
                    "Previous SQL returned 0 rows. Retry once with adjusted filters, "
                    "same business intent, and still read-only SELECT."
                )
                forced_tool_name = "execute_sql"
                allowed_tool_switch = False
                continue

            step.status = "done"
            step.last_error_code = None
            step.error = None
            step.result_payload = _safe_json_loads(json.dumps(result, default=str))
            step.result_summary = json.dumps(result, default=str)
            steps[idx] = step
            return {
                "steps": steps,
                "failed_step_index": None,
                "current_step_index": _first_pending_index(steps),
                "terminal_error": None,
            }

        err = result.get("error") if isinstance(result, dict) else None
        error_code = str((err or {}).get("code") or "TOOL_ERROR").upper()
        error_message = str((err or {}).get("message") or result)

        step.status = "failed"
        step.last_error_code = error_code
        step.error = error_message

        history = list(step.retry_history)
        history.append(
            CorrectionAttempt(
                attempt=len(history) + 1,
                error_code=error_code,
                error_message=error_message,
                old_args=tool_args,
                new_args={},
                reason=proposal.reason,
            )
        )
        step.retry_history = history

        retryable = error_code in RETRYABLE_ERROR_CODES
        out_of_attempts = step.attempts >= MAX_EXECUTION_ATTEMPTS
        if (not retryable) or out_of_attempts:
            steps[idx] = step
            return {
                "steps": steps,
                "failed_step_index": idx,
                "current_step_index": idx,
                "terminal_error": error_message,
            }

        # deterministic SQL correction before another proposal
        if tool_name == "execute_sql":
            query = str(tool_args.get("query") or "").strip()
            deterministic = _deterministic_sql_correction(query, error_message)
            if deterministic is not None:
                rewritten_query, det_reason = deterministic
                if rewritten_query and rewritten_query != query:
                    step.status = "pending"
                    step.selected_tool = "execute_sql"
                    step.tool_args = {"query": rewritten_query}
                    step.error = None
                    step.last_error_code = None
                    forced_tool_name = "execute_sql"
                    allowed_tool_switch = False
                    last_error_code = ""
                    last_error_message = ""
                    history = list(step.retry_history)
                    history.append(
                        CorrectionAttempt(
                            attempt=len(history) + 1,
                            error_code=error_code,
                            error_message=error_message,
                            old_args=tool_args,
                            new_args=step.tool_args,
                            reason=det_reason,
                        )
                    )
                    step.retry_history = history
                    continue

        # missing query normalization fallback
        if tool_name == "execute_sql" and "missing 'query' field" in error_message.lower():
            kwargs = tool_args.get("kwargs") if isinstance(tool_args, dict) else None
            if isinstance(kwargs, dict):
                kw_query = kwargs.get("query")
                if isinstance(kw_query, str) and kw_query.strip():
                    step.status = "pending"
                    step.selected_tool = "execute_sql"
                    step.tool_args = {"query": kw_query.strip()}
                    step.error = None
                    step.last_error_code = None
                    forced_tool_name = "execute_sql"
                    allowed_tool_switch = False
                    last_error_code = ""
                    last_error_message = ""
                    continue

        # next retry policy
        last_error_code = error_code
        last_error_message = error_message
        if error_code == "INVALID_INPUT" or signature_repeated:
            allowed_tool_switch = True
            forced_tool_name = ""
        else:
            allowed_tool_switch = False
            forced_tool_name = tool_name

    # Should not normally hit because returns above, but keep safe fallback.
    step.status = "failed"
    step.last_error_code = step.last_error_code or "MAX_RETRIES_EXCEEDED"
    step.error = step.error or "Max retries exceeded"
    steps[idx] = step
    return {
        "steps": steps,
        "failed_step_index": idx,
        "current_step_index": idx,
        "terminal_error": step.error,
    }
