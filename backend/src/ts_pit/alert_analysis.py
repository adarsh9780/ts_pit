from __future__ import annotations

from .llm import generate_cluster_summary
from .services.alert_analysis_data import (
    build_alert_articles,
    find_related_alert_ids,
    build_price_history,
    resolve_alert_row,
)
from .services.alert_analysis_policy import (
    enforce_dismiss_evidence_requirements,
    enrich_needs_review_reason,
    run_deterministic_summary_gates,
)


def analyze_alert_non_persisting(conn, config, alert_id: str | int, llm):
    _ = conn
    alerts_table = config.get_table_name("alerts")
    alert, matched_id_col, matched_id_value = resolve_alert_row(
        config,
        None,
        alerts_table,
        alert_id,
    )
    if not alert:
        return {"ok": False, "error": "Alert not found"}

    start_col = config.get_column("alerts", "start_date")
    end_col = config.get_column("alerts", "end_date")
    trade_type_col = config.get_column("alerts", "trade_type")
    start_date = alert[start_col]
    end_date = alert[end_col]
    trade_type = alert[trade_type_col] if trade_type_col in alert.keys() else None

    price_history = build_price_history(config, None, alert)
    articles = build_alert_articles(config, None, alert, start_date, end_date)
    linked_alerts = find_related_alert_ids(config, None, alert)
    related_alert_ids = linked_alerts.get("related_alert_ids", [])
    related_alert_count = int(linked_alerts.get("related_alert_count", 0) or 0)
    primary_alert_id = str(linked_alerts.get("primary_alert_id") or "")

    if related_alert_count > 1:
        linked_alerts_notice = (
            "Multiple alerts share the same ticker and investigation window: "
            f"{', '.join(related_alert_ids)}. This conclusion generally applies to "
            "all linked alerts unless case-specific evidence differs."
        )
    else:
        linked_alerts_notice = "No linked alerts found for the same ticker and investigation window."
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

    result = enforce_dismiss_evidence_requirements(
        result=result,
        used_articles=used_articles,
        trade_type=trade_type,
    )
    result = enrich_needs_review_reason(
        result=result,
        used_articles=used_articles,
        trade_type=trade_type,
    )

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
        "alert_id": str(alert[config.get_column("alerts", "id")]),
        "primary_alert_id": primary_alert_id,
        "related_alert_ids": related_alert_ids,
        "related_alert_count": related_alert_count,
        "linked_alerts_notice": linked_alerts_notice,
        "source": source,
        "result": result,
        "citations": citations,
        "articles_considered_count": len(used_articles),
        "start_date": start_date,
        "end_date": end_date,
        "matched_id_col": matched_id_col,
        "matched_id_value": matched_id_value,
    }


def get_current_alert_news_non_persisting(
    conn,
    config,
    alert_id: str | int,
    limit: int = 50,
):
    _ = conn
    alerts_table = config.get_table_name("alerts")
    alert, _, _ = resolve_alert_row(config, None, alerts_table, alert_id)
    if not alert:
        return {"ok": False, "error": "Alert not found"}

    start_col = config.get_column("alerts", "start_date")
    end_col = config.get_column("alerts", "end_date")
    start_date = alert[start_col]
    end_date = alert[end_col]
    articles = build_alert_articles(config, None, alert, start_date, end_date)
    return {
        "ok": True,
        "articles": articles[: max(1, min(int(limit), 200))],
        "articles_total": len(articles),
        "start_date": start_date,
        "end_date": end_date,
    }


__all__ = [
    "analyze_alert_non_persisting",
    "build_price_history",
    "get_current_alert_news_non_persisting",
    "resolve_alert_row",
]
