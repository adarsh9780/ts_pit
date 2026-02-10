from __future__ import annotations

import json
from typing import Any


ANALYSIS_TABLE = "alert_analysis"


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
    conn,
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
    cursor = conn.cursor()
    cursor.execute(
        f'''
        INSERT INTO "{ANALYSIS_TABLE}" (
            "alert_id",
            "generated_at",
            "source",
            "narrative_theme",
            "narrative_summary",
            "bullish_events",
            "bearish_events",
            "neutral_events",
            "recommendation",
            "recommendation_reason"
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            str(alert_id),
            generated_at,
            source,
            narrative_theme,
            narrative_summary,
            _to_json(bullish_events),
            _to_json(bearish_events),
            _to_json(neutral_events),
            recommendation,
            recommendation_reason,
        ),
    )


def fetch_latest_analysis_map(conn, alert_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not alert_ids:
        return {}

    norm_ids = [str(aid) for aid in alert_ids if aid is not None]
    if not norm_ids:
        return {}

    cursor = conn.cursor()
    placeholders = ",".join(["?"] * len(norm_ids))
    cursor.execute(
        f'''
        SELECT
            "id",
            "alert_id",
            "generated_at",
            "source",
            "narrative_theme",
            "narrative_summary",
            "bullish_events",
            "bearish_events",
            "neutral_events",
            "recommendation",
            "recommendation_reason"
        FROM "{ANALYSIS_TABLE}"
        WHERE "alert_id" IN ({placeholders})
        ORDER BY "alert_id" ASC, "generated_at" DESC, "id" DESC
        ''',
        tuple(norm_ids),
    )

    latest: dict[str, dict[str, Any]] = {}
    for row in cursor.fetchall():
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
