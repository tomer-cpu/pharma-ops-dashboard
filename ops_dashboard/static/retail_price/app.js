/* Retail price monitor dashboard — vanilla JS front end. */

const API_BASE = "/api/retail-price";

const state = {
  selectedDate: null, // YYYY-MM-DD (null = latest)
  comparison: null,   // cached comparison payload
  products: [],
  selectedProductId: null,
  selectedTrendDays: 30,
  alerts: [],
};

// ── Utilities ─────────────────────────────────────────────────────────

const $ = (sel) => document.querySelector(sel);
const fmtPrice = (v) => (v == null ? "—" : `${Number(v).toFixed(2)} ₪`);
const fmtPct = (v) => {
  if (v == null) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${Number(v).toFixed(1)}%`;
};
const pctClass = (v) => {
  if (v == null) return "";
  if (v > 0) return "rpm-change-up";
  if (v < 0) return "rpm-change-down";
  return "";
};

async function api(path) {
  const url = state.selectedDate && !path.includes("?")
    ? `${API_BASE}${path}?date=${state.selectedDate}`
    : state.selectedDate
      ? `${API_BASE}${path}&date=${state.selectedDate}`
      : `${API_BASE}${path}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }

function createRow(cells, rowClasses = "") {
  const tr = document.createElement("tr");
  if (rowClasses) tr.className = rowClasses;
  cells.forEach((c) => {
    const td = document.createElement("td");
    if (c instanceof Node) td.appendChild(c);
    else td.innerHTML = c == null ? "—" : c;
    tr.appendChild(td);
  });
  return tr;
}

// ── Tab switching ─────────────────────────────────────────────────────

document.querySelectorAll(".rpm-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".rpm-tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".rpm-panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    const target = `panel-${tab.dataset.tab}`;
    document.getElementById(target).classList.add("active");
    onTabChanged(tab.dataset.tab);
  });
});

async function onTabChanged(tab) {
  if (tab === "compare") await ensureComparison();
  if (tab === "trends")  await ensureTrendUI();
  if (tab === "anomalies") await loadAnomalies();
  if (tab === "alerts") await loadAlerts();
}

// ── Executive screen ──────────────────────────────────────────────────

async function loadExecutive() {
  try {
    const [brief, summary] = await Promise.all([
      api("/morning-brief"),
      api("/summary"),
    ]);
    state.selectedDate = summary.date;
    $("#rpmDatePicker").value = summary.date;
    $("#rpmSubtitle").textContent =
      `תמונת מצב ליום ${summary.date} · סה״כ ${summary.kpis.retailers_active} רשתות נסרקו`;

    const briefList = $("#rpmBrief");
    clear(briefList);
    brief.lines.forEach((line) => {
      const li = document.createElement("li");
      li.textContent = line;
      briefList.appendChild(li);
    });

    $("#kpiProducts").textContent = summary.kpis.products_collected;
    $("#kpiRetailers").textContent =
      `${summary.kpis.retailers_active} / ${summary.kpis.retailers_total}`;
    $("#kpiPromos").textContent = summary.kpis.promos_active;
    $("#kpiChanges").textContent = summary.kpis.significant_changes;

    // Retailer ranking
    const ranking = $("#rpmRetailerRanking");
    clear(ranking);
    summary.retailer_pricing.all.forEach((r, idx) => {
      const row = document.createElement("div");
      row.className = "row";
      const badge = idx === 0 ? '<span class="rpm-badge cheapest">הזולה</span>'
                   : idx === summary.retailer_pricing.all.length - 1 ? '<span class="rpm-badge expensive">היקרה</span>'
                   : "";
      row.innerHTML = `<span>${r.name} ${badge}</span><strong>${fmtPrice(r.avg_price)}</strong>`;
      ranking.appendChild(row);
    });

    fillTopTable("#rpmTopSpread", summary.top_spread, (p) => [
      p.product_name,
      fmtPrice(p.avg_price),
      fmtPrice(p.min_price),
      fmtPrice(p.max_price),
      `<strong>${p.spread_pct}%</strong>`,
    ]);

    fillTopTable("#rpmTopDrops", summary.top_drops, (p) => [
      p.product_name,
      fmtPrice(p.avg_price),
      `<span class="${pctClass(p.day_change_pct)}">${fmtPct(p.day_change_pct)}</span>`,
    ]);

    fillTopTable("#rpmTopJumps", summary.top_jumps, (p) => [
      p.product_name,
      fmtPrice(p.avg_price),
      `<span class="${pctClass(p.day_change_pct)}">${fmtPct(p.day_change_pct)}</span>`,
    ]);

    $("#rpmLastCollection").textContent = `איסוף אחרון: ${summary.date}`;
  } catch (err) {
    console.error(err);
    $("#rpmBrief").innerHTML = `<li>שגיאה בטעינת נתונים: ${err.message}</li>`;
  }
}

function fillTopTable(sel, rows, cellFn) {
  const body = $(sel);
  clear(body);
  if (!rows || rows.length === 0) {
    body.appendChild(createRow(["אין נתונים"], "rpm-muted"));
    return;
  }
  rows.forEach((row) => body.appendChild(createRow(cellFn(row))));
}

// ── Comparison screen ────────────────────────────────────────────────

async function ensureComparison() {
  if (!state.comparison || state.comparison.date !== state.selectedDate) {
    state.comparison = await api("/comparison");
  }
  renderComparison();
  populateCategoryFilter();
}

function populateCategoryFilter() {
  const select = $("#cmpCategory");
  if (select.options.length > 1) return;
  const categories = new Set();
  state.comparison.products.forEach((p) => p.category && categories.add(p.category));
  Array.from(categories).sort().forEach((c) => {
    const opt = document.createElement("option");
    opt.value = c; opt.textContent = c;
    select.appendChild(opt);
  });
}

function renderComparison() {
  const body = $("#rpmCompareBody");
  clear(body);
  const search = $("#cmpSearch").value.trim();
  const category = $("#cmpCategory").value;

  const filtered = state.comparison.products.filter((p) => {
    if (category && p.category !== category) return false;
    if (search) {
      const hay = `${p.product_name} ${p.barcode || ""}`.toLowerCase();
      if (!hay.includes(search.toLowerCase())) return false;
    }
    return true;
  });

  if (filtered.length === 0) {
    body.appendChild(createRow(["לא נמצאו תוצאות תואמות", "", "", "", "", "", "", "", "", ""]));
    return;
  }

  filtered.forEach((p) => {
    const promoBadge = p.has_promo
      ? '<span class="rpm-badge promo">במבצע</span>'
      : '<span class="rpm-badge no-promo">ללא</span>';
    const detailBtn = document.createElement("button");
    detailBtn.className = "rpm-link-btn";
    detailBtn.textContent = "מגמה ›";
    detailBtn.addEventListener("click", () => openTrendFor(p.product_id));

    body.appendChild(createRow([
      p.product_name,
      p.barcode || "—",
      p.category || "—",
      fmtPrice(p.min_price),
      fmtPrice(p.avg_price),
      fmtPrice(p.max_price),
      `<strong>${p.spread_pct}%</strong>`,
      p.retailers_count,
      promoBadge,
      detailBtn,
    ]));
  });
}

$("#cmpSearch").addEventListener("input", renderComparison);
$("#cmpCategory").addEventListener("change", renderComparison);

// ── Trend screen ─────────────────────────────────────────────────────

async function ensureTrendUI() {
  if (state.products.length === 0) {
    const data = await api("/products");
    state.products = data.products;
    const select = $("#trendProduct");
    clear(select);
    state.products.forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = p.name;
      select.appendChild(opt);
    });
  }
  if (!state.selectedProductId && state.products.length) {
    state.selectedProductId = state.products[0].id;
    $("#trendProduct").value = state.selectedProductId;
  }
  await loadTrend();
}

async function openTrendFor(productId) {
  state.selectedProductId = productId;
  document.querySelectorAll(".rpm-tab").forEach((t) => t.classList.remove("active"));
  document.querySelectorAll(".rpm-panel").forEach((p) => p.classList.remove("active"));
  document.querySelector('.rpm-tab[data-tab="trends"]').classList.add("active");
  $("#panel-trends").classList.add("active");
  await ensureTrendUI();
  $("#trendProduct").value = productId;
  await loadTrend();
}

$("#trendProduct").addEventListener("change", (e) => {
  state.selectedProductId = Number(e.target.value);
  loadTrend();
});
$("#trendDays").addEventListener("change", (e) => {
  state.selectedTrendDays = Number(e.target.value);
  loadTrend();
});

async function loadTrend() {
  if (!state.selectedProductId) return;
  const data = await fetch(
    `${API_BASE}/products/${state.selectedProductId}/trend?days=${state.selectedTrendDays}`
  ).then((r) => r.json());
  renderTrend(data);
}

const RETAILER_COLORS = [
  "#2f5bea", "#d4361a", "#1ea97c", "#e08a00",
  "#9333ea", "#0891b2", "#ca8a04", "#db2777", "#0f766e",
];

function renderTrend(data) {
  $("#trendD1").textContent  = fmtPct(data.change && data.change.d1_change_pct);
  $("#trendD1").className    = pctClass(data.change && data.change.d1_change_pct);
  $("#trendD7").textContent  = fmtPct(data.change && data.change.d7_change_pct);
  $("#trendD7").className    = pctClass(data.change && data.change.d7_change_pct);
  $("#trendD30").textContent = fmtPct(data.change && data.change.d30_change_pct);
  $("#trendD30").className   = pctClass(data.change && data.change.d30_change_pct);
  const labelMap = { rising: "עולה", falling: "יורד", stable: "יציב", unknown: "—" };
  $("#trendLabel").textContent = labelMap[data.trend_label] || data.trend_label;

  const svg = $("#trendChart");
  clear(svg);
  const legend = $("#trendLegend");
  clear(legend);
  if (!data.series.length) return;

  const width = 800, height = 320;
  const padL = 50, padR = 20, padT = 20, padB = 36;
  const innerW = width - padL - padR;
  const innerH = height - padT - padB;

  const dates = data.series.map((s) => s.date);
  const allValues = [];
  data.series.forEach((s) => { allValues.push(s.min, s.max, s.avg); });
  Object.values(data.per_retailer).forEach((map) => Object.values(map).forEach((v) => allValues.push(v)));
  const minV = Math.min(...allValues);
  const maxV = Math.max(...allValues);
  const span = maxV - minV || 1;
  const yMin = minV - span * 0.08;
  const yMax = maxV + span * 0.08;

  const xFor = (i) => padL + (i / Math.max(1, dates.length - 1)) * innerW;
  const yFor = (v) => padT + (1 - (v - yMin) / (yMax - yMin)) * innerH;

  // Grid + axes
  const ns = "http://www.w3.org/2000/svg";
  const gridSteps = 4;
  for (let i = 0; i <= gridSteps; i++) {
    const y = padT + (i / gridSteps) * innerH;
    const line = document.createElementNS(ns, "line");
    line.setAttribute("class", "grid");
    line.setAttribute("x1", padL); line.setAttribute("x2", width - padR);
    line.setAttribute("y1", y);    line.setAttribute("y2", y);
    svg.appendChild(line);

    const lbl = document.createElementNS(ns, "text");
    lbl.setAttribute("x", padL - 6);
    lbl.setAttribute("y", y + 3);
    lbl.setAttribute("text-anchor", "end");
    lbl.textContent = `${(yMax - ((yMax - yMin) * i) / gridSteps).toFixed(1)} ₪`;
    svg.appendChild(lbl);
  }

  // X labels
  const xStep = Math.max(1, Math.floor(dates.length / 6));
  dates.forEach((d, i) => {
    if (i % xStep !== 0 && i !== dates.length - 1) return;
    const txt = document.createElementNS(ns, "text");
    txt.setAttribute("x", xFor(i));
    txt.setAttribute("y", height - padB + 16);
    txt.setAttribute("text-anchor", "middle");
    txt.textContent = d.slice(5);
    svg.appendChild(txt);
  });

  // Retailer series
  Object.entries(data.per_retailer).forEach(([code, map], idx) => {
    const color = RETAILER_COLORS[idx % RETAILER_COLORS.length];
    const pts = dates
      .map((d, i) => {
        const val = map[d];
        return val == null ? null : `${xFor(i)},${yFor(val)}`;
      })
      .filter(Boolean);
    if (!pts.length) return;
    const g = document.createElementNS(ns, "g");
    g.setAttribute("class", "series");
    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", "M" + pts.join(" L"));
    path.setAttribute("stroke", color);
    path.setAttribute("fill", "none");
    g.appendChild(path);
    svg.appendChild(g);

    const chip = document.createElement("span");
    chip.innerHTML = `<span class="swatch" style="background:${color}"></span>${code}`;
    legend.appendChild(chip);
  });

  // Market average line on top
  const avgPts = data.series.map((s, i) => `${xFor(i)},${yFor(s.avg)}`);
  const g = document.createElementNS(ns, "g");
  g.setAttribute("class", "market");
  const avgPath = document.createElementNS(ns, "path");
  avgPath.setAttribute("d", "M" + avgPts.join(" L"));
  avgPath.setAttribute("stroke", "#0f172a");
  avgPath.setAttribute("stroke-dasharray", "4 4");
  avgPath.setAttribute("fill", "none");
  g.appendChild(avgPath);
  svg.appendChild(g);

  const avgChip = document.createElement("span");
  avgChip.innerHTML = `<span class="swatch" style="background:#0f172a"></span>ממוצע שוק`;
  legend.appendChild(avgChip);
}

// ── Anomalies screen ────────────────────────────────────────────────

async function loadAnomalies() {
  const data = await api("/anomalies");

  fillTopTable("#anomVariance", data.high_variance_products, (p) => [
    p.product_name,
    `${fmtPrice(p.min_price)} – ${fmtPrice(p.max_price)}`,
    (p.cov * 100).toFixed(1) + "%",
  ]);

  fillTopTable("#anomJumps", data.sharp_jumps, (p) => [
    p.product_name,
    fmtPrice(p.avg_price),
    `<span class="${pctClass(p.day_change_pct)}">${fmtPct(p.day_change_pct)}</span>`,
  ]);

  fillTopTable("#anomDrops", data.sharp_drops, (p) => [
    p.product_name,
    fmtPrice(p.avg_price),
    `<span class="${pctClass(p.day_change_pct)}">${fmtPct(p.day_change_pct)}</span>`,
  ]);

  fillTopTable("#anomIncomplete", data.incomplete_coverage, (p) => [
    p.product_name,
    p.retailers_count,
    p.missing_from,
  ]);

  fillTopTable("#anomSuspicious", data.suspicious_matches, (m) => [
    m.source_product_name,
    m.product_name || "—",
    m.retailer_name_he || "—",
    m.match_confidence,
  ]);
}

// ── Alerts screen ───────────────────────────────────────────────────

async function loadAlerts() {
  const data = await api("/alerts");
  state.alerts = data.alerts || [];
  renderAlerts();
}

function renderAlerts() {
  const list = $("#rpmAlertsList");
  clear(list);
  const filter = $("#alertType").value;
  const items = state.alerts.filter((a) => !filter || a.alert_type === filter);
  if (!items.length) {
    const li = document.createElement("li");
    li.textContent = "לא זוהו התראות עבור היום הנבחר";
    list.appendChild(li);
    return;
  }
  items.forEach((alert) => {
    const li = document.createElement("li");
    li.className = `rpm-severity-${alert.severity}`;
    const title = document.createElement("div");
    title.className = "rpm-alert-title";
    title.textContent = alert.title;
    const desc = document.createElement("div");
    desc.className = "rpm-alert-description";
    const meta = [];
    if (alert.retailer_name_he) meta.push(alert.retailer_name_he);
    if (alert.pct_change != null) meta.push(fmtPct(alert.pct_change));
    desc.textContent = `${alert.description || ""}${meta.length ? " · " + meta.join(" · ") : ""}`;
    li.appendChild(title);
    li.appendChild(desc);
    list.appendChild(li);
  });
}

$("#alertType").addEventListener("change", renderAlerts);

// ── Date picker ─────────────────────────────────────────────────────

$("#rpmDatePicker").addEventListener("change", async (e) => {
  state.selectedDate = e.target.value || null;
  state.comparison = null;
  await loadExecutive();
  const active = document.querySelector(".rpm-tab.active");
  if (active) onTabChanged(active.dataset.tab);
});

$("#rpmTodayBtn").addEventListener("click", async () => {
  state.selectedDate = null;
  state.comparison = null;
  await loadExecutive();
  const active = document.querySelector(".rpm-tab.active");
  if (active) onTabChanged(active.dataset.tab);
});

$("#rpmCollectBtn").addEventListener("click", async () => {
  const btn = $("#rpmCollectBtn");
  btn.disabled = true;
  btn.textContent = "רץ על האתרים…";
  const statusCard = $("#rpmCollectStatus");
  const body = $("#rpmCollectBody");
  clear(body);
  statusCard.style.display = "block";
  $("#rpmCollectMeta").textContent = "מתחיל ריצה…";
  try {
    const res = await fetch(`${API_BASE}/collect`, { method: "POST" });
    const data = await res.json();
    const statusLabels = { ok: "הצלחה", partial: "חלקי", failed: "נכשל", skipped: "דולג" };
    const dot = { ok: "🟢", partial: "🟡", failed: "🔴", skipped: "⚪" };
    $("#rpmCollectMeta").textContent =
      `הרצה ליום ${data.date} · ${data.observations_written} תצפיות נכתבו · ` +
      `${data.products_created || 0} מוצרים חדשים זוהו`;
    data.collectors.forEach((c) => {
      body.appendChild(createRow([
        c.retailer_code,
        `${dot[c.status] || "●"} ${statusLabels[c.status] || c.status}`,
        c.observations,
        c.error_message || (c.meta && c.meta.price_file) || "",
      ]));
    });
    // Refresh dashboard data for the new day.
    state.comparison = null;
    await loadExecutive();
    const active = document.querySelector(".rpm-tab.active");
    if (active) onTabChanged(active.dataset.tab);
  } catch (err) {
    $("#rpmCollectMeta").textContent = "שגיאה בהפעלת ה-collectors: " + err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "רוץ על האתרים עכשיו";
  }
});

// ── Bootstrap ───────────────────────────────────────────────────────

loadExecutive();
