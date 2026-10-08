// Station page: chassis picture with a circle on every torque point, callout boxes
// above / below joined by leader lines, refreshed every 2 s. On a portrait screen (digital
// standee) the chassis stands upright and the boxes go to its left / right.
// A wrench with Set Count 0 (not used for the vehicle now at the station) is not shown.
// Logged-in managers can click "Edit positions", drag the circles and Save; the
// server writes the new x / y into templates/station_<n>.html.
(function () {
  const script = document.currentScript;
  const stationId = script.getAttribute("data-station-id");
  const csrf = script.getAttribute("data-csrf");
  const $ = (id) => document.getElementById(id);
  // positions as the page sees them, also when the page is turned for a portrait screen
  const R = el => (window.logicalRect ? window.logicalRect(el) : el.getBoundingClientRect());
  const portrait = () => document.documentElement.classList.contains("portrait");
  let setup = false;   // true while a manager is editing positions

  let st = JSON.parse($("station-data").textContent || "{}");
  let positions = {};  // setup mode: tag -> {x, y} as dragged (percent)
  let drag = null;

  function esc(v) {
    return String(v === null || v === undefined ? "" : v).replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  const show = v => (v === null || v === undefined ? "-" : v);
  const statusClass = s => (s === "OK" ? "ok" : s === "PENDING" ? "pending" : "bad");
  // ring / bar fill: counts done of set, or for a U-bolt group the nuts done of 4
  const pct = t => (t.kind === "ubolt" ? (t.nuts && t.nuts.length ? Math.floor(t.done * 100 / t.nuts.length) : 0)
    : t.set ? Math.max(0, Math.min(100, Math.floor((t.actual || 0) * 100 / t.set))) : 0);
  const nm = v => (v === null || v === undefined ? "-" : String(Math.round(v * 10) / 10));   // torque, 1 decimal
  const isPlaced = t => t.x !== null && t.x !== undefined;

  // in setup mode every tool gets a position (dragged, from the template, or the centre);
  // wrenches with Set Count 0 only show up while a manager is placing circles
  function tools() {
    return (st.tools || []).filter(t => setup || !t.hidden).map(t => {
      if (!setup) return t;
      const p = positions[t.tag] || (isPlaced(t) ? { x: t.x, y: t.y } : { x: 50, y: 50 });
      positions[t.tag] = p;
      return { ...t, x: p.x, y: p.y };
    });
  }

  // ---------------------------------------------------------------- render
  // U-bolt group: set torque and the 4 nut torques, each nut green (>= set) or red
  function ubCard(t) {
    const cls = statusClass(t.status);
    const nuts = (t.nuts || []).map((n, i) =>
      `<span class="nut nut-${n.state}" title="Nut ${i + 1}">${esc(nm(n.value))}</span>`).join("");
    return `<div class="tool-box tool-ub tool-${cls}" data-tag="${esc(t.tag)}">
      <div class="tool-title" title="${esc(t.label)}">${esc(t.short)}: ${esc(t.label)}</div>
      <div class="tool-meta">${t.status === "PENDING" ? `<span class="chip">${esc(t.note || "awaiting data")}</span>` : ""}</div>
      <div class="tool-row"><span>Set Torque:</span><b>${t.set === null || t.set === undefined ? "-" : esc(nm(t.set)) + " Nm"}</b></div>
      <div class="nuts">${nuts || '<span class="nut nut-pending">-</span>'.repeat(4)}</div>
      <div class="bar"><i style="width:${pct(t)}%"></i></div>
    </div>`;
  }

  function card(t) {
    if (t.kind === "ubolt") return ubCard(t);
    const cls = statusClass(t.status);
    return `<div class="tool-box tool-${cls}" data-tag="${esc(t.tag)}">
      <div class="tool-title" title="${esc(t.tag)}: ${esc(t.label)}">${esc(t.tag)}: ${esc(t.label)}</div>
      <div class="tool-meta">
        ${t.status === "PENDING" ? '<span class="chip">awaiting data</span>' : ""}
        ${t.hidden ? '<span class="chip">Set Count 0 - not shown</span>' : ""}
      </div>
      <div class="tool-row"><span>Set Count:</span><b>${esc(show(t.set))}</b></div>
      <div class="tool-row"><span>Actual Count:</span><b>${esc(show(t.actual))}</b></div>
      <div class="bar"><i style="width:${pct(t)}%"></i></div>
    </div>`;
  }

  function marker(t) {
    const cls = statusClass(t.status) + (setup ? " marker-edit" : "");
    return `<button type="button" class="marker marker-${cls}" data-tag="${esc(t.tag)}"
      style="left:${t.x}%;top:${t.y}%;--pct:${pct(t)}" title="${esc(t.short || t.tag)}: ${esc(t.label)}">
      <span>${esc(t.short || t.tag)}</span></button>`;
  }

  function render() {
    $("vc-number").textContent = st.vc_number || "—";
    $("mat-number").textContent = st.mat_number || "—";

    const all = tools();
    const placed = all.filter(isPlaced), unplaced = all.filter(t => !isPlaced(t));

    const checks = all.concat(st.s3 || []);   // torque wrenches and S3 controls
    const bad = checks.filter(t => t.status === "NOT OK").length;
    const waiting = checks.filter(t => t.status === "PENDING").length;
    const parts = [bad && `${bad} NOT OK`, waiting && `${waiting} AWAITING DATA`].filter(Boolean);
    const rib = $("status-ribbon");
    if (st.error) { rib.className = "status-ribbon ribbon-red"; rib.textContent = "TEMPLATE MISTAKE - SEE ABOVE"; }
    else if (setup) { rib.className = "status-ribbon ribbon-edit"; rib.textContent = "EDITING POSITIONS"; }
    else if (!checks.length) {
      rib.className = "status-ribbon ribbon-idle";
      rib.textContent = (st.tools || []).length ? "NO TORQUES FOR THIS VEHICLE" : "NOTHING SET UP FOR THIS STATION";
    }
    else if (!parts.length) {
      rib.className = "status-ribbon ribbon-green";
      rib.textContent = !all.length ? "ALL S3 CONTROLS OK" : (st.s3 || []).length ? "ALL OK" : "ALL TORQUES OK";
    }
    else { rib.className = "status-ribbon " + (bad ? "ribbon-red" : "ribbon-idle"); rib.textContent = parts.join(" · "); }

    // Up to 3 boxes above and 3 below: circles in the top half of the picture get a box above,
    // the rest below; if one half has more than 3, the ones nearest the middle move to the other row.
    const byX = (a, b) => a.x - b.x;
    const byY = [...placed].sort((a, b) => a.y - b.y);
    let topCount = Math.min(3, byY.filter(t => t.y < 50).length);
    if (byY.length - topCount > 3) topCount = byY.length - 3;
    const topRow = byY.slice(0, topCount), bottomRow = byY.slice(topCount);
    $("callouts-top").innerHTML = topRow.sort(byX).map(card).join("");
    $("callouts-bottom").innerHTML = bottomRow.sort(byX).map(card).join("");
    $("markers").innerHTML = placed.map(marker).join("");
    $("unplaced").innerHTML = unplaced.map(card).join("");
    $("unplaced-section").hidden = !unplaced.length;
    if (window.renderS3) window.renderS3(st.s3);
    fitToScreen();
  }

  // Make the chassis as big as possible while the whole page (boxes, un-placed boxes, footer)
  // still fits on one screen without a scroll bar. Every station gets the same chassis size:
  // the one at which the WIDEST picture (--widest-aspect in style.css) just fits.
  function fitToScreen() {
    const img = $("chassis-img"), view = $("station-view"), slot = $("chassis-slot"), box = $("chassis-box");
    if (!img || !img.naturalWidth) { drawLeaders(); return; }
    const css = getComputedStyle(document.documentElement);
    const widest = parseFloat(css.getPropertyValue("--widest-aspect")) || 3.72;
    const cs = getComputedStyle(view);
    const width = view.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);

    if (!portrait()) {
      slot.style.width = slot.style.height = box.style.top = box.style.transform = "";
      img.style.width = img.style.height = "";
      img.style.maxHeight = Math.floor(width / widest) + "px";
      const overflow = window.pageOverflow ? window.pageOverflow() : document.documentElement.scrollHeight - window.innerHeight;
      if (overflow > 0) img.style.maxHeight = Math.max(120, Math.floor(img.offsetHeight - overflow)) + "px";
      drawLeaders();
      return;
    }

    // Portrait: the chassis is turned 90 degrees (front at the top) between two columns of boxes.
    // The slot is as wide as the chassis is "high", and long enough for the widest picture.
    const aspect = img.naturalWidth / img.naturalHeight;
    // one column of boxes each side (--box-w is set in px by base.html for portrait screens)
    const boxW = 2 * (parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--box-w")) || 290);
    const gap = parseFloat(cs.columnGap) || 0;
    const place = short => {
      short = Math.max(60, Math.floor(short));
      slot.style.width = short + "px";
      slot.style.height = Math.floor(short * widest) + "px";
      img.style.maxHeight = "none";
      img.style.width = Math.floor(short * aspect) + "px";
      img.style.height = short + "px";
      box.style.top = Math.floor((short * widest - short * aspect) / 2) + "px";   // centred in the slot
      box.style.transform = `translateX(${short}px) rotate(90deg)`;
      return short;
    };
    const short = place(width - boxW - 2 * gap);
    const overflow = window.pageOverflow ? window.pageOverflow() : 0;
    if (overflow > 0) place(short - overflow / widest);
    drawLeaders();
  }

  // Elbow lines from each circle to its box, computed from the real on-screen positions.
  function drawLeaders() {
    const view = $("station-view"), svg = $("leaders");
    if (!view || !svg) return;
    const vr = R(view);
    const box = R($("chassis-slot"));
    const up = portrait();
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
        const mr = R(m), cr = R(c);
        const mx = mr.left + mr.width / 2 - vr.left, my = mr.top + mr.height / 2 - vr.top;
        const step = (i + 1) / (cards.length + 1);  // stagger the runs so lines don't overlap
        const cls = c.classList.contains("tool-ok") ? "ok" : c.classList.contains("tool-bad") ? "bad" : "pending";
        let d, ex, ey;
        if (up) {   // portrait: "top" boxes are right of the chassis, "bottom" boxes left of it
          ey = cr.top + cr.height / 2 - vr.top;
          let midX;
          if (side === "top") { ex = cr.left - vr.left; midX = ex - (ex - (box.right - vr.left)) * step; }
          else { ex = cr.right - vr.left; midX = ex + ((box.left - vr.left) - ex) * step; }
          d = `M${mx},${my} H${midX} V${ey} H${ex}`;
        } else {
          ex = cr.left + cr.width / 2 - vr.left;
          let midY;
          if (side === "top") { ey = cr.bottom - vr.top; midY = ey + (box.top - vr.top - ey) * step; }
          else { ey = cr.top - vr.top; midY = box.bottom - vr.top + (ey - (box.bottom - vr.top)) * step; }
          d = `M${mx},${my} V${midY} H${ex} V${ey}`;
        }
        paths.push(`<path class="leader leader-${cls}" data-tag="${esc(tag)}" d="${d}"/>` +
                   `<circle class="leader-end leader-${cls}" cx="${ex}" cy="${ey}" r="3.5"/>`);
      });
    });
    svg.innerHTML = paths.join("");
    if (window.drawS3Rays) window.drawS3Rays();
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
      const r = R($("chassis-img"));
      const p = window.logicalPoint ? window.logicalPoint(e.clientX, e.clientY) : { x: e.clientX, y: e.clientY };
      // fraction across / down the picture itself (it stands upright on a portrait screen)
      let u = (p.x - r.left) / r.width, v = (p.y - r.top) / r.height;
      if (portrait()) { const t = u; u = v; v = 1 - t; }
      const clamp = n => Math.round(Math.min(100, Math.max(0, n * 100)) * 10) / 10;
      const x = clamp(u), y = clamp(v);
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
      if (window.checkVersion) window.checkVersion(st.version);
      render();
      setConnection(st.db_ok, st.updated_at);
    } catch (err) {
      setConnection(false);
      console.error("station refresh failed", err);
    }
  }

  $("chassis-img").addEventListener("load", fitToScreen);
  window.addEventListener("resize", fitToScreen);
  const observer = window.ResizeObserver ? new ResizeObserver(drawLeaders) : null;
  if (observer) observer.observe($("station-view"));

  render();
  refresh();
  window.__pageIntervals = window.__pageIntervals || [];
  window.__pageIntervals.push(setInterval(refresh, 2000));
  // spa.js runs these when moving to another page, so listeners don't pile up
  window.__pageCleanups = window.__pageCleanups || [];
  window.__pageCleanups.push(() => {
    window.removeEventListener("resize", fitToScreen);
    if (observer) observer.disconnect();
  });
})();
