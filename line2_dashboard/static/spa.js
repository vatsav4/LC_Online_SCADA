// Lightweight same-origin client-side navigation ("pjax"-style).
//
// Flask still serves complete, real pages for every route - direct loads,
// refreshes, and bookmarks all keep working normally. This script only
// intercepts clicks on internal links (station tiles, the Home button,
// the logo) and swaps in the fetched page's .content / titles instead of
// doing a full browser navigation. That matters because cycle.js (the
// live Set/Elapsed timer) and this script are loaded once in base.html
// and are never part of what gets swapped - a full page reload would
// destroy and restart cycle.js's state on every click, which is what
// made the timer visibly reset when moving between stations.

(function () {
  function clearPageIntervals() {
    (window.__pageIntervals || []).forEach(clearInterval);
    window.__pageIntervals = [];
  }

  function runPageScripts(doc) {
    doc.querySelectorAll("script").forEach(orig => {
      const src = orig.getAttribute("src") || "";
      if (src.includes("cycle.js") || src.includes("spa.js")) return; // already persistent, don't re-run

      const s = document.createElement("script");
      Array.from(orig.attributes).forEach(attr => s.setAttribute(attr.name, attr.value));
      if (!orig.src) s.textContent = orig.textContent;
      document.body.appendChild(s);
    });
  }

  function swapContent(doc) {
    const newContent = doc.querySelector(".content");
    if (!newContent) return false;

    document.querySelector(".content").innerHTML = newContent.innerHTML;

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

      clearPageIntervals();
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
    if (link.hasAttribute("download")) return;
    if (link.origin !== window.location.origin) return;

    e.preventDefault();
    navigate(link.href, true);
  });

  window.addEventListener("popstate", () => {
    navigate(window.location.href, false);
  });
})();
