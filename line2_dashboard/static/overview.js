// Refreshes the All Stations tiles from /api/status.
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
        el.querySelector(".tile-count").textContent = st.ok + "/" + st.total + " OK";
      });
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
