// Station page: chassis picture with a marker on every torque point, callout
// boxes above / below joined by leader lines, live refresh every 2 s, and a
// drag-and-drop layout editor for logged-in line managers.
(function () {
  const script = document.currentScript;
  const stationId = script.getAttribute("data-station-id");
  const csrf = script.getAttribute("data-csrf");
  const $ = (id) => document.getElementById(id);

  let st = JSON.parse($("station-data").textContent || "{}");
  let draft = null;         // layout being edited: {image, tools: [{t_no, x, y, label}]}
  let dirty = false;
  let editorInfo = null;    // {tools, assigned, images} from /api/editor
  let drag = null;

  // ---------------------------------------------------------------- helpers
  function esc(v) {
    return String(v ?? "").replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  const show = v => (v === null || v === undefined ? "-" : v);
  const statusClass = s => (s === "OK" ? "ok" : s === "PENDING" ? "pending" : "bad");
  function pct(t) {
    return t.set ? Math.max(0, Math.min(100, Math.floor((t.actual || 0) * 100 / t.set))) : 0;
  }

  // The tools to draw: live data, or (while editing) the draft layout merged with live data.
  function currentTools() {
    if (!draft) return st.tools || [];
    const live = {};
    (st.tools || []).forEach(t => { live[t.tag.toUpperCase()] = t; });
    return draft.tools.map(d => {
      const t = live[d.t_no.toUpperCase()] || { tag: d.t_no, label: "", set: null, actual: null,
                                                 status: "PENDING", mode: "", torque_nm: null };
      return { ...t, tag: d.t_no, x: d.x, y: d.y, label: d.label || t.label || d.t_no, _draft: d };
    });
  }

  // ---------------------------------------------------------------- render
  function card(t) {
    const cls = statusClass(t.status);
    const editing = !!draft;
    const title = editing
      ? `<input class="label-input" data-tag="${esc(t.tag)}" value="${esc(t._draft.label)}" placeholder="${esc(t.label)}" maxlength="80">`
      : esc(t.label);
    const editBtns = editing ? `<div class="card-edit">
        ${t.x === null || t.x === undefined
          ? `<button type="button" data-act="place" data-tag="${esc(t.tag)}">Place on chassis</button>`
          : `<button type="button" data-act="unplace" data-tag="${esc(t.tag)}">Take off chassis</button>`}
        <button type="button" data-act="remove" data-tag="${esc(t.tag)}">Remove</button></div>` : "";
    return `<div class="tool-box tool-${cls}${t.status === "PENDING" ? " tool-pending" : ""}" data-tag="${esc(t.tag)}">
      <div class="tool-title"><span class="tool-tag">${esc(t.tag)}:</span> ${title}</div>
      <div class="tool-meta">
        ${t.torque_nm !== null && t.torque_nm !== undefined ? `<span class="chip">${esc(t.torque_nm)} Nm</span>` : ""}
        ${t.mode === "BYPASS" ? '<span class="chip chip-bypass">BYPASS</span>' : ""}
        ${t.status === "PENDING" ? '<span class="chip">awaiting data</span>' : ""}
      </div>
      <div class="tool-row"><span>Set Count:</span><b>${esc(show(t.set))}</b></div>
      <div class="tool-row"><span>Actual Count:</span><b>${esc(show(t.actual))}</b></div>
      <div class="bar"><i style="width:${pct(t)}%"></i></div>
      ${editBtns}
    </div>`;
  }

  function marker(t) {
    const cls = statusClass(t.status) + (t.mode === "BYPASS" ? " marker-bypass" : "");
    return `<button type="button" class="marker marker-${cls}${draft ? " marker-edit" : ""}"
      data-tag="${esc(t.tag)}" style="left:${t.x * 100}%;top:${t.y * 100}%;--pct:${pct(t)}"
      title="${esc(t.tag)}: ${esc(t.label)}"><span>${esc(t.tag)}</span></button>`;
  }

  function render() {
    $("vc-number").textContent = st.vc_number || "—";
    $("mat-number").textContent = st.mat_number || "—";

    const tools = currentTools();
    const placed = tools.filter(t => t.x !== null && t.x !== undefined);
    const unplaced = tools.filter(t => t.x === null || t.x === undefined);

    // ribbon
    const rib = $("status-ribbon");
    const bad = tools.filter(t => t.status === "NOT OK").length;
    const waiting = tools.filter(t => t.status === "PENDING").length;
    const parts = [bad && `${bad} NOT OK`, waiting && `${waiting} AWAITING DATA`].filter(Boolean);
    if (draft) { rib.className = "status-ribbon ribbon-edit"; rib.textContent = "EDITING LAYOUT"; }
    else if (!tools.length) { rib.className = "status-ribbon ribbon-idle"; rib.textContent = "NO WRENCHES ASSIGNED YET"; }
    else if (!parts.length) { rib.className = "status-ribbon ribbon-green"; rib.textContent = "ALL TORQUES OK"; }
    else { rib.className = "status-ribbon " + (bad ? "ribbon-red" : "ribbon-idle"); rib.textContent = parts.join(" · "); }

    // picture
    const image = draft ? draft.image : st.image;
    const img = $("chassis-img");
    if (image && img.getAttribute("data-name") !== image) {
      img.setAttribute("data-name", image);
      img.src = "/chassis/" + encodeURIComponent(image);
    }

    // callouts: top half of the picture -> above, bottom half -> below; left to right
    const byX = (a, b) => a.x - b.x;
    $("callouts-top").innerHTML = placed.filter(t => t.y < 0.5).sort(byX).map(card).join("");
    $("callouts-bottom").innerHTML = placed.filter(t => t.y >= 0.5).sort(byX).map(card).join("");
    $("markers").innerHTML = placed.map(marker).join("");
    $("unplaced").innerHTML = unplaced.map(card).join("");
    $("unplaced-section").hidden = !unplaced.length;

    $("layout-updated").textContent = st.layout_updated ? "Layout last changed " + st.layout_updated : "";
    drawLeaders();
  }

  // Elbow lines from each marker to its callout box, recomputed from real positions.
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
        // stagger the horizontal runs so neighbouring lines don't sit on top of each other
        const step = (i + 1) / (cards.length + 1);
        let cy, midY;
        if (side === "top") {
          cy = cr.bottom - vr.top;
          midY = cy + (box.top - vr.top - cy) * step;
        } else {
          cy = cr.top - vr.top;
          midY = box.bottom - vr.top + (cy - (box.bottom - vr.top)) * step;
        }
        const cls = c.className.includes("tool-ok") ? "ok" : c.className.includes("tool-bad") ? "bad" : "pending";
        paths.push(`<path class="leader leader-${cls}" data-tag="${esc(tag)}"
          d="M${mx},${my} V${midY} H${cx} V${cy}"/><circle class="leader-end leader-${cls}" cx="${cx}" cy="${cy}" r="3.5"/>`);
      });
    });
    svg.innerHTML = paths.join("");
  }

  // hover a marker or a box -> highlight both and the line between them
  function highlight(tag, on) {
    document.querySelectorAll(`#station-view [data-tag="${CSS.escape(tag)}"], #unplaced [data-tag="${CSS.escape(tag)}"]`)
      .forEach(el => el.classList.toggle("hl", on));
  }
  $("station-view").addEventListener("mouseover", e => {
    const el = e.target.closest("[data-tag]"); if (el) highlight(el.getAttribute("data-tag"), true);
  });
  $("station-view").addEventListener("mouseout", e => {
    const el = e.target.closest("[data-tag]"); if (el) highlight(el.getAttribute("data-tag"), false);
  });

  // ---------------------------------------------------------------- live data
  function setConnection(ok, updatedAt) {
    const conn = $("conn"), text = $("conn-text"), upd = $("updated-at");
    if (conn) conn.className = "conn " + (ok ? "conn-ok" : "conn-down");
    if (text) text.textContent = ok ? "Online" : "Offline";
    if (upd && updatedAt) upd.textContent = "Updated " + updatedAt;
  }

  async function refresh() {
    if (drag) return; // don't redraw under the user's finger
    try {
      const res = await fetch(`/api/station/${stationId}`, { cache: "no-store" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      st = await res.json();
      // while editing, keep the draft on screen (and any label being typed) untouched
      if (!draft) render();
      setConnection(st.db_ok, st.updated_at);
    } catch (err) {
      setConnection(false);
      console.error("station refresh failed", err);
    }
  }

  // ---------------------------------------------------------------- editor
  const editToggle = $("edit-toggle");
  const msg = text => { $("editor-msg").textContent = text || ""; };

  async function api(url, options) {
    const res = await fetch(url, { ...options, headers: { "X-CSRF-Token": csrf, ...(options && options.headers) } });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || "HTTP " + res.status);
    return body;
  }

  function fillEditorControls() {
    const inStation = new Set(draft.tools.map(t => t.t_no.toUpperCase()));
    $("add-tool").innerHTML = editorInfo.tools
      .filter(t => !inStation.has(t.toUpperCase()))
      .map(t => {
        const other = editorInfo.assigned[t];
        const note = other && String(other) !== String(stationId) ? ` (on station ${other})` : "";
        return `<option value="${esc(t)}">${esc(t)}${note}</option>`;
      }).join("") + `<option value="__other">Other… (type number)</option>`;
    $("image-select").innerHTML = editorInfo.images
      .map(i => `<option value="${esc(i.name)}"${i.name === draft.image ? " selected" : ""}>${esc(i.name)} (${i.kind})</option>`)
      .join("");
  }

  async function startEdit() {
    try {
      editorInfo = await api("/api/editor");
    } catch (err) { alert(err.message); return; }
    const layout = st.layout || { image: st.image, tools: [] };
    draft = { image: layout.image || st.image, tools: (layout.tools || []).map(t => ({ ...t })) };
    dirty = false;
    $("editor-bar").hidden = false;
    editToggle.hidden = true;
    msg("");
    fillEditorControls();
    render();
  }

  function stopEdit() {
    draft = null; dirty = false; drag = null;
    $("editor-bar").hidden = true;
    editToggle.hidden = false;
    render();
  }

  function changed() { dirty = true; msg("Unsaved changes"); }

  if (editToggle) {
    editToggle.addEventListener("click", startEdit);
    $("edit-cancel").addEventListener("click", () => {
      if (!dirty || confirm("Discard your layout changes?")) stopEdit();
    });
    $("edit-save").addEventListener("click", async () => {
      msg("Saving…");
      try {
        await api(`/api/layout/${stationId}`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(draft) });
        stopEdit();
        await refresh();
      } catch (err) { msg("Not saved: " + err.message); }
    });
    $("add-tool-btn").addEventListener("click", () => {
      let tno = $("add-tool").value;
      if (tno === "__other") tno = (prompt("Wrench number, e.g. T12") || "").trim().toUpperCase();
      if (!tno) return;
      if (!/^[A-Za-z0-9_-]{1,16}$/.test(tno)) { msg("Invalid wrench number"); return; }
      if (draft.tools.some(t => t.t_no.toUpperCase() === tno.toUpperCase())) { msg(tno + " is already here"); return; }
      draft.tools.push({ t_no: tno, x: 0.5, y: 0.5, label: "" });
      changed(); fillEditorControls(); render();
    });
    $("image-select").addEventListener("change", e => { draft.image = e.target.value; changed(); render(); });
    $("image-upload").addEventListener("change", async e => {
      const file = e.target.files[0];
      if (!file) return;
      const form = new FormData();
      form.append("image", file);
      msg("Uploading…");
      try {
        const body = await api("/api/chassis-images", { method: "POST", body: form });
        editorInfo.images = body.images;
        draft.image = body.name;
        changed(); fillEditorControls(); render();
      } catch (err) { msg("Upload failed: " + err.message); }
      e.target.value = "";
    });
  }

  // card buttons and label inputs (edit mode). Listeners go on page elements (not
  // document) so in-app navigation between stations doesn't stack them up.
  const editArea = [$("station-view"), $("unplaced-section")];
  const onEditClick = e => {
    const btn = e.target.closest(".card-edit button");
    if (!btn || !draft) return;
    const tag = btn.getAttribute("data-tag");
    const d = draft.tools.find(t => t.t_no === tag);
    if (!d) return;
    const act = btn.getAttribute("data-act");
    if (act === "place") { d.x = 0.5; d.y = 0.5; }
    if (act === "unplace") { d.x = null; d.y = null; }
    if (act === "remove") draft.tools = draft.tools.filter(t => t !== d);
    changed(); fillEditorControls(); render();
  };
  const onEditInput = e => {
    if (!draft || !e.target.classList.contains("label-input")) return;
    const d = draft.tools.find(t => t.t_no === e.target.getAttribute("data-tag"));
    if (d) { d.label = e.target.value; dirty = true; msg("Unsaved changes"); }
  };
  editArea.forEach(el => { el.addEventListener("click", onEditClick); el.addEventListener("input", onEditInput); });

  // drag markers (mouse, touch and pen)
  $("markers").addEventListener("pointerdown", e => {
    const m = e.target.closest(".marker");
    if (!m || !draft) return;
    e.preventDefault();
    m.setPointerCapture(e.pointerId);
    drag = { el: m, tag: m.getAttribute("data-tag") };
    m.classList.add("dragging");
  });
  $("markers").addEventListener("pointermove", e => {
    if (!drag) return;
    const r = $("chassis-img").getBoundingClientRect();
    const x = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    const y = Math.min(1, Math.max(0, (e.clientY - r.top) / r.height));
    const d = draft.tools.find(t => t.t_no === drag.tag);
    if (!d) return;
    d.x = Math.round(x * 10000) / 10000;
    d.y = Math.round(y * 10000) / 10000;
    drag.el.style.left = d.x * 100 + "%";
    drag.el.style.top = d.y * 100 + "%";
    dirty = true;
    drawLeaders();
  });
  const endDrag = () => {
    if (!drag) return;
    drag = null;
    changed();
    render(); // may move the box between the top and bottom rows
  };
  $("markers").addEventListener("pointerup", endDrag);
  $("markers").addEventListener("pointercancel", endDrag);

  // ask before leaving with unsaved changes (full reloads and in-app navigation)
  window.__confirmLeave = () => !dirty || confirm("You have unsaved layout changes. Leave anyway?");
  window.onbeforeunload = () => (dirty ? true : undefined);

  // redraw lines whenever the layout reflows (resize, image load, fonts)
  $("chassis-img").addEventListener("load", drawLeaders);
  if (window.ResizeObserver) new ResizeObserver(drawLeaders).observe($("station-view"));

  render();
  refresh();
  window.__pageIntervals = window.__pageIntervals || [];
  window.__pageIntervals.push(setInterval(refresh, 2000));
})();
