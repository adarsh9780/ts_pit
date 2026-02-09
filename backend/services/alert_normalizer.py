from __future__ import annotations

from datetime import datetime
from typing import Any

from ..config import get_config
from ..logger import logprint


config = get_config()


def _normalize_status(raw_status: str | None) -> str | None:
    if raw_status is None:
        return None
    normalized = config.normalize_status(raw_status)
    if config.is_status_enforced() and not config.is_valid_status(normalized):
        fallback_status = config.get_valid_statuses()[0]
        logprint(
            "Invalid alert status encountered, using fallback",
            level="WARNING",
            raw_status=raw_status,
            fallback_status=fallback_status,
        )
        return fallback_status
    return normalized


def normalize_impact_label(raw_label: str | None) -> str | None:
    if raw_label is None:
        return None
    normalized = config.normalize_impact_label(raw_label)
    return normalized if normalized else raw_label


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_trade_type(alert: dict[str, Any]) -> str:
    direct = str(alert.get("trade_type") or "").strip().upper()
    if direct in {"BUY", "SELL"}:
        return direct

    for key in ("trade_side", "tradeSide", "side", "buy_sell", "type"):
        value = str(alert.get(key) or "").strip().upper()
        if value in {"BUY", "SELL"}:
            return value

    buy_qty = _to_float(alert.get("buy_quantity") or alert.get("buyQty"))
    sell_qty = _to_float(alert.get("sell_quantity") or alert.get("sellQty"))
    if buy_qty is not None and sell_qty is not None:
        if buy_qty > sell_qty:
            return "BUY"
        if sell_qty > buy_qty:
            return "SELL"

    return "UNKNOWN"


def _normalize_date(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    # Preserve date-only values and normalize common datetime values.
    if len(raw) >= 10:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed.date().isoformat()
        except ValueError:
            pass
    return raw


def normalize_alert_response(alert: dict[str, Any]) -> dict[str, Any]:
    """Normalize alert payload to a stable API shape consumed by frontend."""
    normalized = dict(alert)

    if normalized.get("id") is not None:
        normalized["id"] = str(normalized["id"])
    elif normalized.get("alert_id") is not None:
        normalized["id"] = str(normalized["alert_id"])

    normalized["status"] = _normalize_status(normalized.get("status"))
    normalized["trade_type"] = _normalize_trade_type(normalized)

    for key in ("alert_date", "start_date", "end_date", "execution_date"):
        if key in normalized:
            normalized[key] = _normalize_date(normalized.get(key))

    return normalized

