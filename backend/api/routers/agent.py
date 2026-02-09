from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import aiosqlite
from fastapi import APIRouter, Request
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
async def get_chat_history(session_id: str, request: Request):
    agent = request.app.state.agent
    run_config = {"configurable": {"thread_id": session_id}}

    try:
        state = await agent.aget_state(run_config)
        if not state or not state.values:
            return {"messages": []}

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

        return {"messages": frontend_messages}

    except Exception as e:
        logprint("Failed to fetch chat history", level="ERROR", session_id=session_id, error=str(e))
        return {"messages": []}


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

    async def event_generator():
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
                    yield f"data: {json.dumps({'type': 'tool_start', 'tool': tool_name})}\n\n"

                elif kind == "on_tool_end":
                    tool_name = event["name"]
                    tool_output = event.get("data", {}).get("output")
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
                    yield f"data: {json.dumps({'type': 'tool_end', 'tool': tool_name, 'output': 'Hidden'})}\n\n"

            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as e:
            logprint("Agent stream error", level="ERROR", session_id=body.session_id, error=str(e))
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

