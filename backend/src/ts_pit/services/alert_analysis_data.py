from __future__ import annotations

from typing import Any

from sqlalchemy import MetaData, Table, Text, and_, cast, desc, select

from ..db import get_engine
from ..scoring import calculate_p2, calculate_p3
from .db_helpers import (
    get_alert_id_candidates as _get_alert_id_candidates,
    resolve_alert_row as _resolve_alert_row,
)


metadata = MetaData()
_table_cache: dict[str, Table] = {}


def _table(table_name: str) -> Table:
    cached = _table_cache.get(table_name)
    if cached is not None:
        return cached
    reflected = Table(table_name, metadata, autoload_with=get_engine())
    _table_cache[table_name] = reflected
    return reflected


def get_alert_id_candidates(config, cursor, table_name: str) -> list[str]:
    _ = config
    _ = cursor
    return _get_alert_id_candidates(table_name)


def resolve_alert_row(config, cursor, table_name: str, alert_id: str | int):
    _ = config
    _ = cursor
    return _resolve_alert_row(table_name, alert_id)


def find_related_alert_ids(config, cursor, alert) -> dict[str, Any]:
    _ = cursor
    alerts_table = config.get_table_name("alerts")
    alerts = _table(alerts_table)

    id_col = config.get_column("alerts", "id")
    ticker_col = config.get_column("alerts", "ticker")
    start_col = config.get_column("alerts", "start_date")
    end_col = config.get_column("alerts", "end_date")

    primary_alert_id = alert.get(id_col) if isinstance(alert, dict) else None
    primary_alert_id_str = str(primary_alert_id) if primary_alert_id is not None else None
    ticker = alert.get(ticker_col) if isinstance(alert, dict) else None
    start_date = alert.get(start_col) if isinstance(alert, dict) else None
    end_date = alert.get(end_col) if isinstance(alert, dict) else None

    fallback_ids = [primary_alert_id_str] if primary_alert_id_str else []
    if not (primary_alert_id_str and ticker and start_date and end_date):
        return {
            "primary_alert_id": primary_alert_id_str or "",
            "related_alert_ids": fallback_ids,
            "related_alert_count": len(fallback_ids),
        }

    stmt = (
        select(cast(alerts.c[id_col], Text).label("alert_id"))
        .where(
            and_(
                cast(alerts.c[ticker_col], Text) == str(ticker),
                cast(alerts.c[start_col], Text) == str(start_date),
                cast(alerts.c[end_col], Text) == str(end_date),
            )
        )
        .order_by(cast(alerts.c[id_col], Text).asc())
    )
    with get_engine().connect() as conn:
        rows = conn.execute(stmt).mappings().all()

    ids = sorted({str(row["alert_id"]) for row in rows if row.get("alert_id") is not None})
    if primary_alert_id_str not in ids:
        ids.append(primary_alert_id_str)
        ids = sorted(set(ids))
    return {
        "primary_alert_id": primary_alert_id_str,
        "related_alert_ids": ids,
        "related_alert_count": len(ids),
    }


def build_alert_articles(
    config,
    cursor,
    alert,
    start_date: str | None,
    end_date: str | None,
):
    _ = cursor

    articles_table = config.get_table_name("articles")
    themes_table = config.get_table_name("article_themes")
    articles = _table(articles_table)
    themes = _table(themes_table)

    art_id_col = config.get_column("articles", "id")
    art_isin_col = config.get_column("articles", "isin")
    date_col = config.get_column("articles", "created_date")
    title_col = config.get_column("articles", "title")
    summary_col = config.get_column("articles", "summary")
    impact_score_col = config.get_column("articles", "impact_score")
    original_theme_col = config.get_column("articles", "theme")

    theme_art_id_col = config.get_column("article_themes", "art_id")
    ai_theme_col = config.get_column("article_themes", "theme")
    ai_summary_col = config.get_column("article_themes", "summary")
    ai_analysis_col = config.get_column("article_themes", "analysis")
    ai_p1_col = config.get_column("article_themes", "p1_prominence")

    isin_col = config.get_column("alerts", "isin")
    isin = alert[isin_col]

    stmt = (
        select(
            cast(articles.c[art_id_col], Text).label("article_id"),
            cast(articles.c[title_col], Text).label("title"),
            cast(articles.c[summary_col], Text).label("original_summary"),
            cast(articles.c[date_col], Text).label("created_date"),
            cast(articles.c[impact_score_col], Text).label("impact_score"),
            cast(articles.c[original_theme_col], Text).label("original_theme"),
            cast(themes.c[ai_theme_col], Text).label("ai_theme"),
            cast(themes.c[ai_summary_col], Text).label("ai_summary"),
            cast(themes.c[ai_analysis_col], Text).label("ai_analysis"),
            cast(themes.c[ai_p1_col], Text).label("ai_p1"),
        )
        .select_from(
            articles.outerjoin(themes, articles.c[art_id_col] == themes.c[theme_art_id_col])
        )
        .where(articles.c[art_isin_col] == str(isin))
    )
    if start_date:
        stmt = stmt.where(articles.c[date_col] >= str(start_date))
    if end_date:
        stmt = stmt.where(articles.c[date_col] <= str(end_date))
    stmt = stmt.order_by(desc(articles.c[date_col]))

    with get_engine().connect() as conn:
        rows = conn.execute(stmt).mappings().all()
    articles = []
    for row in rows:
        row_data = dict(row)
        theme = row_data.get("ai_theme")
        if not theme or str(theme).lower() == "string":
            theme = row_data.get("original_theme") or "UNCATEGORIZED"
        summary = row_data.get("original_summary")
        if not summary or not str(summary).strip():
            summary = row_data.get("ai_summary")

        p1 = row_data.get("ai_p1") or "L"
        p2 = calculate_p2(row_data.get("created_date"), start_date, end_date)
        p3 = calculate_p3(theme)
        materiality = f"{p1}{p2}{p3}"

        articles.append(
            {
                "article_id": row_data.get("article_id"),
                "title": row_data.get("title"),
                "summary": summary,
                "created_date": row_data.get("created_date"),
                "theme": theme,
                "analysis": row_data.get("ai_analysis"),
                "impact_score": row_data.get("impact_score"),
                "materiality": materiality,
            }
        )
    return articles


def build_price_history(config, cursor, alert):
    _ = cursor
    price_history = []
    ticker_col = config.get_column("alerts", "ticker")
    start_col = config.get_column("alerts", "start_date")
    end_col = config.get_column("alerts", "end_date")
    ticker = alert[ticker_col] if ticker_col in alert.keys() else None
    start_date = alert[start_col]
    end_date = alert[end_col]
    if not (ticker and start_date and end_date):
        return price_history

    prices_table = config.get_table_name("prices")
    prices = _table(prices_table)
    price_ticker_col = config.get_column("prices", "ticker")
    price_date_col = config.get_column("prices", "date")
    price_close_col = config.get_column("prices", "close")
    stmt = (
        select(
            cast(prices.c[price_date_col], Text).label("date"),
            cast(prices.c[price_close_col], Text).label("close"),
        )
        .where(
            and_(
                prices.c[price_ticker_col] == str(ticker),
                prices.c[price_date_col] >= str(start_date),
                prices.c[price_date_col] <= str(end_date),
            )
        )
        .order_by(prices.c[price_date_col].asc())
    )
    with get_engine().connect() as conn:
        return [dict(row) for row in conn.execute(stmt).mappings().all()]
