import yfinance as yf
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

MARKET_INDICES = {
    "KOSPI": "^KS11",
    "KOSDAQ": "^KQ11",
    "S&P500": "^GSPC",
    "NASDAQ": "^IXIC",
    "DOW": "^DJI",
    "WTI유가": "CL=F",
    "VIX": "^VIX",
    "USD/KRW": "USDKRW=X"
}

UNITS = {
    "KOSPI": "pt",
    "KOSDAQ": "pt",
    "S&P500": "pt",
    "NASDAQ": "pt",
    "DOW": "pt",
    "WTI유가": "$",
    "VIX": "pt",
    "USD/KRW": "원"
}


def _fetch_one(item):
    name, ticker = item
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="5d")

        if hist.empty:
            return name, None

        current = float(hist["Close"].iloc[-1])

        if len(hist) >= 2:
            prev = float(hist["Close"].iloc[-2])
            change_pct = ((current - prev) / prev) * 100
        else:
            change_pct = 0.0

        return name, {
            "price": round(current, 2),
            "change_pct": round(change_pct, 2),
            "up": change_pct >= 0,
            "unit": UNITS.get(name, "")
        }
    except Exception as e:
        return name, {"price": 0, "change_pct": 0, "up": True, "unit": "", "error": str(e)}


def get_market_data():
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(_fetch_one, MARKET_INDICES.items()))

    data = {name: val for name, val in results if val}

    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data": data
    }
