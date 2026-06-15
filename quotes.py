"""
Live quote fetching for the trade-plan tab.

Given a small set of tickers (a user's saved plans), return the current price
and today's change for each. Uses yfinance's fast_info, which is a lightweight
call compared to a full history download. Results are cached briefly so rapid
polling from the frontend doesn't hammer Yahoo.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import yfinance as yf

# Short in-process cache: {ticker: (timestamp, quote_dict)}
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 20  # seconds — comfortably under the 30s frontend poll interval


def _fetch_one(ticker: str) -> dict:
    now = time.time()
    cached = _CACHE.get(ticker)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]

    quote = {"ticker": ticker, "price": None, "prev_close": None,
             "change_pct": None, "error": None}
    try:
        fi = yf.Ticker(ticker).fast_info
        price = fi.get("lastPrice") or fi.get("last_price")
        prev = fi.get("previousClose") or fi.get("previous_close")
        if price is not None:
            quote["price"] = round(float(price), 2)
        if prev is not None:
            quote["prev_close"] = round(float(prev), 2)
        if price is not None and prev:
            quote["change_pct"] = round((float(price) / float(prev) - 1) * 100, 2)
        if quote["price"] is None:
            quote["error"] = "no price"
    except Exception as e:
        quote["error"] = str(e)

    _CACHE[ticker] = (now, quote)
    return quote


def get_quotes(tickers: list[str]) -> dict[str, dict]:
    """Returns {ticker: quote_dict} for the requested tickers."""
    # De-dupe and clamp to a sane max so a malformed request can't fan out huge.
    uniq = list(dict.fromkeys(t.strip().upper() for t in tickers if t.strip()))[:60]
    if not uniq:
        return {}
    with ThreadPoolExecutor(max_workers=min(8, len(uniq))) as pool:
        results = list(pool.map(_fetch_one, uniq))
    return {q["ticker"]: q for q in results}
