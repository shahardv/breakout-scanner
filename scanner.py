"""
Breakout/momentum scanner.

For each ticker we pull ~6 months of daily candles and score it on a 0-100 scale
across confluence signals that historically precede continuation moves:

  - Proximity to 52-week high (close, but not exhausted)
  - Trend stack: price > 20MA > 50MA > 200MA
  - RSI in the strong-but-not-overbought zone (55-70)
  - MACD bullish (line > signal, histogram rising)
  - Volume confirmation (recent vol > 20d avg)
  - Bollinger squeeze release (low volatility -> expansion up)
  - Higher highs / higher lows over the last ~10 sessions

A ticker is reported as a candidate only if its score >= 60 AND it has at least
3 distinct bullish signals firing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf


# ---------- indicator helpers ----------

def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(close: pd.Series):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    line = ema12 - ema26
    signal = line.ewm(span=9, adjust=False).mean()
    hist = line - signal
    return line, signal, hist


def _bollinger(close: pd.Series, period: int = 20, mult: float = 2.0):
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = mid + mult * std
    lower = mid - mult * std
    width = (upper - lower) / mid
    return upper, mid, lower, width


# ---------- result type ----------

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
    signals: list  # list[str] - human-readable bullish signals
    details: dict  # raw indicator snapshot
    rationale: str  # paragraph explaining why this looks like a setup
    sparkline: list  # last ~60 closes for the mini chart
    indexes: list  # which index/indexes the ticker belongs to: ["sp500", "nasdaq100"]

    def to_dict(self):
        return asdict(self)


# ---------- core scan ----------

def analyze(ticker: str, sp500: set | None = None, nasdaq100: set | None = None) -> Optional[Candidate]:
    """Returns Candidate if the ticker passes the bullish-setup screen, else None.

    `sp500` and `nasdaq100` are membership sets used to tag the candidate so the
    frontend can filter by index. If omitted, the candidate is returned with no
    index tags (useful for ad-hoc analyses).
    """
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

    if df is None or df.empty or len(df) < 60:
        return None

    # yfinance can return a multiindex when multiple tickers are requested; normalise.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    volume = df["Volume"].astype(float)

    last_close = float(close.iloc[-1])
    prev_close = float(close.iloc[-2])
    if not math.isfinite(last_close) or last_close <= 0:
        return None
    change_pct = (last_close / prev_close - 1) * 100 if prev_close > 0 else 0.0

    # --- moving averages
    ma20 = close.rolling(20).mean().iloc[-1]
    ma50 = close.rolling(50).mean().iloc[-1]
    ma200_series = close.rolling(200).mean()
    ma200 = ma200_series.iloc[-1] if len(close) >= 200 else float("nan")

    # --- RSI
    rsi = _rsi(close).iloc[-1]

    # --- MACD
    macd_line, macd_signal, macd_hist = _macd(close)
    macd_now = float(macd_line.iloc[-1])
    sig_now = float(macd_signal.iloc[-1])
    hist_now = float(macd_hist.iloc[-1])
    hist_prev = float(macd_hist.iloc[-2])

    # --- Bollinger
    bb_u, bb_m, bb_l, bb_w = _bollinger(close)
    bb_width_now = float(bb_w.iloc[-1])
    bb_width_avg = float(bb_w.rolling(60).mean().iloc[-1]) if len(bb_w) >= 60 else float("nan")

    # --- 52w high proximity (use 252 sessions or as much as we have)
    lookback = min(252, len(close))
    rolling_high = float(high.iloc[-lookback:].max())
    pct_from_high = (last_close / rolling_high - 1) * 100  # negative = below high

    # --- volume confirmation
    vol_avg20 = float(volume.rolling(20).mean().iloc[-1])
    vol_recent = float(volume.iloc[-3:].mean())
    vol_ratio = vol_recent / vol_avg20 if vol_avg20 > 0 else 0.0

    # --- HH / HL pattern (last ~10 sessions split in halves)
    last10 = close.iloc[-10:]
    first_half = last10.iloc[:5]
    second_half = last10.iloc[5:]
    higher_highs = float(second_half.max()) > float(first_half.max())
    higher_lows = float(second_half.min()) > float(first_half.min())

    # --- ATR for stop/target sizing
    tr = pd.concat([
        (high - low),
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1])

    # ---------------- scoring ----------------
    score = 0
    signals: list[str] = []

    # 1. Proximity to 52-week high — sweet spot is within 1-6% of the high.
    if -6 <= pct_from_high <= -0.5:
        score += 22
        signals.append(f"Within {abs(pct_from_high):.1f}% of 52-week high — coiled near resistance")
    elif -10 < pct_from_high < -6:
        score += 10
        signals.append(f"{abs(pct_from_high):.1f}% off 52-week high — uptrend intact")
    elif pct_from_high >= -0.5:
        # already at/above the high — momentum buy zone but riskier
        score += 14
        signals.append("At/above 52-week high — breakout in progress")

    # 2. Trend stack
    if math.isfinite(ma20) and math.isfinite(ma50):
        if last_close > ma20 > ma50:
            score += 18
            signals.append("Bullish stack: price > 20MA > 50MA")
            if math.isfinite(ma200) and ma50 > ma200:
                score += 6
                signals.append("Long-term uptrend confirmed (50MA > 200MA)")

    # 3. RSI strong-but-not-overbought
    if math.isfinite(rsi):
        if 55 <= rsi <= 70:
            score += 14
            signals.append(f"RSI {rsi:.0f} — strong momentum, not overbought")
        elif 50 <= rsi < 55:
            score += 7
            signals.append(f"RSI {rsi:.0f} — momentum turning up")
        elif 70 < rsi <= 75:
            score += 4
            signals.append(f"RSI {rsi:.0f} — hot, watch for pullback")

    # 4. MACD bullish
    if math.isfinite(macd_now) and math.isfinite(sig_now):
        if macd_now > sig_now and hist_now > 0 and hist_now > hist_prev:
            score += 15
            signals.append("MACD bullish & expanding")
        elif macd_now > sig_now:
            score += 7
            signals.append("MACD above signal")

    # 5. Volume confirmation
    if vol_ratio >= 1.4:
        score += 12
        signals.append(f"Volume surge {vol_ratio:.2f}× the 20-day average")
    elif vol_ratio >= 1.1:
        score += 5
        signals.append(f"Volume above average ({vol_ratio:.2f}×)")

    # 6. Bollinger squeeze release (narrow band + price pushing upper)
    if math.isfinite(bb_width_now) and math.isfinite(bb_width_avg) and bb_width_avg > 0:
        if bb_width_now < bb_width_avg * 0.85 and last_close > float(bb_m.iloc[-1]):
            score += 8
            signals.append("Bollinger squeeze — volatility compression before expansion")

    # 7. Higher highs / higher lows
    if higher_highs and higher_lows:
        score += 8
        signals.append("Higher highs and higher lows — clean uptrend structure")
    elif higher_highs:
        score += 4

    # ---- gating ----
    if score < 60 or len(signals) < 3:
        return None

    # ---- targets / stops ----
    # Target: closer of (next round resistance via 52w high + ATR breakout extension)
    target_price = max(rolling_high + atr * 1.5, last_close + atr * 2.5)
    upside_pct = (target_price / last_close - 1) * 100

    # Stop: 1.5 ATR below entry, or below 20MA — whichever is tighter & below price
    stop_atr = last_close - atr * 1.5
    stop_ma = float(ma20) if math.isfinite(ma20) else stop_atr
    stop_loss = max(stop_atr, stop_ma) if stop_ma < last_close else stop_atr
    risk_pct = (1 - stop_loss / last_close) * 100
    reward_risk = upside_pct / risk_pct if risk_pct > 0 else 0.0

    rationale = _build_rationale(ticker, signals, last_close, target_price, stop_loss, reward_risk)

    sparkline = [round(float(x), 2) for x in close.iloc[-60:].tolist()]

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
            "rsi": round(float(rsi), 1) if math.isfinite(rsi) else None,
            "macd": round(macd_now, 3),
            "macd_signal": round(sig_now, 3),
            "ma20": round(float(ma20), 2) if math.isfinite(ma20) else None,
            "ma50": round(float(ma50), 2) if math.isfinite(ma50) else None,
            "ma200": round(float(ma200), 2) if math.isfinite(ma200) else None,
            "atr": round(atr, 2),
            "vol_ratio": round(vol_ratio, 2),
            "pct_from_52w_high": round(pct_from_high, 2),
            "52w_high": round(rolling_high, 2),
        },
        rationale=rationale,
        sparkline=sparkline,
        indexes=indexes,
    )


def _build_rationale(ticker, signals, price, target, stop, rr) -> str:
    bullets = " ".join(f"• {s}." for s in signals)
    return (
        f"{ticker} is showing a high-confluence bullish setup at ${price:.2f}. "
        f"{bullets} "
        f"Suggested target ${target:.2f}, protective stop ${stop:.2f}, "
        f"reward/risk ≈ {rr:.2f}×. "
        f"Trade plan: enter on strength above current price with the stop honoured on a daily close basis; "
        f"trail the stop to breakeven once the position is up ~½ ATR."
    )
