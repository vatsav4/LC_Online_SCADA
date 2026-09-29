// Live refresh of a station detail page: VC/MAT plates, status ribbon and tool boxes.
// When a new vehicle reaches the station the whole tool grid is redrawn for it.
(function () {
  const scriptTag = document.currentScript;
  const stationId = scriptTag.getAttribute("data-station-id");

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }
  const show = v => (v === null || v === undefined ? "-" : v);

  function toolBox(t) {
    const cls = (t.status === "OK" ? "tile-green" : "tile-red") + (t.status === "PENDING" ? " tool-pending" : "");
    const pct = t.set ? Math.min(100, Math.floor((t.actual || 0) * 100 / t.set)) : 0;
    return `<div class="tool-box ${cls}">
      <div class="tool-title">${esc(t.tag)}: ${esc(t.label)}</div>
      <div class="tool-meta">
        ${t.torque_nm !== null ? `<span class="chip">${esc(t.torque_nm)} Nm</span>` : ""}
        ${t.mode === "BYPASS" ? '<span class="chip chip-bypass">BYPASS</span>' : ""}
      </div>
      <div class="tool-row"><span>Set Count:</span><b>${esc(show(t.set))}</b></div>
      <div class="tool-row"><span>Actual Count:</span><b>${esc(show(t.actual))}</b></div>
      <div class="bar"><i style="width: ${pct}%"></i></div>
    </div>`;
  }

  function ribbon(st) {
    if (!st.tools.length) return ["idle", "NO TIGHTENING DATA YET"];
    if (st.status === "green") return ["green", "ALL TOOLS OK"];
    const bad = st.tools.filter(t => t.status !== "OK").length;
    return ["red", bad + " TOOL(S) NOT OK"];
  }

  function setConnection(ok, updatedAt) {
    const conn = document.getElementById("conn");
    const text = document.getElementById("conn-text");
    if (conn) conn.className = "conn " + (ok ? "conn-ok" : "conn-down");
    if (text) text.textContent = ok ? "Online" : "Offline";
    const upd = document.getElementById("updated-at");
    if (upd && updatedAt) upd.textContent = "Updated " + updatedAt;
  }

  async function refresh() {
    try {
      const res = await fetch(`/api/station/${stationId}`, { cache: "no-store" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const st = await res.json();

      document.getElementById("vc-number").textContent = st.vc_number || "—";
      document.getElementById("mat-number").textContent = st.mat_number || "—";

      const [kind, label] = ribbon(st);
      const rib = document.getElementById("status-ribbon");
      rib.className = "status-ribbon ribbon-" + kind;
      rib.textContent = label;

      document.getElementById("tool-grid").innerHTML = st.tools.length
        ? st.tools.map(toolBox).join("")
        : `<p class="placeholder-note">No tools logged yet for this vehicle at Station ${esc(stationId)}.</p>`;

      setConnection(st.db_ok, st.updated_at);
    } catch (err) {
      setConnection(false);
      console.error("station refresh failed", err);
    }
  }

  refresh();
  window.__pageIntervals = window.__pageIntervals || [];
  window.__pageIntervals.push(setInterval(refresh, 2000));
})();
