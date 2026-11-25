/* Scalable front end. Reads data/feeds.json (built by `python -m scalable`).
 * Routes: #            home: topic cards + top stories across every topic
 *         #tech        a topic's stories (clusters ranked by coverage and recency)
 *         #tech/columns   a box of latest headlines per source
 *         #tech/list      every headline, newest first
 */
(function () {
  "use strict";

  const state = {data: null, topic: null, mode: "stories", q: "", cat: null};
  let CATS = [];   // [{id, name, re}] from data.categories
  const MODES = [["stories", "Stories"], ["columns", "Columns"], ["list", "List"]];
  // Monogram colors from Electable's validated categorical palette (white text on each).
  const BADGES = ["#2a78d6", "#eb6834", "#1baf7a", "#6250d6", "#e34948", "#008300", "#d55181", "#256abf"];
  const view = document.getElementById("view");

  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const safeHref = (u) => /^https?:\/\//.test(u || "") ? u : null;
  const ago = (iso) => {
    if (!iso) return "";
    const m = Math.round((Date.now() - new Date(iso)) / 6e4);
    return m < 1 ? "just now" : m < 60 ? `${m}m ago` : m < 1440 ? `${Math.round(m / 60)}h ago` : `${Math.round(m / 1440)}d ago`;
  };
  const fmtTime = (iso) => { const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleString(undefined, {month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short"}); };
  const timeEl = (iso, text) => { const t = el("time", null, text || ago(iso)); if (iso) { t.dateTime = iso; t.title = fmtTime(iso); } return t; };
  const hash = (s) => [...s].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);
  const monogram = (name) => name.replace(/^The\s+/i, "").split(/[\s·.+&-]+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
  const badge = (name, cls) => { const b = el("span", "badge" + (cls ? " " + cls : ""), monogram(name)); b.style.background = BADGES[hash(name) % BADGES.length]; b.setAttribute("aria-hidden", "true"); return b; };
  const out = (a) => { a.target = "_blank"; a.rel = "noopener noreferrer"; return a; };
  const link = (title, url, cls) => { const a = el("a", cls, title); const h = safeHref(url); if (h) a.href = h; return out(a); };
  const plural = (n, w) => `${n} ${n === 1 ? w : w.endsWith("y") ? w.slice(0, -1) + "ies" : w + "s"}`;
  const storyText = (s) => [s.lead.title, s.lead.summary, s.ai && s.ai.summary, ...s.more.map((m) => m.title)].join(" ").toLowerCase();
  const catOf = (id) => CATS.find((c) => c.id === id);
  const inCat = (text, id) => { const c = catOf(id); return !c || c.re.test(text); };
  // A story is in a category if its lead headline/summary says so, or at least half its headlines do.
  const storyInCat = (s, c) => c.re.test(`${s.lead.title} ${s.lead.summary || ""} ${(s.ai && s.ai.summary) || ""}`)
    || [s.lead.title, ...s.more.map((m) => m.title)].filter((t) => c.re.test(t)).length * 2 >= s.more.length + 1;
  const itemMatches = (it) => (!state.q || `${it.title} ${it.summary || ""}`.toLowerCase().includes(state.q))
    && inCat(`${it.title} ${it.summary || ""}`, state.cat);
  const storyMatches = (s) => (!state.q || storyText(s).includes(state.q)) && (!catOf(state.cat) || storyInCat(s, catOf(state.cat)));
  // Hash routes: #topic/mode?c=category (each part optional).
  const hashFor = (topic, mode, cat) => "#" + (topic || "") + (topic && mode && mode !== "stories" ? "/" + mode : "") + (cat ? "?c=" + cat : "");

  /* ---------------- hover / focus preview (Columns and List) ---------------- */
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
    if (!matchMedia("(hover: hover)").matches) return a;
    a.addEventListener("mouseenter", (e) => preview(e, item, source));
    a.addEventListener("focus", (e) => preview(e, item, source));
    a.addEventListener("mouseleave", hide); a.addEventListener("blur", hide);
    return a;
  }

  /* ---------------- shared pieces ---------------- */
  function kicker(label, note) {
    const k = el("div", "kicker"); k.append(el("b", null, label), el("i", "rule"));
    if (note) k.appendChild(el("span", null, note));
    return k;
  }

  function storyCard(s, byId) {
    const card = el("article", "story");
    const meta = el("div", "story-meta");
    meta.append(badge(s.lead.source), el("span", "src", s.lead.source), el("span", "dot", "·"));
    const upd = timeEl(s.updated, "Updated " + ago(s.updated)); meta.appendChild(upd);
    if (s.n_sources > 1) meta.append(el("span", "dot", "·"), el("span", "mono", plural(s.n_sources, "source")));
    if (s.hot) meta.appendChild(el("span", "hot", "HOT"));
    const h = el("h3"); h.appendChild(link(s.lead.title, s.lead.url));
    card.append(meta, h);

    const summary = (s.ai && s.ai.summary) || s.lead.summary;
    if (summary) card.appendChild(el("p", "summary", summary));
    if (s.ai && s.ai.why_it_matters) {
      const w = el("div", "why"); w.append(el("b", null, "Why it matters"), s.ai.why_it_matters); card.appendChild(w);
    }
    if (s.more.length) {
      const row = el("div", "more-row"); row.appendChild(el("b", null, "MORE"));
      const shown = s.more.slice(0, 3);
      const add = (m) => { const a = link("", m.url); a.title = m.title; a.append(badge(m.source), m.source); row.insertBefore(a, extra); };
      const extra = s.more.length > 3 ? el("button", null, `+${s.more.length - 3} more`) : null;
      if (extra) { extra.type = "button"; row.appendChild(extra); extra.addEventListener("click", () => { s.more.slice(3).forEach(add); extra.remove(); }); }
      shown.forEach(add);
      card.appendChild(row);
    }
    const rel = s.related.map((id) => byId[id]).filter(Boolean);
    if (rel.length) {
      const box = el("div", "related");
      rel.forEach((r) => {
        const d = el("div");
        if (r.ai && r.ai.label) d.appendChild(el("span", "rel-label", r.ai.label));
        d.appendChild(link(r.lead.title, r.lead.url));
        d.appendChild(el("small", null, [r.lead.source, r.n_sources > 1 ? plural(r.n_sources, "source") : "", ago(r.updated)].filter(Boolean).join(" · ")));
        box.appendChild(d);
      });
      card.appendChild(box);
    }
    return card;
  }

  function topicStories(topic) {
    return state.data.stories.filter((s) => topic === null || s.topics.includes(topic));
  }

  /* ---------------- views ---------------- */
  function renderStories(topic) {
    const all = topicStories(topic);
    const byId = Object.fromEntries(state.data.stories.map((s) => [s.id, s]));
    const filtering = Boolean(state.q || state.cat);
    const lead = all.filter((s) => !s.related_to && storyMatches(s));
    const top = lead.slice(0, filtering ? 60 : 12);
    const frag = document.createDocumentFragment();
    const label = state.cat ? catOf(state.cat).name : "Top stories";
    frag.appendChild(kicker(label, filtering ? plural(lead.length, "story") + (state.q ? ` matching “${state.q}”` : "") : "Ranked by coverage · refreshed every 30 min"));
    top.forEach((s) => frag.appendChild(storyCard(s, byId)));
    if (!top.length) frag.appendChild(el("p", "banner", state.q ? "No stories match your search." : "No stories in this category right now."));
    if (filtering || topic === null) return frag;

    // "More in <topic>": the rest, grouped by sub-category.
    const used = new Set(top.flatMap((s) => [s.id, ...s.related]));
    const rest = all.filter((s) => !used.has(s.id));
    if (!rest.length) return frag;
    const name = state.data.topics.find((t) => t.id === topic).name;
    frag.appendChild(kicker(`More in ${name}`));
    const groups = {};
    rest.forEach((s) => { const g = (s.category && s.category[topic]) || "More"; (groups[g] = groups[g] || []).push(s); });
    Object.keys(groups).sort((a, b) => (a === "More") - (b === "More") || groups[b].length - groups[a].length).forEach((g) => {
      frag.appendChild(el("h3", "section-h", g));
      const ul = el("ul", "rows");
      groups[g].slice(0, 8).forEach((s) => {
        const li = el("li"); li.appendChild(link(s.lead.title, s.lead.url));
        li.appendChild(el("span", "when", [ago(s.updated), s.n_sources > 1 ? `${s.n_sources}s` : s.lead.source].join(" · ")));
        ul.appendChild(li);
      });
      frag.appendChild(ul);
    });
    return frag;
  }

  function renderColumns(topic) {
    const grid = el("div", "grid");
    state.data.sources.filter((s) => s.topic === topic).forEach((s) => {
      const items = s.items.filter(itemMatches);
      if ((state.q || state.cat) && !items.length) return;
      const card = el("article", "card source"), head = el("div", "source-head");
      const name = el("a", null, s.name); if (safeHref(s.home)) name.href = s.home; out(name);
      head.append(badge(s.name, "lg"), name); card.appendChild(head);
      const ul = el("ul", "heads");
      items.forEach((it) => {
        const li = el("li"); li.appendChild(withPreview(link(it.title, it.url), it, s.name));
        if (it.published) li.appendChild(timeEl(it.published));
        ul.appendChild(li);
      });
      card.appendChild(ul);
      const more = el("a", "more-link", `More from ${s.name} →`); if (safeHref(s.home)) more.href = s.home; card.appendChild(out(more));
      grid.appendChild(card);
    });
    if (!grid.children.length) return el("p", "banner", "No headlines match this filter.");
    return grid;
  }

  function renderList(topic) {
    const names = new Set(state.data.sources.filter((s) => s.topic === topic).map((s) => s.name));
    const items = state.data.sources.filter((s) => names.has(s.name))
      .flatMap((s) => s.items.map((it) => ({...it, source: s.name})))
      .filter(itemMatches).sort((a, b) => (b.published || "").localeCompare(a.published || ""));
    const frag = document.createDocumentFragment();
    frag.appendChild(kicker("Latest headlines", "Newest first"));
    const ul = el("ul", "rows");
    items.forEach((it) => {
      const li = el("li"), left = el("div", "list-item");
      left.append(badge(it.source), " ", withPreview(link(it.title, it.url), it, it.source));
      li.append(left, el("span", "when", [it.source, it.published ? ago(it.published) : ""].filter(Boolean).join(" · ")));
      ul.appendChild(li);
    });
    frag.appendChild(items.length ? ul : el("p", "banner", "No headlines match this filter."));
    return frag;
  }

  // "Last updated Wed, Nov 25, 2026, 5:23 PM EST · 12 min ago", above each page title.
  function updatedLine() {
    const iso = state.data.generated_at, d = new Date(iso);
    const p = el("p", "updated");
    if (isNaN(d)) return p;
    const t = el("time", null, d.toLocaleString(undefined, {weekday: "short", month: "short", day: "numeric", year: "numeric",
      hour: "numeric", minute: "2-digit", timeZoneName: "short"}));
    t.dateTime = iso;
    p.append(el("b", null, "Last updated"), t, el("span", "updated-ago", "· " + ago(iso)));
    return p;
  }
  // Keep "x min ago" current, and pick up new headlines without a reload.
  function tick() {
    document.querySelectorAll(".updated-ago").forEach((e) => { e.textContent = "· " + ago(state.data.generated_at); });
  }
  async function refresh() {
    const data = await fetch("data/feeds.json", {cache: "no-cache"}).then((r) => r.ok ? r.json() : null).catch(() => null);
    if (!data || data.generated_at === state.data.generated_at) return;
    const y = scrollY;
    data.stories = data.stories || [];
    state.data = data; renderMeta(); render(); scrollTo(0, y);
  }

  function pageHead(title, statsText, withModes, crumb) {
    const head = el("section", "page-head");
    if (crumb) { const c = el("a", "crumb", "← All topics"); c.href = hashFor(null, null, state.cat); head.appendChild(c); }
    head.appendChild(updatedLine());
    head.appendChild(el("h1", "page-title", title));
    const row = el("div", "title-row");
    const st = el("div", "stats"); st.append(el("i", "live"), statsText); row.appendChild(st);
    head.appendChild(row);
    if (withModes) {
      const v = el("div", "views"); v.setAttribute("role", "group"); v.setAttribute("aria-label", "View");
      MODES.forEach(([id, label]) => {
        const b = el("button", null, label); b.type = "button"; b.setAttribute("aria-pressed", id === state.mode);
        b.addEventListener("click", () => { location.hash = hashFor(state.topic, id, state.cat); });
        v.appendChild(b);
      });
      head.appendChild(v);
    }
    return head;
  }

  // Category chips (AI, Wearables, ...): only those with something in view, with counts.
  function chipRow(things) {
    const nav = el("nav", "chips"); nav.setAttribute("aria-label", "Filter by category");
    const add = (id, label, n) => {
      const a = el("a", "chip"); a.href = hashFor(state.topic, state.mode, id);
      a.append(label); if (n != null) a.appendChild(el("span", null, String(n)));
      if ((state.cat || null) === id) a.setAttribute("aria-current", "true");
      nav.appendChild(a);
    };
    add(null, "All", null);
    CATS.forEach((c) => {
      const n = things.filter((t) => typeof t === "string" ? c.re.test(t) : storyInCat(t, c)).length;
      if (n || c.id === state.cat) add(c.id, c.name, n);
    });
    return nav;
  }

  function renderHome() {
    const d = state.data;
    const frag = document.createDocumentFragment();
    frag.appendChild(pageHead("All topics", `${d.sources.length} sources · ${d.stories.length} stories in the last 3 days`, false, false));
    const cards = el("div", "topics");
    d.topics.forEach((t) => {
      const a = el("a", "card topic-card"); a.href = hashFor(t.id, null, null);
      const n = d.sources.filter((s) => s.topic === t.id).length;
      a.append(el("h2", null, t.name), el("span", null, `${n} sources · ${topicStories(t.id).filter((s) => !s.related_to).length} stories`));
      const ol = el("ol");
      topicStories(t.id).filter((s) => !s.related_to).slice(0, 3).forEach((s) => ol.appendChild(el("li", null, s.lead.title)));
      a.appendChild(ol); cards.appendChild(a);
    });
    frag.appendChild(chipRow(d.stories.filter((s) => !s.related_to)));
    if (!state.q && !state.cat) frag.appendChild(cards);
    frag.appendChild(renderStories(null));
    return frag;
  }

  function renderTopic() {
    const d = state.data, t = d.topics.find((x) => x.id === state.topic);
    const srcs = d.sources.filter((s) => s.topic === t.id);
    const items = srcs.reduce((n, s) => n + s.items.length, 0);
    const frag = document.createDocumentFragment();
    frag.appendChild(pageHead(t.name, `${srcs.length} sources · ${items} recent items`, true, true));
    frag.appendChild(chipRow(state.mode === "stories"
      ? topicStories(t.id).filter((s) => !s.related_to)
      : srcs.flatMap((s) => s.items.map((it) => `${it.title} ${it.summary || ""}`))));
    frag.appendChild(state.mode === "columns" ? renderColumns(t.id) : state.mode === "list" ? renderList(t.id) : renderStories(t.id));
    return frag;
  }

  function render() {
    hide();
    const [path, query] = location.hash.replace(/^#/, "").split("?");
    const [h, m] = path.split("/");
    const c = new URLSearchParams(query || "").get("c");
    state.cat = catOf(c) ? c : null;
    state.topic = state.data.topics.some((t) => t.id === h) ? h : null;
    state.mode = MODES.some(([id]) => id === m) ? m : "stories";
    document.body.classList.toggle("wide", state.topic !== null && state.mode === "columns");
    view.replaceChildren(state.topic ? renderTopic() : renderHome());
    const name = state.topic && state.data.topics.find((t) => t.id === state.topic).name;
    const catName = state.cat && catOf(state.cat).name;
    document.title = [catName, name].filter(Boolean).join(" · ") + (name || catName ? " — Scalable" : "Scalable — Top Tech & Business News");
    const cur = view.querySelector('.chips [aria-current="true"]');
    if (cur) cur.scrollIntoView({block: "nearest", inline: "center"});
  }

  function renderMeta() {
    const d = state.data;
    const m = document.getElementById("meta"); m.replaceChildren();
    m.append("Updated ", el("strong", null, fmtTime(d.generated_at)), ` · ${d.sources.length} sources · refreshed about every 30 minutes`);
    document.getElementById("sources-note").textContent = "Sources: " + d.sources.map((x) => x.name).join(", ") + ".";
    if (d.ai && d.ai.enabled) document.getElementById("ai-note").textContent =
      " Story summaries, “Why it matters” notes and story labels are written by AI from the outlets' own headlines and feed summaries, and may contain mistakes; follow the links for the full reporting.";
  }

  /* ---------------- theme ---------------- */
  // Light / Dark switch. Until someone picks, the page follows the device setting.
  const themeButtons = document.querySelectorAll("[data-theme-choice]");
  const darkQuery = matchMedia("(prefers-color-scheme: dark)");
  function showTheme() {
    const t = document.documentElement.dataset.theme || (darkQuery.matches ? "dark" : "light");
    themeButtons.forEach((b) => b.setAttribute("aria-pressed", b.dataset.themeChoice === t));
  }
  themeButtons.forEach((b) => b.addEventListener("click", () => {
    document.documentElement.dataset.theme = b.dataset.themeChoice;
    try { localStorage.setItem("scalable-theme", b.dataset.themeChoice); } catch (e) { /* storage unavailable */ }
    showTheme();
  }));
  darkQuery.addEventListener("change", showTheme);
  showTheme();

  async function load() {
    const data = await fetch("data/feeds.json", {cache: "no-cache"}).then((r) => r.ok ? r.json() : null).catch(() => null);
    if (!data) {
      const e = document.getElementById("empty"); e.hidden = false;
      e.textContent = "Headlines haven't been compiled yet. Run: python -m scalable";
      return;
    }
    data.stories = data.stories || [];
    CATS = (data.categories || []).flatMap((c) => {
      try { return [{id: c.id, name: c.name, re: new RegExp(c.pattern, "i")}]; } catch (e) { return []; }
    });
    state.data = data;
    renderMeta(); render();
    addEventListener("hashchange", () => { render(); scrollTo(0, 0); });
    let t; document.getElementById("search").addEventListener("input", (e) => {
      clearTimeout(t); t = setTimeout(() => { state.q = e.target.value.trim().toLowerCase(); render(); }, 150);
    });
    addEventListener("scroll", hide, {passive: true});
    setInterval(tick, 60e3);
    setInterval(() => { if (!document.hidden) refresh(); }, 5 * 60e3);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) { tick(); refresh(); } });
  }
  load();
})();
