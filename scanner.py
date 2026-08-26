"""
Wyckoff Spring scanner.

Finds stocks that have just completed a Wyckoff Spring — a sharp shakeout
below a prior support shelf, followed by a reclaim of that support. This is
the "institutional absorption" phase before the markup, so we want to catch
tickers HERE, before the sharp rally that follows (as SPOT did in mid-2020,
running from ~150 to 240+ after the March spring low).

Detection:
  1. Identify the spring low = lowest low in the last 60 sessions.
  2. Define the pre-spring support shelf from the 30 sessions before that low.
  3. Require the spring pierced support by >=3% (real shakeout).
  4. Require current close is back above support (reclaimed).
  5. Require current close is still below range_top × 1.05 (not yet marked up).
  6. Require the spring is fresh (within the last 30 sessions).

Bonuses (higher score): deeper spring, high-volume spring bar, close to
support, volume calming after the spring, spring within the last 15 sessions.
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
    """Return a Candidate if the ticker just completed a Wyckoff spring, else None."""
    try:
        df = yf.download(
            ticker,
            period="9mo",
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
    if len(df) < 90:
        return None

    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    volume = df["Volume"].astype(float)

    last_close = float(close.iloc[-1])
    if not math.isfinite(last_close) or last_close <= 0:
        return None
    prev_close = float(close.iloc[-2])
    change_pct = (last_close / prev_close - 1) * 100 if prev_close > 0 else 0.0

    # --- Find the spring low: lowest low in the last 60 sessions ---
    lookback = 60
    recent_lows = low.iloc[-lookback:]
    spring_pos_in_window = int(recent_lows.values.argmin())
    spring_low = float(recent_lows.iloc[spring_pos_in_window])
    days_since_spring = (len(recent_lows) - 1) - spring_pos_in_window
    spring_abs_idx = len(df) - lookback + spring_pos_in_window

    # --- Pre-spring shelf: 30 sessions before the spring low ---
    pre_start = max(0, spring_abs_idx - 30)
    pre_end = spring_abs_idx
    if pre_end - pre_start < 10:
        return None
    pre_shelf_close = close.iloc[pre_start:pre_end]
    pre_shelf_high = high.iloc[pre_start:pre_end]

    # Support = the 20th-percentile close of the shelf (the low band that got tested)
    support = float(pre_shelf_close.quantile(0.20))
    # Range top = 90th-percentile high (target for the markup)
    range_top = float(pre_shelf_high.quantile(0.90))
    if support <= 0 or range_top <= support:
        return None

    # --- Spring depth: how far below support was the shakeout ---
    spring_depth = (support - spring_low) / support
    if spring_depth < 0.03:  # need at least a 3% piercing to count
        return None

    # --- Gates: reclaim + still in entry zone + spring is fresh ---
    reclaimed = last_close > support * 0.98
    still_in_range = last_close < range_top * 1.05
    if not reclaimed or not still_in_range or days_since_spring > 30:
        return None

    # --- Spring bar volume (institutional absorption on the wick) ---
    spring_vol = float(volume.iloc[spring_abs_idx])
    avg_vol_60 = float(volume.iloc[-60:].mean())
    spring_vol_ratio = spring_vol / avg_vol_60 if avg_vol_60 > 0 else 0.0

    # --- Volume calming after the spring? (absorption complete) ---
    post = volume.iloc[spring_abs_idx + 1:]
    post_vol_avg = float(post.mean()) if len(post) > 0 else spring_vol
    vol_calming = post_vol_avg < spring_vol * 0.8

    # --- ATR for stop sizing ---
    tr = pd.concat([
        (high - low),
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1])
    if not math.isfinite(atr) or atr <= 0:
        atr = last_close * 0.02

    # --- Scoring ---
    score = 40
    signals = [
        f"Spring: pierced support ${support:.2f} down to ${spring_low:.2f} "
        f"({spring_depth * 100:.1f}%) {days_since_spring}d ago",
        f"Reclaimed support: price ${last_close:.2f} back above ${support:.2f}",
    ]

    if spring_depth >= 0.05:
        score += 15
        signals.append(f"Deep spring ({spring_depth * 100:.1f}%) — strong shakeout")

    if spring_vol_ratio >= 1.5:
        score += 15
        signals.append(f"High volume on spring bar ({spring_vol_ratio:.1f}× avg) — institutional absorption")

    if days_since_spring <= 15:
        score += 15
        signals.append(f"Fresh spring ({days_since_spring}d ago) — early accumulation phase")

    if last_close < support * 1.05:
        score += 10
        signals.append("Price still near reclaimed support — ideal entry zone")

    if vol_calming:
        score += 5
        signals.append("Volume calming after the spring — absorption phase complete")

    score = int(min(100, score))

    # --- Targets / stops ---
    range_height = range_top - support
    target_price = range_top + range_height  # measured-move projection above the range
    upside_pct = (target_price / last_close - 1) * 100
    stop_loss = spring_low - atr * 0.5  # below the spring low
    risk_pct = (1 - stop_loss / last_close) * 100
    reward_risk = upside_pct / risk_pct if risk_pct > 0 else 0.0

    rationale = (
        f"{ticker} completed a Wyckoff spring {days_since_spring} days ago: "
        f"price pierced the ${support:.2f} support shelf down to ${spring_low:.2f} "
        f"({spring_depth * 100:.1f}% shakeout) and has since reclaimed the level. "
        f"Trading at ${last_close:.2f}, range top ${range_top:.2f}. "
        f"Measured-move target ${target_price:.2f}, stop ${stop_loss:.2f} "
        f"(below spring low), R/R ≈ {reward_risk:.2f}×. "
        f"Trade plan: accumulate near support; invalidation on a daily close below the spring low."
    )
    sparkline = [round(float(x), 2) for x in close.iloc[-90:].tolist()]

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
            "spring_low": round(spring_low, 2),
            "support": round(support, 2),
            "range_top": round(range_top, 2),
            "spring_depth_pct": round(spring_depth * 100, 2),
            "days_since_spring": days_since_spring,
            "spring_vol_ratio": round(spring_vol_ratio, 2),
            "vol_calming": vol_calming,
            "atr": round(atr, 2),
        },
        rationale=rationale,
        sparkline=sparkline,
        indexes=indexes,
    )


# ponytail: synthetic SPOT-like series (sideways → spring shakeout → reclaim)
if __name__ == "__main__":
    rng = np.random.default_rng(42)
    # 65 sideways bars at 150, 5-bar shakeout to 115, 20-bar recovery back to 148
    sideways = 150 + rng.normal(0, 3, 65)
    shakeout = np.array([148.0, 130.0, 115.0, 125.0, 135.0])
    recovery = np.linspace(137, 148, 20) + rng.normal(0, 1.0, 20)
    closes = np.concatenate([sideways, shakeout, recovery])
    highs = closes + 1.5
    lows = closes - 1.5
    lows[65 + 2] = 112.0  # deeper spring wick
    opens = closes - 0.2
    vols = np.concatenate([
        rng.integers(2_000_000, 3_000_000, 65),
        np.array([6_000_000, 9_000_000, 14_000_000, 8_000_000, 5_000_000]),
        rng.integers(1_500_000, 2_500_000, 20),  # calming
    ])
    idx = pd.date_range("2020-01-01", periods=len(closes), freq="B")
    fake = pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": vols},
        index=idx,
    )

    def fake_download(*_a, **_kw):
        return fake

    yf.download = fake_download  # type: ignore
    result = analyze("TEST")
    assert result is not None, "SPOT-like spring should be detected"
    d = result.details
    assert d["spring_depth_pct"] >= 3.0, d
    assert d["days_since_spring"] <= 30, d
    print(f"OK  score={result.score}  spring_low={d['spring_low']}  "
          f"support={d['support']}  depth={d['spring_depth_pct']}%  "
          f"days_ago={d['days_since_spring']}  vol_ratio={d['spring_vol_ratio']}")
