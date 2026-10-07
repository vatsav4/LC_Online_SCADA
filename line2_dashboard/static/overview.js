// Refreshes the All Stations tiles (L3 torque wrenches and S3 controls) from /api/status.
(function () {
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
      const res = await fetch("/api/status", { cache: "no-store" });
      const data = await res.json();
      data.stations.forEach(st => {
        const el = document.getElementById("station-tile-" + st.id);
        if (!el) return;
        el.classList.remove("tile-green", "tile-red", "tile-idle");
        el.classList.add("tile-" + st.status);
        const l3 = el.querySelector('[data-kind="l3"]'), s3 = el.querySelector('[data-kind="s3"]');
        if (l3) l3.textContent = `L3 ${st.l3_ok}/${st.l3_total}`;
        if (s3) s3.textContent = `S3 ${st.s3_ok}/${st.s3_total}`;
      });
      const count = s => data.stations.filter(st => st.status === s).length;
      const sum = document.getElementById("home-summary");
      if (sum) {
        sum.querySelector(".sum-bad b").textContent = count("red");
        sum.querySelector(".sum-ok b").textContent = count("green");
        sum.querySelector(".sum-idle b").textContent = count("idle");
      }
      setConnection(data.db_ok, data.updated_at);
    } catch (err) {
      setConnection(false);
      console.error("status refresh failed", err);
    }
  }

  refresh();
  window.__pageIntervals = window.__pageIntervals || [];
  window.__pageIntervals.push(setInterval(refresh, 2000));
})();
