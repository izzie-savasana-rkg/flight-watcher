/* Flight watcher dashboard + config editor. */

let SETTINGS = {};
let WATCHES = { watches: [] };

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function banner(msg, cls = "") {
  const el = $("#banner");
  if (!msg) { el.classList.add("hidden"); return; }
  el.textContent = msg;
  el.className = `banner ${cls}`;
}

function ago(iso) {
  if (!iso) return "–";
  const mins = Math.round((Date.now() - new Date(iso)) / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  if (mins < 48 * 60) return `${Math.round(mins / 60)}h`;
  return `${Math.round(mins / 1440)}d`;
}

/* ---------- dashboard ---------- */

function dailyMins(observations) {
  const byDay = {};
  for (const o of observations) {
    if (!o.price) continue;
    const day = (o.observed_at || "").slice(0, 10);
    if (!byDay[day] || o.price < byDay[day]) byDay[day] = o.price;
  }
  return Object.keys(byDay).sort().map((d) => byDay[d]);
}

function sparkline(series, color) {
  if (series.length < 2) return `<div class="spark muted small">collecting history…</div>`;
  const w = 260, h = 36, pad = 3;
  const min = Math.min(...series), max = Math.max(...series);
  const span = max - min || 1;
  const pts = series.map((v, i) => {
    const x = pad + (i / (series.length - 1)) * (w - 2 * pad);
    const y = pad + (1 - (v - min) / span) * (h - 2 * pad);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const last = pts[pts.length - 1].split(",");
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <polyline points="${pts.join(" ")}" fill="none" stroke="${color}" stroke-width="2"/>
    <circle cx="${last[0]}" cy="${last[1]}" r="3" fill="${color}"/></svg>`;
}

function median(arr) {
  if (!arr.length) return null;
  const s = [...arr].sort((a, b) => a - b);
  return s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2;
}

async function renderDashboard() {
  const [status, alerts, ft] = await Promise.all([
    readFile("data/status.json", {}),
    readFile("data/alerts.json", { log: [] }),
    readFile("data/flyertalk.json", { threads: {} }),
  ]);

  const weekAgo = Date.now() - 7 * 86400000;
  const alertsWeek = (alerts.log || []).filter((a) => new Date(a.at) > weekAgo).length;

  const cardsEl = $("#route-cards");
  cardsEl.innerHTML = "";
  let bestDropPct = null;

  for (const w of WATCHES.watches.filter((w) => w.enabled !== false)) {
    const trip = (w.trip_types || ["return"])[0];
    const hist = await readFile(`data/history/${w.id}_${trip}.json`, { observations: [] });
    const obs = hist.observations || [];
    const recent = obs.slice(-40).filter((o) => o.price);
    const series = dailyMins(obs);
    const med = median(obs.map((o) => o.price).filter(Boolean));
    const current = recent.length ? Math.min(...recent.map((o) => o.price)) : null;
    const bestObs = recent.find((o) => o.price === current);
    let badge = `<span class="badge neutral">collecting data</span>`;
    let dropTxt = "";
    if (current && med && series.length >= 5) {
      const drop = Math.round((1 - current / med) * 100);
      if (drop > bestDropPct || bestDropPct === null) bestDropPct = drop;
      badge = drop >= 15
        ? `<span class="badge good">−${drop}% vs normal</span>`
        : `<span class="badge neutral">normal range</span>`;
      dropTxt = `median £${Math.round(med)}`;
    }
    const gLink = `https://www.google.com/travel/flights?q=${encodeURIComponent(
      `Flights from ${w.origin} to ${w.destination}`)}`;
    cardsEl.insertAdjacentHTML("beforeend", `
      <div class="card">
        ${badge}
        <div class="route">${esc(w.origin)} → ${esc(w.destination)}
          <span class="sub">${esc(trip)} · ${esc(w.cabin || "economy")}</span></div>
        <div class="price">${current ? "£" + Math.round(current) : "–"}
          <span class="ctx">${dropTxt}${bestObs ? " · depart " + esc(bestObs.depart) : ""}</span></div>
        ${sparkline(series, current && med && current < med * 0.85 ? "#1d9e75" : "#888780")}
        <div class="card-foot">
          <a href="${gLink}" target="_blank" rel="noopener">Open in Google Flights</a>
          <span class="muted">history: ${series.length} days</span>
        </div>
      </div>`);
  }
  if (!WATCHES.watches.length) cardsEl.innerHTML = `<p class="muted">No watches yet — add one in the Watches tab.</p>`;

  $("#metrics").innerHTML = `
    <div class="metric"><div class="label">Active watches</div>
      <div class="value">${WATCHES.watches.filter((w) => w.enabled !== false).length}</div></div>
    <div class="metric"><div class="label">Best vs normal</div>
      <div class="value ${bestDropPct >= 15 ? "good" : ""}">${bestDropPct === null ? "–" : "−" + Math.max(bestDropPct, 0) + "%"}</div></div>
    <div class="metric"><div class="label">Alerts this week</div>
      <div class="value">${alertsWeek}</div></div>
    <div class="metric"><div class="label">Last scan</div>
      <div class="value">${ago(status.finished_at)}</div></div>`;

  const threads = Object.entries(ft.threads || {})
    .sort((a, b) => new Date(b[1].posted_at || 0) - new Date(a[1].posted_at || 0))
    .slice(0, 12);
  $("#flyertalk-list").innerHTML = threads.length ? threads.map(([, t]) => {
    const d = t.decoded || {};
    const routes = (d.routes || []).join(", ");
    const dealType = d.is_deal ? (d.deal_type || "deal").replace(/_/g, " ") : "not a deal";
    const label = routes ? `${dealType} · ${routes}` : dealType;
    // decoded extras (populated when Claude decoding is on): price / cabin / urgency
    const bits = [];
    if (d.approx_price) bits.push(d.approx_price);
    if (d.cabin) bits.push(d.cabin);
    if (d.urgency && d.urgency !== "unknown") bits.push(d.urgency.replace(/_/g, " "));
    const chips = bits.length ? `<span class="chips">${esc(bits.join(" · "))}</span>` : "";
    const when = t.posted_at ? ago(t.posted_at) : "";
    return `<div class="item">
      <div class="head">${t.starred ? "⭐ " : ""}${esc(label)}
        <span class="when">${esc(t.forum || "")}${when ? " · " + when : ""}</span></div>
      <div class="body">${esc(d.summary || t.title)}${chips ? " " + chips : ""}</div>
      <a href="${esc(t.link)}" target="_blank" rel="noopener">Open thread ↗</a>
    </div>`;
  }).join("") : `<div class="item muted">Nothing decoded yet.</div>`;

  const log = (alerts.log || []).slice(-12).reverse();
  const icons = { anomaly: "📉", flyertalk: "🗣", fuel_dump: "⛽", feed: "📰", health: "🚨" };
  const linkLabel = {
    anomaly: "Open in Google Flights", fuel_dump: "Open in Google Flights",
    flyertalk: "Open thread", feed: "Open deal",
  };
  $("#alerts-list").innerHTML = log.length ? log.map((a) => {
    const plain = a.text.replace(/<[^>]+>/g, "");
    const urlMatch = a.text.match(/https?:\/\/\S+/);
    const url = urlMatch ? urlMatch[0]
      : (a.meta && (a.meta.thread || a.meta.url)) || "";
    const body = plain.split("\n").filter((l) => l.trim() && !/^https?:/.test(l.trim()))
      .join(" · ");
    const link = url
      ? `<a href="${esc(url)}" target="_blank" rel="noopener">${linkLabel[a.kind] || "Open"} ↗</a>`
      : "";
    return `<div class="item">
      <div class="head">${icons[a.kind] || ""} ${esc(a.kind)}
        <span class="when">${ago(a.at)}</span></div>
      <div class="body">${esc(body)}</div>
      ${link}
    </div>`;
  }).join("") : `<div class="item muted">No alerts yet.</div>`;
}

/* ---------- watches ---------- */

function renderWatches() {
  const el = $("#watch-list");
  el.innerHTML = WATCHES.watches.map((w, i) => `
    <div class="row-card">
      <div class="grow"><strong>${esc(w.origin)} → ${esc(w.destination)}</strong>
        <span class="muted small">${(w.trip_types || []).join(", ")} · ${esc(w.cabin || "economy")}
        · ${w.date_window_days || 180}d window${w.max_price ? " · cap £" + w.max_price : ""}</span></div>
      <label class="inline small"><input type="checkbox" data-toggle="${i}" ${w.enabled !== false ? "checked" : ""}> enabled</label>
      <button class="ghost" data-del="${i}">Delete</button>
    </div>`).join("") || `<p class="muted">No watches yet.</p>`;

  el.querySelectorAll("[data-del]").forEach((b) => b.onclick = async () => {
    if (!confirm("Delete this watch? Its price history file stays in the repo.")) return;
    WATCHES.watches.splice(Number(b.dataset.del), 1);
    await saveWatches();
  });
  el.querySelectorAll("[data-toggle]").forEach((b) => b.onchange = async () => {
    WATCHES.watches[Number(b.dataset.toggle)].enabled = b.checked;
    await saveWatches();
  });
}

async function saveWatches() {
  try {
    await writeFile("data/watches.json", WATCHES, "site: update watches");
    banner("Watches saved. Next scan picks them up.", "ok");
    renderWatches(); renderDashboard();
  } catch (err) { banner(err.message, "error"); }
}

$("#watch-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const origin = f.get("origin").toUpperCase().trim();
  const destination = f.get("destination").toUpperCase().trim();
  const tripTypes = [...e.target.querySelector("[name=trip_types]").selectedOptions].map((o) => o.value);
  const watch = {
    id: `${origin}-${destination}`.toLowerCase(),
    origin, destination,
    trip_types: tripTypes.length ? tripTypes : ["return"],
    cabin: f.get("cabin"),
    date_window_days: Number(f.get("date_window_days")) || 180,
    stay_nights: f.get("stay_nights").split(",").map((s) => Number(s.trim())).filter(Boolean),
    max_price: f.get("max_price") ? Number(f.get("max_price")) : null,
    enabled: true,
  };
  WATCHES.watches = WATCHES.watches.filter((w) => w.id !== watch.id).concat(watch);
  const kw = f.get("keywords").split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);
  if (kw.length) {
    SETTINGS.watch_keywords = SETTINGS.watch_keywords || {};
    SETTINGS.watch_keywords[destination] =
      [...new Set([...(SETTINGS.watch_keywords[destination] || []), ...kw])];
    try { await writeFile("data/settings.json", SETTINGS, "site: update keywords"); }
    catch (err) { banner(err.message, "error"); return; }
  }
  await saveWatches();
  e.target.reset();
});

async function saveSettings(msg) {
  try {
    await writeFile("data/settings.json", SETTINGS, msg);
    banner("Settings saved.", "ok");
  } catch (err) { banner(err.message, "error"); }
}

/* ---------- settings ---------- */

async function renderSettings() {
  $("#gh-token").value = GH.token;
  $("#gh-repo").value = GH.repo;
  $("#set-drop").value = SETTINGS.anomaly?.drop_threshold_pct ?? 30;
  $("#set-budget").value = SETTINGS.scan?.max_google_queries_per_run ?? 60;
  $("#set-cooldown").value = SETTINGS.alerts?.cooldown_hours ?? 24;
  $("#set-hb-enabled").checked = SETTINGS.heartbeat?.enabled ?? true;
  $("#set-hb-interval").value = SETTINGS.heartbeat?.min_interval_hours ?? 20;
  const status = await readFile("data/status.json", {});
  $("#status-json").textContent = JSON.stringify(status, null, 2);
}

$("#save-conn").addEventListener("click", async () => {
  GH.token = $("#gh-token").value.trim();
  GH.repo = $("#gh-repo").value.trim();
  localStorage.setItem("fw_token", GH.token);
  localStorage.setItem("fw_repo", GH.repo);
  const ok = await readFile("data/watches.json", null);
  $("#conn-status").textContent = ok ? "✓ connected" : "✗ could not read repo";
  if (ok) { WATCHES = ok; boot(); }
});

$("#save-settings").addEventListener("click", async () => {
  SETTINGS.anomaly = SETTINGS.anomaly || {};
  SETTINGS.scan = SETTINGS.scan || {};
  SETTINGS.alerts = SETTINGS.alerts || {};
  SETTINGS.heartbeat = SETTINGS.heartbeat || {};
  SETTINGS.anomaly.drop_threshold_pct = Number($("#set-drop").value);
  SETTINGS.scan.max_google_queries_per_run = Number($("#set-budget").value);
  SETTINGS.alerts.cooldown_hours = Number($("#set-cooldown").value);
  SETTINGS.heartbeat.enabled = $("#set-hb-enabled").checked;
  SETTINGS.heartbeat.min_interval_hours = Number($("#set-hb-interval").value);
  await saveSettings("site: update detection settings");
});

/* ---------- shell ---------- */

document.querySelectorAll(".tab").forEach((tab) => tab.onclick = () => {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
  document.querySelectorAll(".view").forEach((v) =>
    v.classList.toggle("hidden", v.id !== `view-${tab.dataset.view}`));
});

async function boot() {
  if (!GH.repo) {
    banner("Set your repository (username/flight-watcher) in Settings.", "");
  }
  SETTINGS = await readFile("data/settings.json", SETTINGS) || {};
  WATCHES = await readFile("data/watches.json", { watches: [] });
  renderDashboard();
  renderWatches();
  renderSettings();
}

boot();
