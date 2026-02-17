# Trade Surveillance Knowledge Base

## System Definitions
### Lookback Window (Investigation Period)
The **Lookback Window** is the critical time period relevant to an alert, typically defined by the `start_date` and `end_date` fields in the alert record. 
- **Purpose**: It represents the period during which market abuse is suspected to have occurred or the period relevant for finding news catalysts.
- **Usage**: When investigating an alert, all checks (news search, price analysis, volume analysis) should be focused on this window to avoid irrelevant data.
- **Dynamic Nature**: The window varies by alert type. For example, an Insider Trading alert might look back 2 weeks before a major announcement, while a Momentum Ignition alert might focus on a specific 2-hour window.

### Alerts vs. Events
- **Alert**: A triggered signal requiring investigation (e.g., "Potential Insider Trading").
- **Event**: A specific news item, corporate action, or price movement that may explain or corroborate the alert.

---

## Alert Types & Market Abuse Concepts

### Potential Insider Trading
**Definition**: Trading based on material non-public information (MNPI) about a company.
- **Indicators**:
    - Abnormal trading volume *before* a major news announcement (M&A, Earnings).
    - Profitable trades executed just prior to a price-moving event.
    - Patterns of accumulation (buying) or dumping (selling) without public justification.
- **Investigation Steps**:
    1. Identify the major news event (e.g., Merger announcement).
    2. Check if the trade occurred in the days/weeks leading up to it.
    3. Look for connections between the trader and the company (though the agent typically focuses on market data).

### Front Running
**Definition**: A broker or trader executing orders on a security for its own account while taking advantage of advance knowledge of pending orders from its customers.
- **Scenario**: A broker knows a client is about to buy 1M shares of Apple. The broker buys 10k shares for themselves first, knowing the client's order will push the price up.

### Spoofing / Layering
**Definition**: Placing non-bona fide orders (orders intended to be cancelled) to create a false impression of market demand or supply.
- **Mechanism**:
    1. **Layering**: Placing multiple limit orders on one side of the book (e.g., buy side) at different price levels to create the appearance of strong buying pressure.
    2. **Execution**: Once other traders react and move the price, the manipulator executes a trade on the *opposite* side (sell) at the uniform price.
    3. **Cancellation**: The original "layered" orders are cancelled.
- **Key Signal**: High ratio of order cancellations to executions.

### Momentum Ignition
**Definition**: Aggressively trading to start a rapid price move (momentum) to attract other algorithms/traders, then trading against them.
- **Indicators**: Rapid spike in price and volume followed by a reversal.

### Marking the Close
**Definition**: Executing trades at or near the market close to influence the closing price calculation.
- **Purpose**: To avoid margin calls, improve portfolio valuation, or support a derivative position.

---

## Surveillance Systems (Nasdaq SMARTS style)
**SMARTS** is a leading trade surveillance system used by exchanges and regulators. 
- **Pattern Matching**: It uses sophisticated algorithms to detect patterns like the ones above (Spoofing, Layering) in real-time.
- **Alert Generation**: When a pattern threshold is breached, an "Alert" is generated.
- **Workflow**: Analysts review these alerts to decide if they are "False Positives" (benign behavior) or "True Positives" (potential abuse requiring escalation).

## Investigation Best Practices
1. **Context is King**: A price spike is meaningless without news. A news story is irrelevant if the price didn't move.
2. **Benign Explanations**: Always look for innocent reasons first. 
    - *Did the price drop because the whole sector dropped?* (Sector correlation)
    - *Was the high volume due to a scheduled index rebalancing?*
3. **Data Triangulation**: Verify suspicious activity across Price, Volume, and News.
