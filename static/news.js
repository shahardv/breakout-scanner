(() => {
  const $ = (id) => document.getElementById(id);
  const listEl = $("news-list");
  const metaEl = $("news-meta");
  const refreshBtn = $("news-refresh-btn");
  const tpl = $("news-tpl");

  let loaded = false;
  let loading = false;

  // ponytail: tiny relative-time formatter, Intl.RelativeTimeFormat handles
  // locale + pluralization for free.
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  function relTime(ts) {
    const secs = Math.round(ts - Date.now() / 1000);
    const abs = Math.abs(secs);
    if (abs < 60) return rtf.format(Math.round(secs), "second");
    if (abs < 3600) return rtf.format(Math.round(secs / 60), "minute");
    if (abs < 86400) return rtf.format(Math.round(secs / 3600), "hour");
    return rtf.format(Math.round(secs / 86400), "day");
  }

  function renderOne(n) {
    const node = tpl.content.firstElementChild.cloneNode(true);
    node.href = n.link || "#";
    if (!n.link) node.removeAttribute("target");
    const img = node.querySelector("img");
    if (n.thumbnail) img.src = n.thumbnail;
    else node.querySelector(".news-thumb").classList.add("no-img");
    node.querySelector(".news-headline").textContent = n.title;
    node.querySelector(".news-publisher").textContent = n.publisher || "Source";
    node.querySelector(".news-time").textContent = relTime(n.published_ts);
    const tEl = node.querySelector(".news-tickers");
    (n.tickers || []).slice(0, 4).forEach((t) => {
      const chip = document.createElement("span");
      chip.className = "news-chip";
      chip.textContent = t;
      tEl.appendChild(chip);
    });
    return node;
  }

  async function load() {
    if (loading) return;
    loading = true;
    metaEl.textContent = loaded ? "Refreshing…" : "Loading…";
    try {
      const res = await fetch("/api/news");
      if (!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();
      const items = data.items || [];
      listEl.innerHTML = "";
      if (items.length === 0) {
        listEl.innerHTML = `<p class="news-empty">No headlines in the last 72 hours (Yahoo may be throttling). Try Refresh in a minute.</p>`;
      } else {
        items.forEach((n) => listEl.appendChild(renderOne(n)));
      }
      const t = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      metaEl.textContent = `${items.length} headlines · updated ${t}`;
      loaded = true;
    } catch (e) {
      metaEl.textContent = "Couldn't load news — tap Refresh to retry.";
    } finally {
      loading = false;
    }
  }

  refreshBtn.addEventListener("click", load);

  window.StockNews = {
    onShow() { if (!loaded) load(); },
  };
})();
