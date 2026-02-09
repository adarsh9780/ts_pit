from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


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


def enforce_dismiss_evidence_requirements(
    result: dict[str, Any],
    used_articles: list[dict[str, Any]],
    trade_type: str | None,
) -> dict[str, Any]:
    """
    Guardrail: DISMISS must be backed by strong evidence.
    If evidence is weak or incomplete, downgrade to NEEDS_REVIEW with detailed gaps.
    """
    recommendation = str(result.get("recommendation") or "").upper()
    if recommendation != "DISMISS":
        return result

    total_articles = len(used_articles)
    material_articles = [a for a in used_articles if is_material_news(a)]
    impactful_articles = []
    for article in used_articles:
        try:
            if abs(float(article.get("impact_score") or 0.0)) >= 2.0:
                impactful_articles.append(article)
        except (TypeError, ValueError):
            continue

    bullish_count = len(result.get("bullish_events") or [])
    bearish_count = len(result.get("bearish_events") or [])
    normalized_trade_type = str(trade_type or "").strip().upper()

    missing_evidence = []
    if total_articles < 2:
        missing_evidence.append(
            f"At least 2 pre-trade articles are required, but only {total_articles} were considered."
        )
    if len(material_articles) < 2:
        missing_evidence.append(
            f"At least 2 material pre-trade articles (materiality containing H) are required, but only {len(material_articles)} were found."
        )
    if len(impactful_articles) < 1:
        missing_evidence.append(
            "At least 1 article with meaningful market reaction (|impact_score| >= 2.0) is required, but none were found."
        )

    if normalized_trade_type == "BUY":
        if bullish_count < 1:
            missing_evidence.append(
                "BUY alert requires at least one bullish evidence event, but none were identified."
            )
        if bearish_count > bullish_count:
            missing_evidence.append(
                "BUY alert has bearish evidence dominating bullish evidence, so directional alignment is weak."
            )
    elif normalized_trade_type == "SELL":
        if bearish_count < 1:
            missing_evidence.append(
                "SELL alert requires at least one bearish evidence event, but none were identified."
            )
        if bullish_count > bearish_count:
            missing_evidence.append(
                "SELL alert has bullish evidence dominating bearish evidence, so directional alignment is weak."
            )
    else:
        missing_evidence.append(
            "Trade type is missing or non-standard, so directional justification cannot be validated."
        )

    if not missing_evidence:
        return result

    observed_metrics = [
        f"Pre-trade articles considered: {total_articles}",
        f"Material pre-trade articles (contains H): {len(material_articles)}",
        f"Impactful articles (|impact_score| >= 2.0): {len(impactful_articles)}",
        f"Bullish events: {bullish_count}",
        f"Bearish events: {bearish_count}",
        f"Trade type: {normalized_trade_type or 'UNKNOWN'}",
    ]

    reason_lines = ["- Dismissal guardrail triggered: strong evidence threshold not met."]
    reason_lines.extend([f"- Observed: {line}" for line in observed_metrics])
    reason_lines.extend([f"- Missing: {line}" for line in missing_evidence])
    reason_lines.append(
        "- Decision changed to NEEDS_REVIEW because available evidence is not sufficiently strong for a safe dismissal."
    )

    downgraded = dict(result)
    downgraded["recommendation"] = "NEEDS_REVIEW"
    downgraded["narrative_theme"] = "NEEDS_REVIEW_INSUFFICIENT_DISMISS_EVIDENCE"
    downgraded["recommendation_reason"] = "\n".join(reason_lines)
    return downgraded


def enrich_needs_review_reason(
    result: dict[str, Any],
    used_articles: list[dict[str, Any]],
    trade_type: str | None,
) -> dict[str, Any]:
    """
    For NEEDS_REVIEW decisions, provide explicit dual rationale:
    - why dismissal is not safe
    - why escalation criteria are not yet met
    - what additional information is needed to dismiss
    """
    recommendation = str(result.get("recommendation") or "").upper()
    if recommendation != "NEEDS_REVIEW":
        return result

    total_articles = len(used_articles)
    material_articles = [a for a in used_articles if is_material_news(a)]
    high_impact_articles = []
    meaningful_impact_articles = []
    for article in used_articles:
        try:
            score = abs(float(article.get("impact_score") or 0.0))
            if score >= 2.0:
                meaningful_impact_articles.append(article)
            if score >= 4.0:
                high_impact_articles.append(article)
        except (TypeError, ValueError):
            continue

    bullish_count = len(result.get("bullish_events") or [])
    bearish_count = len(result.get("bearish_events") or [])
    normalized_trade_type = str(trade_type or "").strip().upper()

    not_dismiss_reasons = []
    if total_articles < 2:
        not_dismiss_reasons.append("insufficient number of pre-trade evidence articles")
    if len(material_articles) < 2:
        not_dismiss_reasons.append("not enough material evidence (materiality containing H)")
    if len(meaningful_impact_articles) < 1:
        not_dismiss_reasons.append("no article shows meaningful market reaction (|impact_score| >= 2.0)")
    if normalized_trade_type == "BUY" and bearish_count > bullish_count:
        not_dismiss_reasons.append("directional alignment is weak for BUY (bearish evidence dominates)")
    if normalized_trade_type == "SELL" and bullish_count > bearish_count:
        not_dismiss_reasons.append("directional alignment is weak for SELL (bullish evidence dominates)")
    if normalized_trade_type not in {"BUY", "SELL"}:
        not_dismiss_reasons.append("trade direction is missing/unclear")
    if not not_dismiss_reasons:
        not_dismiss_reasons.append("evidence quality/confidence is not strong enough for safe dismissal")

    not_escalate_reasons = []
    if len(high_impact_articles) == 0:
        not_escalate_reasons.append("no high-impact anomaly (|impact_score| >= 4.0) was detected")
    if len(high_impact_articles) > 0 and len(material_articles) > 0:
        not_escalate_reasons.append("high-impact movement has some material public evidence, so deterministic auto-escalation is not triggered")
    if len(high_impact_articles) > 0 and len(material_articles) == 0:
        not_escalate_reasons.append("high-impact signal exists but overall evidence set is inconsistent/low-confidence and requires manual adjudication")
    if not not_escalate_reasons:
        not_escalate_reasons.append("escalation criteria are not conclusively met from current evidence")

    needed_for_dismiss = [
        "additional pre-trade, company-specific public news with clear causal linkage to the move",
        "stronger materiality evidence (more H in P1/P3 dimensions)",
        "clear trade-direction alignment between alert type and evidence sentiment",
    ]

    detail_lines = [
        "",
        "Why this is NOT DISMISS:",
        *[f"- {reason}" for reason in not_dismiss_reasons],
        "",
        "Why this is NOT ESCALATE_L2:",
        *[f"- {reason}" for reason in not_escalate_reasons],
        "",
        "Information needed to move toward DISMISS:",
        *[f"- {reason}" for reason in needed_for_dismiss],
        "",
        "Evidence snapshot:",
        f"- pre-trade articles considered: {total_articles}",
        f"- material articles (contains H): {len(material_articles)}",
        f"- meaningful impact articles (|impact_score| >= 2.0): {len(meaningful_impact_articles)}",
        f"- high-impact articles (|impact_score| >= 4.0): {len(high_impact_articles)}",
        f"- bullish events: {bullish_count}",
        f"- bearish events: {bearish_count}",
    ]

    enriched = dict(result)
    base_reason = str(enriched.get("recommendation_reason") or "").strip()
    if base_reason:
        enriched["recommendation_reason"] = base_reason + "\n" + "\n".join(detail_lines)
    else:
        enriched["recommendation_reason"] = "\n".join(detail_lines).strip()
    return enriched
