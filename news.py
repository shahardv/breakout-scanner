"""News feed — last 72h of headlines from a small set of market-mover tickers.

Uses yfinance (already a dep). Defensive against yfinance's shifting news schema:
older versions returned flat dicts, recent versions nest under "content".

ponytail: tickers list is hardcoded, swap to Finnhub if Yahoo throttling on
Render gets bad enough to make this unusable.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import yfinance as yf

HEADLINE_TICKERS = ["SPY", "QQQ", "AAPL", "NVDA", "MSFT", "META",
                    "GOOGL", "AMZN", "TSLA", "AVGO", "AMD", "NFLX"]
WINDOW_SEC = 72 * 3600
_CACHE: dict = {"ts": 0, "items": []}
_TTL = 300  # 5 min


def _pick(d: dict, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, "", []):
            return d[k]
    return default


def _normalize(raw: dict, ticker: str) -> dict | None:
    # yfinance returns either flat (older) or {"id":..., "content": {...}} (newer).
    c = raw.get("content") if isinstance(raw, dict) else None
    src = c if isinstance(c, dict) else raw

    title = _pick(src, "title")
    if not title:
        return None

    # publish time: unix seconds (flat) OR ISO string (nested)
    ts_raw = _pick(src, "providerPublishTime", "pubDate", "displayTime")
    if isinstance(ts_raw, (int, float)):
        ts = int(ts_raw)
    elif isinstance(ts_raw, str):
        try:
            # tolerant ISO parse — strip trailing Z
            import datetime as dt
            ts = int(dt.datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).timestamp())
        except Exception:
            return None
    else:
        return None

    pub = _pick(src, "publisher", "provider")
    if isinstance(pub, dict):
        pub = pub.get("displayName") or pub.get("name")

    link = _pick(src, "link")
    if not link:
        cu = src.get("canonicalUrl") or src.get("clickThroughUrl") or {}
        if isinstance(cu, dict):
            link = cu.get("url")

    thumb = None
    th = src.get("thumbnail")
    if isinstance(th, dict):
        # pick a middling resolution
        res = th.get("resolutions") or []
        if res:
            chosen = sorted(res, key=lambda r: r.get("width", 0))[len(res) // 2]
            thumb = chosen.get("url")
        thumb = thumb or th.get("url")

    related = src.get("relatedTickers") or []
    if not related and ticker:
        related = [ticker]

    return {
        "id": raw.get("id") or src.get("id") or src.get("uuid") or f"{ticker}-{ts}-{hash(title)}",
        "title": title,
        "publisher": pub or "",
        "link": link or "",
        "published_ts": ts,
        "thumbnail": thumb,
        "tickers": [t for t in related if isinstance(t, str)][:6],
    }


def _fetch_one(ticker: str) -> list[dict]:
    try:
        items = yf.Ticker(ticker).news or []
    except Exception:
        return []
    cutoff = time.time() - WINDOW_SEC
    out = []
    for raw in items:
        n = _normalize(raw, ticker)
        if n and n["published_ts"] >= cutoff:
            out.append(n)
    return out


def get_news() -> list[dict]:
    now = time.time()
    if now - _CACHE["ts"] < _TTL and _CACHE["items"]:
        return _CACHE["items"]

    with ThreadPoolExecutor(max_workers=6) as pool:
        chunks = pool.map(_fetch_one, HEADLINE_TICKERS)

    seen, merged = set(), []
    for chunk in chunks:
        for n in chunk:
            if n["id"] in seen:
                continue
            seen.add(n["id"])
            merged.append(n)
    merged.sort(key=lambda x: x["published_ts"], reverse=True)
    merged = merged[:80]
    _CACHE.update(ts=now, items=merged)
    return merged


if __name__ == "__main__":
    # ponytail self-check
    out = get_news()
    assert isinstance(out, list)
    print(f"items: {len(out)}")
    if out:
        n = out[0]
        assert n["title"] and n["published_ts"]
        print(n["title"][:80], "—", n["publisher"], time.strftime("%Y-%m-%d %H:%M", time.localtime(n["published_ts"])))
