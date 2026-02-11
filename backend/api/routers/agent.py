from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import aiosqlite
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from ...logger import logprint


router = APIRouter(tags=["agent"])


class AlertContext(BaseModel):
    id: str | int
    ticker: str
    isin: str
    start_date: str
    end_date: str
    instrument_name: Optional[str] = None
    trade_type: Optional[str] = None
    status: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    session_id: str
    alert_context: Optional[AlertContext] = None


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
        frontend_messages = []
        for msg in messages:
            if hasattr(msg, "type"):
                if msg.type in {"system", "tool"}:
                    continue

            role = "user" if (hasattr(msg, "type") and msg.type == "human") else "agent"
            content = msg.content if hasattr(msg, "content") else str(msg)

            if isinstance(content, list):
                text_parts = []
                for part in content:
                    if isinstance(part, str):
                        text_parts.append(part)
                    elif isinstance(part, dict) and "text" in part:
                        text_parts.append(part["text"])
                content = " ".join(text_parts)

            if not content or (isinstance(content, str) and not content.strip()):
                continue

            if role == "user" and "[USER QUESTION]" in content:
                parts = content.split("[USER QUESTION]")
                if len(parts) > 1:
                    content = parts[1].strip()

            frontend_messages.append({"role": role, "content": content, "tools": []})

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
        logprint("Failed to fetch chat history", level="ERROR", session_id=session_id, error=str(e))
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

        return {"status": "deleted", "session_id": session_id, "deleted_rows": deleted_count}
    except Exception as e:
        logprint("Failed to delete chat history", level="ERROR", session_id=session_id, error=str(e))
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@router.post("/agent/chat")
async def chat_agent(request: Request, body: ChatRequest):
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

    def _safe_preview(value, max_len: int = 2000):
        if value is None:
            return None
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

    async def event_generator():
        tool_started_at: dict[str, float] = {}
        try:
            async for event in agent.astream_events(input_state, run_config, version="v1"):
                kind = event["event"]
                if kind == "on_chat_model_stream":
                    if event.get("metadata", {}).get("langgraph_node") != "agent":
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
                        yield f"data: {json.dumps({'type': 'token', 'content': content})}\n\n"

                elif kind == "on_tool_start":
                    tool_name = event["name"]
                    tool_started_at[tool_name] = time.time()
                    tool_input = event.get("data", {}).get("input")
                    yield (
                        f"data: {json.dumps({'type': 'tool_start', 'tool': tool_name, 'input': _safe_preview(tool_input)})}\n\n"
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
                    if isinstance(parsed_output, dict) and parsed_output.get("ok") is False:
                        ok = False
                        err = parsed_output.get("error") or {}
                        if isinstance(err, dict):
                            error_code = err.get("code")
                            error_message = err.get("message")
                        else:
                            error_message = str(err)
                        logprint(
                            "Tool execution returned error payload",
                            level="ERROR",
                            session_id=body.session_id,
                            tool=tool_name,
                            error_code=error_code,
                            error_message=error_message,
                        )
                    if (
                        tool_name == "generate_current_alert_report"
                        and isinstance(tool_output, str)
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
            logprint("Agent stream error", level="ERROR", session_id=body.session_id, error=str(e))
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
