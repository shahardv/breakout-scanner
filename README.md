# Breakout Scanner

A live S&P 500 / NASDAQ-100 momentum scanner with a trade-plan tracker, built as
an installable PWA (FastAPI + vanilla JS, data via yfinance).

## Features
- Real-time streaming scan (Server-Sent Events) across ~250 or the full ~550 large caps
- Technical confluence scoring: trend stack, RSI, MACD, volume, Bollinger squeeze, 52-week-high proximity, HH/HL
- Filters: score, upside %, R/R, index, price range, ticker search, sort
- **My Plans** tab: save trade plans (entry/stop/target), favorites, live status (In profit / Below entry / Target hit / Stop hit), 30s price polling — stored in localStorage
- Installable on iPhone via "Add to Home Screen"

## Run locally
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 server.py        # http://127.0.0.1:8000 (and your LAN IP for phones)
```

## Deploy to Render (free)
1. Push this repo to GitHub.
2. On [render.com](https://render.com): **New → Blueprint**, connect the repo. Render reads `render.yaml`.
3. Click **Apply**. First build takes a few minutes; you get a free `https://<name>.onrender.com` URL.
4. Open that URL in iPhone Safari → Share → **Add to Home Screen**.

> Note: Render's free tier sleeps after ~15 min idle, so the first scan after a quiet
> period cold-starts in ~30–50s. The HTTPS URL unlocks the service worker (offline shell).

## Disclaimer
Technical-analysis setups are probabilities, not guarantees. Always trade with a
predefined stop. This is an educational tool, not financial advice.
