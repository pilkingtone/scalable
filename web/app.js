/* Scalable front end. Reads data/feeds.json (built by `python -m scalable`).
 * Views: #top (latest from every source) and one Alltop-style page per topic (#tech, #business, ...). */
(function () {
  "use strict";

  const state = {data: null, view: "top", q: ""};
  // Monogram colors from Electable's validated categorical palette (white text on each).
  const BADGES = ["#2a78d6", "#eb6834", "#1baf7a", "#6250d6", "#e34948", "#008300", "#d55181", "#256abf"];

  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const safeHref = (u) => /^https?:\/\//.test(u || "") ? u : null;
  const ago = (iso) => {
    if (!iso) return "";
    const m = Math.round((Date.now() - new Date(iso)) / 6e4);
    return m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} hr ago` : `${Math.round(m / 1440)} d ago`;
  };
  const fmtTime = (iso) => { const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleString(undefined, {month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short"}); };
  const hash = (s) => [...s].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);
  const monogram = (name) => name.replace(/^The\s+/i, "").split(/[\s·.+&-]+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
  const matches = (item) => !state.q || `${item.title} ${item.summary || ""}`.toLowerCase().includes(state.q);
  const link = (item, cls) => {
    const a = el("a", cls, item.title);
    const href = safeHref(item.url); if (href) a.href = href;
    a.target = "_blank"; a.rel = "noopener noreferrer";
    return a;
  };

  /* ---------------- hover / focus preview ---------------- */
  const tip = document.getElementById("preview");
  function preview(evt, item, source) {
    if (!item.summary) return;
    tip.replaceChildren(el("b", null, item.title), el("span", null, item.summary),
      el("small", null, [source, item.published ? fmtTime(item.published) : ""].filter(Boolean).join(" · ")));
    tip.hidden = false;
    const r = evt.currentTarget.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight;
    let x = Math.min(r.left, innerWidth - w - 8), y = r.bottom + 6;
    if (y + h > innerHeight - 8) y = r.top - h - 6;
    tip.style.left = Math.max(8, x) + "px"; tip.style.top = Math.max(8, y) + "px";
  }
  const hide = () => { tip.hidden = true; };
  function withPreview(a, item, source) {
    a.addEventListener("mouseenter", (e) => preview(e, item, source));
    a.addEventListener("focus", (e) => preview(e, item, source));
    a.addEventListener("mouseleave", hide); a.addEventListener("blur", hide);
    return a;
  }

  /* ---------------- views ---------------- */
  function renderTabs() {
    const tabs = document.getElementById("topic-tabs"); tabs.replaceChildren();
    [{id: "top", name: "Top stories"}, ...state.data.topics].forEach((t) => {
      const b = el("button", null, t.name); b.type = "button"; b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", t.id === state.view);
      b.addEventListener("click", () => { location.hash = t.id; });
      tabs.appendChild(b);
    });
    const sel = tabs.querySelector('[aria-selected="true"]');
    if (sel && tabs.scrollWidth > tabs.clientWidth) sel.scrollIntoView({block: "nearest", inline: "center"});
  }

  function renderTop() {
    const list = document.getElementById("top-list"); list.replaceChildren();
    const topicName = Object.fromEntries(state.data.topics.map((t) => [t.id, t.name]));
    const items = state.data.top.filter(matches);
    document.getElementById("top-sub").textContent = state.q
      ? `${items.length} headline${items.length === 1 ? "" : "s"} matching “${state.q}”.`
      : `The newest headlines from ${state.data.sources.length} sources, refreshed every hour.`;
    items.forEach((it) => {
      const li = el("li", "news-item"), meta = el("div", "news-meta");
      const t = el("time", null, ago(it.published)); t.dateTime = it.published; t.title = fmtTime(it.published);
      meta.append(el("span", "src", it.source), el("span", "chip", topicName[it.topic] || it.topic), t);
      li.append(meta, link(it));
      if (it.summary) li.appendChild(el("p", null, it.summary));
      list.appendChild(li);
    });
    if (!items.length) list.appendChild(el("li", "news-item", "No headlines match your search."));
  }

  function renderTopic() {
    const grid = document.getElementById("grid"); grid.replaceChildren();
    const topic = state.data.topics.find((t) => t.id === state.view);
    const sources = state.data.sources.filter((s) => s.topic === state.view);
    let shown = 0;
    sources.forEach((s) => {
      const items = s.items.filter(matches);
      if (state.q && !items.length) return;
      shown++;
      const card = el("article", "card source");
      const head = el("div", "source-head");
      const badge = el("span", "badge", monogram(s.name)); badge.style.background = BADGES[hash(s.name) % BADGES.length];
      badge.setAttribute("aria-hidden", "true");
      const name = el("a", null, s.name); if (safeHref(s.home)) name.href = s.home; name.target = "_blank"; name.rel = "noopener noreferrer";
      head.append(badge, name); card.appendChild(head);
      const ul = el("ul", "heads");
      items.forEach((it) => {
        const li = el("li");
        li.appendChild(withPreview(link(it), it, s.name));
        if (it.published) { const t = el("time", null, ago(it.published)); t.dateTime = it.published; t.title = fmtTime(it.published); li.appendChild(t); }
        ul.appendChild(li);
      });
      card.appendChild(ul);
      const more = el("a", "more", `More from ${s.name} →`); if (safeHref(s.home)) more.href = s.home; more.target = "_blank"; more.rel = "noopener noreferrer";
      card.appendChild(more);
      grid.appendChild(card);
    });
    document.getElementById("topic-sub").textContent = state.q
      ? `${shown} of ${sources.length} ${topic.name} sources have headlines matching “${state.q}”.`
      : `${topic.name}: the latest headlines from ${sources.length} sources.`
        + (matchMedia("(hover: hover)").matches ? " Hover over a headline for a preview; headlines open on the publisher's site." : " Headlines open on the publisher's site.");
  }

  function renderMeta() {
    const m = document.getElementById("meta"); m.replaceChildren();
    const a = el("div"); a.append("Updated "); const s = el("strong", null, fmtTime(state.data.generated_at)); a.appendChild(s);
    m.append(a, el("div", null, `${state.data.sources.length} sources · refreshed hourly`));
    document.getElementById("sources-note").textContent = "Sources: " + state.data.sources.map((x) => x.name).join(", ") + ".";
  }

  function render() {
    hide();
    const ids = ["top", ...state.data.topics.map((t) => t.id)];
    const h = location.hash.replace(/^#/, "");
    state.view = ids.includes(h) ? h : "top";
    renderTabs();
    document.getElementById("view-top").hidden = state.view !== "top";
    document.getElementById("view-topic").hidden = state.view === "top";
    if (state.view === "top") renderTop(); else renderTopic();
  }

  async function load() {
    const data = await fetch("data/feeds.json", {cache: "no-cache"}).then((r) => r.ok ? r.json() : null).catch(() => null);
    if (!data) {
      const e = document.getElementById("empty"); e.hidden = false;
      e.textContent = "Headlines haven't been compiled yet. Run: python -m scalable";
      return;
    }
    state.data = data;
    renderMeta(); render();
    addEventListener("hashchange", render);
    let t; document.getElementById("search").addEventListener("input", (e) => {
      clearTimeout(t); t = setTimeout(() => { state.q = e.target.value.trim().toLowerCase(); render(); }, 120);
    });
    addEventListener("scroll", hide, {passive: true});
  }
  load();
})();
