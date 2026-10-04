// Station page: chassis picture with a circle on every torque point, callout boxes
// above / below joined by leader lines, refreshed every 2 s.
// Logged-in managers can click "Edit positions", drag the circles and Save; the
// server writes the new x / y into templates/station_<n>.html.
(function () {
  const script = document.currentScript;
  const stationId = script.getAttribute("data-station-id");
  const csrf = script.getAttribute("data-csrf");
  const $ = (id) => document.getElementById(id);
  let setup = false;   // true while a manager is editing positions

  let st = JSON.parse($("station-data").textContent || "{}");
  let positions = {};  // setup mode: tag -> {x, y} as dragged (percent)
  let drag = null;

  function esc(v) {
    return String(v ?? "").replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  const show = v => (v === null || v === undefined ? "-" : v);
  const statusClass = s => (s === "OK" ? "ok" : s === "PENDING" ? "pending" : "bad");
  const pct = t => (t.set ? Math.max(0, Math.min(100, Math.floor((t.actual || 0) * 100 / t.set))) : 0);
  const isPlaced = t => t.x !== null && t.x !== undefined;

  // in setup mode every tool gets a position (dragged, from the template, or the centre)
  function tools() {
    return (st.tools || []).map(t => {
      if (!setup) return t;
      const p = positions[t.tag] || (isPlaced(t) ? { x: t.x, y: t.y } : { x: 50, y: 50 });
      positions[t.tag] = p;
      return { ...t, x: p.x, y: p.y };
    });
  }

  // ---------------------------------------------------------------- render
  function card(t) {
    const cls = statusClass(t.status);
    return `<div class="tool-box tool-${cls}" data-tag="${esc(t.tag)}">
      <div class="tool-title">${esc(t.tag)}: ${esc(t.label)}</div>
      <div class="tool-meta">
        ${t.mode === "BYPASS" ? '<span class="chip chip-bypass">BYPASS</span>' : ""}
        ${t.status === "PENDING" ? '<span class="chip">awaiting data</span>' : ""}
      </div>
      <div class="tool-row"><span>Set Count:</span><b>${esc(show(t.set))}</b></div>
      <div class="tool-row"><span>Actual Count:</span><b>${esc(show(t.actual))}</b></div>
      <div class="bar"><i style="width:${pct(t)}%"></i></div>
    </div>`;
  }

  function marker(t) {
    const cls = statusClass(t.status) + (t.mode === "BYPASS" ? " marker-bypass" : "") + (setup ? " marker-edit" : "");
    return `<button type="button" class="marker marker-${cls}" data-tag="${esc(t.tag)}"
      style="left:${t.x}%;top:${t.y}%;--pct:${pct(t)}" title="${esc(t.tag)}: ${esc(t.label)}">
      <span>${esc(t.tag)}</span></button>`;
  }

  function render() {
    $("vc-number").textContent = st.vc_number || "—";
    $("mat-number").textContent = st.mat_number || "—";

    const all = tools();
    const placed = all.filter(isPlaced), unplaced = all.filter(t => !isPlaced(t));

    const bad = all.filter(t => t.status === "NOT OK").length;
    const waiting = all.filter(t => t.status === "PENDING").length;
    const parts = [bad && `${bad} NOT OK`, waiting && `${waiting} AWAITING DATA`].filter(Boolean);
    const rib = $("status-ribbon");
    if (setup) { rib.className = "status-ribbon ribbon-edit"; rib.textContent = "EDITING POSITIONS"; }
    else if (!all.length) { rib.className = "status-ribbon ribbon-idle"; rib.textContent = "NO WRENCHES IN THIS STATION'S TEMPLATE"; }
    else if (!parts.length) { rib.className = "status-ribbon ribbon-green"; rib.textContent = "ALL TORQUES OK"; }
    else { rib.className = "status-ribbon " + (bad ? "ribbon-red" : "ribbon-idle"); rib.textContent = parts.join(" · "); }

    // top half of the picture -> box above, bottom half -> box below; left to right
    const byX = (a, b) => a.x - b.x;
    $("callouts-top").innerHTML = placed.filter(t => t.y < 50).sort(byX).map(card).join("");
    $("callouts-bottom").innerHTML = placed.filter(t => t.y >= 50).sort(byX).map(card).join("");
    $("markers").innerHTML = placed.map(marker).join("");
    $("unplaced").innerHTML = unplaced.map(card).join("");
    $("unplaced-section").hidden = !unplaced.length;
    fitToScreen();
  }

  // Make the chassis as big as possible while the whole page (boxes above and below,
  // un-placed boxes, footer) still fits on one screen without a scroll bar.
  function fitToScreen() {
    const img = $("chassis-img");
    if (!img || !img.naturalWidth) { drawLeaders(); return; }
    img.style.maxHeight = "";                       // start from the CSS upper limit
    const overflow = document.documentElement.scrollHeight - window.innerHeight;
    if (overflow > 0) {
      const h = img.getBoundingClientRect().height;
      img.style.maxHeight = Math.max(120, Math.floor(h - overflow)) + "px";
    }
    drawLeaders();
  }

  // Elbow lines from each circle to its box, computed from the real on-screen positions.
  function drawLeaders() {
    const view = $("station-view"), svg = $("leaders");
    if (!view || !svg) return;
    const vr = view.getBoundingClientRect();
    const box = $("chassis-box").getBoundingClientRect();
    svg.setAttribute("width", vr.width);
    svg.setAttribute("height", vr.height);
    svg.setAttribute("viewBox", `0 0 ${vr.width} ${vr.height}`);
    const paths = [];
    ["top", "bottom"].forEach(side => {
      const cards = [...$("callouts-" + side).querySelectorAll(".tool-box")];
      cards.forEach((c, i) => {
        const tag = c.getAttribute("data-tag");
        const m = $("markers").querySelector(`.marker[data-tag="${CSS.escape(tag)}"]`);
        if (!m) return;
        const mr = m.getBoundingClientRect(), cr = c.getBoundingClientRect();
        const mx = mr.left + mr.width / 2 - vr.left, my = mr.top + mr.height / 2 - vr.top;
        const cx = cr.left + cr.width / 2 - vr.left;
        const step = (i + 1) / (cards.length + 1);  // stagger horizontal runs
        let cy, midY;
        if (side === "top") { cy = cr.bottom - vr.top; midY = cy + (box.top - vr.top - cy) * step; }
        else { cy = cr.top - vr.top; midY = box.bottom - vr.top + (cy - (box.bottom - vr.top)) * step; }
        const cls = c.classList.contains("tool-ok") ? "ok" : c.classList.contains("tool-bad") ? "bad" : "pending";
        paths.push(`<path class="leader leader-${cls}" data-tag="${esc(tag)}" d="M${mx},${my} V${midY} H${cx} V${cy}"/>` +
                   `<circle class="leader-end leader-${cls}" cx="${cx}" cy="${cy}" r="3.5"/>`);
      });
    });
    svg.innerHTML = paths.join("");
  }

  // hover a circle or a box -> highlight both and the line between them
  function highlight(tag, on) {
    document.querySelectorAll(`#station-view [data-tag="${CSS.escape(tag)}"]`)
      .forEach(el => el.classList.toggle("hl", on));
  }
  $("station-view").addEventListener("mouseover", e => {
    const el = e.target.closest("[data-tag]"); if (el) highlight(el.getAttribute("data-tag"), true);
  });
  $("station-view").addEventListener("mouseout", e => {
    const el = e.target.closest("[data-tag]"); if (el) highlight(el.getAttribute("data-tag"), false);
  });

  // ---------------------------------------------------------------- edit positions
  const editToggle = $("edit-toggle");
  const msg = text => { if ($("edit-msg")) $("edit-msg").textContent = text || ""; };
  let dirty = false;

  function setEditing(on) {
    setup = on;
    dirty = false;
    positions = {};
    $("edit-bar").hidden = !on;
    editToggle.hidden = on;
    msg("");
    render();
  }

  if (editToggle) {
    editToggle.addEventListener("click", () => setEditing(true));
    $("edit-cancel").addEventListener("click", () => {
      if (!dirty || confirm("Discard the moved positions?")) setEditing(false);
    });
    $("edit-save").addEventListener("click", async () => {
      msg("Saving…");
      try {
        const res = await fetch(`/api/station/${stationId}/positions`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
          body: JSON.stringify({ positions }),
        });
        const body = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(body.error || "HTTP " + res.status);
        setEditing(false);
        await refresh();
      } catch (err) { msg("Not saved: " + err.message); }
    });
    $("markers").addEventListener("pointerdown", e => {
      const m = e.target.closest(".marker");
      if (!m || !setup) return;
      e.preventDefault();
      m.setPointerCapture(e.pointerId);
      drag = { el: m, tag: m.getAttribute("data-tag") };
      m.classList.add("dragging");
    });
    $("markers").addEventListener("pointermove", e => {
      if (!drag) return;
      const r = $("chassis-img").getBoundingClientRect();
      const x = Math.round(Math.min(100, Math.max(0, (e.clientX - r.left) / r.width * 100)) * 10) / 10;
      const y = Math.round(Math.min(100, Math.max(0, (e.clientY - r.top) / r.height * 100)) * 10) / 10;
      positions[drag.tag] = { x, y };
      drag.el.style.left = x + "%";
      drag.el.style.top = y + "%";
      dirty = true;
      msg("Unsaved changes");
      drawLeaders();
    });
    const endDrag = () => { if (drag) { drag = null; render(); } };
    $("markers").addEventListener("pointerup", endDrag);
    $("markers").addEventListener("pointercancel", endDrag);
  }

  // ---------------------------------------------------------------- live data
  function setConnection(ok, updatedAt) {
    const conn = $("conn"), text = $("conn-text"), upd = $("updated-at");
    if (conn) conn.className = "conn " + (ok ? "conn-ok" : "conn-down");
    if (text) text.textContent = ok ? "Online" : "Offline";
    if (upd && updatedAt) upd.textContent = "Updated " + updatedAt;
  }

  async function refresh() {
    if (drag) return;
    try {
      const res = await fetch(`/api/station/${stationId}`, { cache: "no-store" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      st = await res.json();
      render();
      setConnection(st.db_ok, st.updated_at);
    } catch (err) {
      setConnection(false);
      console.error("station refresh failed", err);
    }
  }

  $("chassis-img").addEventListener("load", fitToScreen);
  window.addEventListener("resize", fitToScreen);
  if (window.ResizeObserver) new ResizeObserver(drawLeaders).observe($("station-view"));

  render();
  refresh();
  window.__pageIntervals = window.__pageIntervals || [];
  window.__pageIntervals.push(setInterval(refresh, 2000));
})();
