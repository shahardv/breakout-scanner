"""FastAPI server. Streams scan results live via Server-Sent Events."""

from __future__ import annotations

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from scanner import analyze
from universe import get_universe
from quotes import get_quotes

ROOT = Path(__file__).parent
app = FastAPI(title="Breakout Scanner")


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/sw.js")
def service_worker():
    # Served from root (not /static) so its scope covers the whole app.
    # Service-Worker-Allowed lets it claim "/" even though the file lives in static.
    return FileResponse(
        ROOT / "static" / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(
        ROOT / "static" / "manifest.webmanifest",
        media_type="application/manifest+json",
    )


# Mount static dir AFTER the / route so root still serves index.html
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _run_scan(universe_name: str):
    """Generator that yields SSE messages as candidates are found."""
    started_at = time.time()

    loop = asyncio.get_running_loop()

    # Resolving the "full" universe makes blocking HTTP calls to Wikipedia, so
    # run it in a thread — otherwise we'd freeze the event loop and the SSE
    # response would never start streaming.
    universe = await loop.run_in_executor(None, get_universe, universe_name)
    tickers_list = universe["all"]
    sp500_set = universe["sp500"]
    ndx_set = universe["nasdaq100"]
    total = len(tickers_list)

    yield _sse("start", {
        "total": total,
        "tickers": tickers_list,
        "universe": universe_name,
        "source": universe["source"],
    })

    async def _analyze_one(ticker: str):
        try:
            res = await loop.run_in_executor(pool, analyze, ticker, sp500_set, ndx_set)
            return ticker, res, None
        except Exception as e:
            return ticker, None, str(e)

    # Conservative pool: yfinance hits Yahoo's HTTP API; too many parallel
    # requests get throttled. 8 workers is a good balance.
    with ThreadPoolExecutor(max_workers=8) as pool:
        tasks = [asyncio.create_task(_analyze_one(t)) for t in tickers_list]
        scanned = 0
        found = 0
        for coro in asyncio.as_completed(tasks):
            ticker, result, err = await coro
            scanned += 1

            if err is not None:
                yield _sse("progress", {
                    "ticker": ticker, "scanned": scanned, "total": total,
                    "found": found, "error": err,
                })
                continue

            if result is not None:
                found += 1
                yield _sse("candidate", result.to_dict())

            yield _sse("progress", {
                "ticker": ticker, "scanned": scanned, "total": total, "found": found,
            })
            await asyncio.sleep(0)

    yield _sse("done", {
        "scanned": scanned,
        "found": found,
        "elapsed_sec": round(time.time() - started_at, 1),
    })


@app.get("/api/scan")
async def scan(universe: str = Query("top", pattern="^(top|full)$")):
    return StreamingResponse(
        _run_scan(universe),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/quote")
async def quote(tickers: str = Query(..., description="Comma-separated tickers")):
    """Live prices for the trade-plan tab. e.g. /api/quote?tickers=AAPL,MSFT"""
    symbols = [t for t in tickers.split(",") if t.strip()]
    loop = asyncio.get_running_loop()
    # get_quotes does blocking HTTP, so run it off the event loop.
    data = await loop.run_in_executor(None, get_quotes, symbols)
    return {"quotes": data, "ts": time.time()}


if __name__ == "__main__":
    import os
    import socket
    import uvicorn

    # Hosts like Render/Railway inject the port via the PORT env var.
    # Locally it defaults to 8000.
    port = int(os.environ.get("PORT", "8000"))

    # Bind to 0.0.0.0 so other devices on the same Wi-Fi (e.g. your iPhone)
    # can reach the app at http://<this-mac-LAN-IP>:<port>
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
    except Exception:
        lan_ip = "127.0.0.1"

    if not os.environ.get("PORT"):  # only show the LAN banner for local runs
        print("\n" + "=" * 54)
        print("  Breakout Scanner is running")
        print(f"  On this Mac:        http://127.0.0.1:{port}")
        print(f"  On your iPhone:     http://{lan_ip}:{port}   (same Wi-Fi)")
        print("=" * 54 + "\n")

    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
