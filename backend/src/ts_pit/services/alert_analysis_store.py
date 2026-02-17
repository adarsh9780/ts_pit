from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Text, bindparam, cast, desc, select

from ..db import get_engine
from .db_helpers import get_table


ANALYSIS_TABLE = "alert_analysis"
engine = get_engine()


def _to_json(value: Any) -> str:
    if value is None:
        return "[]"
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _from_json_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def insert_alert_analysis(
    conn=None,
    *,
    alert_id: str,
    generated_at: str,
    source: str,
    narrative_theme: str,
    narrative_summary: str,
    bullish_events: list[Any],
    bearish_events: list[Any],
    neutral_events: list[Any],
    recommendation: str,
    recommendation_reason: str,
) -> None:
    analysis = get_table(ANALYSIS_TABLE)
    payload = {
        "alert_id": str(alert_id),
        "generated_at": generated_at,
        "source": source,
        "narrative_theme": narrative_theme,
        "narrative_summary": narrative_summary,
        "bullish_events": _to_json(bullish_events),
        "bearish_events": _to_json(bearish_events),
        "neutral_events": _to_json(neutral_events),
        "recommendation": recommendation,
        "recommendation_reason": recommendation_reason,
    }
    with engine.begin() as sa_conn:
        sa_conn.execute(analysis.insert().values(payload))


def fetch_latest_analysis_map(
    conn=None, alert_ids: list[str] | None = None
) -> dict[str, dict[str, Any]]:
    alert_ids = alert_ids or []
    if not alert_ids:
        return {}

    norm_ids = [str(aid) for aid in alert_ids if aid is not None]
    if not norm_ids:
        return {}

    analysis = get_table(ANALYSIS_TABLE)
    stmt = (
        select(
            cast(analysis.c.alert_id, Text).label("alert_id"),
            cast(analysis.c.generated_at, Text).label("generated_at"),
            cast(analysis.c.source, Text).label("source"),
            cast(analysis.c.narrative_theme, Text).label("narrative_theme"),
            cast(analysis.c.narrative_summary, Text).label("narrative_summary"),
            cast(analysis.c.bullish_events, Text).label("bullish_events"),
            cast(analysis.c.bearish_events, Text).label("bearish_events"),
            cast(analysis.c.neutral_events, Text).label("neutral_events"),
            cast(analysis.c.recommendation, Text).label("recommendation"),
            cast(analysis.c.recommendation_reason, Text).label("recommendation_reason"),
        )
        .where(
            cast(analysis.c.alert_id, Text).in_(bindparam("alert_ids", expanding=True))
        )
        .order_by(cast(analysis.c.alert_id, Text).asc(), desc(analysis.c.generated_at))
    )
    with engine.connect() as sa_conn:
        rows = sa_conn.execute(stmt, {"alert_ids": norm_ids}).mappings().all()

    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        aid = str(row["alert_id"])
        if aid in latest:
            continue
        latest[aid] = {
            "narrative_theme": row["narrative_theme"],
            "narrative_summary": row["narrative_summary"],
            "summary_generated_at": row["generated_at"],
            "bullish_events": _from_json_list(row["bullish_events"]),
            "bearish_events": _from_json_list(row["bearish_events"]),
            "neutral_events": _from_json_list(row["neutral_events"]),
            "recommendation": row["recommendation"],
            "recommendation_reason": row["recommendation_reason"],
            "analysis_source": row["source"],
        }

    return latest


def apply_latest_analysis_to_alert(
    alert_payload: dict[str, Any],
    latest_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    merged = dict(alert_payload)
    merged.setdefault("narrative_theme", None)
    merged.setdefault("narrative_summary", None)
    merged.setdefault("summary_generated_at", None)
    merged.setdefault("bullish_events", [])
    merged.setdefault("bearish_events", [])
    merged.setdefault("neutral_events", [])
    merged.setdefault("recommendation", None)
    merged.setdefault("recommendation_reason", None)

    aid = alert_payload.get("id")
    if aid is None:
        return merged

    analysis = latest_map.get(str(aid))
    if not analysis:
        return merged

    merged.update(analysis)
    return merged
