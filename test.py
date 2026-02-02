import yfinance as yf
import requests


def get_ticker_from_isin(isin):
    """
    Fetches the Yahoo Finance Ticker symbol for a given ISIN.
    """
    url = "https://query2.finance.yahoo.com/v1/finance/search"
    params = {"q": isin, "quotesCount": 1, "newsCount": 0}

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    try:
        response = requests.get(url, params=params, headers=headers)
        data = response.json()

        # Check if we got any quotes back
        if "quotes" in data and len(data["quotes"]) > 0:
            return data["quotes"][0]["symbol"]  # Return the first matching ticker
        else:
            return None
    except Exception as e:
        print(f"Error looking up ISIN {isin}: {e}")
        return None


# --- usage ---

isin_list = [
    "DE000A12UPJ7",  # Apple (AAPL)
    # "IE00B4BNMY34",  # Accenture (ACN)
    # "GB00BA00BF68",  # Vodafone (VOD.L) - Note the suffix!
]

print(f"{'ISIN':<15} | {'Ticker':<10} | {'Current Price':<10}")
print("-" * 40)

for isin in isin_list:
    ticker_symbol = get_ticker_from_isin(isin)

    if ticker_symbol:
        # Now use yfinance normally with the found ticker
        ticker = yf.Ticker(ticker_symbol)

        # Fast retrieval of current price
        try:
            price = ticker.fast_info["last_price"]
            print(f"{isin:<15} | {ticker_symbol:<10} | {price:.2f}")
        except:
            print(f"{isin:<15} | {ticker_symbol:<10} | N/A")
    else:
        print(f"{isin:<15} | Not Found  | -")
