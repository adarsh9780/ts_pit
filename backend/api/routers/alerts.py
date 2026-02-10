from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...alert_analysis import analyze_alert_non_persisting
from ...config import get_config
from ...database import get_db_connection, remap_row
from ...llm import generate_article_analysis
from ...logger import logprint
from ...services.alert_analysis_store import (
    apply_latest_analysis_to_alert,
    fetch_latest_analysis_map,
    insert_alert_analysis,
)
from ...services.alert_normalizer import normalize_alert_response
from ...services.db_helpers import resolve_alert_row


router = APIRouter(tags=["alerts"])
config = get_config()


class StatusUpdate(BaseModel):
    status: str


@router.post("/articles/{id}/analyze")
def analyze_article(id: str, request: Request):
    conn = get_db_connection()
    cursor = conn.cursor()

    articles_table = config.get_table_name("articles")
    article_id_col = config.get_column("articles", "id")

    cursor.execute(
        f'SELECT * FROM "{articles_table}" WHERE "{article_id_col}" = ?', (id,)
    )
    row = cursor.fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Article not found")

    article = dict(row)
    title = article.get("title", "")
    summary = article.get("summary", "")
    z_score = article.get("impact_score") or 0.0
    price_change = 0.0

    llm = request.app.state.llm
    analysis_result = generate_article_analysis(
        title, summary, z_score, price_change, llm=llm
    )

    if analysis_result.get("theme") == "Error":
        conn.close()
        raise HTTPException(status_code=500, detail=analysis_result.get("analysis"))

    themes_table = config.get_table_name("article_themes")
    art_id_col = config.get_column("article_themes", "art_id")
    theme_col = config.get_column("article_themes", "theme")
    summary_col = config.get_column("article_themes", "summary")
    analysis_col = config.get_column("article_themes", "analysis")

    try:
        cursor.execute(
            f'''
            INSERT OR REPLACE INTO "{themes_table}"
            ("{art_id_col}", "{theme_col}", "{summary_col}", "{analysis_col}")
            VALUES (?, ?, ?, ?)
        ''',
            (
                id,
                analysis_result["theme"],
                analysis_result["summary"] or "",
                analysis_result["analysis"],
            ),
        )
        conn.commit()
    except Exception as e:
        logprint("Failed to persist article analysis", level="ERROR", article_id=id, error=str(e))

    conn.close()
    return analysis_result


@router.get("/alerts")
def get_alerts(date: str | None = None):
    conn = get_db_connection()
    cursor = conn.cursor()

    table_name = config.get_table_name("alerts")
    alert_date_col = config.get_column("alerts", "alert_date")

    if date:
        # Support both raw datetime strings and canonical YYYY-MM-DD filters.
        cursor.execute(
            f'''
            SELECT * FROM "{table_name}"
            WHERE "{alert_date_col}" = ?
               OR date("{alert_date_col}") = date(?)
               OR substr("{alert_date_col}", 1, 10) = ?
            ''',
            (date, date, date),
        )
    else:
        cursor.execute(f'SELECT * FROM "{table_name}"')

    rows = cursor.fetchall()
    results = []
    for row in rows:
        remapped = remap_row(dict(row), "alerts")
        results.append(normalize_alert_response(remapped))

    latest_map = fetch_latest_analysis_map(
        conn, [str(item.get("id")) for item in results if item.get("id") is not None]
    )
    conn.close()
    return [apply_latest_analysis_to_alert(item, latest_map) for item in results]


@router.patch("/alerts/{alert_id}/status")
def update_alert_status(alert_id: str | int, update: StatusUpdate):
    normalized_status = config.normalize_status(update.status)
    valid_statuses = config.get_valid_statuses()
    if config.is_status_enforced() and normalized_status not in valid_statuses:
        raise HTTPException(
            status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}"
        )

    conn = get_db_connection()
    cursor = conn.cursor()

    table_name = config.get_table_name("alerts")
    status_col = config.get_column("alerts", "status")
    _, matched_id_col, matched_id_value = resolve_alert_row(cursor, table_name, alert_id)
    if not matched_id_col:
        conn.close()
        raise HTTPException(status_code=404, detail="Alert not found")

    cursor.execute(
        f'UPDATE "{table_name}" SET "{status_col}" = ? WHERE "{matched_id_col}" = ?',
        (normalized_status, matched_id_value),
    )
    conn.commit()

    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Alert not found")

    conn.close()
    return {"message": "Status updated", "alert_id": alert_id, "status": normalized_status}


@router.get("/alerts/{alert_id}")
def get_alert_detail(alert_id: str | int):
    conn = get_db_connection()
    cursor = conn.cursor()

    table_name = config.get_table_name("alerts")
    row, _, _ = resolve_alert_row(cursor, table_name, alert_id)
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Alert not found")

    result = remap_row(dict(row), "alerts")
    normalized = normalize_alert_response(result)
    latest_map = fetch_latest_analysis_map(
        conn,
        [str(normalized.get("id"))] if normalized.get("id") is not None else [],
    )
    conn.close()
    return apply_latest_analysis_to_alert(normalized, latest_map)


@router.post("/alerts/{alert_id}/summary")
def generate_summary(alert_id: str, request: Request):
    conn = get_db_connection()
    try:
        analysis = analyze_alert_non_persisting(
            conn=conn, config=config, alert_id=alert_id, llm=request.app.state.llm
        )
        if not analysis.get("ok"):
            if analysis.get("error") == "Alert not found":
                raise HTTPException(status_code=404, detail="Alert not found")
            raise HTTPException(status_code=500, detail=analysis.get("error", "Analysis failed"))

        result = analysis["result"]
        canonical_alert_id = str(analysis.get("alert_id") or alert_id)
        now_str = datetime.now().isoformat()

        recommendation = result.get("recommendation", "NEEDS_REVIEW")
        recommendation_reason = result.get("recommendation_reason", "AI analysis completed.")

        insert_alert_analysis(
            conn,
            alert_id=canonical_alert_id,
            generated_at=now_str,
            source=analysis.get("source", "llm"),
            narrative_theme=result["narrative_theme"],
            narrative_summary=result["narrative_summary"],
            bullish_events=result.get("bullish_events", []),
            bearish_events=result.get("bearish_events", []),
            neutral_events=result.get("neutral_events", []),
            recommendation=recommendation,
            recommendation_reason=recommendation_reason,
        )
        conn.commit()

        return {
            "narrative_theme": result["narrative_theme"],
            "narrative_summary": result["narrative_summary"],
            "bullish_events": result.get("bullish_events", []),
            "bearish_events": result.get("bearish_events", []),
            "neutral_events": result.get("neutral_events", []),
            "recommendation": recommendation,
            "recommendation_reason": recommendation_reason,
            "summary_generated_at": now_str,
        }
    finally:
        conn.close()
