# AI Recommendation Logic: The "Justification Test"

This document details the **Artificial Intelligence (AI) Recommendation Engine** implemented in the dashboard. This system acts as an automated "Level 1 Analyst," determining whether an alert should be rejected (justified by news) or escalated (unexplained).

---

## 1. The Core Methodology
The logic is built on a **"Causality Check"**:
> *Does the available public news explain the observed market reaction?*

We compare two magnitudes:
1.  **Market Impact** (Z-Score): How abnormal was the price move?
2.  **News Materiality** (Content): How significant is the news event?

### The Decision Matrix
| Scenario | Impact Score | News Quality | Verdict | Reasoning |
| :--- | :--- | :--- | :--- | :--- |
| **Justified** | **High** (>2.0) | **High** (Earnings/M&A) | **REJECT** | "Market move is explained by major news." |
| **Anomaly** | **High** (>2.0) | **Low / None** | **APPROVE L2** | "Price moved significantly but no news explains it. Suspicious." |
| **Noise** | **Low** (<2.0) | **Any** | **REJECT** | "No significant market impact occurred." |

---

## 2. Technical Data Flow

### Step 1: Data Aggregation (`backend/main.py`)
When the user clicks **"Analyze with AI"**:
1.  Backend fetches the **Alert Detail** and **Active Articles**.
2.  It calculates the **Max Impact Score** from the active articles (or Alert history).
    *   *Note*: The Z-Score comes from `scripts/calc_impact_scores.py` and is stored in the DB.

### Step 2: Context Construction (`backend/llm.py`)
The `generate_cluster_summary` function builds a context block for the LLM.

**What is sent to the LLM?**
We use a **Smart Filter** to select the most relevant evidence (capped at 30 articles):
1.  **High Importance**: Any article with an 'H' component in Materiality (e.g., `HML`, `LHM`).
2.  **High Impact**: Any article with a significant Impact Score (> 2.0).
3.  **Fallback**: If fewer than 3 significant articles exist, we default to the Top 15 sorted by date.

For *each* selected article, we send:
*   **Title**: The headline.
*   **Summary**: The full content/summary.
*   **Theme**: The AI-classified category (e.g., `EARNINGS_ANNOUNCEMENT`).
*   **Impact Score**: The specific Z-Score (Evidence of market reaction).
*   **Materiality**: The P1P2P3 score (Evidence of importance).

**Example Input to LLM:**
```text
Title: AAPL Stock Falls on SUV Delay
Summary: Apple announced it is delaying the Apple Car indefinitely...
CONFIRMED THEME: PRODUCT_TECH_LAUNCH
IMPACT SCORE (Z-Score): 3.2
```

### Step 3: The Prompt (`backend/prompts.py`)
The `CLUSTER_SUMMARY_SYSTEM_PROMPT` contains the "Analyst Instructions".
It explicitly directs the model to perform the **Justification Test**:

> "Check Evidence: Do the provided articles explain the *direction* and *magnitude* of the move?
> IF High Impact AND High Materiality News -> REJECT (Justified).
> IF High Impact BUT No Material News -> APPROVE_L2 (Suspicious)."

### Step 4: Structured Output (`backend/schemas.py`)
The LLM returns a strict JSON object (`ClusterSummaryOutput`):
```json
{
  "recommendation": "REJECT",
  "recommendation_reason": "High impact score (3.2) is fully justified by the negative product delay announcement."
}
```

### Step 5: Frontend Display (`frontend/.../AlertDetail.vue`)
*   **Green Badge (REJECT)**: Displays "✅ MARKET MOVE EXPLAINED".
*   **Red Badge (APPROVE_L2)**: Displays "⚠️ UNEXPLAINED ANOMALY".

---

## 3. Code Locations (Where to Edit)

| Component | File Path | Purpose |
| :--- | :--- | :--- |
| **Prompt Logic** | `backend/prompts.py` | Edit the "Analyst Persona" and decision rules. |
| **Context Builder** | `backend/llm.py` | Change *what data* (e.g., prices, volume) is sent to the LLM. |
| **Output Schema** | `backend/schemas.py` | Add new fields (e.g., Confidence Score) to the JSON output. |
| **UI Badge** | `frontend/src/views/AlertDetail.vue` | Change colors, icons, or layout of the recommendation. |

---

## 4. Why This Works
By forcing the LLM to look at the **Impact Score** (Data) alongside the **Summary** (Narrative), we prevent it from "hallucinating" importance. A news article might *sound* scary, but if the Z-Score is 0.5, the LLM knows to ignore it (Verdict: Noise). Conversely, if the Z-Score is 4.0 and there is no news, it knows to flag it (Verdict: Anomaly).
