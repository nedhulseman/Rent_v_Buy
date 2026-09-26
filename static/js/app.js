const FIELDS = [
  "home_price", "down_payment", "mortgage_rate_pct", "n_years",
  "monthly_rent", "available_capital", "investment_return_pct",
  "property_tax_rate_pct", "hoa", "home_appreciation_pct", "rent_growth_pct",
  "moving_cost", "closing_costs", "realtor_fees",
  "maintenance_rate_pct", "insurance_rate_pct", "pmi_rate_pct", "selling_cost_pct",
  "marginal_tax_rate_pct", "standard_deduction", "salt_cap", "other_itemized",
];

const COLORS = {
  house: "#2563eb",
  rent: "#f59e0b",
  equity: "#1d4ed8",
  invest: "#60a5fa",
  good: "#16a34a",
  bad: "#dc2626",
  ink: "#0f172a",
  muted: "#94a3b8",
  line: "#e2e8f0",
};

const fmt$ = (v) => {
  if (v == null || isNaN(v)) return "—";
  const sign = v < 0 ? "-" : "";
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 10_000) return `${sign}$${Math.round(abs / 1000)}k`;
  return `${sign}$${Math.round(abs).toLocaleString()}`;
};
const fmt$Full = (v) =>
  v == null || isNaN(v) ? "—" : `$${Math.round(v).toLocaleString()}`;

function readForm() {
  const out = {};
  for (const id of FIELDS) {
    const el = document.getElementById(id);
    out[id] = el ? Number(el.value) : 0;
  }
  return out;
}

const baseLayout = (extra = {}) => ({
  margin: { l: 60, r: 20, t: 16, b: 40 },
  paper_bgcolor: "white",
  plot_bgcolor: "white",
  font: { family: "Inter, sans-serif", size: 12, color: COLORS.ink },
  xaxis: {
    title: "Years",
    gridcolor: COLORS.line,
    zeroline: false,
    showline: false,
  },
  yaxis: {
    tickprefix: "$",
    tickformat: ",.0f",
    gridcolor: COLORS.line,
    zeroline: false,
  },
  legend: { orientation: "h", y: -0.18 },
  hovermode: "x unified",
  ...extra,
});

const config = { displaylogo: false, responsive: true, displayModeBar: false };

function monthsToYears(months) {
  return months.map((m) => m / 12);
}

function renderMain(data) {
  const x = monthsToYears(data.chart.months);
  Plotly.react(
    "chart-main",
    [
      {
        x,
        y: data.chart.house_total,
        name: "Buying — total assets",
        mode: "lines",
        line: { color: COLORS.house, width: 3 },
        hovertemplate: "Year %{x:.1f}<br>$%{y:,.0f}<extra>Buying</extra>",
      },
      {
        x,
        y: data.chart.apt_total,
        name: "Renting — total assets",
        mode: "lines",
        line: { color: COLORS.rent, width: 3 },
        hovertemplate: "Year %{x:.1f}<br>$%{y:,.0f}<extra>Renting</extra>",
      },
    ],
    baseLayout(),
    config
  );
}

function renderBreakdown(data) {
  const x = monthsToYears(data.chart.months);
  Plotly.react(
    "chart-breakdown",
    [
      {
        x,
        y: data.chart.house_equity,
        name: "Home equity",
        stackgroup: "one",
        line: { color: COLORS.equity, width: 0 },
        fillcolor: "rgba(37, 99, 235, 0.7)",
        hovertemplate: "Year %{x:.1f}<br>$%{y:,.0f}<extra>Equity</extra>",
      },
      {
        x,
        y: data.chart.house_investments,
        name: "Side investments",
        stackgroup: "one",
        line: { color: COLORS.invest, width: 0 },
        fillcolor: "rgba(96, 165, 250, 0.6)",
        hovertemplate: "Year %{x:.1f}<br>$%{y:,.0f}<extra>Investments</extra>",
      },
    ],
    baseLayout(),
    config
  );
}

function renderMonthly(data) {
  const x = monthsToYears(data.chart.months);
  Plotly.react(
    "chart-monthly",
    [
      {
        x,
        y: data.chart.house_monthly_cost,
        name: "Owning (mortgage + tax + HOA)",
        mode: "lines",
        line: { color: COLORS.house, width: 2.5 },
        hovertemplate: "Year %{x:.1f}<br>$%{y:,.0f}/mo<extra>Owning</extra>",
      },
      {
        x,
        y: data.chart.rent_monthly,
        name: "Renting",
        mode: "lines",
        line: { color: COLORS.rent, width: 2.5 },
        hovertemplate: "Year %{x:.1f}<br>$%{y:,.0f}/mo<extra>Renting</extra>",
      },
    ],
    baseLayout(),
    config
  );
}

function renderSensitivity(data) {
  const x = monthsToYears(data.months);
  const palette = ["#1e40af", "#2563eb", "#3b82f6", "#60a5fa", "#93c5fd"];
  const traces = data.scenarios.map((s, i) => ({
    x,
    y: s.house_total,
    name: s.label,
    mode: "lines",
    line: { color: palette[i % palette.length], width: 2 },
    hovertemplate: `Year %{x:.1f}<br>$%{y:,.0f}<extra>${s.label}</extra>`,
  }));
  Plotly.react("chart-sensitivity", traces, baseLayout(), config);
}

function updateSummary(s) {
  const setText = (id, v) => (document.getElementById(id).textContent = v);
  setText("m-house", fmt$Full(s.house_final));
  setText("m-apt", fmt$Full(s.apt_final));
  setText("m-delta", fmt$Full(s.delta));
  setText("m-winner", `${s.winner} comes out ahead`);
  setText("m-mortgage", fmt$Full(s.monthly_mortgage));
  setText("m-monthly", fmt$Full(s.first_month_house_cost));
  setText(
    "m-cross",
    s.crossover_year != null ? `${s.crossover_year} years` : "—"
  );

  const deltaCard = document.querySelector(".metric-delta");
  if (deltaCard) {
    deltaCard.classList.toggle("negative", s.delta < 0);
  }
}

let inflight = null;
async function recalc() {
  const payload = readForm();
  if (inflight) inflight.abort();
  const ctrl = new AbortController();
  inflight = ctrl;

  try {
    const [simRes, sensRes] = await Promise.all([
      fetch("/api/simulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: ctrl.signal,
      }).then((r) => r.json()),
      fetch("/api/sensitivity", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: ctrl.signal,
      }).then((r) => r.json()),
    ]);

    document.getElementById("results").classList.remove("hidden");
    updateSummary(simRes.summary);
    renderMain(simRes);
    renderBreakdown(simRes);
    renderMonthly(simRes);
    renderSensitivity(sensRes);
  } catch (e) {
    if (e.name !== "AbortError") console.error(e);
  }
}

let debounceTimer;
function scheduleRecalc() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(recalc, 300);
}

document.addEventListener("DOMContentLoaded", () => {
  for (const id of FIELDS) {
    const el = document.getElementById(id);
    if (el) el.addEventListener("input", scheduleRecalc);
  }
  document.getElementById("recalc").addEventListener("click", recalc);
  recalc();
});


/* ===================== Explore sensitivity ===================== */

// Default sweep range for a dimension, derived from the value currently in the form.
const DIM_RANGES = {
  mortgage_rate_pct: [3, 9], investment_return_pct: [2, 10], property_tax_rate_pct: [0.3, 2.5],
  home_appreciation_pct: [0, 6], rent_growth_pct: [0, 6], maintenance_rate_pct: [0, 2.5],
  insurance_rate_pct: [0, 1.5], pmi_rate_pct: [0, 1.5], selling_cost_pct: [0, 10],
  marginal_tax_rate_pct: [0, 45], n_years: [10, 30], hoa: [0, 1200],
  moving_cost: [0, 15000], closing_costs: [0, 30000], realtor_fees: [0, 30000],
  standard_deduction: [0, 40000], salt_cap: [0, 40000], other_itemized: [0, 40000],
};
const PCT_DIMS = new Set(Object.keys(DIM_RANGES).filter((k) => k.endsWith("_pct")));

function defaultRange(key) {
  if (DIM_RANGES[key]) return DIM_RANGES[key];
  const cur = Number(document.getElementById(key)?.value) || 0;
  if (!cur) return [0, 100000];
  const lo = key === "down_payment" ? cur * 0.3 : cur * 0.7;
  const hi = key === "down_payment" ? cur * 2.0 : cur * 1.3;
  return [Math.round(lo), Math.round(hi)];
}

function syncRangeInputs(which) {
  const sel = document.getElementById(`grid_var${which}`);
  const key = sel.value;
  const min = document.getElementById(`grid_var${which}_min`);
  const max = document.getElementById(`grid_var${which}_max`);
  if (!key) { min.value = ""; max.value = ""; min.disabled = max.disabled = true; return; }
  min.disabled = max.disabled = false;
  const [lo, hi] = defaultRange(key);
  min.value = lo;
  max.value = hi;
}

const gridFmt = (v, metric) => {
  if (v == null) return "—";
  if (metric === "crossover") return `${v.toFixed(1)} yr`;
  return fmt$(v);
};

// "Buying ahead by $120k" reads better than "120000" — and says which side won.
const winnerText = (v) => {
  if (v == null) return "—";
  if (Math.abs(v) < 1) return "dead even";
  return v > 0 ? `Buying ahead by ${fmt$(v)}` : `Renting ahead by ${fmt$(-v)}`;
};

function renderGrid(res) {
  const metric = res.metric;
  const legend = document.getElementById("grid_legend");
  const isCross = metric === "crossover";
  const isVs = metric === "delta";
  const metricLabel =
    { delta: "Buy vs Rent", crossover: "Crossover year",
      house_final: "Buying: final wealth", apt_final: "Renting: final wealth" }[metric] || metric;

  if (res.mode === "1d") {
    const traces = [{
      x: res.x, y: res.values, type: "scatter", mode: "lines+markers",
      line: { color: COLORS.house, width: 3 },
      marker: {
        size: 8,
        // Each point takes the colour of whoever wins there.
        color: isVs ? res.values.map((v) => (v >= 0 ? COLORS.good : COLORS.bad)) : COLORS.house,
      },
      text: isVs ? res.values.map(winnerText) : undefined,
      hovertemplate: isVs
        ? `${res.x_label}: %{x}<br>%{text}<extra></extra>`
        : `${res.x_label}: %{x}<br>${metricLabel}: %{y:,.0f}<extra></extra>`,
    }];
    const layout = baseLayout({
      xaxis: { title: res.x_label, zeroline: false },
      yaxis: {
        title: isVs ? "Buying ahead  ←→  Renting ahead" : metricLabel,
        zeroline: true, zerolinecolor: COLORS.ink, zerolinewidth: 1.5,
      },
    });
    Plotly.react("chart-grid", traces, layout, { displayModeBar: false, responsive: true });
    legend.textContent = isCross
      ? "Gaps mean buying never overtakes renting within the horizon."
      : (isVs ? "Above the line buying ends ahead; below it renting does." : "");
    return;
  }

  // 2-D: heatmap. For delta, a diverging scale centred on zero reads as "who wins".
  const flat = res.z.flat().filter((v) => v != null);
  const maxAbs = Math.max(...flat.map(Math.abs), 1);
  const colorscale = metric === "delta"
    ? [[0, "#dc2626"], [0.5, "#f8fafc"], [1, "#16a34a"]]
    : [[0, "#eff6ff"], [1, "#1d4ed8"]];
  const trace = {
    x: res.x, y: res.y, z: res.z, type: "heatmap", colorscale,
    zmid: metric === "delta" ? 0 : undefined,
    zmin: metric === "delta" ? -maxAbs : undefined,
    zmax: metric === "delta" ? maxAbs : undefined,
    hoverongaps: false,
    text: isVs ? res.z.map((row) => row.map(winnerText)) : undefined,
    hovertemplate: isVs
      ? `${res.x_label}: %{x}<br>${res.y_label}: %{y}<br>%{text}<extra></extra>`
      : `${res.x_label}: %{x}<br>${res.y_label}: %{y}<br>${metricLabel}: %{z:,.0f}<extra></extra>`,
    colorbar: {
      title: { text: isVs ? "buying ahead →" : (isCross ? "years" : "$"), side: "right" },
      thickness: 14,
    },
  };
  const layout = baseLayout({
    xaxis: { title: res.x_label, type: "category" },
    yaxis: { title: res.y_label, type: "category" },
  });
  Plotly.react("chart-grid", [trace], layout, { displayModeBar: false, responsive: true });
  legend.textContent = isCross
    ? "Blank cells mean buying never overtakes renting within the horizon."
    : (isVs ? "Green = buying ends ahead, red = renting does, white = too close to call." : "");
}

async function runGrid() {
  const status = document.getElementById("grid_status");
  const v1 = document.getElementById("grid_var1").value;
  const v2 = document.getElementById("grid_var2").value;
  if (v1 && v2 && v1 === v2) {
    status.textContent = "Pick two different variables.";
    return;
  }
  const body = {
    ...readForm(),
    metric: document.getElementById("grid_metric").value,
    var1: {
      key: v1,
      min: Number(document.getElementById("grid_var1_min").value),
      max: Number(document.getElementById("grid_var1_max").value),
      steps: Number(document.getElementById("grid_var1_steps").value),
    },
    var2: v2 ? {
      key: v2,
      min: Number(document.getElementById("grid_var2_min").value),
      max: Number(document.getElementById("grid_var2_max").value),
      steps: Number(document.getElementById("grid_var2_steps").value),
    } : null,
  };
  status.textContent = "Running…";
  try {
    const res = await fetch("/api/grid", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }).then((r) => r.json());
    if (res.error) { status.textContent = res.error; return; }
    renderGrid(res);
    const cells = res.mode === "2d" ? res.x.length * res.y.length : res.x.length;
    status.textContent = `${cells} scenarios`;
  } catch (e) {
    status.textContent = "Couldn't run that — check the ranges.";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const v1 = document.getElementById("grid_var1");
  const v2 = document.getElementById("grid_var2");
  if (!v1) return;
  v1.addEventListener("change", () => { syncRangeInputs(1); runGrid(); });
  v2.addEventListener("change", () => { syncRangeInputs(2); runGrid(); });
  document.getElementById("grid_metric").addEventListener("change", runGrid);
  document.getElementById("grid_run").addEventListener("click", runGrid);
  syncRangeInputs(1);
  syncRangeInputs(2);
  // Show a result immediately — the default pair (investment return x mortgage rate) is the one
  // most worth seeing, and waiting for a click hides the whole feature.
  runGrid();
});


/* ===================== ZIP lookup ===================== */

async function fetchZip() {
  const box = document.getElementById("zip_result");
  const zip = (document.getElementById("zip_code").value || "").trim();
  if (!/^\d{5}$/.test(zip)) { box.textContent = "Enter a 5-digit ZIP code."; return; }
  box.textContent = "Looking up… (first lookup downloads Zillow's data, ~10s)";

  const res = await fetch(`/api/zip/${zip}`).then((r) => r.json()).catch(() => null);
  if (!res || (!res.place && !Object.keys(res.fields || {}).length)) {
    box.textContent = "Couldn't find data for that ZIP.";
    return;
  }
  const LABELS = {
    home_price: "Home price", monthly_rent: "Monthly rent",
    home_appreciation_pct: "Home appreciation", rent_growth_pct: "Rent increases",
    property_tax_rate_pct: "Property tax",
  };
  const entries = Object.entries(res.fields);
  const lines = entries.map(([k, f]) => {
    const isPct = k.endsWith("_pct");
    const val = isPct ? `${f.value}%` : fmt$Full(f.value);
    const tag = f.estimated ? '<span class="est">estimated</span>' : "";
    return `<li><strong>${LABELS[k] || k}:</strong> ${val} ${tag}
            <span class="src">— ${f.source}, ${f.asof}</span></li>`;
  });
  box.innerHTML =
    `<div class="zip-place">${res.place || zip}</div>` +
    (lines.length ? `<ul>${lines.join("")}</ul>` : "<div>No data for this ZIP.</div>") +
    (res.warnings?.length ? `<div class="src">${res.warnings.join(" ")}</div>` : "") +
    (lines.length ? `<button id="zip_apply" class="btn zip-apply">Use these values</button>` : "");

  const applyBtn = document.getElementById("zip_apply");
  if (applyBtn) {
    applyBtn.addEventListener("click", () => {
      for (const [k, f] of entries) {
        const el = document.getElementById(k);
        if (el) el.value = f.value;
      }
      // Keep the down payment at the same share of the price it was before.
      recalc();
      runGrid();
      applyBtn.textContent = "Applied";
      setTimeout(() => (applyBtn.textContent = "Use these values"), 1600);
    });
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("zip_fetch");
  if (!btn) return;
  btn.addEventListener("click", fetchZip);
  document.getElementById("zip_code").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); fetchZip(); }
  });
});
