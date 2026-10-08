// S3 controls drawn around the chassis on a station page (s3_controls in the station template):
//   area_scanner   safety area scanner above ("place": "top") or below ("bottom") the chassis, its
//                  head facing the chassis; its beams fan out onto the chassis - faint green when OK,
//                  bright red and flashing when NOT OK
//   light_curtain  a bar in the same place, beams straight onto the chassis
//   over_travel    roller limit switch at the right-hand end of its row; red light bursts out of it
//                  and the lever is tripped when NOT OK
//   sensor         any other S3 signal: a beacon lamp
// Tag 0 = OK (green), 1 = NOT OK (red), no row in SQL yet = grey.
// station.js calls window.renderS3(st.s3) on every refresh and window.drawS3Rays() whenever the
// layout changes. A device is only redrawn when its status changes, so animations run smoothly.
(function () {
  const $ = id => document.getElementById(id);
  const R = el => (window.logicalRect ? window.logicalRect(el) : el.getBoundingClientRect());
  const esc = v => String(v === null || v === undefined ? "" : v).replace(/[&<>"']/g, c => ({
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

  // Drawn head up (as the device stands); CSS turns it so the head faces the chassis.
  function areaScanner(c, s) {
    return `${tag(c, s)}
      <svg class="sc" viewBox="0 0 64 60" role="img" aria-label="Area scanner">
        <ellipse cx="32" cy="8" rx="19" ry="6" class="sc-cap"/>
        <path d="M13,9 L51,9 L45,30 L19,30 Z" class="sc-cone"/>
        <rect x="17" y="15" width="30" height="9" rx="2" class="sc-head"/>
        <rect x="19" y="18.5" width="26" height="2" class="sc-scanline"/>
        <rect x="18" y="30" width="28" height="4" class="sc-neck"/>
        <rect x="5" y="33" width="54" height="25" rx="4" class="sc-body"/>
        <rect x="5" y="33" width="54" height="5" rx="2" class="sc-plate"/>
        <rect x="27" y="41" width="10" height="9" rx="1" class="sc-display"/>
        <circle cx="16" cy="43" r="2.2" class="sc-led"/><circle cx="16" cy="50" r="2.2" class="sc-led"/>
        <circle cx="48" cy="43" r="2.2" class="sc-led"/><circle cx="48" cy="50" r="2.2" class="sc-led"/>
      </svg>`;
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

  const KIND = { area_scanner: ["s3-scanner", areaScanner], light_curtain: ["s3-curtain", curtain], over_travel: ["s3-switch", limitSwitch], sensor: ["s3-beacon", beacon] };

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

  // Light-curtain beams: from each stud of the bar onto the chassis picture. On a portrait screen
  // the curtains stand to the right ("top") / left ("bottom") of the upright chassis and shine sideways.
  let lastRays = "";
  window.drawS3Rays = function () {
    const svg = $("s3-rays"), view = $("station-view"), img = $("chassis-img");
    if (!svg || !view || !img) return;
    const vr = R(view), ir = R(img);
    const upright = document.documentElement.classList.contains("portrait");
    const p = n => Math.round(n * 10) / 10;
    const parts = [];
    view.querySelectorAll(".s3-curtain").forEach(dev => {
      const s = dev.getAttribute("data-status");
      if (s === "pending") return;
      const top = dev.parentElement.id === "s3-top";
      const reach = s === "bad" ? 0.42 : 0.1;                  // how far into the picture the light goes
      const studs = [...dev.querySelectorAll(".lc-studs i")].map(R);
      if (!studs.length) return;
      // work along / across the bar, then swap x and y for an upright chassis
      let a0, a1, b0, bEnd, dir, at;
      if (!upright) {
        a0 = studs[0].left - vr.left; a1 = studs[studs.length - 1].right - vr.left;
        b0 = (top ? studs[0].bottom : studs[0].top) - vr.top;
        bEnd = (top ? ir.top + ir.height * reach : ir.bottom - ir.height * reach) - vr.top;
        dir = top ? "down" : "up";
        at = r => r.left + r.width / 2 - vr.left;
      } else {
        a0 = studs[0].top - vr.top; a1 = studs[studs.length - 1].bottom - vr.top;
        b0 = (top ? studs[0].left : studs[0].right) - vr.left;
        bEnd = (top ? ir.right - ir.width * reach : ir.left + ir.width * reach) - vr.left;
        dir = top ? "left" : "right";
        at = r => r.top + r.height / 2 - vr.top;
      }
      const pt = (a, b) => (upright ? `${p(b)},${p(a)}` : `${p(a)},${p(b)}`);
      parts.push(`<polygon class="sheet" fill="url(#s3-${dir}-${s})" points="${pt(a0, b0)} ${pt(a1, b0)} ${pt(a1 + 14, bEnd)} ${pt(a0 - 14, bEnd)}"/>`);
      studs.forEach(r => {
        const [x1, y1] = pt(at(r), b0).split(","), [x2, y2] = pt(at(r), bEnd).split(",");
        parts.push(`<line class="ray ray-${s}" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/>`);
      });
    });
    // Area scanners: a fan of beams from the scan head onto the same stretch of chassis a curtain covers
    view.querySelectorAll(".s3-scanner").forEach(dev => {
      const s = dev.getAttribute("data-status");
      if (s === "pending") return;
      const top = dev.parentElement.id === "s3-top";
      const reach = s === "bad" ? 0.42 : 0.1;
      const head = R(dev.querySelector(".sc-head")), span = R(dev);
      let o, a0, a1, bEnd, dir;   // o = beam origin [along, across]; a0..a1 = covered stretch
      if (!upright) {
        o = [head.left + head.width / 2 - vr.left, (top ? head.bottom : head.top) - vr.top];
        a0 = span.left - vr.left; a1 = span.right - vr.left;
        bEnd = (top ? ir.top + ir.height * reach : ir.bottom - ir.height * reach) - vr.top;
        dir = top ? "down" : "up";
      } else {
        o = [head.top + head.height / 2 - vr.top, (top ? head.left : head.right) - vr.left];
        a0 = span.top - vr.top; a1 = span.bottom - vr.top;
        bEnd = (top ? ir.right - ir.width * reach : ir.left + ir.width * reach) - vr.left;
        dir = top ? "left" : "right";
      }
      const pt = (a, b) => (upright ? `${p(b)},${p(a)}` : `${p(a)},${p(b)}`);
      parts.push(`<polygon class="sheet" fill="url(#s3-${dir}-${s})" points="${pt(o[0] - 5, o[1])} ${pt(o[0] + 5, o[1])} ` +
                 `${pt(a1 + 14, bEnd)} ${pt(a0 - 14, bEnd)}"/>`);
      const n = 16;
      for (let i = 0; i < n; i++) {
        const a = a0 - 14 + (a1 - a0 + 28) * (i + 0.5) / n;
        const [x1, y1] = pt(o[0], o[1]).split(","), [x2, y2] = pt(a, bEnd).split(",");
        parts.push(`<line class="ray ray-${s}" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/>`);
      }
    });
    // light fades out away from the device
    const DIRS = { down: [0, 0, 0, 1], up: [0, 1, 0, 0], right: [0, 0, 1, 0], left: [1, 0, 0, 0] };
    const grad = (dir, s, color) => { const [x1, y1, x2, y2] = DIRS[dir];
      return `<linearGradient id="s3-${dir}-${s}" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}">` +
        `<stop offset="0" stop-color="${color}" stop-opacity="0.45"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient>`; };
    const markup = "<defs>" + Object.keys(DIRS).map(d => grad(d, "bad", "#ff2b2b") + grad(d, "ok", "#2fb350")).join("") +
      "</defs>" + parts.join("");
    svg.setAttribute("width", vr.width);
    svg.setAttribute("height", vr.height);
    if (markup !== lastRays) { svg.innerHTML = markup; lastRays = markup; }  // unchanged: keep animations running
  };
})();
