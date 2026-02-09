import sqlite3
import yaml
import random
import sys

print("DEBUG: Core imports done", flush=True)

try:
    import yfinance as yf
    import pandas as pd
    from datetime import datetime, timedelta
    from faker import Faker
    from colorama import init, Fore, Style
except ImportError as e:
    print(f"DEBUG: Import error: {e}", flush=True)
    sys.exit(1)

print("DEBUG: All imports done", flush=True)

# Initialize Colorama and Faker
init(autoreset=True)
fake = Faker()

# Global Constraints
START_BOUND = "2025-10-01"
END_BOUND = "2026-01-31"


def load_config(config_path):
    try:
        with open(config_path, "r") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"{Fore.RED}Error loading config: {e}")
        sys.exit(1)


def get_db_type(column_name, key_name):
    """Infers SQLite data type and Primary Key status."""
    col_lower = column_name.lower()
    # Check if this column is meant to be a Primary Key
    # It looks for 'id' in the YAML key or the DB column name
    is_pk = "PRIMARY KEY" if (key_name == "id" or key_name == "art_id") else ""

    dtype = "TEXT"
    if any(x in col_lower for x in ["id", "quantity", "volume", "score"]):
        dtype = "INTEGER"
    elif any(x in col_lower for x in ["date", "at"]):
        dtype = "DATE"
    elif any(x in col_lower for x in ["price", "open", "high", "low", "close"]):
        dtype = "REAL"

    return f"{dtype} {is_pk}"


def insert_dynamic(cursor, table_name, data):
    """Dynamically inserts data into SQLite table using column mapping."""
    filtered_data = {k: v for k, v in data.items() if k}
    cols = ", ".join([f'"{k}"' for k in filtered_data.keys()])
    placeholders = ", ".join(["?" for _ in filtered_data])
    sql = f"INSERT OR IGNORE INTO {table_name} ({cols}) VALUES ({placeholders})"
    cursor.execute(sql, tuple(filtered_data.values()))


def fetch_real_prices(ticker, interval):
    """Downloads and flattens yfinance data for a single ticker."""
    df = yf.download(
        ticker, start=START_BOUND, end=END_BOUND, interval=interval, progress=False
    )
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def main():
    config_file = "config.yaml"
    cfg = load_config(config_file)
    db_path = cfg["database"]["path"]
    available_tables = cfg.get("tables", {})

    print(f"\n{Fore.MAGENTA}{Style.BRIGHT}SQLite Financial Data Generator (v2.1)")
    print(f"{Fore.WHITE}{'=' * 50}")

    table_keys = list(available_tables.keys())
    for idx, key in enumerate(table_keys, 1):
        print(f"{Fore.YELLOW}{idx}. {Fore.WHITE}{key}")

    # Check for CLI argument to bypass prompt
    if "--all" in sys.argv:
        choice = "all"
        print(f"\n{Fore.CYAN}Auto-selecting ALL tables (CLI argument detected)")
    else:
        choice = (
            input(f"\n{Fore.CYAN}Select tables to build (e.g. 1,2) or 'all': ")
            .strip()
            .lower()
        )
    selected_keys = (
        table_keys
        if choice == "all"
        else [table_keys[int(i) - 1] for i in choice.split(",") if i.strip().isdigit()]
    )

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 1. Schema Creation with Correct Primary Keys
    for key in selected_keys:
        t_info = available_tables[key]
        col_defs = []
        for yaml_key, db_name in t_info["columns"].items():
            if db_name:
                col_defs.append(f'"{db_name}" {get_db_type(db_name, yaml_key)}')

        cursor.execute(
            f"DROP TABLE IF EXISTS {t_info['name']}"
        )  # Resetting to fix PK issue
        cursor.execute(f"CREATE TABLE {t_info['name']} ({', '.join(col_defs)})")
        print(f"{Fore.GREEN}[✓] Schema Created: {t_info['name']} (PK Set)")

    # 2. Market Data Processing
    tickers = ["AAPL", "TSLA", "MSFT", "NVDA", "JPM"]
    if any(k in selected_keys for k in ["prices", "prices_hourly"]):
        for ticker in tickers:
            print(f"{Fore.CYAN}Fetching prices for {ticker}...")
            if "prices" in selected_keys:
                df_d = fetch_real_prices(ticker, "1d")
                t = available_tables["prices"]
                for index, row in df_d.iterrows():
                    if pd.isna(row["Open"]):
                        continue
                    insert_dynamic(
                        cursor,
                        t["name"],
                        {
                            t["columns"]["ticker"]: ticker,
                            t["columns"]["date"]: index.strftime("%Y-%m-%d"),
                            t["columns"]["open"]: float(row["Open"]),
                            t["columns"]["high"]: float(row["High"]),
                            t["columns"]["low"]: float(row["Low"]),
                            t["columns"]["close"]: float(row["Close"]),
                            t["columns"]["volume"]: int(row["Volume"]),
                        },
                    )

    # 3. Alerts, Articles & Article Themes
    if "alerts" in selected_keys:
        print(f"{Fore.CYAN}Generating Relational Data & Summaries...")
        alt = available_tables["alerts"]
        art = available_tables.get("articles")
        ath = available_tables.get("article_themes")
        start_dt = datetime.strptime(START_BOUND, "%Y-%m-%d")

        sentiments = ["Bullish", "Bearish", "Neutral"]

        for i in range(1, 11):
            ticker = random.choice(tickers)
            a_start = start_dt + timedelta(days=random.randint(5, 30))
            a_end = a_start + timedelta(days=random.randint(5, 15))
            alert_date = a_end + timedelta(days=1)
            isin = f"US{random.randint(100, 999)}PIT{i}"

            # Insert Alert
            insert_dynamic(
                cursor,
                alt["name"],
                {
                    alt["columns"]["id"]: i,
                    alt["columns"]["ticker"]: ticker,
                    alt["columns"]["isin"]: isin,
                    alt["columns"]["status"]: random.choice(cfg["valid_statuses"]),
                    alt["columns"]["start_date"]: a_start.strftime("%Y-%m-%d"),
                    alt["columns"]["end_date"]: a_end.strftime("%Y-%m-%d"),
                    alt["columns"]["alert_date"]: alert_date.strftime("%Y-%m-%d"),
                    alt["columns"][
                        "narrative_summary"
                    ]: f"Detected movement in {ticker}.",
                },
            )

            # Insert Articles and matching Themes
            if art and "articles" in selected_keys:
                for j in range(2):
                    art_id = (i * 100) + j
                    art_date = a_start + timedelta(
                        days=random.randint(0, (a_end - a_start).days)
                    )

                    insert_dynamic(
                        cursor,
                        art["name"],
                        {
                            art["columns"]["id"]: art_id,
                            art["columns"]["isin"]: isin,
                            art["columns"]["ticker"]: ticker,
                            art["columns"]["created_date"]: art_date.strftime(
                                "%Y-%m-%d %H:%M:%S"
                            ),
                            art["columns"][
                                "title"
                            ]: f"{ticker} Report: {fake.bs().title()}",
                            art["columns"]["body"]: fake.paragraph(nb_sentences=10),
                            art["columns"]["summary"]: fake.sentence(nb_words=12),
                            art["columns"]["sentiment"]: random.choice(sentiments),
                        },
                    )

                    # Populate Themes table to ensure ON CONFLICT has data to work with
                    if ath and "article_themes" in selected_keys:
                        insert_dynamic(
                            cursor,
                            ath["name"],
                            {
                                ath["columns"]["art_id"]: art_id,
                                ath["columns"]["theme"]: random.choice(
                                    ["Regulatory", "Earnings", "Product"]
                                ),
                                ath["columns"]["summary"]: fake.sentence(),
                                ath["columns"]["analysis"]: fake.paragraph(),
                            },
                        )

    conn.commit()
    conn.close()
    print(
        f"\n{Fore.GREEN}{Style.BRIGHT}Success! Database updated with Primary Keys fixed."
    )


if __name__ == "__main__":
    main()
