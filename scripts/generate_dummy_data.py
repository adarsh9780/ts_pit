import pandas as pd
import sqlite3
import random
import uuid
from datetime import datetime, timedelta
from pandas.tseries.offsets import BusinessDay
import shutil
import os


def generate_dummy_data(num_records=50):
    # Sample data for tickers and instruments
    assets = [
        {"Ticker": "AAPL", "ISIN": "US0378331005", "Name": "Apple Inc."},
        {"Ticker": "MSFT", "ISIN": "US5949181045", "Name": "Microsoft Corporation"},
        {"Ticker": "GOOGL", "ISIN": "US02079K3051", "Name": "Alphabet Inc."},
        {"Ticker": "AMZN", "ISIN": "US0231351067", "Name": "Amazon.com Inc."},
        {"Ticker": "TSLA", "ISIN": "US88160R1014", "Name": "Tesla Inc."},
        {"Ticker": "NVDA", "ISIN": "US67066G1040", "Name": "NVIDIA Corporation"},
        {"Ticker": "META", "ISIN": "US30303M1027", "Name": "Meta Platforms Inc."},
        {"Ticker": "JPM", "ISIN": "US46625H1005", "Name": "JPMorgan Chase & Co."},
        {"Ticker": "V", "ISIN": "US92826C8394", "Name": "Visa Inc."},
        {"Ticker": "WMT", "ISIN": "US9311421039", "Name": "Walmart Inc."},
    ]

    themes_info = [
        {
            "theme": "EARNINGS_ANNOUNCEMENT",
            "desc": "Official earnings releases, EPS beats/misses, guidance updates.",
        },
        {"theme": "M_AND_A", "desc": "Mergers, acquisitions, buyouts, tender offers."},
        {"theme": "DIVIDEND_CORP_ACTION", "desc": "Dividends, stock splits, buybacks."},
        {
            "theme": "PRODUCT_TECH_LAUNCH",
            "desc": "Major product reveals, FDA approvals, patent wins.",
        },
        {
            "theme": "COMMERCIAL_CONTRACTS",
            "desc": "Major contract wins, government tenders.",
        },
        {"theme": "LEGAL_REGULATORY", "desc": "Lawsuits, SEC probes, settlements."},
        {"theme": "EXECUTIVE_CHANGE", "desc": "CEO/CFO resignations or appointments."},
        {
            "theme": "ANALYST_OPINION",
            "desc": "Upgrades/downgrades, price targets (Weak Justification).",
        },
        {"theme": "IRRELEVANT", "desc": "General market noise, daily summaries."},
    ]

    alerts_data = []
    articles_data = []
    base_date = datetime.now()

    for i in range(num_records):
        asset = random.choice(assets)
        # Random trade execution date within the last 30 days
        trade_date = base_date - timedelta(days=random.randint(2, 30))

        # Alert date = Trade execution date + 1 working day
        alert_date = trade_date + BusinessDay(1)

        # Lookback period: Start date and End date
        lookback_start = trade_date - timedelta(days=random.randint(5, 15))
        lookback_end = trade_date + timedelta(days=random.randint(0, 2))

        trade_type = random.choice(["Buy", "Sell"])

        alert_record = {
            "Alert ID": f"ALT-{1000 + i}",
            "ISIN": asset["ISIN"],
            "Ticker": asset["Ticker"],
            "Instrument Name": asset["Name"],
            "Sum of buy quantity": random.randint(100, 10000)
            if trade_type == "Buy"
            else 0,
            "Sum of sell quantity": random.randint(100, 10000)
            if trade_type == "Sell"
            else 0,
            "Trade execution date": trade_date.strftime("%Y-%m-%d"),
            "trade type": trade_type,
            "Alert date": alert_date.strftime("%Y-%m-%d"),
            "Start date": lookback_start.strftime("%Y-%m-%d"),
            "End date": lookback_end.strftime("%Y-%m-%d"),
            "status": "Pending",  # All new alerts start as Pending
        }
        alerts_data.append(alert_record)

        # Generate articles for each day in lookback period
        current_date = lookback_start
        while current_date <= lookback_end:
            # Randomly decide how many articles per day (0 to 2)
            for _ in range(random.randint(1, 2)):
                theme = random.choice(themes_info)
                sentiment_prefix = random.choice(["Bullish", "Bearish", "Neutral"])

                # Generate a concise summary (1-2 sentences)
                summary_templates = [
                    f"{asset['Ticker']} {theme['theme'].lower().replace('_', ' ')} event detected.",
                    f"Significant {theme['theme'].lower().replace('_', ' ')} activity for {asset['Name']}.",
                    f"{sentiment_prefix} development in {theme['theme'].lower().replace('_', ' ')} for {asset['Ticker']}.",
                ]
                art_summary = random.choice(summary_templates)

                article_record = {
                    "art_id": str(uuid.uuid4()),
                    "crescendo_id": asset["ISIN"],
                    "isin": asset["ISIN"],
                    "art_created_date": current_date.strftime("%Y-%m-%d"),
                    "art_title": f"{asset['Ticker']} - {theme['theme']} reported on {current_date.strftime('%Y-%m-%d')}",
                    "art_body": f"The latest reports for {asset['Name']} indicate a major activity in the {theme['theme']} sector. {theme['desc']}",
                    "sentiment": f"{sentiment_prefix}: This {theme['theme']} event could significantly impact investor sentiment.",
                    "theme": theme["theme"],
                    "art_summary": art_summary,
                    "Materiality": "".join(random.choices(["H", "M", "L"], k=3)),
                }
                articles_data.append(article_record)
            current_date += timedelta(days=1)

    alerts_df = pd.DataFrame(alerts_data)
    articles_df = pd.DataFrame(articles_data)
    return alerts_df, articles_df


def save_to_sqlite(alerts_df, articles_df, db_name="alerts.db"):
    # SAFETY: Backup existing DB
    if os.path.exists(db_name):
        backup_name = f"{db_name}.bak_dummy"
        try:
            print(f"📦 Creating backup at '{backup_name}'...")
            shutil.copy2(db_name, backup_name)
        except Exception as e:
            print(f"⚠️  Warning: Failed to create backup: {e}")

    conn = sqlite3.connect(db_name)
    # OPTIMIZATION: Use WAL mode
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")

    try:
        alerts_df.to_sql("alerts", conn, if_exists="replace", index=False)
        articles_df.to_sql("articles", conn, if_exists="replace", index=False)
        print(
            f"Successfully saved {len(alerts_df)} alerts and {len(articles_df)} articles to {db_name}."
        )
    finally:
        conn.close()


if __name__ == "__main__":
    alerts, articles = generate_dummy_data(50)
    save_to_sqlite(alerts, articles)

    print("\nSample Alerts Data:")
    print(alerts.head())

    print("\nSample Articles Data:")
    print(articles.head())
