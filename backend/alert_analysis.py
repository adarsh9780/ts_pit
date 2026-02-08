from datetime import datetime, timezone
from typing import Any

from .llm import generate_cluster_summary
from .scoring import calculate_p2, calculate_p3


def parse_datetime(value: str | None) -> datetime | None:
    """Parse common date/datetime formats used in alerts/articles."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def is_high_impact(score: float | int | None) -> bool:
    """Canonical impact threshold: High >= 4.0."""
    try:
        return abs(float(score)) >= 4.0
    except (TypeError, ValueError):
        return False


def is_material_news(article: dict[str, Any]) -> bool:
    """Material if entity prominence or theme relevance is high (P1/P3 == H)."""
    materiality = str(article.get("materiality") or "").upper()
    return len(materiality) >= 3 and (materiality[0] == "H" or materiality[2] == "H")


def get_alert_id_candidates(config, cursor, table_name: str) -> list[str]:
    cursor.execute(f'PRAGMA table_info("{table_name}")')
    available_cols = {row["name"] for row in cursor.fetchall()}
    preferred = [
        config.get_column("alerts", "id"),
        "alert_id",
        "Alert ID",
        "id",
    ]
    return [c for c in dict.fromkeys(preferred) if c in available_cols]


def resolve_alert_row(config, cursor, table_name: str, alert_id: str | int):
    id_cols = get_alert_id_candidates(config, cursor, table_name)
    probe_values = [alert_id]
    if not isinstance(alert_id, str):
        probe_values.append(str(alert_id))
    elif alert_id.isdigit():
        probe_values.append(int(alert_id))

    for value in probe_values:
        for id_col in id_cols:
            cursor.execute(
                f'SELECT * FROM "{table_name}" WHERE "{id_col}" = ? LIMIT 1', (value,)
            )
            row = cursor.fetchone()
            if row:
                return row, id_col, value

    return None, None, None


def run_deterministic_summary_gates(
    config,
    alert,
    articles: list[dict[str, Any]],
    start_date: str | None,
    end_date: str | None,
    trade_type: str | None,
):
    missing_fields = []
    if not trade_type:
        missing_fields.append("trade_type")
    if not start_date:
        missing_fields.append("start_date")
    if not end_date:
        missing_fields.append("end_date")

    execution_col = config.get_column("alerts", "execution_date")
    trade_ts = None
    if execution_col and execution_col in alert.keys():
        trade_ts = parse_datetime(alert[execution_col])
    if trade_ts is None:
        trade_ts = parse_datetime(end_date)

    if trade_ts is None:
        missing_fields.append("trade timestamp (execution_date or end_date)")

    if missing_fields:
        reason = (
            "- Data readiness check failed.\n"
            f"- Missing required fields: {', '.join(missing_fields)}.\n"
            "- Deterministic policy requires manual review when key fields are missing."
        )
        return (
            {
                "narrative_theme": "NEEDS_REVIEW_DATA_GAP",
                "narrative_summary": "Insufficient data for deterministic validation. Manual review required before AI justification.",
                "bullish_events": [],
                "bearish_events": [],
                "neutral_events": [],
                "recommendation": "NEEDS_REVIEW",
                "recommendation_reason": reason,
            },
            articles,
        )

    if not articles:
        reason = (
            "- No linked news articles found for the alert window.\n"
            "- Deterministic policy blocks auto-justification without evidence."
        )
        return (
            {
                "narrative_theme": "NEEDS_REVIEW_NO_NEWS",
                "narrative_summary": "No linked news available for deterministic causality checks. Manual review required.",
                "bullish_events": [],
                "bearish_events": [],
                "neutral_events": [],
                "recommendation": "NEEDS_REVIEW",
                "recommendation_reason": reason,
            },
            articles,
        )

    parsed_articles = []
    for article in articles:
        article_ts = parse_datetime(article.get("created_date"))
        if article_ts is None:
            reason = (
                "- At least one linked article is missing a valid timestamp.\n"
                "- Deterministic policy requires valid article timestamps for causality checks."
            )
            return (
                {
                    "narrative_theme": "NEEDS_REVIEW_INVALID_TIMESTAMP",
                    "narrative_summary": "Article timestamp quality check failed. Manual review required.",
                    "bullish_events": [],
                    "bearish_events": [],
                    "neutral_events": [],
                    "recommendation": "NEEDS_REVIEW",
                    "recommendation_reason": reason,
                },
                articles,
            )
        parsed_articles.append((article, article_ts))

    pre_trade_articles = [a for a, ts in parsed_articles if ts <= trade_ts]
    if not pre_trade_articles:
        has_high_any = any(is_high_impact(a.get("impact_score")) for a in articles)
        if has_high_any:
            reason = (
                f"- Trade timestamp boundary: {trade_ts.isoformat()}.\n"
                "- No pre-trade public articles were found to justify the move.\n"
                "- High-impact movement exists without valid causal public evidence."
            )
            recommendation = "ESCALATE_L2"
            theme = "ESCALATE_NO_PRETRADE_NEWS"
            summary = "High-impact behavior found, but no pre-trade public news evidence was available for justification."
        else:
            reason = (
                f"- Trade timestamp boundary: {trade_ts.isoformat()}.\n"
                "- No pre-trade public articles were found.\n"
                "- Deterministic policy requires manual review when causality cannot be established."
            )
            recommendation = "NEEDS_REVIEW"
            theme = "NEEDS_REVIEW_NO_PRETRADE_NEWS"
            summary = "No pre-trade public news evidence was available to establish deterministic causality."
        return (
            {
                "narrative_theme": theme,
                "narrative_summary": summary,
                "bullish_events": [],
                "bearish_events": [],
                "neutral_events": [],
                "recommendation": recommendation,
                "recommendation_reason": reason,
            },
            pre_trade_articles,
        )

    has_high_impact = any(is_high_impact(a.get("impact_score")) for a in pre_trade_articles)
    has_material_pretrade = any(is_material_news(a) for a in pre_trade_articles)
    if has_high_impact and not has_material_pretrade:
        reason = (
            f"- Trade timestamp boundary: {trade_ts.isoformat()}.\n"
            "- Pre-trade public articles exist, but none meet materiality criteria (P1/P3 high).\n"
            "- High-impact movement without material pre-trade public news."
        )
        return (
            {
                "narrative_theme": "ESCALATE_HIGH_IMPACT_NO_MATERIAL_NEWS",
                "narrative_summary": "Deterministic gates detected high-impact behavior without material pre-trade public justification.",
                "bullish_events": [],
                "bearish_events": [],
                "neutral_events": [],
                "recommendation": "ESCALATE_L2",
                "recommendation_reason": reason,
            },
            pre_trade_articles,
        )

    return None, pre_trade_articles


def build_alert_articles(config, cursor, alert, start_date: str | None, end_date: str | None):
    articles_table = config.get_table_name("articles")
    themes_table = config.get_table_name("article_themes")

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

    query = f'''
        SELECT
            a."{art_id_col}" as article_id,
            a."{title_col}" as title,
            a."{summary_col}" as original_summary,
            a."{date_col}" as created_date,
            a."{impact_score_col}" as impact_score,
            a."{original_theme_col}" as original_theme,
            t."{ai_theme_col}" as ai_theme,
            t."{ai_summary_col}" as ai_summary,
            t."{ai_analysis_col}" as ai_analysis,
            t."{ai_p1_col}" as ai_p1
        FROM "{articles_table}" a
        LEFT JOIN "{themes_table}" t ON a."{art_id_col}" = t."{theme_art_id_col}"
        WHERE a."{art_isin_col}" = ?
    '''
    params = [isin]
    if start_date:
        query += f' AND a."{date_col}" >= ?'
        params.append(start_date)
    if end_date:
        query += f' AND a."{date_col}" <= ?'
        params.append(end_date)
    query += f' ORDER BY a."{date_col}" DESC'

    cursor.execute(query, params)
    articles = []
    for row in cursor.fetchall():
        r = dict(row)
        theme = r.get("ai_theme")
        if not theme or str(theme).lower() == "string":
            theme = r.get("original_theme") or "UNCATEGORIZED"
        summary = r.get("original_summary")
        if not summary or not str(summary).strip():
            summary = r.get("ai_summary")

        p1 = r.get("ai_p1") or "L"
        p2 = calculate_p2(r.get("created_date"), start_date, end_date)
        p3 = calculate_p3(theme)
        materiality = f"{p1}{p2}{p3}"

        articles.append(
            {
                "article_id": r.get("article_id"),
                "title": r.get("title"),
                "summary": summary,
                "created_date": r.get("created_date"),
                "theme": theme,
                "analysis": r.get("ai_analysis"),
                "impact_score": r.get("impact_score"),
                "materiality": materiality,
            }
        )
    return articles


def build_price_history(config, cursor, alert):
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
    price_ticker_col = config.get_column("prices", "ticker")
    price_date_col = config.get_column("prices", "date")
    price_close_col = config.get_column("prices", "close")
    cursor.execute(
        f'SELECT "{price_date_col}" as date, "{price_close_col}" as close FROM "{prices_table}" WHERE "{price_ticker_col}" = ? AND "{price_date_col}" BETWEEN ? AND ? ORDER BY "{price_date_col}" ASC',
        (ticker, start_date, end_date),
    )
    return [dict(row) for row in cursor.fetchall()]


def analyze_alert_non_persisting(conn, config, alert_id: str | int, llm):
    cursor = conn.cursor()
    alerts_table = config.get_table_name("alerts")
    alert, matched_id_col, matched_id_value = resolve_alert_row(config, cursor, alerts_table, alert_id)
    if not alert:
        return {"ok": False, "error": "Alert not found"}

    start_col = config.get_column("alerts", "start_date")
    end_col = config.get_column("alerts", "end_date")
    trade_type_col = config.get_column("alerts", "trade_type")
    start_date = alert[start_col]
    end_date = alert[end_col]
    trade_type = alert[trade_type_col] if trade_type_col in alert.keys() else None

    price_history = build_price_history(config, cursor, alert)
    articles = build_alert_articles(config, cursor, alert, start_date, end_date)
    deterministic_result, llm_articles = run_deterministic_summary_gates(
        config=config,
        alert=alert,
        articles=articles,
        start_date=start_date,
        end_date=end_date,
        trade_type=trade_type,
    )
    if deterministic_result is not None:
        result = deterministic_result
        used_articles = llm_articles or articles
        source = "deterministic"
    else:
        result = generate_cluster_summary(
            llm_articles or articles,
            price_history=price_history,
            trade_type=trade_type,
            llm=llm,
        )
        used_articles = llm_articles or articles
        source = "llm"

    citations = []
    for article in used_articles[:20]:
        citations.append(
            {
                "article_id": article.get("article_id"),
                "created_date": article.get("created_date"),
                "title": article.get("title"),
                "impact_score": article.get("impact_score"),
                "materiality": article.get("materiality"),
                "reason": "Pre-trade in-window evidence considered for analysis",
            }
        )

    return {
        "ok": True,
        "source": source,
        "result": result,
        "citations": citations,
        "articles_considered_count": len(used_articles),
        "start_date": start_date,
        "end_date": end_date,
        "matched_id_col": matched_id_col,
        "matched_id_value": matched_id_value,
    }


def get_current_alert_news_non_persisting(conn, config, alert_id: str | int, limit: int = 50):
    cursor = conn.cursor()
    alerts_table = config.get_table_name("alerts")
    alert, _, _ = resolve_alert_row(config, cursor, alerts_table, alert_id)
    if not alert:
        return {"ok": False, "error": "Alert not found"}

    start_col = config.get_column("alerts", "start_date")
    end_col = config.get_column("alerts", "end_date")
    start_date = alert[start_col]
    end_date = alert[end_col]
    articles = build_alert_articles(config, cursor, alert, start_date, end_date)
    return {
        "ok": True,
        "articles": articles[: max(1, min(int(limit), 200))],
        "articles_total": len(articles),
        "start_date": start_date,
        "end_date": end_date,
    }
