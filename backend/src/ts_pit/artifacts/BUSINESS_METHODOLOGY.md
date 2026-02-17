# Business Methodology: Financial Alert Investigation

## 1. Purpose

This platform helps compliance and surveillance teams answer one core question quickly and
consistently:

Is a flagged trade explainable by public information, or does it need deeper investigation?

It is designed to reduce false positives, improve analyst throughput, and produce a defensible
audit trail for each decision.

## 2. Business Outcomes

The system is successful when it improves:

1. Analyst productivity:
   - Less manual searching and stitching of data.
2. Decision consistency:
   - Same evidence leads to same recommendation logic.
3. Escalation quality:
   - Fewer weak escalations and fewer missed suspicious cases.
4. Audit readiness:
   - Every recommendation is explainable with explicit evidence.

## 3. Business Workflow

For each alert:

1. Analyst opens the alert from the queue.
2. System displays:
   - Alert metadata (who/what/when),
   - price behavior around the alert window,
   - linked news evidence.
3. Analyst clicks "Analyze with AI."
4. System runs deterministic policy checks first, then AI narrative generation.
5. Analyst reviews:
   - system recommendation,
   - reasoning and evidence list,
   - chart/news context.
6. Analyst makes final workflow decision and updates status.

## 4. Two Different Decision Tracks

These are intentionally separate:

1. System recommendation (investigation interpretation):
   - `DISMISS`
   - `ESCALATE_L2`
   - `NEEDS_REVIEW`
2. Workflow status (case lifecycle state):
   - `NEEDS_REVIEW`
   - `ESCALATE_L2`
   - `DISMISS`

Reason to keep this distinction:
System recommendation is advisory logic; workflow status is operational ownership and closure.

## 5. Recommendation Policy

### 5.1 Canonical recommendation meanings

1. `DISMISS`
   - Evidence indicates market behavior is reasonably explained by public information or abnormality is weak.
2. `ESCALATE_L2`
   - Behavior appears unexplained/suspicious and requires deeper review.
3. `NEEDS_REVIEW`
   - Evidence is insufficient, conflicting, or blocked by data/technical quality issues.

### 5.2 Deterministic-first policy

Before AI recommendation, the system enforces deterministic gates:

1. Data readiness:
   - Required fields must exist (trade type, dates, trade timestamp context).
2. Timestamp quality:
   - Linked articles must have valid publication timestamps.
3. Causality:
   - Only pre-trade or at-trade public articles can justify the trade.

If these fail, recommendation defaults safely to `NEEDS_REVIEW`.

If there is high impact without pre-trade evidence, policy can escalate to `ESCALATE_L2`.

## 6. Scoring and Evidence (Business Interpretation)

The system combines two evidence dimensions:

1. Impact score:
   - Measures how unusual the price move was around article publication time.
   - Labels:
     - `Low`
     - `Medium`
     - `High`
2. Materiality triplet (`P1P2P3`):
   - P1: entity prominence in article context.
   - P2: timing proximity to alert window.
   - P3: thematic relevance tier.

Business use:

1. High impact + strong materiality + valid pre-trade public evidence can support `DISMISS`.
2. High impact + weak/absent causally valid evidence supports `ESCALATE_L2`.
3. Missing/poor-quality evidence supports `NEEDS_REVIEW`.

## 7. Why This Method Is Defensible

The methodology is defensible because it is:

1. Deterministic-first:
   - Hard policy checks reduce arbitrary AI behavior.
2. Evidence-linked:
   - Recommendations require tied facts (dates, scores, article linkage).
3. Auditable:
   - Inputs and outputs can be traced in DB/API records.
4. Conservative on uncertainty:
   - Unknown or broken context defaults to review, not auto-dismiss.

## 8. Governance and Change Control

Any policy change to labels, thresholds, or gating must include:

1. Business sign-off:
   - Confirm risk appetite and expected override behavior.
2. Technical change:
   - Prompt/schema/backend/frontend updates as needed.
3. Migration plan:
   - Backfill/normalization for historical values if labels change.
4. Validation:
   - Dry-run checks and before/after distributions on representative data.

## 9. Operating KPIs

Track these KPIs to judge business value:

1. False-dismiss rate.
2. Escalation precision.
3. Analyst override rate.
4. Time-to-disposition per alert.
5. Rate of `NEEDS_REVIEW` due to data quality failures.

## 10. FAQ for Business Stakeholders

1. Why not always rely on AI?
   - AI is best used after deterministic policy gates confirm minimum evidence quality.
2. Why does `NEEDS_REVIEW` happen even when AI is available?
   - Data quality and causality checks intentionally block overconfident automation.
3. Can labels change in the future?
   - Yes, but only through controlled migration and contract updates.
4. Does high impact alone prove suspicious behavior?
   - No. It signals abnormal movement, not causality by itself.
