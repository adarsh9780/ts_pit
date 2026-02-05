This is a comprehensive **Methodology and Solution Design Document** for the Insider Trading Alert Validator. This document details the architectural logic, scoring algorithms, and validation steps required to build a "Defense Engine" that automatically identifies public justifications for suspicious trades.

---

# 📘 Solution Design: Insider Trading "Defense Engine"

## 1. Core Philosophy: The "Exculpatory" Approach

Traditional surveillance systems are **accusatory**—they flag trades based on "suspicious" timing (e.g., trading before a price spike). This creates high false-positive rates because professional traders often trade *reactively* to public news.

This solution flips the model to be **defensive**. instead of looking for guilt, the system actively hunts for **innocence**. It assumes the trade is valid and attempts to find a "Public Justification" (e.g., a dividend announcement or earnings release) that explains the activity. If a strong justification is found, the alert is recommended for dismissal.

---

## 2. Phase I: Data Ingestion & Context Construction

Before analysis begins, the system must construct a complete timeline of the "Crime Scene."

### Step 1: Defining the Search Windows

We cannot simply "search for news." We must define specific time horizons to answer different questions.

* **The "Justification Window" (Look-Back):**
* **Range:**  to .
* **Purpose:** To find the *cause* of the trade. We look for news released *before* the trade execution.
* *Why:* Information released *after* the trade cannot justify the decision to buy/sell (unless it is insider trading). We strictly filter for prior knowledge.

* **The "Impact Window" (Look-Forward):**
* **Range:**  to .
* **Purpose:** To measure the *effect* of the news/trade.
* *Why:* To prove "Materiality." If the news found in the Look-Back window didn't move the price in the Look-Forward window, it may not be a valid justification.

### Step 2: Data Normalization

* **Entity Resolution:** Convert the Alert ISIN (e.g., "US0378331005") into a readable Ticker/Company Name (e.g., "Apple Inc.") to ensure news searches are accurate.
* **Time Standardization:** Convert all timestamps (Trade Time, News Publication Time, Exchange Open Time) to **UTC** to prevent "Time Zone Hallucinations" (e.g., thinking a trade happened before news just because of a timezone difference).

---

## 3. Phase II: The Justification Analysis (AI Logic)

This phase uses a Large Language Model (LLM) to act as a **Senior Financial Analyst**. It performs two distinct cognitive tasks: Classification and Extraction.

### Step 3: Classification (The "Why")

The system analyzes every news article found in the "Justification Window" to determine if it describes a market-moving event.

**Methodology:**
The AI classifies the article into one of three weighted tiers.

* **Tier 1: Strong Justification (High Probability of Market Move)**
* *Categories:* `EARNINGS_ANNOUNCEMENT`, `M_AND_A` (Mergers), `DIVIDEND_CORP_ACTION`, `PRODUCT_TECH_LAUNCH`.
* *Why:* These are factual, hard events. A dividend declaration is a mathematical reason to buy stock. These carry the highest "Exculpatory Weight."

* **Tier 2: Directional Justification (Sentiment Dependent)**
* *Categories:* `LEGAL_REGULATORY`, `EXECUTIVE_CHANGE`, `OPERATIONAL_CRISIS`.
* *Why:* These justify a trade *only if* the direction matches. (e.g., "CEO Resigns" justifies Selling, but makes Buying suspicious/contrarian).

* **Tier 3: Weak / Noise (Low Justification)**
* *Categories:* `ANALYST_OPINION`, `MACRO_SECTOR` (e.g., "Tech stocks are down"), `IRRELEVANT`.
* *Why:* These are opinions, not facts. A trader claiming they bought because "Jim Cramer said so" is a weak defense compared to "The company raised guidance."

### Step 4: Context-Aware Date Extraction (The "When")

This is the most critical step to prevent "Time Travel" errors. A generic date extractor is insufficient because articles contain multiple dates (e.g., "Launched today, Earnings next month").

**Methodology:**
We use a **Context-Aware** approach. The system passes the *Category* identified in Step 3 into the date extraction logic.

* *Instruction:* "Extract dates *only* related to the [Specific Category]."
* *Target 1: Announcement Date ():* The exact moment the public was informed.
* *Target 2: Effective Date ():* The date the event actually applies (e.g., the Ex-Dividend date).

*Why:* This ensures we don't accidentally validate a trade using a *future* date mentioned in the text.

---

## 4. Phase III: The Validation Engine (Scoring Logic)

Once the AI extracts the structured data, we apply deterministic logic (math/code) to calculate the final "Justification Score."

### Step 5: The "Time Travel" Check (Front-Running Prevention)

This is a binary Pass/Fail gate. We compare the **Trade Timestamp** () with the **Announcement Timestamp** ().

* **Scenario A:  (FAIL)**
* *Diagnosis:* **Prescient Trading / Front-Running.**
* *Logic:* The trader bought *before* the news was public. This is the definition of Insider Trading.
* *Action:* Score is forced to **0**. Status = **"SUSPICIOUS"**.

* **Scenario B:  (PASS)**
* *Diagnosis:* **Reactive Trading.**
* *Logic:* The trader acted on public information.
* *Action:* Proceed to scoring.

### Step 6: The Scoring Algorithm

We calculate a score between **0.0** and **1.0** to quantify the strength of the defense.

**1. Base Weight (Event Type):**

* `M_AND_A`, `EARNINGS`, `DIVIDEND`: **0.8** (Strongest)
* `PRODUCT`, `LEGAL`: **0.6**
* `ANALYST`, `MACRO`: **0.3** (Weakest)

**2. Relevance Multiplier (Content Match):**

* **High (1.0):** Company Name appears in the **Headline**. (The news is *about* the company).
* **Low (0.5):** Company Name appears only in the **Body**. (The news might be tangential).

**3. Timing Bonus (Recency):**

* **Immediate Reaction (+0.2):** Trade occurred  hours after news. (Highly likely to be a reaction).
* **Delayed Reaction (+0.1):** Trade occurred 1–3 days after news.
* **Stale News (0.0):** Trade occurred  days after news.

**Example Calculation:**

* *Event:* Dividend Announcement (Base 0.8).
* *Relevance:* In Headline (x 1.0).
* *Timing:* Trade was 2 hours later (+0.2).
* *Final Score:*  (Perfect Justification).

---

## 5. Phase IV: Market Impact Verification

Even if the news is real, we must check if it was **Material**. Did the market care?

### Step 7: Relative Volume Ratio (RVR) Calculation

We compare the volume on the day of the news against the "Normal" volume.

* **RVR > 2.0:** **High Impact.** The volume doubled. The market clearly treated this as material news. This strengthens the justification.
* **RVR < 1.0:** **Low Impact.** The market ignored it. If the trader bet heavily on this, it might be suspicious (or just a bad trade).

---

## 6. Phase V: Evidence Presentation (The Dashboard)

The final output is a visual "Evidence Pack" for the human investigator.

### Step 8: The "Event Overlay" Chart

To allow for 30-second decision-making, we generate a specific chart:

* **Visual:** A standard Price Candle chart.
* **Overlay 1 (Green Pin):** Placed at . Label: "News: [Headline]".
* **Overlay 2 (Red Triangle):** Placed at . Label: "Trade: [Buy/Sell]".
* **The "Cognitive Check":** The investigator simply looks at the chart. If the **Green Pin is to the left of the Red Triangle**, the trade is visually confirmed as reactive.

### Step 9: The "Tear Sheet" Narrative

We generate a concise summary using the following template:

> *"This alert is recommended for **DISMISSAL (Score: 0.95)**. The user executed a **BUY** order 4 hours after **Apple Inc.** announced a **Special Dividend** (Category: DIVIDEND_CORP_ACTION). Market volume spiked **2.5x** following the news, confirming materiality. No evidence of pre-announcement positioning found."*

---

## 7. Summary of Logic Gates

| Gate | Check | If Pass | If Fail |
| --- | --- | --- | --- |
| **1. News Existence** | Is there any news in the 5 days prior? | Proceed to AI | **Escalate** (Unexplained) |
| **2. Classification** | Is the news a "Material Event" (Tier 1/2)? | Proceed to Dates | **Escalate** (Noise only) |
| **3. Time Travel** | Was ? | Proceed to Score | **FLAG** (Prescient/Inside Info) |
| **4. Justification** | Is Final Score ? | **Auto-Dismiss** | **Escalate** (Weak Justification) |
