(function () {
  "use strict";

  const refreshMs = Math.max(2, parseInt(document.body.dataset.refresh, 10) || 5) * 1000;
  const $ = (id) => document.getElementById(id);
  const onlyProblems = $("only-problems");
  let lastSnapshot = null;

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  const slug = (status) => String(status || "unknown").toLowerCase().replace(/\s+/g, "-");
  const num = (v) => (v === null || v === undefined ? "–" : v);

  function toolRow(r) {
    const statusCls = r.status === "OK" ? "st-ok" : r.status === "NOT OK" ? "st-not-ok" : "";
    const modeCls = r.mode === "BYPASS" ? "mode-bypass" : "";
    return `<tr>
      <td><b>${esc(r.tag)}</b>${r.torque_nm !== null ? ` · ${esc(r.torque_nm)} Nm` : ""}
        <div class="tool-name">${esc(r.name)}</div></td>
      <td class="${modeCls}">${esc(r.mode || "–")}</td>
      <td class="num">${esc(num(r.actual_count))} / ${esc(num(r.set_count))}</td>
      <td class="${statusCls}">${esc(r.status)}</td>
    </tr>`;
  }

  function stationCard(s) {
    const body = s.records.length
      ? `<table class="tools">
           <thead><tr><th>Tool</th><th>Mode</th><th class="num">Act / Set</th><th>Status</th></tr></thead>
           <tbody>${s.records.map(toolRow).join("")}</tbody>
         </table>`
      : `<div class="no-data">No tightening data yet for this vehicle</div>`;
    return `<article class="station s-${slug(s.status)}">
      <div class="station-head">
        <span class="station-no">Station ${esc(s.station)}</span>
        <span class="status-pill pill-${slug(s.status)}">${esc(s.status)}</span>
      </div>
      <dl class="ids">
        <dt>VC No</dt><dd>${esc(s.vc_number || "–")}</dd>
        <dt>MAT No</dt><dd>${esc(s.mat_number || "–")}</dd>
      </dl>
      ${body}
      <div class="station-foot">${s.last_update ? "Last update " + esc(s.last_update) : ""}</div>
    </article>`;
  }

  function renderStations() {
    if (!lastSnapshot) return;
    const stations = onlyProblems.checked
      ? lastSnapshot.stations.filter((s) => s.status === "NOT OK")
      : lastSnapshot.stations;
    $("stations").innerHTML = stations.length
      ? stations.map(stationCard).join("")
      : `<div class="no-data">No stations to show</div>`;
  }

  function renderSummary(snap) {
    $("kpi-stations").textContent = snap.summary.stations;
    $("kpi-ok").textContent = snap.summary.ok;
    $("kpi-not-ok").textContent = snap.summary.not_ok;
    $("kpi-waiting").textContent = snap.summary.waiting;
    $("kpi-bypass").textContent = snap.summary.bypass;
    $("demo-badge").hidden = !snap.demo;
  }

  function renderEvents(events) {
    $("events").innerHTML = events.map((e) => `
      <li class="${e.status === "NOT OK" ? "bad" : ""}">
        <div class="ev-top">
          <span><b>ST ${esc(e.station ?? "?")}</b> · ${esc(e.tag)} ·
            <span class="${e.status === "OK" ? "st-ok" : "st-not-ok"}">${esc(e.status)}</span></span>
          <span class="ev-time">${esc(e.time)}</span>
        </div>
        <div>${esc(e.mat)} · ${esc(num(e.actual_count))}/${esc(num(e.set_count))}
          ${e.mode === "BYPASS" ? '<span class="mode-bypass">BYPASS</span>' : ""}</div>
        <div class="ev-name">${esc(e.name)}</div>
      </li>`).join("");
  }

  function setConnection(ok, message) {
    $("conn-dot").className = "dot " + (ok ? "live" : "down");
    $("conn-text").textContent = message;
    const banner = $("error-banner");
    banner.hidden = ok;
    if (!ok) banner.textContent = message;
  }

  async function getJson(url) {
    const res = await fetch(url, { cache: "no-store" });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
    return body;
  }

  async function refresh() {
    try {
      const [snap, ev] = await Promise.all([getJson("api/line"), getJson("api/events")]);
      lastSnapshot = snap;
      renderSummary(snap);
      renderStations();
      renderEvents(ev.events);
      setConnection(true, "Live · updated " + snap.generated_at);
    } catch (err) {
      setConnection(false, "Cannot reach Line data: " + err.message + " (showing last known data)");
    } finally {
      setTimeout(refresh, refreshMs);
    }
  }

  onlyProblems.addEventListener("change", renderStations);
  refresh();
})();
