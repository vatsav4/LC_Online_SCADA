// S3 controls drawn around the chassis on a station page (s3_controls in the station template):
//   light_curtain  a bar above ("place": "top") or below ("bottom") the chassis; its beams shine onto
//                  the chassis - faint green when OK, bright red and flashing when NOT OK
//   over_travel    roller limit switch at the right-hand end of its row; red light bursts out of it
//                  and the lever is tripped when NOT OK
//   sensor         any other S3 signal: a beacon lamp
// Tag 0 = OK (green), 1 = NOT OK (red), no row in SQL yet = grey.
// station.js calls window.renderS3(st.s3) on every refresh and window.drawS3Rays() whenever the
// layout changes. A device is only redrawn when its status changes, so animations run smoothly.
(function () {
  const $ = id => document.getElementById(id);
  const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const cls = s => (s === "OK" ? "ok" : s === "NOT OK" ? "bad" : "pending");
  const LABEL = { ok: "OK", bad: "NOT OK", pending: "NO DATA" };
  const STUDS = 16;
  const since = (c, s) => (c.since && s !== "pending" ? "since " + c.since : "");

  function tag(c, s) {
    return `<div class="s3-tag"><b>${esc(c.name)}</b><span class="s3-state">${LABEL[s]}</span>` +
           `<span class="s3-since">${esc(since(c, s))}</span></div>`;
  }

  function curtain(c, s) {
    return `${tag(c, s)}
      <div class="lc-bar"><i class="lc-cap"></i><span class="lc-body"><span class="lc-led"></span></span><i class="lc-cap"></i></div>
      <div class="lc-studs">${"<i></i>".repeat(STUDS)}</div>`;
  }

  function limitSwitch(c, s) {
    const lever = s === "bad" ? 38 : 0;
    // red light bursting out of the switch in every direction except up into the mounting
    const burst = s === "bad" ? [-10, 15, 40, 65, 90, 115, 140, 165, 190].map(deg => {
      const a = deg * Math.PI / 180, c = Math.cos(a), n = Math.sin(a);
      return `<line x1="${(35 + 30 * c).toFixed(1)}" y1="${(40 + 30 * n).toFixed(1)}" x2="${(35 + 52 * c).toFixed(1)}" y2="${(40 + 52 * n).toFixed(1)}"/>`;
    }).join("") : "";
    return `${tag(c, s)}
      <svg class="ls" viewBox="0 0 70 100" role="img" aria-label="Over-travel limit switch">
        ${burst ? `<g class="ls-burst">${burst}</g>` : ""}
        <rect x="0" y="0" width="70" height="6" class="ls-mount"/>
        <rect x="32" y="6" width="6" height="8" class="ls-mount"/>
        <rect x="13" y="14" width="44" height="36" rx="5" class="ls-body"/>
        <rect x="20" y="25" width="20" height="14" rx="2" class="ls-window"/>
        <circle cx="48" cy="22" r="4.5" class="ls-led"/>
        <g transform="rotate(${lever} 35 50)">
          <line x1="35" y1="50" x2="35" y2="80" class="ls-arm"/>
          <circle cx="35" cy="86" r="8" class="ls-roller"/>
        </g>
        <circle cx="35" cy="50" r="3" class="ls-pivot"/>
      </svg>`;
  }

  function beacon(c, s) {
    return `${tag(c, s)}<span class="beacon"><i></i></span>`;
  }

  const KIND = { light_curtain: ["s3-curtain", curtain], over_travel: ["s3-switch", limitSwitch], sensor: ["s3-beacon", beacon] };

  function device(c) {
    const s = cls(c.status);
    const [kind, draw] = KIND[c.picture] || KIND.sensor;
    return `<div class="s3-dev ${kind} s3-${s}" data-s3="${esc(c.tag)}" data-status="${s}" title="${esc(c.tag)}">${draw(c, s)}</div>`;
  }

  function fill(layer, controls) {
    if (!layer) return;
    const tags = controls.map(c => c.tag).join("|");
    if (layer.getAttribute("data-tags") !== tags) {           // first draw / list changed
      layer.setAttribute("data-tags", tags);
      layer.innerHTML = controls.map(device).join("");
      return;
    }
    controls.forEach((c, i) => {
      const el = layer.children[i], s = cls(c.status);
      if (el.getAttribute("data-status") !== s) el.outerHTML = device(c);
      else el.querySelector(".s3-since").textContent = since(c, s);
    });
  }

  window.renderS3 = function (controls) {
    if (!controls || !controls.length) return;
    fill($("s3-top"), controls.filter(c => c.place !== "bottom"));
    fill($("s3-bottom"), controls.filter(c => c.place === "bottom"));
    window.drawS3Rays();
  };

  // Light-curtain beams: from each stud of the bar onto the chassis picture.
  let lastRays = "";
  window.drawS3Rays = function () {
    const svg = $("s3-rays"), view = $("station-view"), img = $("chassis-img");
    if (!svg || !view || !img) return;
    const vr = view.getBoundingClientRect(), ir = img.getBoundingClientRect();
    const parts = [];
    view.querySelectorAll(".s3-curtain").forEach(dev => {
      const s = dev.getAttribute("data-status");
      if (s === "pending") return;
      const top = dev.parentElement.id === "s3-top";
      const reach = s === "bad" ? 0.42 : 0.1;                  // how far into the picture the light goes
      const yEnd = top ? ir.top + ir.height * reach : ir.bottom - ir.height * reach;
      const studs = [...dev.querySelectorAll(".lc-studs i")].map(i => i.getBoundingClientRect());
      if (!studs.length) return;
      const y0 = top ? studs[0].bottom : studs[0].top;
      const x0 = studs[0].left, x1 = studs[studs.length - 1].right;
      const p = n => Math.round(n * 10) / 10;
      parts.push(`<polygon class="sheet" fill="url(#s3-${top ? "down" : "up"}-${s})" points="${p(x0 - vr.left)},${p(y0 - vr.top)} ` +
                 `${p(x1 - vr.left)},${p(y0 - vr.top)} ${p(x1 - vr.left + 14)},${p(yEnd - vr.top)} ${p(x0 - vr.left - 14)},${p(yEnd - vr.top)}"/>`);
      studs.forEach(r => {
        const x = p(r.left + r.width / 2 - vr.left);
        parts.push(`<line class="ray ray-${s}" x1="${x}" y1="${p(y0 - vr.top)}" x2="${x}" y2="${p(yEnd - vr.top)}"/>`);
      });
    });
    // light fades out away from the bar
    const grad = (id, color, down) => `<linearGradient id="${id}" x1="0" y1="${down ? 0 : 1}" x2="0" y2="${down ? 1 : 0}">` +
      `<stop offset="0" stop-color="${color}" stop-opacity="0.45"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient>`;
    const markup = `<defs>${grad("s3-down-bad", "#ff2b2b", true)}${grad("s3-up-bad", "#ff2b2b", false)}` +
      `${grad("s3-down-ok", "#2fb350", true)}${grad("s3-up-ok", "#2fb350", false)}</defs>${parts.join("")}`;
    svg.setAttribute("width", vr.width);
    svg.setAttribute("height", vr.height);
    if (markup !== lastRays) { svg.innerHTML = markup; lastRays = markup; }  // unchanged: keep animations running
  };
})();
