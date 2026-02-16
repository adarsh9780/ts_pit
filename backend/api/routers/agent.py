from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

import aiosqlite
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from ...logger import logprint


router = APIRouter(tags=["agent"])
STREAMABLE_MODEL_NODES = {
    "agent",
    "direct_answer",
    "planner",
    "respond",
    "answer_rewriter",
}
FALLBACK_MODEL_OUTPUT_NODES = {
    "agent",
    "direct_answer",
    "planner",
    "respond",
    "answer_validator",
    "answer_rewriter",
}


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


def _should_stream_model_chunk(event: dict) -> bool:
    node_name = event.get("metadata", {}).get("langgraph_node")
    return node_name in STREAMABLE_MODEL_NODES


def _content_to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        text_parts: list[str] = []
        for part in value:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict) and "text" in part:
                text_parts.append(str(part["text"]))
        return " ".join(text_parts)
    return str(value)


def _extract_fallback_ai_text(event: dict) -> str:
    """
    Extract final assistant text when no token stream chunks are emitted.
    This is needed for agent_v3 planner/structured output flows.
    """
    output = event.get("data", {}).get("output")
    node_name = event.get("metadata", {}).get("langgraph_node")
    allow_ephemeral = node_name in {"planner", "respond", "answer_rewriter"}

    if output is None:
        return ""

    if isinstance(output, dict):
        messages = output.get("messages")
        if isinstance(messages, list):
            for msg in reversed(messages):
                role = str(getattr(msg, "type", "")).lower()
                if role in {"ai", "assistant"}:
                    additional = getattr(msg, "additional_kwargs", None)
                    if (
                        isinstance(additional, dict)
                        and additional.get("ephemeral_node_output")
                        and not allow_ephemeral
                    ):
                        continue
                    return _content_to_text(getattr(msg, "content", ""))
        return _content_to_text(output.get("content"))

    role = str(getattr(output, "type", "")).lower()
    if role in {"ai", "assistant"}:
        additional = getattr(output, "additional_kwargs", None)
        if (
            isinstance(additional, dict)
            and additional.get("ephemeral_node_output")
            and not allow_ephemeral
        ):
            return ""
        return _content_to_text(getattr(output, "content", ""))

    return ""


def _extract_ephemeral_ai_text(event: dict) -> str:
    """
    Extract assistant text from ephemeral node outputs.
    Used for draft-update ribbons in the UI.
    """
    output = event.get("data", {}).get("output")
    if output is None:
        return ""

    if isinstance(output, dict):
        messages = output.get("messages")
        if isinstance(messages, list):
            for msg in reversed(messages):
                role = str(getattr(msg, "type", "")).lower()
                if role not in {"ai", "assistant"}:
                    continue
                additional = getattr(msg, "additional_kwargs", None)
                if not isinstance(additional, dict):
                    continue
                if not additional.get("ephemeral_node_output"):
                    continue
                return _content_to_text(getattr(msg, "content", ""))
        return ""

    role = str(getattr(output, "type", "")).lower()
    if role in {"ai", "assistant"}:
        additional = getattr(output, "additional_kwargs", None)
        if isinstance(additional, dict) and additional.get("ephemeral_node_output"):
            return _content_to_text(getattr(output, "content", ""))
    return ""


def _extract_context_debug_payload(event: dict) -> dict | None:
    output = event.get("data", {}).get("output")
    if not isinstance(output, dict):
        return None

    payload = output
    nested = output.get("context_manager")
    if isinstance(nested, dict):
        payload = nested

    if "token_estimate" not in payload and "summary_version" not in payload:
        return None

    token_estimate = payload.get("token_estimate")
    summary_version = payload.get("summary_version")
    summarization_triggered = any(
        key in payload
        for key in (
            "conversation_summary",
            "summary_version",
            "last_summarized_message_index",
        )
    )
    return {
        "type": "context_debug",
        "active": True,
        "token_estimate": token_estimate if isinstance(token_estimate, int) else None,
        "summary_version": summary_version if isinstance(summary_version, int) else None,
        "summarization_triggered": bool(summarization_triggered),
    }


def _extract_tool_calls(msg) -> list[dict]:
    raw_calls = getattr(msg, "tool_calls", None)
    if not raw_calls:
        additional = getattr(msg, "additional_kwargs", None)
        if isinstance(additional, dict):
            raw_calls = additional.get("tool_calls")
    if not isinstance(raw_calls, list):
        return []

    tools: list[dict] = []
    for idx, call in enumerate(raw_calls, start=1):
        if not isinstance(call, dict):
            continue
        tool_name = call.get("name")
        if not tool_name:
            fn = call.get("function")
            if isinstance(fn, dict):
                tool_name = fn.get("name")
        if not tool_name:
            continue

        tool_args = call.get("args")
        if tool_args is None:
            fn = call.get("function")
            if isinstance(fn, dict):
                tool_args = fn.get("arguments")
        if isinstance(tool_args, (dict, list)):
            tool_input = json.dumps(tool_args, default=str)
        elif tool_args is None:
            tool_input = None
        else:
            tool_input = str(tool_args)

        call_id = call.get("id")
        if not call_id:
            call_id = f"{tool_name}-{idx}"

        tools.append(
            {
                "id": str(call_id),
                "name": str(tool_name),
                "status": "done",
                "input": tool_input,
                "output": None,
                "durationMs": None,
                "commentary": None,
                "errorCode": None,
                "errorMessage": None,
            }
        )
    return tools


def _attach_tool_output(tool_map: dict[str, dict], tool_entry: dict) -> None:
    call_id = tool_entry.get("tool_call_id")
    tool_name = tool_entry.get("name")
    target = None
    if call_id and call_id in tool_map:
        target = tool_map[call_id]
    elif tool_name:
        for existing in tool_map.values():
            if existing.get("name") == tool_name:
                target = existing
    if not target:
        return

    target["output"] = tool_entry.get("output")
    if tool_entry.get("status"):
        target["status"] = tool_entry["status"]


def _build_frontend_messages(messages: list) -> list[dict]:
    normalized_events: list[dict] = []
    for msg in messages:
        msg_type = getattr(msg, "type", "")
        if msg_type == "system":
            continue

        if msg_type in {"human", "user"}:
            user_content = _content_to_text(getattr(msg, "content", ""))
            if user_content and "[USER QUESTION]" in user_content:
                parts = user_content.split("[USER QUESTION]")
                if len(parts) > 1:
                    user_content = parts[1].strip()
            if user_content and user_content.strip():
                normalized_events.append({"kind": "user", "content": user_content.strip()})
            continue

        if msg_type in {"ai", "assistant"}:
            additional = getattr(msg, "additional_kwargs", None)
            if isinstance(additional, dict) and additional.get("ephemeral_node_output"):
                continue
            assistant_content = _content_to_text(getattr(msg, "content", ""))
            tool_calls = _extract_tool_calls(msg)
            normalized_events.append(
                {
                    "kind": "assistant",
                    "content": assistant_content.strip()
                    if isinstance(assistant_content, str)
                    else "",
                    "tools": tool_calls,
                }
            )
            continue

        if msg_type == "tool":
            normalized_events.append(
                {
                    "kind": "tool",
                    "name": str(getattr(msg, "name", "") or ""),
                    "tool_call_id": str(getattr(msg, "tool_call_id", "") or ""),
                    "output": _content_to_text(getattr(msg, "content", "")),
                    "status": str(getattr(msg, "status", "") or "done"),
                }
            )

    frontend_messages: list[dict] = []
    turn_tools_map: dict[str, dict] = {}
    turn_tool_seq = 0
    assistant_parts: list[str] = []
    last_user_content: str | None = None

    def _flush_turn():
        nonlocal turn_tools_map, turn_tool_seq, assistant_parts
        content = "\n\n".join([part for part in assistant_parts if part]).strip()
        tools = list(turn_tools_map.values())

        # Drop pure assistant echo of the latest user prompt when there are no tool traces.
        if (
            content
            and not tools
            and last_user_content
            and " ".join(content.split()).lower()
            == " ".join(last_user_content.split()).lower()
        ):
            content = ""

        if content:
            if (
                frontend_messages
                and frontend_messages[-1].get("role") == "agent"
                and str(frontend_messages[-1].get("content", "")).strip() == content
            ):
                if tools:
                    existing = frontend_messages[-1].setdefault("tools", [])
                    existing.extend(tools)
            else:
                frontend_messages.append(
                    {"role": "agent", "content": content, "tools": tools}
                )
        turn_tools_map = {}
        turn_tool_seq = 0
        assistant_parts = []

    for event in normalized_events:
        kind = event.get("kind")
        if kind == "user":
            _flush_turn()
            last_user_content = str(event["content"])
            frontend_messages.append(
                {"role": "user", "content": event["content"], "tools": []}
            )
            continue

        if kind == "assistant":
            content = str(event.get("content") or "").strip()
            if content and (not assistant_parts or assistant_parts[-1] != content):
                assistant_parts.append(content)

            for tool in event.get("tools", []):
                turn_tool_seq += 1
                tool_id = str(
                    tool.get("id") or f"{tool.get('name', 'tool')}-{turn_tool_seq}"
                )
                if tool_id in turn_tools_map:
                    continue
                turn_tools_map[tool_id] = tool
            continue

        if kind == "tool":
            _attach_tool_output(turn_tools_map, event)

    _flush_turn()
    return frontend_messages


class AlertContext(BaseModel):
    id: str | int
    ticker: str
    isin: str
    start_date: str
    end_date: str
    instrument_name: Optional[str] = None
    trade_type: Optional[str] = None
    status: Optional[str] = None
    buy_qt: Optional[float] = None
    sell_qt: Optional[float] = None
    buy_quantity: Optional[float] = None
    sell_quantity: Optional[float] = None


class ChatRequest(BaseModel):
    message: str
    session_id: str
    alert_context: Optional[AlertContext] = None


def _to_int_quantity(value) -> int:
    try:
        return int(float(value))
    except Exception:
        return 0


@router.get("/agent/history/{session_id}")
async def get_chat_history(
    session_id: str,
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    agent = request.app.state.agent
    run_config = {"configurable": {"thread_id": session_id}}

    try:
        state = await agent.aget_state(run_config)
        if not state or not state.values:
            return {
                "messages": [],
                "pagination": {
                    "limit": limit,
                    "offset": offset,
                    "next_offset": offset,
                    "has_more": False,
                    "total": 0,
                },
            }

        messages = state.values.get("messages", [])
        frontend_messages = _build_frontend_messages(messages)

        total = len(frontend_messages)
        end = max(total - offset, 0)
        start = max(end - limit, 0)
        page_messages = frontend_messages[start:end]
        next_offset = offset + len(page_messages)

        return {
            "messages": page_messages,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "next_offset": next_offset,
                "has_more": start > 0,
                "total": total,
            },
        }

    except Exception as e:
        logprint(
            "Failed to fetch chat history",
            level="ERROR",
            session_id=session_id,
            exception=e,
        )
        return {
            "messages": [],
            "pagination": {
                "limit": limit,
                "offset": offset,
                "next_offset": offset,
                "has_more": False,
                "total": 0,
            },
        }


@router.delete("/agent/history/{session_id}")
async def delete_chat_history(session_id: str, request: Request):
    db_path = Path.home() / ".ts_pit" / "agent_memory.db"

    if not db_path.exists():
        return {
            "status": "deleted",
            "session_id": session_id,
            "message": "No history database found",
        }

    try:
        async with aiosqlite.connect(str(db_path)) as conn:
            deleted_count = 0
            for table in ["checkpoints", "checkpoint_writes", "checkpoint_blobs"]:
                try:
                    cursor = await conn.execute(
                        f"DELETE FROM {table} WHERE thread_id = ?", (session_id,)
                    )
                    deleted_count += cursor.rowcount
                except Exception:
                    pass
            await conn.commit()

        return {
            "status": "deleted",
            "session_id": session_id,
            "deleted_rows": deleted_count,
        }
    except Exception as e:
        logprint(
            "Failed to delete chat history",
            level="ERROR",
            session_id=session_id,
            exception=e,
        )
        return JSONResponse(
            status_code=500, content={"status": "error", "message": str(e)}
        )


@router.post("/agent/chat")
async def chat_agent(request: Request, body: ChatRequest):
    if _looks_like_code_submission(body.message):
        refusal = (
            "I can't process submitted SQL or Python code. "
            "Please describe your objective in plain language, and I can help with analysis steps or findings."
        )

        async def rejection_event_generator():
            yield f"data: {json.dumps({'type': 'token', 'content': refusal})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        return StreamingResponse(
            rejection_event_generator(), media_type="text/event-stream"
        )

    agent = request.app.state.agent
    run_config = {"configurable": {"thread_id": body.session_id}}

    if body.alert_context:
        ctx = body.alert_context
        enriched_message = f"""[CURRENT ALERT CONTEXT]
Alert ID: {ctx.id}
Session ID: {body.session_id}
Ticker: {ctx.ticker} ({ctx.instrument_name or "N/A"})
ISIN: {ctx.isin}
Investigation Window: {ctx.start_date} to {ctx.end_date}
Trade Type: {ctx.trade_type or "N/A"}
Status: {ctx.status or "N/A"}

[USER QUESTION]
{body.message}"""
    else:
        enriched_message = body.message

    input_state = {"messages": [("user", enriched_message)]}
    if body.alert_context and getattr(request.app.state, "agent_mode", "") == "v3":
        ctx = body.alert_context
        alert_id_int: int | None = None
        try:
            alert_id_int = int(ctx.id)
        except Exception:
            alert_id_int = None
        buy_qt = (
            ctx.buy_qt if ctx.buy_qt is not None else ctx.buy_quantity
        )
        sell_qt = (
            ctx.sell_qt if ctx.sell_qt is not None else ctx.sell_quantity
        )
        input_state["current_alert"] = {
            "alert_id": alert_id_int,
            "ticker": ctx.ticker,
            "start_date": ctx.start_date,
            "end_date": ctx.end_date,
            "buy_qt": _to_int_quantity(buy_qt),
            "sell_qt": _to_int_quantity(sell_qt),
        }
    debug_stream = (
        str(request.query_params.get("debug", "")).strip().lower() in {"1", "true", "yes"}
        or str(request.headers.get("x-agent-debug", "")).strip().lower()
        in {"1", "true", "yes"}
    )

    def _safe_preview(value, max_len: int = 2000):
        def _truncate_json_value(raw, max_string_len: int = 900):
            if isinstance(raw, str):
                if len(raw) <= max_string_len:
                    return raw
                return raw[:max_string_len] + "...(truncated)"
            if isinstance(raw, dict):
                return {k: _truncate_json_value(v, max_string_len) for k, v in raw.items()}
            if isinstance(raw, list):
                return [_truncate_json_value(v, max_string_len) for v in raw]
            return raw

        if value is None:
            return None
        if isinstance(value, (dict, list)):
            try:
                # Keep preview JSON parseable in the frontend by truncating
                # long leaf strings instead of truncating the serialized blob.
                structured_preview = _truncate_json_value(value)
                text_value = json.dumps(structured_preview, default=str)
                if len(text_value) > max_len:
                    compact_preview = _truncate_json_value(value, max_string_len=300)
                    text_value = json.dumps(compact_preview, default=str)
                return text_value
            except Exception:
                pass
        try:
            text_value = json.dumps(value, default=str)
        except Exception:
            text_value = str(value)
        if len(text_value) > max_len:
            return text_value[:max_len] + "...(truncated)"
        return text_value

    def _extract_tool_output_payload(raw_output):
        """
        Normalize tool output event payload.

        LangGraph may emit plain strings or ToolMessage-like objects with
        `.content`. We normalize to the actual content string/object so error
        parsing works consistently.
        """
        if raw_output is None:
            return None
        if isinstance(raw_output, (dict, list)):
            return raw_output
        content = getattr(raw_output, "content", None)
        if content is not None:
            return content
        return raw_output

    def _parse_tool_json_payload(normalized_output):
        """
        Parse JSON payload when tool returned stringified JSON.
        Supports wrappers like: content='{"ok": false, ...}'.
        """
        if isinstance(normalized_output, dict):
            return normalized_output
        if not isinstance(normalized_output, str):
            return None
        txt = normalized_output.strip()
        try:
            return json.loads(txt)
        except Exception:
            pass
        marker = "content='"
        if marker in txt and txt.endswith("'"):
            start = txt.find(marker) + len(marker)
            candidate = txt[start:-1]
            try:
                return json.loads(candidate)
            except Exception:
                return None
        return None

    def _tool_commentary(tool_name: str, tool_input=None) -> str:
        parsed_input = None
        if isinstance(tool_input, dict):
            parsed_input = tool_input
        elif isinstance(tool_input, str):
            try:
                maybe = json.loads(tool_input)
                if isinstance(maybe, dict):
                    parsed_input = maybe
            except Exception:
                parsed_input = None

        if tool_name == "read_file":
            path_value = (parsed_input or {}).get("path")
            if path_value:
                return f"I need to inspect `{path_value}` to confirm schema/method details before proceeding."
            return "I need to inspect a reference document before proceeding."

        if tool_name == "execute_sql":
            query = str((parsed_input or {}).get("query") or "").strip()
            if query:
                tables = re.findall(
                    r"\b(?:from|join)\s+([A-Za-z_][\w.]*)", query, flags=re.IGNORECASE
                )
                table_text = (
                    ", ".join(dict.fromkeys(tables))
                    if tables
                    else "the relevant tables"
                )
                return (
                    f"I need to gather the requested fields from {table_text}. "
                    "I will run a read-only SQL query with mapped column names and type-aware filters."
                )
            return "I need to retrieve structured data with a read-only SQL query."

        if tool_name == "execute_python":
            code = str((parsed_input or {}).get("code") or "").strip()
            if code:
                return (
                    "I need to compute derived metrics from the retrieved dataset. "
                    "I will run a bounded Python script and validate input types first."
                )
            return "I need to run a bounded Python computation on the collected inputs."

        comments = {
            "get_article_by_id": "I will load the target article details first.",
            "get_python_capabilities": "I will verify runtime limits and available Python capabilities before computing.",
            "analyze_current_alert": "I will run deterministic alert analysis for the current alert.",
            "generate_current_alert_report": "I will generate the report artifact now.",
            "list_files": "I will enumerate available reference files relevant to this request.",
            "write_file": "I will save the generated markdown artifact to the session report folder.",
            "search_web": "I will search web and news sources for supporting external context.",
        }
        return comments.get(tool_name, f"I will run `{tool_name}` to continue.")

    async def event_generator():
        tool_started_at: dict[str, float] = {}
        streamed_nodes: set[str] = set()
        emitted_fallback_texts: set[str] = set()
        try:
            async for event in agent.astream_events(
                input_state, run_config, version="v1"
            ):
                kind = event["event"]
                if kind == "on_chat_model_stream":
                    node_name = event.get("metadata", {}).get("langgraph_node")
                    if not _should_stream_model_chunk(event):
                        continue

                    chunk = event["data"]["chunk"]
                    content = chunk.content
                    if isinstance(content, list):
                        text_content = ""
                        for block in content:
                            if isinstance(block, str):
                                text_content += block
                            elif isinstance(block, dict) and "text" in block:
                                text_content += block["text"]
                        content = text_content

                    if content:
                        if isinstance(node_name, str) and node_name:
                            streamed_nodes.add(node_name)
                        yield (
                            "data: "
                            + json.dumps(
                                {
                                    "type": "token",
                                    "content": content,
                                    "node": node_name,
                                }
                            )
                            + "\n\n"
                        )

                elif kind == "on_chain_end":
                    node_name = event.get("metadata", {}).get("langgraph_node")
                    if node_name in {"context_manager", "context_metrics"}:
                        debug_payload = _extract_context_debug_payload(event)
                        if debug_payload is not None:
                            yield f"data: {json.dumps(debug_payload)}\n\n"
                    if node_name not in FALLBACK_MODEL_OUTPUT_NODES:
                        continue
                    if node_name == "answer_validator" and debug_stream:
                        validator_text = (_extract_ephemeral_ai_text(event) or "").strip()
                        if validator_text:
                            yield (
                                "data: "
                                + json.dumps(
                                    {
                                        "type": "draft_update",
                                        "node": node_name,
                                        "content": validator_text,
                                    }
                                )
                                + "\n\n"
                            )
                    if isinstance(node_name, str) and node_name in streamed_nodes:
                        continue
                    fallback_text = (_extract_fallback_ai_text(event) or "").strip()
                    if not fallback_text or fallback_text in emitted_fallback_texts:
                        continue
                    emitted_fallback_texts.add(fallback_text)
                    yield (
                        "data: "
                        + json.dumps(
                            {
                                "type": "token",
                                "content": fallback_text,
                                "node": node_name,
                            }
                        )
                        + "\n\n"
                    )

                elif kind == "on_tool_start":
                    tool_name = event["name"]
                    tool_started_at[tool_name] = time.time()
                    tool_input = event.get("data", {}).get("input")
                    yield (
                        f"data: {json.dumps({'type': 'tool_start', 'tool': tool_name, 'input': _safe_preview(tool_input), 'commentary': _tool_commentary(tool_name, tool_input)})}\n\n"
                    )

                elif kind == "on_tool_end":
                    tool_name = event["name"]
                    raw_tool_output = event.get("data", {}).get("output")
                    tool_output = _extract_tool_output_payload(raw_tool_output)
                    duration_ms = None
                    started = tool_started_at.pop(tool_name, None)
                    if started is not None:
                        duration_ms = int((time.time() - started) * 1000)
                    ok = True
                    error_code = None
                    error_message = None
                    parsed_output = _parse_tool_json_payload(tool_output)
                    if (
                        isinstance(parsed_output, dict)
                        and parsed_output.get("ok") is False
                    ):
                        ok = False
                        err = parsed_output.get("error") or {}
                        if isinstance(err, dict):
                            error_code = err.get("code")
                            error_message = err.get("message")
                        else:
                            error_message = str(err)
                        logprint(
                            f"Tool execution returned error payload: {error_message}",
                            level="ERROR",
                            session_id=body.session_id,
                            tool=tool_name,
                            error_code=error_code,
                            error_message=error_message,
                        )
                    if tool_name == "generate_current_alert_report" and isinstance(
                        tool_output, str
                    ):
                        try:
                            parsed = json.loads(tool_output)
                            if parsed.get("ok"):
                                data = parsed.get("data") or {}
                                yield (
                                    f"data: {json.dumps({'type': 'artifact_created', 'tool': tool_name, 'session_id': data.get('session_id'), 'artifact_name': data.get('report_filename'), 'relative_path': data.get('report_filename'), 'expires_at': data.get('expires_at')})}\n\n"
                                )
                        except Exception:
                            pass
                    yield (
                        f"data: {json.dumps({'type': 'tool_end', 'tool': tool_name, 'ok': ok, 'error_code': error_code, 'error_message': error_message, 'output': _safe_preview(tool_output), 'duration_ms': duration_ms})}\n\n"
                    )

            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as e:
            logprint(
                "Agent stream error",
                level="ERROR",
                session_id=body.session_id,
                exception=e,
            )
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
