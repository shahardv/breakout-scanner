"""
Universe loader.

Two universes are exposed to the rest of the app:
  - "top": the curated, fast list defined in tickers.py (~250 names)
  - "full": the full live S&P 500 + NASDAQ-100 constituent lists fetched
            from Wikipedia and cached on disk for 24 hours.

If the Wikipedia fetch fails for any reason (network, layout change, throttle),
we fall back to the curated list so the app keeps working.
"""

from __future__ import annotations

import json
import time
from io import StringIO
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from tickers import ALL_TICKERS as CURATED_ALL, SP500 as CURATED_SP, NASDAQ100 as CURATED_NDX

CACHE_FILE = Path(__file__).parent / ".universe_cache.json"
CACHE_TTL_SEC = 24 * 60 * 60  # 1 day
UA = {"User-Agent": "BreakoutScanner/1.0 (educational; +http://localhost)"}


def _normalize(sym: str) -> str:
    """Wikipedia uses 'BRK.B'; Yahoo Finance uses 'BRK-B'."""
    return sym.strip().upper().replace(".", "-")


def _fetch_sp500() -> list[str]:
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    tables = pd.read_html(StringIO(r.text))
    df = tables[0]  # first table is the constituent list
    syms = df["Symbol"].dropna().astype(str).tolist()
    return sorted({_normalize(s) for s in syms if s})


def _fetch_nasdaq100() -> list[str]:
    url = "https://en.wikipedia.org/wiki/Nasdaq-100"
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    tables = pd.read_html(StringIO(r.text))
    for t in tables:
        cols_lower = [str(c).lower() for c in t.columns]
        if "ticker" in cols_lower or "symbol" in cols_lower:
            col = "Ticker" if "Ticker" in t.columns else "Symbol"
            syms = t[col].dropna().astype(str).tolist()
            return sorted({_normalize(s) for s in syms if s})
    raise RuntimeError("Nasdaq-100 constituent table not found")


def _load_cache() -> Optional[dict]:
    if not CACHE_FILE.exists():
        return None
    try:
        data = json.loads(CACHE_FILE.read_text())
        if time.time() - data.get("ts", 0) < CACHE_TTL_SEC:
            return data
    except Exception:
        return None
    return None


def _save_cache(sp500: list[str], ndx: list[str]) -> None:
    try:
        CACHE_FILE.write_text(json.dumps({
            "ts": time.time(),
            "sp500": sp500,
            "nasdaq100": ndx,
        }))
    except OSError:
        pass  # cache is a nice-to-have


def get_full_universe(force_refresh: bool = False) -> dict:
    """
    Returns {"sp500": [...], "nasdaq100": [...], "all": [...], "source": "cache|live|fallback"}
    """
    if not force_refresh:
        cached = _load_cache()
        if cached:
            sp = cached["sp500"]
            ndx = cached["nasdaq100"]
            return {
                "sp500": sp, "nasdaq100": ndx,
                "all": sorted(set(sp) | set(ndx)),
                "source": "cache",
            }

    try:
        sp = _fetch_sp500()
        ndx = _fetch_nasdaq100()
        _save_cache(sp, ndx)
        return {
            "sp500": sp, "nasdaq100": ndx,
            "all": sorted(set(sp) | set(ndx)),
            "source": "live",
        }
    except Exception as e:
        print(f"[universe] Wikipedia fetch failed: {e}; using curated fallback")
        return {
            "sp500": sorted(CURATED_SP),
            "nasdaq100": sorted(CURATED_NDX),
            "all": list(CURATED_ALL),
            "source": "fallback",
        }


def get_universe(name: str) -> dict:
    """
    name in {"top", "full"}.
    Returns {"sp500": set, "nasdaq100": set, "all": list, "source": str}
    where the sets are used for index-membership tagging.
    """
    if name == "full":
        u = get_full_universe()
        return {
            "sp500": set(u["sp500"]),
            "nasdaq100": set(u["nasdaq100"]),
            "all": u["all"],
            "source": u["source"],
        }
    # default: curated top list
    return {
        "sp500": set(CURATED_SP),
        "nasdaq100": set(CURATED_NDX),
        "all": list(CURATED_ALL),
        "source": "curated",
    }
