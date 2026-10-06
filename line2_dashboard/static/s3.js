// S3 controls panel on a station page: one card per control with a drawing of it
//   light_curtain  safety light curtain; NOT OK = a hand breaks the beams
//   over_travel    overhead roller limit switch; NOT OK = carriage past the limit, lever tripped
//   sensor         any other S3 signal (shield with tick / cross)
// Green = OK (tag 0), red = NOT OK (tag 1), grey = no data yet.
// station.js calls window.renderS3(st.s3) on every refresh. A card is only redrawn when its
// status changes, so the beam animation keeps running smoothly.
(function () {
  const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const cls = s => (s === "OK" ? "ok" : s === "NOT OK" ? "bad" : "pending");
  const LABEL = { ok: "OK", bad: "NOT OK", pending: "NO DATA" };

  // ---------------------------------------------------------------- drawings (viewBox 200 x 140)
  function post(x, lensX) {
    return `<rect x="${x}" y="8" width="16" height="124" rx="3" class="housing"/>
      <rect x="${lensX}" y="18" width="5" height="104" class="lens"/>
      <rect x="${x}" y="8" width="16" height="9" rx="3" class="cap"/>
      <rect x="${x}" y="123" width="16" height="9" rx="3" class="cap"/>
      <circle cx="${x + 8}" cy="12.5" r="2.6" class="led"/>`;
  }

  const HAND = `<g class="hand">
      <rect x="97" y="-4" width="24" height="40" rx="3" class="sleeve"/>
      <rect x="93" y="56" width="6.5" height="24" rx="3.2" class="skin"/>
      <rect x="100.5" y="58" width="6.5" height="28" rx="3.2" class="skin"/>
      <rect x="108" y="58" width="6.5" height="27" rx="3.2" class="skin"/>
      <rect x="115.5" y="56" width="6.5" height="22" rx="3.2" class="skin"/>
      <rect x="83" y="40" width="7" height="22" rx="3.5" class="skin" transform="rotate(-28 87 51)"/>
      <rect x="92" y="35" width="32" height="28" rx="9" class="skin"/>
      <rect x="95" y="30" width="28" height="7" rx="2" class="cuff"/>
    </g>`;

  function lightCurtain(state) {
    const beams = [];
    for (let i = 0; i < 13; i++) {
      const y = 22 + i * 8;
      if (state === "bad" && y <= 86) {   // beam stopped by the hand: lit up to it, dark after it
        beams.push(`<line class="beam" x1="38" y1="${y}" x2="88" y2="${y}"/>`,
                   `<line class="beam beam-dead" x1="126" y1="${y}" x2="162" y2="${y}"/>`);
      } else {
        beams.push(`<line class="beam" x1="38" y1="${y}" x2="162" y2="${y}"/>`);
      }
    }
    return `<svg viewBox="0 0 200 140" role="img" aria-label="Light curtain">
      <rect x="38" y="18" width="124" height="104" class="field"/>
      ${beams.join("")}
      ${post(22, 33)}${post(162, 162)}
      ${state === "bad" ? HAND : ""}
    </svg>`;
  }

  function overTravel(state) {
    const x = state === "bad" ? 104 : 20;          // carriage position on the rail
    const lever = state === "bad" ? -50 : 0;       // roller lever pushed over by the cam
    return `<svg viewBox="0 0 200 140" role="img" aria-label="Over-travel limit switch">
      <rect x="6" y="4" width="188" height="9" rx="2" class="steel"/>
      <rect x="146" y="13" width="4" height="6" class="steel"/>
      <rect x="134" y="18" width="30" height="28" rx="3" class="housing"/>
      <rect x="138" y="30" width="16" height="11" rx="2" class="lens"/>
      <circle cx="158" cy="25" r="2.8" class="led"/>
      <g transform="rotate(${lever} 148 46)">
        <line x1="148" y1="46" x2="148" y2="64" class="arm"/>
        <circle cx="148" cy="66" r="6" class="roller"/>
      </g>
      <circle cx="148" cy="46" r="2.6" class="pivot"/>
      <line x1="178" y1="54" x2="178" y2="128" class="limit-line"/>
      <g class="carriage">
        <polygon points="${x + 38},76 ${x + 44},64 ${x + 58},64 ${x + 62},76" class="cam"/>
        <rect x="${x}" y="76" width="64" height="24" rx="4" class="body"/>
        <rect x="${x + 6}" y="82" width="22" height="8" rx="2" class="window"/>
        <circle cx="${x + 13}" cy="104" r="6" class="wheel"/>
        <circle cx="${x + 51}" cy="104" r="6" class="wheel"/>
      </g>
      <rect x="6" y="110" width="188" height="7" rx="2" class="steel"/>
      <rect x="6" y="122" width="132" height="5" rx="2" class="zone-ok"/>
      <rect x="138" y="122" width="56" height="5" rx="2" class="zone-bad"/>
      ${state === "bad" ? `<g class="warn"><polygon points="30,24 46,52 14,52"/><text x="30" y="49">!</text></g>` : ""}
    </svg>`;
  }

  function sensor(state) {
    const mark = state === "ok" ? `<polyline points="80,72 95,88 122,56" class="mark"/>`
      : state === "bad" ? `<path d="M82,56 L118,92 M118,56 L82,92" class="mark"/>` : `<circle cx="100" cy="74" r="4" class="mark-dot"/>`;
    return `<svg viewBox="0 0 200 140" role="img" aria-label="Safety signal">
      <path d="M100,12 L146,30 V70 C146,100 124,120 100,130 C76,120 54,100 54,70 V30 Z" class="shield"/>
      ${mark}
    </svg>`;
  }

  const PICTURES = { light_curtain: lightCurtain, over_travel: overTravel, sensor: sensor };

  // ---------------------------------------------------------------- cards
  const since = (c, s) => (c.since ? (s === "bad" ? "since " : s === "ok" ? "OK since " : "") + c.since : "");

  function card(c) {
    const s = cls(c.status);
    return `<div class="s3-card s3-${s}" data-s3="${esc(c.tag)}" data-status="${s}" title="${esc(c.tag)}">
      <div class="s3-pic">${(PICTURES[c.picture] || sensor)(s)}</div>
      <div class="s3-info">
        <div class="s3-name">${esc(c.name)}</div>
        <span class="s3-state">${LABEL[s]}</span>
        <div class="s3-since">${esc(since(c, s))}</div>
      </div>
    </div>`;
  }

  window.renderS3 = function (controls) {
    const list = document.getElementById("s3-list");
    if (!list || !controls) return;
    const tags = controls.map(c => c.tag).join("|");
    if (list.getAttribute("data-tags") !== tags) {           // first draw / list changed
      list.setAttribute("data-tags", tags);
      list.innerHTML = controls.map(card).join("");
    } else {
      controls.forEach((c, i) => {
        const el = list.children[i];
        if (el.getAttribute("data-status") !== cls(c.status)) el.outerHTML = card(c);
        else el.querySelector(".s3-since").textContent = since(c, cls(c.status));
      });
    }
    const bad = controls.filter(c => c.status === "NOT OK").length;
    const waiting = controls.filter(c => c.status === "PENDING").length;
    const sum = document.getElementById("s3-summary");
    if (sum) {
      sum.className = "s3-summary " + (bad ? "s3-sum-bad" : waiting ? "s3-sum-pending" : "s3-sum-ok");
      sum.textContent = bad ? `${bad} NOT OK` : waiting ? "NO DATA" : "ALL OK";
    }
  };
})();
