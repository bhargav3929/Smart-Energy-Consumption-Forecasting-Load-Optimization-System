"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const NODES = [
  [1, "Appliance Log & City Gatekeeper"], [2, "7-Day Weather & Cooling/Heating Telemetry"],
  [3, "Monthly Bill & Peak-Load Shaving Engine"], [4, "Groq Load-Optimization Strategist"], [5, "Report & SQLite Persistence"],
];
const state = { demo: false, selectedPreset: null, rows: [], label: "", presets: [], forecast: null, running: false, events: [], timer: null, t0: 0, view: "bill", currentId: null };

// ---------- demo ticket + relative API helper ----------
// The app may be served under a sub-path, so every URL is relative (api/info, never /api/info).
let TICKET = "";
try {
  const u = new URL(location.href), t = u.searchParams.get("ticket");
  if (t) { sessionStorage.setItem("lastsem_ticket", t); u.searchParams.delete("ticket"); history.replaceState(null, "", u.pathname + u.search + u.hash); }
  TICKET = sessionStorage.getItem("lastsem_ticket") || "";
} catch {}
function api(url, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (TICKET) headers["X-LastSem-Ticket"] = TICKET;
  return fetch(url, { ...opts, headers });
}

// ---------- formatting ----------
const cur = () => (state.forecast ? state.forecast.currency : "₹");
const fmtMoney = (n, c = cur()) => c + Number(n).toLocaleString(c === "₹" ? "en-IN" : "en-US", { maximumFractionDigits: c === "₹" ? 0 : 2, minimumFractionDigits: c === "₹" ? 0 : 2 });
const fmt = (n, d = 1) => Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const hh = (h) => String(h).padStart(2, "0") + ":00";

// ---------- status ----------
function setPill(text, low, title) { const p = $("#quotaPill"); p.textContent = text; p.classList.toggle("low", !!low); p.title = title || ""; }
async function loadStatus() {
  try {
    const s = await (await api("api/info")).json();
    state.demo = s.mode === "demo"; $("#keysBtn").hidden = state.demo;
    if (state.demo) {
      const d = s.demo || {};
      if (!d.ticket_valid) setPill("Samples only · sign in on lastsem.com to run your own", true);
      else if (d.daily_cap_reached) setPill("Demo daily limit reached · samples still work", true);
      else setPill(`${d.runs_left} live run${d.runs_left === 1 ? "" : "s"} left on this ticket`, d.runs_left < 1);
    } else if (s.ai.ready) setPill("Groq AI ready", false, "Model: " + s.ai.model);
    else setPill("No Groq key · click API Keys", true, "Paste your free key from console.groq.com/keys");
    return s;
  } catch { return null; }
}

// ---------- input panel ----------
function renderPresets() {
  $("#presets").innerHTML = state.presets.map((p) => `<button class="preset" data-id="${esc(p.id)}">${esc(p.title)}</button>`).join("");
}
function hourOptions(sel) {
  return Array.from({ length: 24 }, (_, h) => `<option value="${h}" ${h === +sel ? "selected" : ""}>${hh(h)}${h >= 18 && h < 22 ? " (peak)" : ""}</option>`).join("");
}
function renderRows() {
  $("#logBody").innerHTML = state.rows.map((r, i) => `
    <tr data-i="${i}">
      <td><input type="text" data-f="name" value="${esc(r.name)}" maxlength="60" aria-label="Appliance name"></td>
      <td><input type="number" data-f="watts" value="${esc(r.watts)}" min="1" step="any" aria-label="Power in watts"></td>
      <td><input type="number" data-f="hours_per_day" value="${esc(r.hours_per_day)}" min="0" max="24" step="any" aria-label="Hours per day"></td>
      <td><select data-f="peak_hour" aria-label="Preferred run window start">${hourOptions(r.peak_hour)}</select></td>
      <td><label class="switch"><input type="checkbox" data-f="shiftable" ${r.shiftable ? "checked" : ""} aria-label="Shiftable"><i></i></label></td>
      <td><button class="del" data-del="${i}" aria-label="Remove row">×</button></td>
    </tr>`).join("") || `<tr><td colspan="6" class="muted" style="padding:12px">No appliances yet — add a row, upload a log, or pick a preset.</td></tr>`;
}
function setRows(rows) { state.rows = rows.map((r) => ({ name: r.name, watts: r.watts, hours_per_day: r.hours_per_day, peak_hour: +r.peak_hour, shiftable: !!r.shiftable })); renderRows(); }
function msg(el, text, kind = "") { el.textContent = text; el.className = "msg " + kind; }

$("#presets").addEventListener("click", (e) => {
  const b = e.target.closest(".preset"); if (!b) return;
  const p = state.presets.find((x) => x.id === b.dataset.id);
  $$(".preset").forEach((x) => x.classList.toggle("on", x === b));
  state.selectedPreset = p.id; $("#viewSaved").hidden = false;
  $("#city").value = p.city; state.label = p.title.split(" — ")[0]; setRows(p.appliances);
  msg($("#inputMsg"), `Loaded preset: ${p.short}. Press Run Forecast & Optimize.`, "ok");
});
$("#logBody").addEventListener("input", (e) => {
  const tr = e.target.closest("tr[data-i]"); if (!tr) return;
  const f = e.target.dataset.f, r = state.rows[+tr.dataset.i];
  r[f] = f === "shiftable" ? e.target.checked : f === "name" ? e.target.value : e.target.value === "" ? "" : +e.target.value;
  state.label = "";
});
$("#logBody").addEventListener("click", (e) => {
  const d = e.target.closest("[data-del]"); if (!d) return;
  state.rows.splice(+d.dataset.del, 1); renderRows();
});
$("#addRow").addEventListener("click", () => { state.rows.push({ name: "", watts: 1000, hours_per_day: 2, peak_hour: 18, shiftable: false }); renderRows(); });
$("#fileIn").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (!f) return;
  const fd = new FormData(); fd.append("file", f);
  try {
    const r = await api("api/parse-log", { method: "POST", body: fd });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || "Upload failed");
    setRows(j.appliances); state.label = "Uploaded log";
    msg($("#inputMsg"), `Loaded ${j.appliances.length} rows from ${f.name}.` + (j.warnings.length ? " Skipped: " + j.warnings.join(" ") : ""), j.warnings.length ? "err" : "ok");
  } catch (err) { msg($("#inputMsg"), err.message, "err"); }
  e.target.value = "";
});
$("#sampleCsv").addEventListener("click", () => {
  const csv = "appliance,watts,hours_per_day,peak_hour,shiftable\nAir Conditioner,1500,8,21,false\nGeyser,2000,1.5,19,true\nEV Charger,3300,4,19,true\nRefrigerator,75,24,0,false\nWashing Machine,500,1.5,18,true\nLED Lighting,200,6,18,false\n";
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" })); a.download = "sample_appliance_log.csv"; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
});

// ---------- run + stream ----------
function renderStepper(status = {}) {
  $("#stepper").innerHTML = NODES.map(([id, name]) => {
    const s = status[id] || {};
    return `<li class="${s.status || ""}"><b>${id}. ${esc(name)}</b><span class="ms">${s.status === "done" ? s.ms + " ms" : s.status === "running" ? "running…" : s.status === "error" ? "failed" : "waiting"}</span></li>`;
  }).join("");
}
function startTimer() {
  state.t0 = performance.now();
  clearInterval(state.timer);
  state.timer = setInterval(() => { $("#timer").textContent = ((performance.now() - state.t0) / 1000).toFixed(1) + "s"; }, 100);
}
function stopTimer() {
  clearInterval(state.timer);
  $("#timer").textContent = ((performance.now() - state.t0) / 1000).toFixed(1) + "s";
}
function showAlert(t) { const a = $("#alert"); a.hidden = !t; a.textContent = t || ""; }

async function runForecast() {
  if (state.running) return;
  showAlert("");
  const city = $("#city").value.trim();
  if (!city) return msg($("#inputMsg"), "Enter a city first.", "err");
  if (!state.rows.length) return msg($("#inputMsg"), "Add at least one appliance row.", "err");
  msg($("#inputMsg"), "");
  state.running = true; state.events = []; $("#runBtn").disabled = true; $("#runBtn").textContent = "Running pipeline…";
  const status = {}; renderStepper(status); startTimer(); renderDebug(null);
  let finished = false;
  try {
    const res = await api("api/forecast", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ city, label: state.label, appliances: state.rows }) });
    if (!res.ok) { const j = await res.json().catch(() => ({})); if (j.code === "AI_NOT_CONFIGURED" && !state.demo) openModal(); throw new Error(j.error || "Request failed (" + res.status + ")"); }
    const reader = res.body.getReader(), dec = new TextDecoder(); let buf = "";
    const handle = (line) => {
      if (!line.trim()) return;
      const ev = JSON.parse(line);
      state.events.push(ev.type === "result" ? { type: "result", forecast_id: ev.forecast_id, data: "…(full forecast payload, " + line.length + " bytes)" } : ev);
      if (ev.type === "node") status[ev.id] = { status: ev.status, ms: ev.ms }; renderStepper(status);
      if (ev.type === "error") { if (ev.node) status[ev.node] = { status: "error" }; renderStepper(status); showAlert(ev.error || ev.message); if (ev.code === "AI_NOT_CONFIGURED" && !state.demo) openModal(); if (ev.code === "AI_KEY_INVALID" && !state.demo) openModal(); finished = true; }
      if (ev.type === "result") { finished = true; state.forecast = ev.data; state.currentId = ev.forecast_id; renderForecast(ev.data); }
      renderDebug(state.forecast && state.events.some((x) => x.type === "result") ? state.forecast : null);
    };
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split("\n"); buf = lines.pop(); lines.forEach(handle);
    }
    if (buf.trim()) handle(buf);
  } catch (err) { showAlert(err.message); }
  stopTimer(); state.running = false; $("#runBtn").disabled = false; $("#runBtn").textContent = "Run Forecast & Optimize";
  if (!finished) showAlert("The pipeline ended unexpectedly. Please retry.");
  loadStatus();
}
$("#runBtn").addEventListener("click", runForecast);

// ---------- debug panel ----------
function renderDebug(f) {
  const body = $("#debugBody");
  const dbg = f && f.debug;
  const nodeRows = (dbg ? dbg.nodes : []).map((n) => `<tr><td>${n.id}. ${esc(n.name)}</td><td class="r">${n.ms} ms</td></tr>`).join("");
  let html = "";
  if (dbg) {
    const model = dbg.groq_model ? `${esc(dbg.groq_model)} ${dbg.groq_fallback ? '<span class="badge">(fallback)</span>' : '<span class="badge green">primary</span>'}` : '<span class="badge">no Groq call</span>';
    html += `<table class="dtable"><thead><tr><th>Node</th><th class="r">Time</th></tr></thead><tbody>${nodeRows}</tbody></table>
      <table class="dtable"><tbody>
        <tr><td>Open-Meteo geocoding latency</td><td class="r">${dbg.geocode_ms ?? "–"} ms</td></tr>
        <tr><td>Open-Meteo forecast latency (${esc(dbg.weather_source || "–")})</td><td class="r">${dbg.weather_ms ?? "–"} ms</td></tr>
        <tr><td>Groq latency</td><td class="r">${dbg.groq_ms ?? "–"} ms</td></tr>
        <tr><td>Active Groq model</td><td class="r" style="font-family:var(--sans)">${model}</td></tr>
        <tr><td>Total pipeline time</td><td class="r">${dbg.total_ms ?? "–"} ms</td></tr></tbody></table>`;
    if (dbg.notes && dbg.notes.length) html += `<p class="muted small">${dbg.notes.map(esc).join("<br>")}</p>`;
  } else if (state.running) html += `<p class="muted">Pipeline running…</p>`;
  else html += `<p class="muted">Per-node timings appear after a forecast finishes.</p>`;
  if (state.events.length) html += `<div><b>Raw NDJSON events</b><pre>${esc(state.events.map((e) => JSON.stringify(e)).join("\n"))}</pre></div>`;
  body.innerHTML = html;
}

// ---------- views ----------
function setView(v) {
  state.view = v;
  $$(".tab").forEach((t) => { const on = t.dataset.view === v; t.classList.toggle("active", on); t.setAttribute("aria-selected", on); });
  ["bill", "compare", "report"].forEach((x) => { $("#view-" + x).hidden = x !== v || !state.forecast; });
}
$$(".tab").forEach((t) => t.addEventListener("click", () => setView(t.dataset.view)));

function renderForecast(f) {
  state.forecast = f; $("#empty").hidden = true;
  $("#view-bill").innerHTML = billView(f); $("#view-compare").innerHTML = compareView(f); $("#view-report").innerHTML = reportView(f);
  drawChart($("#chart"), f.energy.baseline_curve, f.energy.optimized_curve, f.currency);
  setView(state.view);
}

function billView(f) {
  const e = f.energy, w = f.weather, c = f.currency, b1 = e.bill_breakdown_baseline, b2 = e.bill_breakdown_optimized;
  const wx = (w.daily || []).map((d) => `<div>${esc(d.date.slice(5))}<b>${d.avg}°</b><span class="muted">${d.min}–${d.max}</span></div>`).join("");
  return `
  <div class="kpis">
    <div class="kpi"><div class="k">Daily consumption</div><div class="v">${fmt(e.daily_kwh_baseline)} kWh</div><div class="s">${fmt(e.daily_kwh_unadjusted)} kWh before weather</div></div>
    <div class="kpi"><div class="k">30-day projected</div><div class="v">${fmt(e.month_kwh, 0)} kWh</div><div class="s">+${fmt(e.weather_extra_kwh_month)} kWh from weather</div></div>
    <div class="kpi accent"><div class="k">Monthly bill (weather-adjusted)</div><div class="v">${fmtMoney(e.bill_baseline, c)}</div><div class="s">Optimized: <b class="num">${fmtMoney(e.bill_optimized, c)}</b></div></div>
    <div class="kpi warn"><div class="k">Cooling degree factor</div><div class="v">×${fmt(w.cooling_degree_factor, 2)}</div><div class="s">${w.avg_temp != null ? `avg ${w.avg_temp} °C · ${esc(f.city.name)}` : "weather unavailable"}</div></div>
  </div>
  <div class="card"><div class="head"><h3>24-hour load profile · ${esc(f.title)}</h3>
    <div class="legend"><span><i style="background:var(--copper)"></i>Baseline kW</span><span><i style="background:var(--sage)"></i>Optimized kW</span><span><i class="pk"></i>Peak tariff 18:00–22:00</span></div></div>
    <div class="chart-wrap" id="chartWrap"><div id="chart"></div><div class="tip" id="tip"></div></div>
    <p class="muted small">Peak demand ${fmt(e.peak_kw_before, 2)} kW → ${fmt(e.peak_kw_after, 2)} kW. Hover the chart for hourly values.</p></div>
  <div class="card"><h3>Appliance-by-appliance shift schedule</h3><div class="table-wrap"><table class="dtable"><thead><tr><th>Appliance</th><th>Action</th><th>Current window</th><th>Suggested window</th><th class="r">kWh/day</th><th class="r">Saves/mo</th></tr></thead><tbody>
  ${f.schedule.map((s) => `<tr><td>${esc(s.appliance)}<br><span class="muted small num">${fmt(s.watts, 0)} W · ${s.hours} h</span></td><td><span class="tag ${esc(s.action)}">${s.action === "shift" ? "Shift" : s.action === "precool" ? "Pre-cool" : "Keep"}</span></td><td class="num">${esc(s.original_window)}</td><td class="num">${esc(s.new_window)}${s.note ? `<br><span class="muted small" style="font-family:var(--sans)">${esc(s.note)}</span>` : ""}</td><td class="r">${fmt(s.daily_kwh, 2)}</td><td class="r">${s.monthly_saving ? fmtMoney(s.monthly_saving, c) : "–"}</td></tr>`).join("")}
  </tbody></table></div></div>
  <div class="grid2">
    <div class="card"><h3>Bill breakdown (tiered + ToU)</h3><table class="dtable"><thead><tr><th></th><th class="r">Baseline</th><th class="r">Optimized</th></tr></thead><tbody>
      <tr><td>Tiered energy charge</td><td class="r">${fmtMoney(b1.energy, c)}</td><td class="r">${fmtMoney(b2.energy, c)}</td></tr>
      <tr><td>ToU peak surcharge / off-peak credit</td><td class="r">${fmtMoney(b1.tou, c)}</td><td class="r">${fmtMoney(b2.tou, c)}</td></tr>
      <tr><td>Fixed charge</td><td class="r">${fmtMoney(b1.fixed, c)}</td><td class="r">${fmtMoney(b2.fixed, c)}</td></tr>
      <tr><td><b>Total</b></td><td class="r"><b>${fmtMoney(b1.total, c)}</b></td><td class="r"><b>${fmtMoney(b2.total, c)}</b></td></tr></tbody></table>
      <p class="muted small">${esc(f.tariff.label)}: peak +${c}${f.tariff.peak_surcharge}/kWh (18–22h), off-peak −${c}${f.tariff.off_discount}/kWh (22–06h).</p></div>
    <div class="card"><h3>7-day weather · ${esc(f.city.name)}, ${esc(f.city.country)}</h3><div class="wx">${wx || '<span class="muted">No weather data</span>'}</div>
      <p class="muted small">Open-Meteo hourly temperature &amp; solar radiation → cooling factor ×${fmt(w.cooling_degree_factor, 2)}${w.heating > 1 ? `, heating ×${fmt(w.heating, 2)}` : ""}. Extra weather cost: ${fmtMoney(e.weather_extra_cost_month, c)}/month.</p></div>
  </div>`;
}

function compareView(f) {
  const c = f.currency, maxBill = Math.max(...f.scenarios.map((s) => s.bill), 1), maxKwh = Math.max(...f.benchmark.map((b) => b.daily_kwh), f.energy.daily_kwh_baseline, 1);
  const maxShare = Math.max(...f.per_appliance.map((p) => p.kwh_day), 1);
  return `
  <div class="card"><h3>Scenario comparison</h3><div class="table-wrap"><table class="dtable"><thead><tr><th>Scenario</th><th class="r">kWh/day</th><th class="r">Peak kW</th><th class="r">Monthly bill</th><th style="width:160px"></th><th class="r">Savings</th><th class="r">CO₂ / mo</th></tr></thead><tbody>
  ${f.scenarios.map((s, i) => `<tr><td>${esc(s.name)}</td><td class="r">${fmt(s.daily_kwh, 2)}</td><td class="r">${fmt(s.peak_kw, 2)}</td><td class="r">${fmtMoney(s.bill, c)}</td><td><div class="bar ${i ? "g" : ""}"><i style="width:${s.bill / maxBill * 100}%"></i></div></td><td class="r">${i ? `${fmtMoney(s.savings, c)} (${s.savings_pct}%)` : "–"}</td><td class="r">${fmt(s.co2_kg, 0)} kg</td></tr>`).join("")}
  </tbody></table></div><p class="muted small">Thermostat scenario assumes ~6% less cooling energy per °C raised (12% for +2 °C).</p></div>
  <div class="grid2">
    <div class="card"><h3>Facility compare · same weather &amp; tariff</h3>
      ${[{ name: "This log", daily_kwh: f.energy.daily_kwh_baseline, bill: f.energy.bill_baseline, peak_kw: f.energy.peak_kw_before, savings_pct: f.energy.savings_pct, me: true }, ...f.benchmark].map((b) => `
      <div style="margin:10px 0"><div style="display:flex;justify-content:space-between;gap:8px"><span>${b.me ? "<b>This log</b>" : esc(b.name)}</span><span class="num">${fmt(b.daily_kwh)} kWh/day · ${fmtMoney(b.bill, c)}/mo · −${b.savings_pct}%</span></div>
      <div class="bar ${b.me ? "" : "g"}"><i style="width:${b.daily_kwh / maxKwh * 100}%"></i></div></div>`).join("")}
      <p class="muted small">Benchmarks run the four built-in presets through the same engine using this city's weather.</p></div>
    <div class="card"><h3>Where the energy goes</h3>
      ${f.per_appliance.map((p) => `<div style="margin:9px 0"><div style="display:flex;justify-content:space-between;gap:8px"><span>${esc(p.name)}</span><span class="num">${fmt(p.kwh_day, 2)} kWh · ${p.share_pct}%</span></div><div class="bar"><i style="width:${p.kwh_day / maxShare * 100}%"></i></div></div>`).join("")}</div>
  </div>`;
}

function reportView(f) {
  const e = f.energy, c = f.currency, s = f.strategist;
  const src = s.source === "groq" ? `<span class="badge green">Groq · ${esc(s.model)}</span>${s.fallback ? ' <span class="badge">(fallback)</span>' : ""}` : '<span class="badge">Deterministic energy-audit rules</span>';
  return `
  <div class="kpis">
    <div class="kpi good"><div class="k">Peak-load reduction</div><div class="v">${fmt(e.peak_reduction_pct)}%</div><div class="s">${fmt(e.peak_shaved_kw, 2)} kW shaved (${fmt(e.peak_kw_before, 2)} → ${fmt(e.peak_kw_after, 2)})</div></div>
    <div class="kpi good"><div class="k">Monthly cost savings</div><div class="v">${fmtMoney(e.savings_month, c)}</div><div class="s">${e.savings_pct}% of ${fmtMoney(e.bill_baseline, c)}</div></div>
    <div class="kpi good"><div class="k">Carbon reduction</div><div class="v">${fmt(e.co2_saved_kg, 0)} kg</div><div class="s">CO₂ per month (${fmt(e.co2_before_kg, 0)} → ${fmt(e.co2_after_kg, 0)})</div></div>
    <div class="kpi warn"><div class="k">Peak-window energy</div><div class="v">${fmt(e.peak_window_kwh_after, 1)} kWh</div><div class="s">per day, down from ${fmt(e.peak_window_kwh_before, 1)} kWh (18–22h)</div></div>
  </div>
  <div class="card"><div class="head"><h3>Strategist summary</h3><div>${src}</div></div>
    <p>${esc(s.summary)}</p>
    <h3 style="margin-top:14px">Appliance scheduling actions</h3>
    ${s.actions.map((a) => `<div class="act"><b>${esc(a.appliance)} — ${esc(a.action)}</b><span>${esc(a.reason)}</span></div>`).join("")}
  </div>
  <div class="grid2">
    <div class="card"><h3>Thermostat set-point adjustments</h3><ul class="list">${s.thermostat.map((t) => `<li>${esc(t)}</li>`).join("")}</ul></div>
    <div class="card"><h3>Peak-tariff avoidance tips</h3><ul class="list">${s.tips.map((t) => `<li>${esc(t)}</li>`).join("")}</ul></div>
  </div>
  <div><button class="btn" onclick="window.print()">Print / save report as PDF</button></div>`;
}

// ---------- SVG dual-curve chart ----------
function drawChart(el, base, opt) {
  const W = 760, H = 320, L = 46, R = 12, T = 14, B = 34, pw = W - L - R, ph = H - T - B;
  const max = Math.max(...base, ...opt, 0.1), top = Math.ceil(max * 1.15 * 2) / 2 || 1;
  const X = (h) => L + (h / 24) * pw, Y = (v) => T + ph - (v / top) * ph;
  const step = (arr) => arr.map((v, i) => `${i ? "L" : "M"}${X(i)},${Y(v)}L${X(i + 1)},${Y(v)}`).join("");
  let g = "";
  const ticks = 5;
  for (let i = 0; i <= ticks; i++) { const v = (top / ticks) * i; g += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="#E6DFD5" stroke-width="1"/><text x="${L - 6}" y="${Y(v) + 4}" text-anchor="end" font-size="11" fill="#7A6F66" font-family="ui-monospace,monospace">${v.toFixed(1)}</text>`; }
  for (let h = 0; h <= 24; h += 3) g += `<text x="${X(h)}" y="${H - 12}" text-anchor="middle" font-size="11" fill="#7A6F66" font-family="ui-monospace,monospace">${hh(h % 24)}</text>`;
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="24-hour baseline versus optimized load in kW">
    <rect x="${X(18)}" y="${T}" width="${X(22) - X(18)}" height="${ph}" fill="#B45309" opacity=".14"/>
    <text x="${(X(18) + X(22)) / 2}" y="${T + 13}" text-anchor="middle" font-size="11" fill="#B45309" font-weight="600">PEAK TARIFF</text>
    ${g}
    <text transform="translate(12 ${T + ph / 2}) rotate(-90)" text-anchor="middle" font-size="11" fill="#7A6F66">Load (kW)</text>
    <path d="${step(opt)}" fill="none" stroke="#15803D" stroke-width="2.5" stroke-linejoin="round"/>
    <path d="${step(base)}" fill="none" stroke="#C2410C" stroke-width="2.5" stroke-linejoin="round" stroke-dasharray="6 3"/>
    <rect id="hov" y="${T}" width="${pw / 24}" height="${ph}" fill="#1F1A17" opacity="0"/>
    <rect id="hit" x="${L}" y="${T}" width="${pw}" height="${ph}" fill="transparent"/></svg>`;
  const svg = $("svg", el), hov = $("#hov", el), tip = $("#tip"), wrap = $("#chartWrap");
  const move = (ev) => {
    const r = svg.getBoundingClientRect(), x = ((ev.clientX - r.left) / r.width) * W;
    const h = Math.max(0, Math.min(23, Math.floor(((x - L) / pw) * 24)));
    hov.setAttribute("x", X(h)); hov.setAttribute("opacity", ".07");
    tip.innerHTML = `${hh(h)}–${hh((h + 1) % 24)}${h >= 18 && h < 22 ? " · peak" : ""}<br>Baseline <b>${base[h].toFixed(2)}</b> kW<br>Optimized <b>${opt[h].toFixed(2)}</b> kW`;
    const wr = wrap.getBoundingClientRect();
    tip.style.left = Math.min(Math.max(ev.clientX - wr.left, 70), wr.width - 70) + "px";
    tip.style.top = (((Y(Math.max(base[h], opt[h])) / H) * r.height) + (r.top - wr.top)) + "px"; tip.style.opacity = 1;
  };
  $("#hit", el).addEventListener("mousemove", move);
  $("#hit", el).addEventListener("mouseleave", () => { tip.style.opacity = 0; hov.setAttribute("opacity", "0"); });
}

// ---------- history drawer ----------
const drawer = $("#drawer"), scrim = $("#scrim");
function openDrawer() { drawer.hidden = scrim.hidden = false; loadHistory(); }
function closeDrawer() { drawer.hidden = scrim.hidden = true; }
$("#historyBtn").addEventListener("click", openDrawer); $("#drawerClose").addEventListener("click", closeDrawer); scrim.addEventListener("click", () => { closeDrawer(); closeModal(); });
async function loadHistory() {
  const list = await (await api("api/history")).json();
  $("#historyList").innerHTML = list.map((h) => `<li><button class="hitem ${h.id === state.currentId ? "on" : ""}" data-id="${h.id}"><b>${esc(h.title)}</b><span>${new Date(h.created_at * 1000).toLocaleString()}${h.daily_kwh != null ? ` · ${fmt(h.daily_kwh)} kWh/day` : ""}</span></button><button class="hdel" data-del="${h.id}" aria-label="Delete forecast">Delete</button></li>`).join("") || '<li class="muted">No saved forecasts yet.</li>';
  return list;
}
async function loadForecast(id) {
  const r = await api("api/history/" + id); if (!r.ok) return;
  const f = await r.json(); state.currentId = id; state.events = [];
  $("#city").value = f.city.name; state.label = f.title.split(" · ")[0]; setRows(f.appliances);
  renderForecast(f); renderDebug(f);
  const st = {}; (f.debug.nodes || []).forEach((n) => (st[n.id] = { status: "done", ms: n.ms })); renderStepper(st);
}
$("#historyList").addEventListener("click", async (e) => {
  const d = e.target.closest("[data-del]"), o = e.target.closest(".hitem");
  if (d) {
    const id = +d.dataset.del;
    await api("api/history/" + id, { method: "DELETE" });
    if (id === state.currentId) { state.forecast = null; state.currentId = null; ["bill", "compare", "report"].forEach((v) => ($("#view-" + v).innerHTML = "")); $("#empty").hidden = false; setView(state.view); }
    loadHistory();
  } else if (o) { await loadForecast(+o.dataset.id); closeDrawer(); }
});

// ---------- API keys modal ----------
const modal = $("#modal");
async function openModal() {
  modal.hidden = false; msg($("#keyMsg"), ""); $("#groqKey").value = "";
  try { await refreshKeyState(); } catch { $("#keyState").textContent = ""; }
}
function closeModal() { modal.hidden = true; }
$("#keysBtn").addEventListener("click", openModal); $("#modalClose").addEventListener("click", closeModal);
modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeModal(); closeDrawer(); } });
$("#testKey").addEventListener("click", async () => {
  msg($("#keyMsg"), "Testing…");
  try {
    const r = await (await api("api/keys/test", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ groq_api_key: $("#groqKey").value.trim() }) })).json();
    msg($("#keyMsg"), r.message, r.ok ? "ok" : "err");
  } catch (e) { msg($("#keyMsg"), e.message, "err"); }
});
async function refreshKeyState() {
  const k = await (await api("api/keys")).json();
  const g = k.groq || {};
  $("#keyState").textContent = g.configured ? `A key is configured (${g.masked}, from ${g.source === "ui" ? "this app" : ".env"}).` : "No key configured yet.";
}
$("#saveKey").addEventListener("click", async () => {
  const key = $("#groqKey").value.trim();
  try {
    const res = key
      ? await api("api/keys", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ groq_api_key: key }) })
      : await api("api/keys/groq", { method: "DELETE" });
    const j = await res.json();
    if (!res.ok) return msg($("#keyMsg"), j.error || "Could not save", "err");
    msg($("#keyMsg"), key ? "Key saved." : "Saved key cleared.", "ok");
    $("#groqKey").value = "";
    await refreshKeyState(); loadStatus();
  } catch (e) { msg($("#keyMsg"), e.message, "err"); }
});

// ---------- saved sample results (shown instantly, no AI call) ----------
$("#viewSaved").addEventListener("click", async () => {
  if (!state.selectedPreset) return;
  try {
    const r = await api("api/samples/" + encodeURIComponent(state.selectedPreset));
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || "Could not load the saved result");
    if (!j.result) return msg($("#inputMsg"), "No saved result for this sample yet. Press Run Forecast & Optimize.", "err");
    state.forecast = j.result; state.currentId = null; state.events = [];
    showAlert(""); renderForecast(j.result); renderDebug(j.result);
    const st = {}; (j.result.debug.nodes || []).forEach((n) => (st[n.id] = { status: "done", ms: n.ms })); renderStepper(st);
    msg($("#inputMsg"), "Showing the saved result for this sample.", "ok");
  } catch (e) { msg($("#inputMsg"), e.message, "err"); }
});

// ---------- init ----------
(async function init() {
  renderStepper(); renderRows(); renderDebug(null);
  loadStatus();
  try { state.presets = await (await api("api/presets")).json(); renderPresets(); } catch {}
  try {
    const list = await (await api("api/history")).json();
    if (list.length) { await loadForecast(list[0].id); }
  } catch {}
})();
