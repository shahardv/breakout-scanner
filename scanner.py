"""
Volume-surge scanner.

Finds stocks where the last 3 days of trading volume are massively above the
recent baseline — the fingerprint of institutional accumulation or a sudden
news/catalyst move. We rank by the ratio of 3-day-average volume to 20-day-
average volume; direction (bullish vs distribution) is reported but not gated.

Gate: 3-day average volume >= 2× the 20-day average volume.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf


@dataclass
class Candidate:
    ticker: str
    score: int
    price: float
    change_pct: float
    target_price: float
    upside_pct: float
    stop_loss: float
    risk_pct: float
    reward_risk: float
    signals: list
    details: dict
    rationale: str
    sparkline: list
    indexes: list

    def to_dict(self):
        return asdict(self)


def analyze(ticker: str, sp500: set | None = None, nasdaq100: set | None = None) -> Optional[Candidate]:
    """Return a Candidate if the ticker shows a 3-day volume surge, else None."""
    try:
        df = yf.download(
            ticker,
            period="6mo",
            interval="1d",
            progress=False,
            auto_adjust=True,
            threads=False,
        )
    except Exception:
        return None

    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.dropna(subset=["Close"])
    if len(df) < 30:
        return None

    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    open_ = df["Open"].astype(float)
    volume = df["Volume"].astype(float)

    last_close = float(close.iloc[-1])
    if not math.isfinite(last_close) or last_close <= 0:
        return None
    prev_close = float(close.iloc[-2])
    change_pct = (last_close / prev_close - 1) * 100 if prev_close > 0 else 0.0

    # ---- volume surge ----
    # Baseline is the 50 days BEFORE the surge window — long enough that a
    # multi-day ramp doesn't contaminate the baseline (a 20-day baseline
    # gets inflated once the surge is a few days in, hiding continuation
    # moves like a stock that's been running for a week).
    vol_recent3 = float(volume.iloc[-3:].mean())
    baseline_slice = volume.iloc[-53:-3] if len(volume) >= 53 else volume.iloc[:-3]
    vol_baseline = float(baseline_slice.mean())
    if vol_baseline <= 0 or not math.isfinite(vol_recent3):
        return None
    vol_ratio = vol_recent3 / vol_baseline

    # ---- direction of the surge ----
    net_change_pct = (float(close.iloc[-1]) / float(close.iloc[-4]) - 1) * 100 \
        if len(close) >= 4 and float(close.iloc[-4]) > 0 else 0.0
    body_sum = float((close.iloc[-3:] - open_.iloc[-3:]).sum())
    bullish = body_sum > 0 and net_change_pct >= 0

    # Gate: either a clear volume surge, OR a strong price move on
    # above-baseline volume (catches continuation moves like GM where
    # volume has been elevated for a week so the ratio compresses, but
    # price is clearly moving).
    strong_move = abs(net_change_pct) >= 5.0 and vol_ratio >= 1.15
    if vol_ratio < 1.5 and not strong_move:
        return None

    # ---- freshness: is this the biggest 3-day surge in the last 60 days? ----
    vol_3d_series = volume.rolling(3).mean()
    lookback = min(60, len(vol_3d_series) - 3)
    recent_max = float(vol_3d_series.iloc[-lookback:-3].max()) if lookback > 0 else 0.0
    is_new_high = vol_recent3 > recent_max if recent_max > 0 else False

    # ---- ATR for stop/target sizing ----
    tr = pd.concat([
        (high - low),
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1])
    if not math.isfinite(atr) or atr <= 0:
        atr = last_close * 0.02  # 2% fallback

    # ---- scoring: bigger ratio = higher score ----
    # 1.5× → 52, 2× → 60, 3× → 75, 5× → 100
    score = int(min(100, 30 + vol_ratio * 15))
    signals = [f"3-day avg volume is {vol_ratio:.2f}× the prior 50-day baseline"]

    if bullish:
        signals.append(f"Bullish surge: price up {net_change_pct:+.2f}% over the 3 days")
    else:
        signals.append(f"Distribution: price {net_change_pct:+.2f}% over the 3 days")
        score -= 10  # de-emphasize distribution (still shown)

    if is_new_high:
        score += 5
        signals.append("Highest 3-day volume in the last 60 sessions")

    score = int(max(0, min(100, score)))

    # ---- targets / stops (bullish framing) ----
    target_price = last_close + atr * 3.0
    upside_pct = (target_price / last_close - 1) * 100
    stop_loss = last_close - atr * 1.5
    risk_pct = (1 - stop_loss / last_close) * 100
    reward_risk = upside_pct / risk_pct if risk_pct > 0 else 0.0

    rationale = (
        f"{ticker} traded {vol_ratio:.2f}× its 50-day baseline volume over the last 3 sessions, "
        f"with price moving {net_change_pct:+.2f}%. "
        f"{'Bullish accumulation' if bullish else 'Heavy distribution'} signature. "
        f"ATR-based target ${target_price:.2f}, stop ${stop_loss:.2f}, R/R ≈ {reward_risk:.2f}×."
    )
    sparkline = [round(float(x), 2) for x in close.iloc[-60:].tolist()]

    indexes = []
    if sp500 and ticker in sp500:
        indexes.append("sp500")
    if nasdaq100 and ticker in nasdaq100:
        indexes.append("nasdaq100")

    return Candidate(
        ticker=ticker,
        score=score,
        price=round(last_close, 2),
        change_pct=round(change_pct, 2),
        target_price=round(target_price, 2),
        upside_pct=round(upside_pct, 2),
        stop_loss=round(stop_loss, 2),
        risk_pct=round(risk_pct, 2),
        reward_risk=round(reward_risk, 2),
        signals=signals,
        details={
            "vol_ratio_3d_vs_baseline": round(vol_ratio, 2),
            "vol_recent_3d_avg": int(vol_recent3),
            "vol_baseline_50d_avg": int(vol_baseline),
            "net_change_3d_pct": round(net_change_pct, 2),
            "bullish": bullish,
            "new_60d_vol_high": is_new_high,
            "atr": round(atr, 2),
        },
        rationale=rationale,
        sparkline=sparkline,
        indexes=indexes,
    )


# ponytail: quick self-check on a synthetic volume-surge series
if __name__ == "__main__":
    rng = np.random.default_rng(42)
    n = 60
    closes = np.linspace(100, 110, n) + rng.normal(0, 0.5, n)
    highs = closes + 0.6
    lows = closes - 0.6
    opens = closes - 0.1
    vols = rng.integers(1_000_000, 1_500_000, n).astype(float)
    vols[-3:] = [4_500_000, 5_000_000, 4_800_000]
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    fake = pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": vols},
        index=idx,
    )

    def fake_download(*_a, **_kw):
        return fake

    yf.download = fake_download  # type: ignore
    result = analyze("TEST")
    assert result is not None, "3× volume surge should be detected"
    assert result.details["vol_ratio_3d_vs_baseline"] >= 3.0, result.details
    assert result.details["bullish"], "up-trending series should score as bullish"
    print(f"OK  score={result.score}  ratio={result.details['vol_ratio_3d_vs_baseline']}  "
          f"bullish={result.details['bullish']}  new_high={result.details['new_60d_vol_high']}")
