from __future__ import annotations

import yfinance as yf
from fastapi import APIRouter, Query
from sqlalchemy import Text, and_, cast, desc, select

from ...config import get_config
from ...database import remap_row
from ...db import get_engine
from ...logger import logprint
from ...prices import fetch_and_cache_prices
from ...scoring import calculate_p2, calculate_p3
from ...services.alert_normalizer import normalize_impact_label
from ...services.db_helpers import get_table


router = APIRouter(tags=["market"])
config = get_config()
engine = get_engine()


@router.get("/prices/{ticker}")
def get_prices(
    ticker: str,
    period: str = Query(None, pattern="^(1mo|3mo|6mo|1y|ytd|max)$"),
    start_date: str = Query(None),
    end_date: str = Query(None),
):
    effective_period = period or "1y"
    if start_date and end_date:
        start_date_str, actual_ticker = fetch_and_cache_prices(
            ticker, "1y", start_date, end_date
        )
    else:
        start_date_str, actual_ticker = fetch_and_cache_prices(
            ticker, effective_period
        )

    table_name = config.get_table_name("prices")
    prices_table = get_table(table_name)
    ticker_col = config.get_column("prices", "ticker")
    date_col = config.get_column("prices", "date")
    price_select_cols = [
        cast(prices_table.c[col.name], Text).label(col.name)
        if col.name == date_col
        else prices_table.c[col.name]
        for col in prices_table.columns
    ]
    stmt = (
        select(*price_select_cols)
        .where(
            and_(
                prices_table.c[ticker_col] == str(actual_ticker),
                prices_table.c[date_col] >= str(start_date_str),
            )
        )
        .order_by(prices_table.c[date_col].asc())
    )
    if end_date:
        stmt = stmt.where(prices_table.c[date_col] <= str(end_date))

    with engine.connect() as conn:
        rows = conn.execute(stmt).mappings().all()

    ticker_data = [remap_row(dict(row), "prices") for row in rows]

    industry_data = []
    industry_name = "Industry Error"

    if ticker_data:
        etf_ticker = None
        sector_etf_mapping = config.get_sector_etf_mapping()

        try:
            info = yf.Ticker(actual_ticker).info
            sector = info.get("sector")
            industry_name = sector

            if sector in sector_etf_mapping:
                etf_ticker = sector_etf_mapping[sector]
            else:
                etf_ticker = "SPY"
                industry_name = "Market (SPY)"
        except Exception as e:
            logprint("Failed to fetch sector info", level="ERROR", ticker=actual_ticker, error=str(e))
            etf_ticker = "SPY"
            industry_name = "Market (SPY)"

        if etf_ticker:
            if start_date and end_date:
                fetch_and_cache_prices(
                    etf_ticker, "1y", start_date, end_date, is_etf=True
                )
            else:
                fetch_and_cache_prices(etf_ticker, effective_period, is_etf=True)

            stmt_etf = (
                select(*price_select_cols)
                .where(
                    and_(
                        prices_table.c[ticker_col] == str(etf_ticker),
                        prices_table.c[date_col] >= str(start_date_str),
                    )
                )
                .order_by(prices_table.c[date_col].asc())
            )
            if end_date:
                stmt_etf = stmt_etf.where(prices_table.c[date_col] <= str(end_date))

            with engine.connect() as conn:
                etf_rows = conn.execute(stmt_etf).mappings().all()

            industry_data = [remap_row(dict(row), "prices") for row in etf_rows]

    return {
        "ticker": ticker_data,
        "industry": industry_data,
        "industry_name": industry_name,
    }


@router.get("/news/{isin}")
def get_news(
    isin: str,
    start_date: str | None = None,
    end_date: str | None = None,
):
    table_name = config.get_table_name("articles")
    articles = get_table(table_name)
    isin_col = config.get_column("articles", "isin")
    date_col = config.get_column("articles", "created_date")

    themes_table = config.get_table_name("article_themes")
    themes = get_table(themes_table)
    art_id_col = config.get_column("articles", "id")
    theme_art_id_col = config.get_column("article_themes", "art_id")
    ai_theme_col = config.get_column("article_themes", "theme")
    ai_summary_col = config.get_column("article_themes", "summary")
    ai_analysis_col = config.get_column("article_themes", "analysis")
    ai_p1_col = config.get_column("article_themes", "p1_prominence")

    original_theme_col = config.get_column("articles", "theme")
    original_summary_col = config.get_column("articles", "summary")
    article_cols = [cast(articles.c[col.name], Text).label(col.name) for col in articles.columns]
    stmt = (
        select(
            *article_cols,
            cast(articles.c[original_theme_col], Text).label("original_theme"),
            cast(articles.c[original_summary_col], Text).label("original_summary"),
            cast(themes.c[ai_theme_col], Text).label("ai_theme"),
            cast(themes.c[ai_summary_col], Text).label("ai_summary"),
            cast(themes.c[ai_analysis_col], Text).label("ai_analysis"),
            cast(themes.c[ai_p1_col], Text).label("ai_p1"),
        )
        .select_from(
            articles.outerjoin(themes, articles.c[art_id_col] == themes.c[theme_art_id_col])
        )
        .where(articles.c[isin_col] == str(isin))
        .order_by(desc(articles.c[date_col]))
    )
    if start_date:
        stmt = stmt.where(articles.c[date_col] >= str(start_date))
    if end_date:
        stmt = stmt.where(articles.c[date_col] <= str(end_date))

    with engine.connect() as conn:
        rows = conn.execute(stmt).mappings().all()

    mat_score_map = {"H": 3, "M": 2, "L": 1}
    results = []
    for row in rows:
        r = dict(row)
        remapped = remap_row(r, "articles")
        if "impact_label" in remapped:
            remapped["impact_label"] = normalize_impact_label(remapped["impact_label"])

        ai_theme = r.get("ai_theme")
        if ai_theme and ai_theme.lower() != "string":
            remapped["theme"] = ai_theme

        if remapped.get("theme") is None:
            remapped["theme"] = r.get("original_theme") or "UNCATEGORIZED"

        p1 = r.get("ai_p1") or "L"
        p2 = calculate_p2(remapped.get("created_date"), start_date, end_date)
        p3 = calculate_p3(remapped.get("theme"))

        final_score = f"{p1}{p2}{p3}"
        remapped["materiality"] = final_score
        remapped["materiality_details"] = {
            "p1": {"score": p1, "reason": "Entity Mention (Title/Lead/Body)"},
            "p2": {"score": p2, "reason": f"Proximity to Window ({start_date} to {end_date})"},
            "p3": {"score": p3, "reason": f"Theme Priority ({remapped['theme']})"},
        }

        sort_score = (
            mat_score_map.get(p1, 1)
            + mat_score_map.get(p2, 1)
            + mat_score_map.get(p3, 1)
        )
        remapped["_sort_score"] = sort_score
        results.append(remapped)

    results.sort(key=lambda x: (x["_sort_score"], x["created_date"]), reverse=True)
    for res in results:
        del res["_sort_score"]

    return results
