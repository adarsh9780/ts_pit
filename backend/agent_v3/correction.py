from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field
import yaml

from backend.agent_v3.prompts import load_chat_prompt
from backend.agent_v3.state import AgentV3State, CorrectionAttempt
from backend.agent_v3.tools import TOOL_REGISTRY
from backend.llm import get_llm_model


class CorrectedArgs(BaseModel):
    tool_args_json: str = "{}"
    reason: str | None = None


SCHEMA_REFERENCE_PATH = Path("artifacts/DB_SCHEMA_REFERENCE.yaml")
QUOTED_SEGMENT_RE = r"(\".*?\"|'.*?')"
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
        with open(SCHEMA_REFERENCE_PATH, "r") as f:
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

    # Explicit table-specific logical aliases for common LLM variants.
    for alias, logical_key in TABLE_ALIAS_OVERRIDES.get(table_name, {}).items():
        db_column = logical_to_db.get(logical_key)
        if not db_column:
            continue
        alias_map[_norm_identifier(alias)] = db_column
    return alias_map


def _replace_aliases_with_physical(query: str, alias_map: dict[str, str]) -> tuple[str, bool]:
    if not alias_map:
        return query, False

    def _replace_outside_quotes(
        text: str, pattern: re.Pattern[str], replacement: str
    ) -> tuple[str, bool]:
        # Replace only in non-quoted segments to avoid repeatedly rewriting
        # already quoted physical identifiers.
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

    # Exact alias hit.
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

    # No fuzzy fallback: deterministic exact aliases only.
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

    reason = (
        "Applied deterministic SQL identifier rewrite using DB schema physical columns."
    )
    return rewritten2, reason


def _deterministic_sql_args_correction(
    tool_args: dict[str, Any], error_text: str
) -> tuple[dict[str, Any], str] | None:
    if "missing 'query' field" not in error_text.lower():
        return None
    kwargs = tool_args.get("kwargs")
    if isinstance(kwargs, dict):
        query = kwargs.get("query")
        if isinstance(query, str) and query.strip():
            return (
                {"query": query.strip()},
                "Normalized execute_sql args from kwargs.query to query.",
            )
    return None


def _parse_tool_args_json(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return {}


def code_correction(state: AgentV3State, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    idx = (
        state.failed_step_index
        if state.failed_step_index is not None
        else state.current_step_index
    )
    if idx < 0 or idx >= len(state.steps):
        return {"should_replan": True}

    steps = list(state.steps)
    step = steps[idx]
    tool = TOOL_REGISTRY.get(step.tool)
    if tool is None:
        return {
            "should_replan": True,
            "terminal_error": f"Unknown tool in correction node: {step.tool}",
        }

    # Deterministic path for SQL DB column errors before using LLM correction.
    old_args = step.tool_args or {}
    if step.tool == "execute_sql" and str(step.last_error_code or "").upper() == "DB_ERROR":
        query = str(old_args.get("query") or "").strip()
        deterministic = _deterministic_sql_correction(query, str(step.error or ""))
        if deterministic is not None:
            rewritten_query, det_reason = deterministic
            if rewritten_query and rewritten_query != query:
                prev_error_code = step.last_error_code
                prev_error_message = step.error
                step.tool_args = {"query": rewritten_query}
                step.status = "pending"
                step.correction_attempts += 1
                step.error = None
                step.last_error_code = None

                history = list(step.correction_history)
                history.append(
                    CorrectionAttempt(
                        attempt=len(history) + 1,
                        error_code=prev_error_code,
                        error_message=prev_error_message,
                        old_args=old_args,
                        new_args=step.tool_args,
                        reason=det_reason,
                    )
                )
                step.correction_history = history
                steps[idx] = step

                return {
                    "steps": steps,
                    "current_step_index": idx,
                    "failed_step_index": None,
                    "should_replan": False,
                }
    if step.tool == "execute_sql" and str(step.last_error_code or "").upper() == "INVALID_INPUT":
        det_args = _deterministic_sql_args_correction(old_args, str(step.error or ""))
        if det_args is not None:
            normalized_args, det_reason = det_args
            prev_error_code = step.last_error_code
            prev_error_message = step.error
            step.tool_args = normalized_args
            step.status = "pending"
            step.correction_attempts += 1
            step.error = None
            step.last_error_code = None

            history = list(step.correction_history)
            history.append(
                CorrectionAttempt(
                    attempt=len(history) + 1,
                    error_code=prev_error_code,
                    error_message=prev_error_message,
                    old_args=old_args,
                    new_args=step.tool_args,
                    reason=det_reason,
                )
            )
            step.correction_history = history
            steps[idx] = step

            return {
                "steps": steps,
                "current_step_index": idx,
                "failed_step_index": None,
                "should_replan": False,
            }

    prompt_template = load_chat_prompt("execution")
    prompt = prompt_template.invoke(
        {
            "query": step.instruction,
            "messages": state.messages,
            "instruction": step.instruction,
            "tool_name": step.tool,
            "tool_description": tool.description,
            "current_tool_args": json.dumps(step.tool_args or {}, default=str),
            "error_code": step.last_error_code or "",
            "error_message": step.error or "",
        }
    )

    model = get_llm_model().with_structured_output(CorrectedArgs)
    corrected = cast(CorrectedArgs, model.invoke(prompt))
    corrected_args = _parse_tool_args_json(corrected.tool_args_json)
    if not corrected_args:
        return {"should_replan": True}

    if corrected_args == old_args:
        return {
            "should_replan": True,
            "terminal_error": (
                "Correction produced identical tool arguments; cannot recover automatically."
            ),
        }
    prev_error_code = step.last_error_code
    prev_error_message = step.error
    step.tool_args = corrected_args
    step.status = "pending"
    step.correction_attempts += 1
    step.error = None
    step.last_error_code = None

    history = list(step.correction_history)
    history.append(
        CorrectionAttempt(
            attempt=len(history) + 1,
            error_code=prev_error_code,
            error_message=prev_error_message,
            old_args=old_args,
            new_args=corrected_args,
            reason=corrected.reason,
        )
    )
    step.correction_history = history
    steps[idx] = step

    return {
        "steps": steps,
        "current_step_index": idx,
        "failed_step_index": None,
        "should_replan": False,
    }
