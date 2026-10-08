// Lightweight same-origin client-side navigation ("pjax"-style).
//
// Flask still serves complete, real pages for every route - direct loads,
// refreshes, and bookmarks all keep working normally. This script only
// intercepts clicks on internal links (station tiles, Home, St n / St n+1)
// and swaps in the fetched page's .content / titles instead of a full
// browser navigation, so moving between stations doesn't flash white.

(function () {
  function clearPage() {
    (window.__pageIntervals || []).forEach(clearInterval);
    window.__pageIntervals = [];
    (window.__pageCleanups || []).forEach(fn => { try { fn(); } catch (e) { console.error(e); } });
    window.__pageCleanups = [];
    document.querySelectorAll("script[data-spa-page]").forEach(s => s.remove());
  }

  // Run the new page's own scripts (station.js, s3.js, overview.js). base.html's inline
  // script and spa.js are already running; data blocks (application/json) are not code.
  function runPageScripts(doc) {
    doc.querySelectorAll("script[src]").forEach(orig => {
      if (orig.getAttribute("src").includes("spa.js")) return;
      const s = document.createElement("script");
      Array.from(orig.attributes).forEach(attr => s.setAttribute(attr.name, attr.value));
      s.async = false;                      // keep page order: s3.js before station.js
      s.setAttribute("data-spa-page", "");
      document.body.appendChild(s);
    });
  }

  function swapContent(doc) {
    const newContent = doc.querySelector(".content");
    if (!newContent) return false;

    const content = document.querySelector(".content");
    content.innerHTML = newContent.innerHTML;
    content.className = newContent.className;

    const newCenter = doc.querySelector(".center-title");
    const newRight = doc.querySelector(".right-title");
    const center = document.querySelector(".center-title");
    const right = document.querySelector(".right-title");
    if (center && newCenter) center.innerHTML = newCenter.innerHTML;
    if (right && newRight) right.innerHTML = newRight.innerHTML;

    if (doc.title) document.title = doc.title;

    return true;
  }

  async function navigate(url, push) {
    try {
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) throw new Error("bad response " + res.status);
      const html = await res.text();
      const doc = new DOMParser().parseFromString(html, "text/html");

      clearPage();
      if (!swapContent(doc)) throw new Error("no .content in response");
      runPageScripts(doc);

      if (push) history.pushState({ url: url }, "", url);
      window.scrollTo(0, 0);
    } catch (err) {
      console.error("spa navigate failed, falling back to full load", err);
      window.location.href = url;
    }
  }

  document.addEventListener("click", (e) => {
    if (e.defaultPrevented || e.button !== 0) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;

    const link = e.target.closest("a");
    if (!link || !link.href) return;
    if (link.target && link.target !== "_self") return;
    if (link.hasAttribute("download") || link.hasAttribute("data-reload")) return;
    if (link.origin !== window.location.origin) return;

    e.preventDefault();
    navigate(link.href, true);
  });

  window.addEventListener("popstate", () => {
    navigate(window.location.href, false);
  });
})();
