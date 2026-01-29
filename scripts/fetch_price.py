import yfinance as yf
import sqlite3
import pandas as pd
from datetime import datetime, timedelta


def fetch_price_data(db_name="alerts.db"):
    conn = sqlite3.connect(db_name)
    try:
        # Get unique tickers and their required date ranges
        query = 'SELECT Ticker, MIN("Start date") as min_start, MAX("End date") as max_end FROM alerts GROUP BY Ticker'
        tickers_df = pd.read_sql_query(query, conn)

        all_prices = []

        for _, row in tickers_df.iterrows():
            ticker_symbol = row["Ticker"]
            start_date = row["min_start"]
            # Add one day to max_end to ensure we include it (yfinance end date is exclusive)
            end_date = (
                datetime.strptime(row["max_end"], "%Y-%m-%d") + timedelta(days=1)
            ).strftime("%Y-%m-%d")

            print(
                f"Fetching data for {ticker_symbol} from {start_date} to {end_date}..."
            )

            ticker_obj = yf.Ticker(ticker_symbol)

            # Fetch historical data
            hist = ticker_obj.history(start=start_date, end=end_date)

            if not hist.empty:
                # Fetch industry info
                industry = "Unknown"
                try:
                    info = ticker_obj.info
                    industry = info.get("industry", "Unknown")
                except Exception as e:
                    print(f"Warning: Could not fetch industry for {ticker_symbol}: {e}")

                # Format the data
                hist = hist.reset_index()
                hist["Ticker"] = ticker_symbol
                hist["Industry"] = industry

                # Keep only required columns
                hist = hist[["Ticker", "Date", "Open", "Close", "Volume", "Industry"]]
                hist["Date"] = hist["Date"].dt.strftime("%Y-%m-%d")

                all_prices.append(hist)
            else:
                print(f"No data found for {ticker_symbol}")

        if all_prices:
            prices_df = pd.concat(all_prices, ignore_index=True)
            # Rename columns to match request exactly
            prices_df.columns = [
                "ticker",
                "date",
                "opening price",
                "closing price",
                "volume",
                "industry",
            ]

            # Save to SQLite
            prices_df.to_sql("prices", conn, if_exists="replace", index=False)
            print(
                f"\nSuccessfully saved {len(prices_df)} price records to 'prices' table in {db_name}."
            )
        else:
            print("\nNo price data was fetched.")

    finally:
        conn.close()


if __name__ == "__main__":
    fetch_price_data()
