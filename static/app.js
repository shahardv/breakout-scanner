(() => {
  const $ = (id) => document.getElementById(id);

  const scanBtn = $("scan-btn");
  const refreshPricesBtn = $("refresh-prices-btn");
  const cardsEl = $("cards");
  const emptyEl = $("empty-state");
  const fillEl = $("progress-fill");
  const metaEl = $("progress-meta");
  const statScanned = $("stat-scanned");
  const statFound = $("stat-found");
  const statElapsed = $("stat-elapsed");
  const filtersMeta = $("filters-meta");
  const tpl = $("card-tpl");

  // Filter inputs
  const fSearch = $("f-search");
  const fSort = $("f-sort");
  const fScore = $("f-score");
  const fScoreVal = $("f-score-val");
  const fUpside = $("f-upside");
  const fUpsideVal = $("f-upside-val");
  const fRR = $("f-rr");
  const fRRVal = $("f-rr-val");
  const fPmin = $("f-pmin");
  const fPmax = $("f-pmax");
  const fReset = $("f-reset");
  const fIndex = $("f-index");
  const fUniverse = $("f-universe");

  let es = null;
  let elapsedTimer = null;
  let startedAt = 0;

  // Candidate store keyed by ticker so we always re-render from one source of truth.
  const candidates = new Map();

  // Filter state
  const filters = {
    search: "",
    index: "all", // "all" | "sp500" | "nasdaq100"
    sort: "score",
    minScore: 60,
    minUpside: 0,
    minRR: 0,
    minPrice: null,
    maxPrice: null,
  };

  // Scan universe (sent to /api/scan as a query param)
  let universe = "top";  // "top" | "full"

  // ----- formatting -----
  const fmtMoney = (v) =>
    v == null
      ? "—"
      : new Intl.NumberFormat("en-US", {
          style: "currency",
          currency: "USD",
          maximumFractionDigits: 2,
        }).format(v);

  const fmtPct = (v, withSign = true) => {
    if (v == null || Number.isNaN(v)) return "—";
    const sign = withSign && v > 0 ? "+" : "";
    return `${sign}${v.toFixed(2)}%`;
  };

  // ----- sparkline -----
  function buildSpark(svg, points) {
    if (!points || points.length < 2) return;
    const W = 240, H = 60, pad = 4;
    const min = Math.min(...points);
    const max = Math.max(...points);
    const range = Math.max(1e-9, max - min);
    const stepX = (W - pad * 2) / (points.length - 1);
    const xy = points.map((p, i) => [
      pad + i * stepX,
      pad + (H - pad * 2) * (1 - (p - min) / range),
    ]);
    const line = xy
      .map(([x, y], i) => (i === 0 ? `M${x.toFixed(1)},${y.toFixed(1)}` : `L${x.toFixed(1)},${y.toFixed(1)}`))
      .join(" ");
    const fill = `${line} L${(pad + (points.length - 1) * stepX).toFixed(1)},${H - pad} L${pad},${H - pad} Z`;
    svg.querySelector(".spark-line").setAttribute("d", line);
    svg.querySelector(".spark-fill").setAttribute("d", fill);

    const up = points[points.length - 1] >= points[0];
    const stroke = up ? "#6ee7b7" : "#fbbf24";
    const fillC = up ? "rgba(110,231,183,0.12)" : "rgba(251,191,36,0.10)";
    svg.querySelector(".spark-line").setAttribute("stroke", stroke);
    svg.querySelector(".spark-fill").setAttribute("fill", fillC);
  }

  // ----- card render -----
  function renderCandidate(c) {
    const node = tpl.content.firstElementChild.cloneNode(true);
    node.dataset.ticker = c.ticker;
    node.dataset.score = c.score;

    node.querySelector(".ticker").textContent = c.ticker;
    const indexLabel = (c.indexes || []).map((i) =>
      i === "sp500" ? "S&P 500" : i === "nasdaq100" ? "NASDAQ-100" : i
    ).join(" · ") || "Bullish setup";
    node.querySelector(".company").textContent = indexLabel;

    const ring = node.querySelector(".score-fg");
    ring.setAttribute("stroke-dasharray", `${c.score},100`);
    // Richer 5-tier color spectrum; also tags the card so CSS can add a
    // matching glow + accent stripe.
    let tier, color;
    if (c.score >= 90) { tier = "elite"; color = "#2dd4bf"; }
    else if (c.score >= 80) { tier = "strong"; color = "#6ee7b7"; }
    else if (c.score >= 72) { tier = "good"; color = "#22d3ee"; }
    else if (c.score >= 66) { tier = "fair"; color = "#60a5fa"; }
    else { tier = "watch"; color = "#a78bfa"; }
    ring.setAttribute("stroke", color);
    node.dataset.tier = tier;
    node.style.setProperty("--tier-color", color);
    node.querySelector(".score-num").textContent = c.score;

    node.querySelector(".price").textContent = fmtMoney(c.price);
    const ch = node.querySelector(".change");
    ch.textContent = fmtPct(c.change_pct);
    ch.classList.add(c.change_pct >= 0 ? "up" : "down");

    buildSpark(node.querySelector(".spark"), c.sparkline);

    node.querySelector(".val.target").textContent = fmtMoney(c.target_price);
    node.querySelector(".val.stop").textContent = fmtMoney(c.stop_loss);
    node.querySelector(".val.upside").textContent = fmtPct(c.upside_pct);
    node.querySelector(".val.risk").textContent = fmtPct(-c.risk_pct);
    node.querySelector(".val.rr").textContent =
      c.reward_risk ? `${c.reward_risk.toFixed(2)}×` : "—";
    node.querySelector(".val.rsi").textContent =
      c.details?.rsi != null ? c.details.rsi.toFixed(1) : "—";

    const sigsEl = node.querySelector(".signals");
    c.signals.forEach((s, i) => {
      const span = document.createElement("span");
      // Cycle chips through 6 hues so the signal stack reads as a colorful set.
      span.className = `chip chip-${i % 6}`;
      span.textContent = s;
      sigsEl.appendChild(span);
    });

    node.querySelector(".rationale").textContent = c.rationale;

    // "+ Create plan from this" — hand the setup to the Plans tab pre-filled.
    const planBtn = node.querySelector(".plan-from-scan");
    if (planBtn) {
      planBtn.addEventListener("click", () => {
        if (window.StockPlans && typeof window.StockPlans.prefillFromScan === "function") {
          window.StockPlans.prefillFromScan({
            ticker: c.ticker,
            entry: c.price,
            stop: c.stop_loss,
            target: c.target_price,
            note: `From scan · score ${c.score}`,
          });
        }
      });
    }

    return node;
  }

  function passesFilters(c) {
    if (c.score < filters.minScore) return false;
    if (c.upside_pct < filters.minUpside) return false;
    if ((c.reward_risk || 0) < filters.minRR) return false;
    if (filters.index !== "all" && !(c.indexes || []).includes(filters.index)) return false;
    if (filters.search && !c.ticker.toLowerCase().includes(filters.search)) return false;
    if (filters.minPrice != null && c.price < filters.minPrice) return false;
    if (filters.maxPrice != null && c.price > filters.maxPrice) return false;
    return true;
  }

  function sortKey(c) {
    switch (filters.sort) {
      case "upside": return -c.upside_pct;
      case "rr": return -(c.reward_risk || 0);
      case "change": return -c.change_pct;
      case "ticker": return c.ticker;
      case "score":
      default:
        // Score desc, then upside desc as a tiebreaker.
        return [-c.score, -c.upside_pct];
    }
  }

  function compare(a, b) {
    const ka = sortKey(a), kb = sortKey(b);
    if (Array.isArray(ka)) {
      for (let i = 0; i < ka.length; i++) {
        if (ka[i] < kb[i]) return -1;
        if (ka[i] > kb[i]) return 1;
      }
      return 0;
    }
    if (ka < kb) return -1;
    if (ka > kb) return 1;
    return 0;
  }

  // Full re-render: cheap because we only have a few dozen cards at most,
  // and it sidesteps any incremental-sort bugs as filters change.
  function rerender() {
    const all = Array.from(candidates.values());
    const visible = all.filter(passesFilters).sort(compare);

    cardsEl.innerHTML = "";
    visible.forEach((c) => cardsEl.appendChild(renderCandidate(c)));

    filtersMeta.textContent =
      `Showing ${visible.length} of ${all.length} setup${all.length === 1 ? "" : "s"}`;

    statFound.textContent = String(all.length);

    if (all.length === 0 && !es) {
      emptyEl.style.display = "block";
    } else {
      emptyEl.style.display = "none";
    }

    // Enable the price-refresh button only when a scan isn't running and we
    // have found setups to refresh.
    refreshPricesBtn.disabled = !!es || all.length === 0;
  }

  function setRunning(running) {
    scanBtn.disabled = running;
    scanBtn.textContent = running ? "Scanning…" : "Start scan";
    // No refreshing mid-scan; rerender() re-enables it once a scan completes.
    if (running) refreshPricesBtn.disabled = true;
  }

  // Update live prices on already-found candidates without re-running the TA
  // scan. Recomputes upside / risk / R:R against the fresh price so each card
  // stays internally consistent.
  async function refreshScanPrices() {
    const tickers = Array.from(candidates.keys());
    if (tickers.length === 0 || es) return;

    refreshPricesBtn.disabled = true;
    const original = refreshPricesBtn.textContent;
    refreshPricesBtn.textContent = "Refreshing…";
    try {
      const res = await fetch(`/api/quote?tickers=${encodeURIComponent(tickers.join(","))}`);
      const data = await res.json();
      const q = data.quotes || {};
      let updated = 0;
      candidates.forEach((c, t) => {
        const quote = q[t];
        if (quote && quote.price != null) {
          c.price = quote.price;
          if (quote.change_pct != null) c.change_pct = quote.change_pct;
          // Recompute the derived trade metrics against the new price.
          if (c.target_price) c.upside_pct = +((c.target_price / c.price - 1) * 100).toFixed(2);
          if (c.stop_loss) c.risk_pct = +((1 - c.stop_loss / c.price) * 100).toFixed(2);
          c.reward_risk = c.risk_pct > 0 ? +(c.upside_pct / c.risk_pct).toFixed(2) : 0;
          updated++;
        }
      });
      rerender();
      const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      metaEl.textContent = `Prices refreshed at ${time} — ${updated} setup${updated === 1 ? "" : "s"} updated.`;
    } catch (e) {
      metaEl.textContent = "Price refresh failed — try again.";
    } finally {
      refreshPricesBtn.textContent = original;
      refreshPricesBtn.disabled = candidates.size === 0 || !!es;
    }
  }

  function startElapsedTimer() {
    startedAt = performance.now();
    if (elapsedTimer) clearInterval(elapsedTimer);
    elapsedTimer = setInterval(() => {
      const s = (performance.now() - startedAt) / 1000;
      statElapsed.textContent = `${s.toFixed(1)}s`;
    }, 100);
  }

  function stopElapsedTimer() {
    if (elapsedTimer) {
      clearInterval(elapsedTimer);
      elapsedTimer = null;
    }
  }

  function startScan() {
    if (es) es.close();
    candidates.clear();
    cardsEl.innerHTML = "";
    emptyEl.style.display = "none";
    statFound.textContent = "0";
    fillEl.style.width = "0%";
    setRunning(true);
    startElapsedTimer();
    rerender();

    es = new EventSource(`/api/scan?universe=${encodeURIComponent(universe)}`);

    es.addEventListener("start", (e) => {
      const d = JSON.parse(e.data);
      statScanned.textContent = `0 / ${d.total}`;
      const universeLabel = d.universe === "full"
        ? `full S&P 500 + NASDAQ-100 (${d.source})`
        : "curated top large-caps";
      metaEl.textContent = `Scanning ${d.total} tickers — ${universeLabel}…`;
    });

    es.addEventListener("progress", (e) => {
      const d = JSON.parse(e.data);
      statScanned.textContent = `${d.scanned} / ${d.total}`;
      fillEl.style.width = `${(d.scanned / d.total) * 100}%`;
      metaEl.textContent =
        `Last scanned: ${d.ticker}  ·  ${d.found} setup${d.found === 1 ? "" : "s"} found so far`;
    });

    es.addEventListener("candidate", (e) => {
      const c = JSON.parse(e.data);
      candidates.set(c.ticker, c);
      rerender();
    });

    es.addEventListener("done", (e) => {
      const d = JSON.parse(e.data);
      metaEl.textContent =
        `Done. Scanned ${d.scanned} tickers in ${d.elapsed_sec}s · ${d.found} bullish setup${d.found === 1 ? "" : "s"} identified.`;
      fillEl.style.width = "100%";
      setRunning(false);
      stopElapsedTimer();
      es.close();
      es = null;
      if (candidates.size === 0) {
        emptyEl.style.display = "block";
        emptyEl.querySelector("h2").textContent = "No bullish setups right now";
        emptyEl.querySelector("p").textContent =
          "The market isn't presenting high-confluence breakout candidates at the moment. Try again later — setups appear and disappear with each session.";
      }
    });

    es.onerror = () => {
      metaEl.textContent = "Connection lost. Press Start scan to retry.";
      setRunning(false);
      stopElapsedTimer();
      if (es) { es.close(); es = null; }
    };
  }

  // ----- filter wiring -----
  function bindFilters() {
    fSearch.addEventListener("input", () => {
      filters.search = fSearch.value.trim().toLowerCase();
      rerender();
    });

    fSort.addEventListener("change", () => {
      filters.sort = fSort.value;
      rerender();
    });

    fScore.addEventListener("input", () => {
      filters.minScore = parseInt(fScore.value, 10);
      fScoreVal.textContent = filters.minScore;
      rerender();
    });

    fUpside.addEventListener("input", () => {
      filters.minUpside = parseFloat(fUpside.value);
      fUpsideVal.textContent = `${filters.minUpside}%`;
      rerender();
    });

    fRR.addEventListener("input", () => {
      filters.minRR = parseFloat(fRR.value);
      fRRVal.textContent = `${filters.minRR.toFixed(1)}×`;
      rerender();
    });

    const onPriceInput = () => {
      const lo = parseFloat(fPmin.value);
      const hi = parseFloat(fPmax.value);
      filters.minPrice = Number.isFinite(lo) && lo > 0 ? lo : null;
      filters.maxPrice = Number.isFinite(hi) && hi > 0 ? hi : null;
      rerender();
    };
    fPmin.addEventListener("input", onPriceInput);
    fPmax.addEventListener("input", onPriceInput);

    fIndex.addEventListener("click", (e) => {
      const btn = e.target.closest(".seg-btn");
      if (!btn) return;
      fIndex.querySelectorAll(".seg-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      filters.index = btn.dataset.val;
      rerender();
    });

    fUniverse.addEventListener("click", (e) => {
      const btn = e.target.closest(".seg-btn");
      if (!btn) return;
      fUniverse.querySelectorAll(".seg-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      universe = btn.dataset.val;
      // Universe only affects the next scan — don't auto-restart.
    });

    fReset.addEventListener("click", () => {
      filters.search = "";
      filters.index = "all";
      filters.sort = "score";
      filters.minScore = 60;
      filters.minUpside = 0;
      filters.minRR = 0;
      filters.minPrice = null;
      filters.maxPrice = null;
      fSearch.value = "";
      fSort.value = "score";
      fScore.value = "60"; fScoreVal.textContent = "60";
      fUpside.value = "0"; fUpsideVal.textContent = "0%";
      fRR.value = "0"; fRRVal.textContent = "0×";
      fPmin.value = "";
      fPmax.value = "";
      fIndex.querySelectorAll(".seg-btn").forEach((b) =>
        b.classList.toggle("active", b.dataset.val === "all"));
      rerender();
    });
  }

  bindFilters();
  scanBtn.addEventListener("click", startScan);
  refreshPricesBtn.addEventListener("click", refreshScanPrices);

  // ----- tab switching (Scanner / Plans) -----
  const tabs = $("tabs");
  const views = {
    scanner: $("view-scanner"),
    plans: $("view-plans"),
    news: $("view-news"),
  };

  function switchView(name) {
    Object.entries(views).forEach(([k, el]) => {
      if (el) el.classList.toggle("active", k === name);
    });
    tabs.querySelectorAll(".tab").forEach((t) =>
      t.classList.toggle("active", t.dataset.view === name));
    // Let the plans module know it became visible so it can refresh prices.
    if (name === "plans" && window.StockPlans && window.StockPlans.onShow) {
      window.StockPlans.onShow();
    }
    if (name === "news" && window.StockNews && window.StockNews.onShow) {
      window.StockNews.onShow();
    }
  }

  tabs.addEventListener("click", (e) => {
    const btn = e.target.closest(".tab");
    if (!btn) return;
    switchView(btn.dataset.view);
  });

  // Expose for the plans module (so "create plan from scan" can jump tabs).
  window.AppNav = { switchView };
})();
