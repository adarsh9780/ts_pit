# Scoring Methodology and Interpretation Guide

This document explains how the system scores news impact and materiality, in both:
- Plain-language steps for non-statistical users.
- Exact formulas for quantitative users.

It is intended to be the single source of truth for the current implementation.

---

## 1. What Problem This Score Solves

When an article is published, investigators need to answer:

"Did the market move unusually strongly right when this article became public?"

The impact score is built to answer that specific question, not to forecast prices.

---

## 2. Plain-Language Walkthrough (No Stats Prerequisite)

Use one article at a time.

### Step A: Find the article publication time

Example: article published at `2025-12-31 10:15:00`.

### Step B: Build a "normal behavior" window

Look at the previous 10 days of hourly candles before publication time.

In simple words:
- This gives us a recent sample of how much this stock usually moves each hour.
- We do this per stock, so NVDA and a low-volatility stock are not treated the same.

### Step C: Measure each hour's movement in that 10-day window

For each hourly candle:
- Start of the hour = `open`
- End of the hour = `close`
- Hourly move = `(close - open) / open`

This creates a list of hourly move percentages.

### Step D: Convert that list into "typical hourly movement size"

From the Step C list, compute standard deviation.

In plain words:
- If this number is small, the stock usually moves little hour to hour.
- If large, the stock is naturally noisy.

### Step E: Measure movement in the article hour

Take the first hourly candle at or after article timestamp.

Example:
- Article at `10:15`
- First hourly candle at/after that time might be `11:00` in stored data.

Compute the same movement:
- `(event_close - event_open) / event_open`

### Step F: Compare article-hour movement vs normal movement

If the article-hour movement is much larger than normal, impact is high.

That comparison value is the impact Z-score.

### Step G: Convert score into a label

Current numeric bands:
- `< 2.0`
- `2.0 to < 4.0`
- `>= 4.0`

Business labels for these bands are described in Section 5.

---

## 3. Statistical Definition (Formula Section)

Let:
- `t0` = article publication timestamp
- Baseline window = `[t0 - 10 days, t0]`
- Hourly candle return for candle `i`:
  - `r_i = (close_i - open_i) / open_i`

Baseline volatility:
- `sigma = std(r_i)` over all hourly candles in the baseline window.

Event candle:
- First hourly candle with `timestamp >= t0`
- Event return:
  - `r_event = (close_event - open_event) / open_event`

Impact score:
- `Z = abs(r_event) / sigma`

Special cases:
- If insufficient baseline rows: no score.
- If `sigma == 0` (flatline): score treated as `0`.

---

## 4. Why This Method Is Preferred Here

This system investigates "event-time abnormality", not long-term valuation drift.

Why this method fits:
1. It is event-local.
The score focuses on the move at publication time, which matches surveillance workflow.
2. It is volatility-normalized.
The same absolute move can be major for one stock and routine for another.
3. It is comparable across names.
Using `Z` makes cross-ticker interpretation more consistent.
4. It is deterministic and explainable.
Each component can be traced and audited from stored candles.

What this method is not:
- It is not a prediction model.
- It is not causality proof by itself.
- It is not a replacement for analyst context review.

---

## 5. Impact Label Terminology

### 5.1 Threshold bands (stable)

The numeric contract is:
- Band 1: `Z < 2.0`
- Band 2: `2.0 <= Z < 4.0`
- Band 3: `Z >= 4.0`

### 5.2 Label names (business-facing)

Recommended business-facing labels:
- Band 1 -> `Low`
- Band 2 -> `Medium`
- Band 3 -> `High`

Legacy labels seen historically:
- Band 1 -> `Noise`
- Band 2 -> `Significant`
- Band 3 -> `Extreme`

These two vocabularies are semantically equivalent by threshold.

---

## 6. Materiality Triplet (P1/P2/P3)

Materiality and impact are complementary:
- Impact asks: "How unusually did price move around article time?"
- Materiality asks: "How relevant is this article to the alert?"

Materiality is shown as a triplet like `HHM`.

### P1: Entity Prominence
- High: company in headline
- Medium: company in lead text
- Low: company only in body / weak mention

### P2: Temporal Proximity to alert window
- High: article near end of alert window
- Medium: middle of window
- Low: early in window or outside

### P3: Theme relevance
- High/Medium/Low based on mapped business theme classes.

#### P3 Category-to-Tier Contract (Authoritative)

This table is the policy contract and must stay aligned with:
- `backend/scoring.py` (`calculate_p3`)

| Tier | Theme categories |
| :--- | :--- |
| High (`H`) | `EARNINGS_ANNOUNCEMENT`, `M_AND_A`, `DIVIDEND_CORP_ACTION`, `PRODUCT_TECH_LAUNCH`, `COMMERCIAL_CONTRACTS` |
| Medium (`M`) | `LEGAL_REGULATORY`, `EXECUTIVE_CHANGE`, `OPERATIONAL_CRISIS`, `CAPITAL_STRUCTURE`, `MACRO_SECTOR`, `ANALYST_OPINION` |
| Low (`L`) | Any other theme not listed above, missing theme, or uncategorized values |

Notes:
- Matching is case-insensitive.
- Matching uses substring containment in implementation (for robustness to extended labels).

---

## 7. How Investigators Should Use the Score

Recommended sequence:
1. Check impact band first (Low/Medium/High).
2. Check materiality triplet next (look for strong P1/P3).
3. Check sentiment and narrative alignment with trade direction.
4. Decide recommendation with all evidence, not impact alone.

Interpretation guidance:
- High impact + high materiality can support a valid public-news explanation.
- High impact + weak materiality is a stronger escalation signal.
- Low impact does not prove innocence; it indicates weak price abnormality at article hour.

---

## 8. Operational Notes

1. The impact score depends on hourly price cache quality and timestamp quality.
2. Missing/poor timestamp data can reduce reliability.
3. If data is sparse, scores may be absent for some rows.
4. Thresholds are policy choices; they can be recalibrated later without changing formula.

---

## 9. Current Implementation Reference

Primary implementation:
- `scripts/calc_impact_scores.py`

Hourly data utilities:
- `scripts/market_data.py`

Materiality logic:
- `backend/scoring.py`
