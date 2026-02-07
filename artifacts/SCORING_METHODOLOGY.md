# Scoring Methodology & Guide

This document details the quantitative and qualitative metrics used in the dashboard to evaluate financial alerts.

---

## 1. Materiality Score (Hybrid Triplet)
The Materiality Score is a **composite triplet** (e.g., `HHM`) representing three distinct dimensions of an article's relevance. It is designed to quickly answer: *"Does this article matter right now?"*

### The Triplet Structure
The score is displayed as three letters (H/M/L) corresponding to **P1**, **P2**, and **P3**.

| Dimension | Type | Represents | Why it matters |
| :--- | :--- | :--- | :--- |
| **P1** | **Entity Prominence** | *Who is it about?* | Filters out noise where the company is just a footnote. |
| **P2** | **Temporal Proximity** | *When did it happen?* | Prioritizes news closest to the event impact window. |
| **P3** | **Thematic Relevance** | *What is it about?* | Prioritizes high-impact event types (e.g., Earnings vs. General News). |

### P1: Entity Prominence (Static)
*   **Calculated By**: `scripts/calc_prominence.py` (Stored in DB)
*   **Methodology**: Regex matching of Ticker and Instrument Name.
    *   **High (H)**: Entity mentioned in the **Headline**.
    *   **Medium (M)**: Entity mentioned in the **Lead Paragraph** (first 500 chars).
    *   **Low (L)**: Entity mentioned only in the body text or not found.
*   **Pros**: Extremely fast, filters "tangential" mentions.
*   **Cons**: Can miss context (e.g., "Competitor of [Ticker]..." might be scored H).

### P2: Temporal Proximity (Dynamic)
*   **Calculated By**: `backend/main.py` (Real-time)
*   **Methodology**: Position of the article within the Alert's "Impact Window" (Start Date to End Date).
    *   Formula: $Ratio = (ArticleDate - StartDate) / (EndDate - StartDate)$
    *   **High (H)**: Top 33% of the window (Closest to the target date).
    *   **Medium (M)**: Middle 33%.
    *   **Low (L)**: First 33% (Oldest news in the window) or outside the window.
*   **Pros**: Auto-adjusts if you change the alert window. Highlights "fresh" information.

### P3: Thematic Relevance (AI + Dynamic)
*   **Calculated By**: AI Analysis / `backend/main.py` map.
*   **Methodology**: Maps the AI-identified "Theme" to a priority tier.
    *   **High (H)**: `Earnings`, `M&A`, `Dividends`, `Product Launch`, `Contracts`.
    *   **Medium (M)**: `Legal/Regulatory`, `Executive Change`, `Operational Crisis`, `Capital Structure`.
    *   **Low (L)**: `Analyst Opinion`, `Market Noise`, `Uncategorized`.
*   **Pros**: Focuses attention on fundamental drivers of value.

---

## 2. Event Impact Score (Z-Score)
The Impact Score is a statistical measure of **market abnormality** at the time of the alert.

*   **Calculated By**: `scripts/calc_impact_scores.py`
*   **Methodology (Current Implementation)**:
    *   Build a baseline from **10 days of hourly candles before article time**.
    *   Compute hourly return baseline: `(close - open) / open`.
    *   Use baseline volatility `std(hourly_returns)`.
    *   Compute event candle return from the first candle at/after article timestamp.
    *   Final score: `Z = abs(event_return) / baseline_volatility`.
*   **Interpretation**:
    *   **Noise**: `< 2.0`
    *   **Significant**: `2.0 - <4.0`
    *   **Extreme**: `>= 4.0`

*   **Why use Z-Score?**
    It normalizes volatility. A 2% move in a stable utility stock is huge (High Z-Score), while a 2% move in a crypto stock might be noise (Low Z-Score).

---

## 3. Sentiment (Bullish/Bearish)
*   **Calculated By**: AI Analysis (`Prompts: ANALYSIS_SYSTEM_PROMPT`).
*   **Methodology**: LLM analyzes the *content* of the articles cluster, not just price.
*   **Categories**:
    *   **Bullish**: Positive news likely to drive price up.
    *   **Bearish**: Negative news likely to drive price down.
    *   **Neutral**: Informational or mixed impact.

---

## How to Review an Alert (Synthesis Guide)

Use the combination of these three metrics to make decisions:

### Scenario A: The "Critical Event" ✅
*   **Impact**: **High (>2.0)** (The market reacted violently)
*   **Materiality**: **HHH** (Headline news, recent, high-priority theme)
*   **Sentiment**: **Bearish**
*   **Conclusion**: Real, explained market event. **High Confidence Short.**

### Scenario B: The "Overreaction" / "Mismatch" ⚠️
*   **Impact**: **High (>2.0)** (Price moved)
*   **Materiality**: **LML** (Tangential mention, old news, low priority)
*   **Conclusion**: Price moved, but the news doesn't explain it. Could be:
    1.  Insider trading / leak (News hasn't hit yet).
    2.  Market manipulation.
    3.  Algo reaction to a false flag.
    *Action: Investigate deeper or wait.*

### Scenario C: The "Priced In" Event 💤
*   **Impact**: **Low (<1.0)** (No price move)
*   **Materiality**: **HHH** (Major earnings report)
*   **Conclusion**: The news was expected or the market doesn't care.

### Summary Strategy
1.  **Check Impact First**: Did the price actually move?
2.  **scan Materiality**: Can the news explain *why*? (Look for `H` in P1/P3).
3.  **Read Sentiment**: Directional check.
