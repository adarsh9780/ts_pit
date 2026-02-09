from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ...config import get_config
from ...database import get_db_connection
from ...reporting import (
    REPORTS_ROOT,
    generate_alert_report_html,
    sanitize_session_id,
    save_chart_snapshot,
)


router = APIRouter(tags=["reports"])
config = get_config()


class ReportRequest(BaseModel):
    session_id: str
    include_web_news: bool = False


class ChartSnapshotRequest(BaseModel):
    session_id: str
    alert_id: str | int
    image_data_url: str


def _session_artifacts_root(session_id: str) -> Path:
    safe_session = sanitize_session_id(session_id)
    return (REPORTS_ROOT / safe_session).resolve()


def _artifact_meta(session_root: Path, file_path: Path) -> dict:
    stat = file_path.stat()
    rel_path = file_path.relative_to(session_root).as_posix()
    return {
        "name": file_path.name,
        "relative_path": rel_path,
        "size_bytes": stat.st_size,
        "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


@router.post("/alerts/{alert_id}/report")
def generate_alert_report(alert_id: str, body: ReportRequest, request: Request):
    conn = get_db_connection()
    try:
        session_id = sanitize_session_id(body.session_id)
        result = generate_alert_report_html(
            conn=conn,
            config=config,
            llm=request.app.state.llm,
            alert_id=alert_id,
            session_id=session_id,
            include_web_news=body.include_web_news,
        )
        if not result.get("ok"):
            if result.get("error") == "Alert not found":
                raise HTTPException(status_code=404, detail="Alert not found")
            raise HTTPException(status_code=500, detail=result.get("error", "Report generation failed"))
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@router.post("/reports/chart-snapshot")
def upload_chart_snapshot(body: ChartSnapshotRequest):
    try:
        session_id = sanitize_session_id(body.session_id)
        return save_chart_snapshot(
            session_id=session_id,
            alert_id=body.alert_id,
            image_data_url=body.image_data_url,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/reports/{session_id}/{report_filename}")
def download_report(session_id: str, report_filename: str):
    session_id = sanitize_session_id(session_id)
    safe_name = Path(report_filename).name
    target = (REPORTS_ROOT / session_id / safe_name).resolve()
    root = REPORTS_ROOT.resolve()

    if not str(target).startswith(str(root)):
        raise HTTPException(status_code=400, detail="Invalid report path")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Report not found")

    return FileResponse(target, filename=safe_name, media_type="text/html")


@router.get("/artifacts/{session_id}")
def list_session_artifacts(session_id: str):
    session_root = _session_artifacts_root(session_id)
    if not session_root.exists() or not session_root.is_dir():
        return {"session_id": session_id, "artifacts": []}

    artifacts = []
    for p in session_root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(session_root).as_posix()
        if rel.startswith("chart_snapshots/"):
            continue
        artifacts.append(_artifact_meta(session_root, p))

    artifacts.sort(key=lambda x: x["created_at"], reverse=True)
    return {"session_id": session_id, "artifacts": artifacts}


@router.get("/artifacts/{session_id}/download")
def download_session_artifact(session_id: str, path: str = Query(..., min_length=1)):
    session_root = _session_artifacts_root(session_id)
    if not session_root.exists() or not session_root.is_dir():
        raise HTTPException(status_code=404, detail="Session artifacts not found")

    candidate = (session_root / path).resolve()
    if not str(candidate).startswith(str(session_root)):
        raise HTTPException(status_code=400, detail="Invalid artifact path")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")

    return FileResponse(candidate, filename=candidate.name)

