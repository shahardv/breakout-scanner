(() => {
  const $ = (id) => document.getElementById(id);

  const STORE_KEY = "stock_plans_v1";
  const POLL_MS = 30000; // auto-refresh prices every 30s while tab is open

  // ----- DOM -----
  const form = $("plan-form");
  const fTicker = $("p-ticker");
  const fEntry = $("p-entry");
  const fStop = $("p-stop");
  const fTarget = $("p-target");
  const fNotes = $("p-notes");
  const fFav = $("p-fav");
  const formMsg = $("plan-form-msg");
  const listEl = $("plans-list");
  const emptyEl = $("plans-empty");
  const countEl = $("plans-count");
  const filterSeg = $("plans-filter");
  const refreshBtn = $("plans-refresh-btn");
  const refreshMeta = $("plans-refresh");
  const tpl = $("plan-tpl");

  let plans = [];
  let filterMode = "all"; // "all" | "fav"
  let quotes = {};        // { TICKER: {price, change_pct, ...} }
  let pollTimer = null;

  // ----- persistence -----
  function load() {
    try {
      plans = JSON.parse(localStorage.getItem(STORE_KEY)) || [];
    } catch {
      plans = [];
    }
  }
  function save() {
    localStorage.setItem(STORE_KEY, JSON.stringify(plans));
  }

  // ----- formatting -----
  const money = (v) =>
    v == null || Number.isNaN(v)
      ? "—"
      : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(v);
  const pct = (v) => (v == null || Number.isNaN(v) ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(2)}%`);

  // ----- status logic (assumes a long trade: stop < entry < target) -----
  function computeStatus(plan, price) {
    if (price == null) return { key: "unknown", label: "No price", cls: "st-unknown" };
    if (price >= plan.target) return { key: "target", label: "Target hit 🎯", cls: "st-target" };
    if (price <= plan.stop) return { key: "stop", label: "Stop hit 🛑", cls: "st-stop" };
    if (price >= plan.entry) return { key: "winning", label: "In profit", cls: "st-win" };
    return { key: "below", label: "Below entry", cls: "st-below" };
  }

  // ----- render -----
  function visiblePlans() {
    const list = filterMode === "fav" ? plans.filter((p) => p.favorite) : plans.slice();
    // Favorites first, then newest first.
    return list.sort((a, b) => (b.favorite - a.favorite) || (b.createdAt - a.createdAt));
  }

  function renderOne(plan) {
    const node = tpl.content.firstElementChild.cloneNode(true);
    node.dataset.id = plan.id;

    const q = quotes[plan.ticker] || {};
    const price = q.price ?? null;
    const status = computeStatus(plan, price);

    node.querySelector(".plan-ticker").textContent = plan.ticker;

    const star = node.querySelector(".fav-star");
    star.classList.toggle("on", !!plan.favorite);
    star.addEventListener("click", () => {
      plan.favorite = !plan.favorite;
      save();
      render();
    });

    const statusEl = node.querySelector(".plan-status");
    statusEl.textContent = status.label;
    statusEl.className = `plan-status ${status.cls}`;

    node.querySelector(".plan-del").addEventListener("click", () => {
      if (confirm(`Delete plan for ${plan.ticker}?`)) {
        plans = plans.filter((p) => p.id !== plan.id);
        save();
        render();
        schedulePoll();
      }
    });

    // current price + today's change
    node.querySelector(".plan-current").textContent = price != null ? money(price) : "—";
    const chEl = node.querySelector(".plan-change");
    if (q.change_pct != null) {
      chEl.textContent = pct(q.change_pct);
      chEl.classList.add(q.change_pct >= 0 ? "up" : "down");
    }

    // P&L vs entry
    const pnlEl = node.querySelector(".plan-pnl");
    if (price != null) {
      const pnlPct = (price / plan.entry - 1) * 100;
      pnlEl.textContent = pct(pnlPct);
      pnlEl.classList.add(pnlPct >= 0 ? "up" : "down");
    }

    // grid
    node.querySelector(".plan-entry").textContent = money(plan.entry);
    node.querySelector(".plan-stop").textContent = money(plan.stop);
    node.querySelector(".plan-target").textContent = money(plan.target);

    const riskPerShare = plan.entry - plan.stop;
    const rewardPerShare = plan.target - plan.entry;
    const rr = riskPerShare > 0 ? rewardPerShare / riskPerShare : null;
    node.querySelector(".plan-risk").textContent = money(riskPerShare);
    node.querySelector(".plan-reward").textContent = money(rewardPerShare);
    node.querySelector(".plan-rr").textContent = rr != null ? `${rr.toFixed(2)}×` : "—";

    // progress bar: stop (left) → target (right), markers for entry + current
    const lo = Math.min(plan.stop, plan.target);
    const hi = Math.max(plan.stop, plan.target);
    const span = Math.max(1e-9, hi - lo);
    const posOf = (v) => `${Math.max(0, Math.min(100, ((v - lo) / span) * 100))}%`;
    node.querySelector(".plan-bar-entry").style.left = posOf(plan.entry);
    node.querySelector(".plan-bar-stop").style.left = "0%";
    node.querySelector(".plan-bar-target").style.left = "100%";
    const nowEl = node.querySelector(".plan-bar-now");
    if (price != null) {
      nowEl.style.left = posOf(price);
      nowEl.classList.add(status.cls);
    } else {
      nowEl.style.display = "none";
    }

    const notesEl = node.querySelector(".plan-notes");
    if (plan.notes) notesEl.textContent = plan.notes;
    else notesEl.style.display = "none";

    return node;
  }

  function render() {
    const vis = visiblePlans();
    listEl.innerHTML = "";
    vis.forEach((p) => listEl.appendChild(renderOne(p)));

    countEl.textContent = String(plans.length);
    emptyEl.style.display = plans.length === 0 ? "block" : "none";
    if (plans.length > 0 && vis.length === 0) {
      emptyEl.style.display = "block";
      emptyEl.querySelector("h2").textContent = "No favorites yet";
      emptyEl.querySelector("p").textContent = "Star a plan to see it here.";
    }
  }

  // ----- live prices -----
  async function refreshPrices() {
    const tickers = [...new Set(plans.map((p) => p.ticker))];
    if (tickers.length === 0) {
      refreshMeta.textContent = "No plans to price";
      return;
    }
    refreshMeta.textContent = "Refreshing…";
    try {
      const res = await fetch(`/api/quote?tickers=${encodeURIComponent(tickers.join(","))}`);
      const data = await res.json();
      quotes = data.quotes || {};
      render();
      const t = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      refreshMeta.textContent = `Updated ${t} · auto every 30s`;
    } catch (e) {
      refreshMeta.textContent = "Price fetch failed — tap Refresh to retry";
    }
  }

  function schedulePoll() {
    if (pollTimer) clearInterval(pollTimer);
    if (plans.length === 0) return;
    pollTimer = setInterval(() => {
      // Only poll while the Plans tab is actually visible.
      if ($("view-plans").classList.contains("active")) refreshPrices();
    }, POLL_MS);
  }

  // ----- form -----
  function showMsg(text, ok) {
    formMsg.textContent = text;
    formMsg.className = `form-msg ${ok ? "ok" : "err"}`;
    if (text) setTimeout(() => { formMsg.textContent = ""; }, 3500);
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const ticker = fTicker.value.trim().toUpperCase();
    const entry = parseFloat(fEntry.value);
    const stop = parseFloat(fStop.value);
    const target = parseFloat(fTarget.value);

    if (!ticker) return showMsg("Enter a ticker.", false);
    if (![entry, stop, target].every(Number.isFinite)) return showMsg("Entry, stop and target must be numbers.", false);
    if (stop >= entry) return showMsg("Stop should be below your entry (long trade).", false);
    if (target <= entry) return showMsg("Target should be above your entry.", false);

    plans.push({
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      ticker, entry, stop, target,
      notes: fNotes.value.trim(),
      favorite: fFav.checked,
      createdAt: Date.now(),
    });
    save();
    form.reset();
    render();
    showMsg(`Plan for ${ticker} created.`, true);
    refreshPrices();
    schedulePoll();
  });

  // ----- filter toggle -----
  filterSeg.addEventListener("click", (e) => {
    const btn = e.target.closest(".seg-btn");
    if (!btn) return;
    filterSeg.querySelectorAll(".seg-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    filterMode = btn.dataset.val;
    render();
  });

  refreshBtn.addEventListener("click", refreshPrices);

  // ----- public API for the scanner tab -----
  window.StockPlans = {
    prefillFromScan(data) {
      fTicker.value = data.ticker || "";
      fEntry.value = data.entry ?? "";
      fStop.value = data.stop ?? "";
      fTarget.value = data.target ?? "";
      fNotes.value = data.note || "";
      if (window.AppNav) window.AppNav.switchView("plans");
      fTicker.focus();
      showMsg("Pre-filled from scan — review and press Create plan.", true);
    },
    onShow() {
      // Called when the Plans tab becomes visible.
      if (plans.length > 0) refreshPrices();
    },
  };

  // ----- init -----
  load();
  render();
  schedulePoll();
})();
