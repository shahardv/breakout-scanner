"""
Wyckoff accumulation scanner.

Finds stocks currently sitting in the "institutional buying zone" of a Wyckoff
accumulation schematic (Phase C / Phase D):

  Phase A — prior downtrend stops (PS, SC, AR, ST) → CHoCH IN
  Phase B — trading range, cause is built (sideways, ST in Phase B)
  Phase C — last shakeout: Spring below support, then reclaim (or LPS w/o spring)
  Phase D — CHoCH OUT: sharp move within the range, SOS, BU/LPS
  Phase E — sustained move above the range

Heuristics we score:
  1. Prior decline: current base sits well below the 52-week high (Phase A happened).
  2. Flat trading range: middle of the base has near-zero slope, contained width.
  3. Selling climax in Phase A: high-volume down bar early in the base.
  4. Spring: recent low pierced range support then closed back inside.
  5. Sign of Strength / CHoCH OUT: recent close above range resistance on volume.
  6. LPS: currently near support with an up-turning short-term trend.
  7. Volume dry-up in mid-base vs recent expansion on the rally.

A ticker is reported only if at least one of {Spring, SOS, LPS} is firing —
i.e. it is actually in the actionable Phase C or D — and total score >= 55.
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
    """Return a Candidate if the ticker is in Phase C or D of a Wyckoff accumulation, else None."""
    try:
        df = yf.download(
            ticker,
            period="1y",
            interval="1d",
            progress=False,
            auto_adjust=True,
            threads=False,
        )
    except Exception:
        return None

    if df is None or df.empty or len(df) < 120:
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

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

    # ---- define the candidate base window (Phase B territory) ----
    base_days = min(120, len(close) - 1)
    base_close = close.iloc[-base_days:]
    base_high = high.iloc[-base_days:]
    base_low = low.iloc[-base_days:]
    base_vol = volume.iloc[-base_days:]

    # Support = 10th percentile of daily lows, resistance = 90th percentile of highs.
    # Quantiles are robust to a single wick (the Spring) — that's the point.
    support = float(base_low.quantile(0.10))
    resistance = float(base_high.quantile(0.90))
    if support <= 0 or resistance <= support:
        return None
    range_width = (resistance - support) / support

    # Prior decline: how far below 52w high is the top of our base?
    year_high = float(high.max())
    decline_pct = (year_high - resistance) / year_high if year_high > 0 else 0.0

    # Flatness: slope of 20-day MA across the middle of the base
    ma20 = close.rolling(20).mean()
    mid_ma = ma20.iloc[-base_days + 20:-20].dropna()
    if len(mid_ma) < 20:
        return None
    slope_pct = (mid_ma.iloc[-1] - mid_ma.iloc[0]) / mid_ma.iloc[0]

    # Selling climax: max down-day volume in first third of the base
    first_third = df.iloc[-base_days:-2 * base_days // 3]
    base_avg_vol = float(base_vol.mean())
    sc_vol_ratio = 0.0
    if base_avg_vol > 0 and not first_third.empty:
        down = first_third[first_third["Close"] < first_third["Open"]]
        if not down.empty:
            sc_vol_ratio = float(down["Volume"].max()) / base_avg_vol

    # Spring: in last 20 sessions, a low pierced support but closed back above it
    last20 = df.iloc[-20:]
    spring_detected = False
    for _, row in last20.iterrows():
        if row["Low"] < support * 0.99 and row["Close"] > support:
            spring_detected = True
            break

    # Sign of Strength / CHoCH OUT: last ~10 days closed above resistance on volume
    vol_avg20 = float(volume.rolling(20).mean().iloc[-1])
    last10 = df.iloc[-10:]
    sos_detected = False
    if vol_avg20 > 0:
        for _, row in last10.iterrows():
            if row["Close"] > resistance and row["Volume"] > vol_avg20 * 1.3:
                sos_detected = True
                break

    # LPS: currently near support (within 5%) and 5-day trend up
    last5 = close.iloc[-5:]
    lps_zone = last_close <= support * 1.05 and float(last5.iloc[-1]) > float(last5.iloc[0])

    # Volume dry-up (mid base) → expansion (recent)
    third = base_days // 3
    mid_vol = float(base_vol.iloc[third:2 * third].mean())
    recent_vol = float(volume.iloc[-5:].mean())
    vol_expansion = (recent_vol / mid_vol) if mid_vol > 0 else 0.0

    # ATR for stop / target sizing
    tr = pd.concat([
        (high - low),
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1])

    # ---------------- scoring ----------------
    score = 0
    signals: list[str] = []

    # 1. Prior decline (Phase A happened)
    if decline_pct >= 0.20:
        score += 15
        signals.append(f"Prior downtrend: base sits {decline_pct * 100:.0f}% below 52-week high")
    elif decline_pct >= 0.10:
        score += 8
        signals.append(f"Corrective decline: {decline_pct * 100:.0f}% off 52-week high")
    else:
        return None  # no meaningful prior decline → not an accumulation

    # 2. Flat trading range (Phase B built)
    if abs(slope_pct) < 0.05 and range_width < 0.25:
        score += 20
        signals.append(f"Flat trading range ({range_width * 100:.0f}% wide) — cause being built")
    elif abs(slope_pct) < 0.10 and range_width < 0.35:
        score += 10
        signals.append(f"Consolidation range ({range_width * 100:.0f}% wide)")
    else:
        return None  # no discernible range → not accumulation

    # 3. Selling climax in Phase A
    if sc_vol_ratio >= 1.8:
        score += 10
        signals.append(f"Selling climax detected ({sc_vol_ratio:.1f}× base-avg volume)")

    # 4. Spring — Phase C confirmed
    if spring_detected:
        score += 20
        signals.append("Spring: shakeout below support, reclaimed — Phase C confirmed")

    # 5. Sign of Strength / CHoCH OUT — Phase D
    if sos_detected:
        score += 25
        signals.append("CHoCH OUT: break above resistance on volume — Phase D")

    # 6. LPS — currently at institutional buy zone
    if lps_zone:
        score += 15
        signals.append(f"At Last Point of Support (~${support:.2f}) — institutional buy zone")

    # 7. Volume expansion vs mid-base dry-up
    if vol_expansion >= 1.5:
        score += 10
        signals.append(f"Volume expansion {vol_expansion:.1f}× the mid-base dry-up")

    # ---- gating: must be actionable (in Phase C or D) ----
    if not (spring_detected or sos_detected or lps_zone):
        return None
    if score < 55 or len(signals) < 3:
        return None

    # ---- targets / stops ----
    # Wyckoff measured move: range height projected above resistance = Phase E target
    range_height = resistance - support
    target_price = resistance + range_height
    upside_pct = (target_price / last_close - 1) * 100

    # Stop: 1 ATR below support (below the Spring low); tighten if already trading above
    stop_loss = support - atr
    if stop_loss >= last_close:
        stop_loss = last_close - atr * 1.5
    risk_pct = (1 - stop_loss / last_close) * 100
    reward_risk = upside_pct / risk_pct if risk_pct > 0 else 0.0

    rationale = _build_rationale(
        ticker, signals, last_close, target_price, stop_loss, reward_risk, support, resistance
    )
    sparkline = [round(float(x), 2) for x in close.iloc[-90:].tolist()]

    indexes = []
    if sp500 and ticker in sp500:
        indexes.append("sp500")
    if nasdaq100 and ticker in nasdaq100:
        indexes.append("nasdaq100")

    return Candidate(
        ticker=ticker,
        score=int(min(100, score)),
        price=round(last_close, 2),
        change_pct=round(change_pct, 2),
        target_price=round(target_price, 2),
        upside_pct=round(upside_pct, 2),
        stop_loss=round(stop_loss, 2),
        risk_pct=round(risk_pct, 2),
        reward_risk=round(reward_risk, 2),
        signals=signals,
        details={
            "support": round(support, 2),
            "resistance": round(resistance, 2),
            "range_width_pct": round(range_width * 100, 1),
            "decline_from_52w_high_pct": round(decline_pct * 100, 1),
            "base_slope_pct": round(slope_pct * 100, 1),
            "spring": spring_detected,
            "sos": sos_detected,
            "lps_zone": lps_zone,
            "sc_vol_ratio": round(sc_vol_ratio, 2),
            "vol_expansion": round(vol_expansion, 2),
            "atr": round(atr, 2),
        },
        rationale=rationale,
        sparkline=sparkline,
        indexes=indexes,
    )


def _build_rationale(ticker, signals, price, target, stop, rr, support, resistance) -> str:
    bullets = " ".join(f"• {s}." for s in signals)
    return (
        f"{ticker} is showing a Wyckoff accumulation setup at ${price:.2f}, "
        f"inside a trading range between ${support:.2f} (support) and ${resistance:.2f} (resistance). "
        f"{bullets} "
        f"Measured-move target ${target:.2f}, stop ${stop:.2f}, R/R ≈ {rr:.2f}×. "
        f"Trade plan: accumulate near support (LPS) or on the CHoCH-out breakout above resistance; "
        f"invalidation on a daily close below ${stop:.2f}."
    )


# ponytail: self-check — runs a synthetic Wyckoff-shaped series through analyze()
# to verify the phase detector still fires. Not a full test suite, just a canary.
if __name__ == "__main__":
    import types

    # Build a synthetic OHLCV that walks A → B → C → D:
    #   130 down bars (mostly out of the 120-day base window) →
    #   109 flat range bars → 1 spring bar → 10 up bars breaking out
    rng = np.random.default_rng(42)
    n_down, n_flat, n_up = 130, 109, 10
    down = np.linspace(100, 72, n_down) + rng.normal(0, 0.5, n_down)
    flat = 72 + rng.normal(0, 1.2, n_flat)  # range roughly 70-74
    spring_bar = np.array([68.5])           # pierces support
    up = np.linspace(73, 82, n_up) + rng.normal(0, 0.3, n_up)  # breaks resistance
    closes = np.concatenate([down, flat, spring_bar, up])
    highs = closes + 0.6
    lows = closes - 0.6
    lows[n_down + n_flat] = 67.0  # make the spring bar wick clearly below support
    opens = closes - 0.1
    vols = np.concatenate([
        rng.integers(1_000_000, 2_000_000, n_down - 5),
        rng.integers(4_000_000, 6_000_000, 5),   # selling climax cluster near end of decline
        rng.integers(500_000, 1_200_000, n_flat),  # dry-up in Phase B
        np.array([3_500_000]),                   # spring volume
        rng.integers(3_000_000, 5_000_000, n_up),  # expansion into Phase D
    ])
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="B")
    fake = pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": vols},
        index=idx,
    )

    def fake_download(*_a, **_kw):
        return fake

    yf.download = fake_download  # type: ignore
    result = analyze("TEST")
    assert result is not None, "synthetic Wyckoff series should be detected"
    assert result.details["spring"] or result.details["sos"] or result.details["lps_zone"], (
        "must fire at least one Phase C/D signal"
    )
    assert result.score >= 55, f"score too low: {result.score}"
    print(f"OK  score={result.score}  signals={len(result.signals)}  "
          f"spring={result.details['spring']}  sos={result.details['sos']}  "
          f"lps={result.details['lps_zone']}")
