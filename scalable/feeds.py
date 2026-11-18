"""Fetch every source's RSS/Atom feed and compile web/data/feeds.json.

Like Alltop: each source keeps its latest few headlines (shown as a box on its
topic page), and a combined list holds the newest stories across all sources.
Only what publishers syndicate in their feeds is kept (headline, link, time and
a trimmed summary); every item links to the original article. Feeds are parsed
with defusedxml because their content is untrusted.
"""
from __future__ import annotations

import html
import json
from concurrent.futures import ThreadPoolExecutor
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from defusedxml import ElementTree as ET

from .http import get

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "feeds.json"
OUT_DIR = ROOT / "web" / "data"
ATOM = "{http://www.w3.org/2005/Atom}"
TAG = re.compile(r"<[^>]+>")


def _text(el, *names) -> str:
    for n in names:
        found = el.find(n)
        if found is not None and (found.text or "").strip():
            return found.text.strip()
    return ""


def _clean(s: str, limit: int | None = None) -> str:
    s = re.sub(r"\s+", " ", html.unescape(TAG.sub(" ", s or ""))).strip()
    if limit and len(s) > limit:
        s = s[:limit].rsplit(" ", 1)[0].rstrip(",;:—-") + "…"
    return s


def _when(s: str) -> datetime | None:
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)                                   # RSS: RFC 822
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))        # Atom: ISO 8601
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _repair(xml: str) -> str:
    """Fix the common ways real feeds break strict XML, for one retry."""
    # Undeclared namespace prefixes (e.g. <media:content> without xmlns:media).
    xml = re.sub(r"<(/?)(?!rss\b)([A-Za-z_][\w.-]*):", r"<\1\2_", xml)
    xml = re.sub(r"\s(?!xmlns)([A-Za-z_][\w.-]*):([A-Za-z_][\w.-]*)=", r" \1_\2=", xml)
    # Bare ampersands and control characters.
    xml = re.sub(r"&(?!(?:[A-Za-z][\w.-]*|#\d+|#x[0-9A-Fa-f]+);)", "&amp;", xml)
    xml = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", xml)
    return xml.lstrip("\ufeff \t\r\n")


def _loose_items(xml: str) -> list[dict]:
    """Last resort for feeds too broken for an XML parser: pull fields out of each
    <item>/<entry> with patterns. No entity expansion, so it is safe on any input."""
    def field(block, *names):
        for n in names:
            m = re.search(rf"<{n}\b[^>]*?(?:/>|>(.*?)</{n}>)", block, re.S)
            if m:
                if n == "link" and not m.group(1):
                    href = re.search(r'href="([^"]+)"', m.group(0))
                    if href:
                        return href.group(1)
                v = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", m.group(1) or "", flags=re.S).strip()
                if v:
                    return html.unescape(v) if n == "link" else v
        return ""
    out = []
    for block in re.findall(r"<(?:item|entry)\b.*?</(?:item|entry)>", xml, re.S):
        title, url = _clean(field(block, "title")), field(block, "link", "guid").strip()
        if title and url.startswith(("https://", "http://")):
            out.append({"title": title, "url": url, "published": _when(field(block, "pubDate", "published", "updated", "dc:date")),
                        "summary": _clean(field(block, "description", "summary", "content:encoded"), 220)})
    return sorted(out, key=lambda i: i["published"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)


def parse_feed(xml: str) -> list[dict]:
    """Items from an RSS 2.0 or Atom feed, newest first."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        try:
            root = ET.fromstring(_repair(xml))
        except ET.ParseError:
            return _loose_items(xml)
    raw = []
    for it in root.iter("item"):
        raw.append((_text(it, "title"), _text(it, "link", "guid"),
                    _text(it, "pubDate", "{http://purl.org/dc/elements/1.1/}date"),
                    _text(it, "description", "{http://purl.org/rss/1.0/modules/content/}encoded")))
    rss1 = "{http://purl.org/rss/1.0/}"   # RSS 1.0 / RDF feeds (e.g. Slashdot)
    for it in root.iter(f"{rss1}item"):
        raw.append((_text(it, f"{rss1}title"), _text(it, f"{rss1}link") or it.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about", ""),
                    _text(it, "{http://purl.org/dc/elements/1.1/}date"), _text(it, f"{rss1}description")))
    for it in root.iter(f"{ATOM}entry"):
        link = it.find(f"{ATOM}link[@rel='alternate']")
        if link is None:      # (an Element with no children is falsy, so no `or` here)
            link = it.find(f"{ATOM}link")
        raw.append((_text(it, f"{ATOM}title"), link.get("href", "") if link is not None else "",
                    _text(it, f"{ATOM}published", f"{ATOM}updated"),
                    _text(it, f"{ATOM}summary", f"{ATOM}content")))
    out = []
    for title, url, when, summary in raw:
        title, url = _clean(title), url.strip()
        if title and url.startswith(("https://", "http://")):
            out.append({"title": title, "url": url, "published": _when(when), "summary": _clean(summary, 220)})
    return sorted(out, key=lambda i: i["published"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _key(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", title.lower())[:80]


def _iso(d: datetime | None) -> str | None:
    return d.astimezone(timezone.utc).isoformat(timespec="seconds") if d else None


def compile_sources(fetched: list[tuple[dict, list[dict]]], cfg: dict, now: datetime) -> tuple[list, list]:
    """Per-source boxes (latest N each) and a combined newest-first list (one copy per story)."""
    cutoff = now - timedelta(days=cfg.get("max_age_days", 10))
    n = cfg.get("items_per_source", 6)
    sources, pool = [], []
    for src, items in fetched:
        # Undated items are kept for the source's own box (some feeds omit dates) but not
        # for the combined list, which is ordered by time.
        fresh = [i for i in items if i["published"] is None or (cutoff <= i["published"] <= now + timedelta(hours=2))]
        box = fresh[:n]
        sources.append({"id": _slug(src["name"]), "name": src["name"], "topic": src["topic"], "home": src["home"],
                        "items": [{**i, "published": _iso(i["published"])} for i in box]})
        pool += [{**i, "source": src["name"], "topic": src["topic"]} for i in box if i["published"]]
    seen, top = set(), []
    for i in sorted(pool, key=lambda x: x["published"], reverse=True):
        k = _key(i["title"])
        if k in seen:
            continue
        seen.add(k)
        top.append({**i, "published": _iso(i["published"])})
        if len(top) >= cfg.get("top_items", 60):
            break
    return sources, top


def _cap(stories: list[dict], cfg: dict) -> list[dict]:
    """Keep the best stories per topic (so one busy topic can't crowd out the rest),
    plus anything shown as a related story under a kept one."""
    per = cfg.get("max_stories_per_topic", 150)
    keep: set[str] = set()
    for topic in {t for s in stories for t in s["topics"]}:
        mine = [s for s in stories if topic in s["topics"] and not s.get("related_to")][:per]
        for s in mine:
            keep.add(s["id"]); keep.update(s["related"])
    return [s for s in stories if s["id"] in keep]


def run(out_dir: Path = OUT_DIR, max_age_hours: float = 0.5) -> dict:
    cfg = json.loads(CONFIG.read_text())
    stale = datetime.now(timezone.utc) - timedelta(days=cfg.get("max_age_days", 10))

    def fetch(src):
        errors = []
        for url in src.get("urls") or [src["url"]]:
            try:
                items = parse_feed(get(url, max_age_hours=max_age_hours, timeout=20))
            except Exception as e:  # noqa: BLE001 - one bad feed must not sink the page
                errors.append(str(e)[:120])
                continue
            # An empty or long-stale feed: try the source's next address, if it has one.
            fresh = any(i["published"] and i["published"] >= stale for i in items)
            if fresh or url == (src.get("urls") or [src["url"]])[-1]:
                return src, items, None
            errors.append(f"{url}: no recent items")
        return src, None, f"{src['name']}: {' | '.join(errors)}"

    # Fetch in parallel (different hosts, mostly); results keep config order.
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(fetch, cfg["sources"]))
    fetched = [(src, items) for src, items, err in results if err is None]
    warnings = [err for _, _, err in results if err]
    now = datetime.now(timezone.utc)
    sources, top = compile_sources(fetched, cfg, now)
    stories = cluster_stories(fetched, cfg, now)
    from . import ai
    ai_note = ai.enrich(stories, cfg)
    out = {"generated_at": now.replace(tzinfo=None).isoformat(timespec="seconds") + "Z",
           "topics": cfg["topics"], "sources": [s for s in sources if s["items"]],
           "top": top, "stories": _cap(stories, cfg),
           "ai": ai_note, "warnings": warnings}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "feeds.json").write_text(json.dumps(out))
    # Explain feeds that loaded but produced no headlines (no items, or all too old).
    shown = {s["name"] for s in sources if s["items"]}
    for src, items in fetched:
        if src["name"] not in shown:
            newest = max((i["published"] for i in items if i["published"]), default=None)
            warnings.append(f"{src['name']}: feed loaded but no recent headlines ({len(items)} items"
                            + (f", newest {newest:%Y-%m-%d})" if newest else ")"))
    ok = sum(1 for s in sources if s["items"])
    print(f"[scalable] {ok}/{len(cfg['sources'])} sources with headlines, {len(stories)} stories "
          f"({sum(1 for c in stories if c['n_sources'] > 1)} covered by 2+ sources)", flush=True)
    for w in warnings:
        print(f"[scalable] WARNING {w}", flush=True)
    return out


# ====================================================================== story clusters
#
# Alltop-style "stories": headlines from different outlets about the same event
# are grouped into one card. Grouping uses the distinctive words two headlines
# share (stopwords dropped, rarer words weigh more), which is robust to title case.

STOP = set("""a an the and or but if of in on at to for from by with without into onto over under about as is are was
were be been being it its this that these those he she they them his her their our your you we i not no new says
say said after before amid as vs via how why what when where who will would could can may might more most than
then up down out off just now year years first last one two three four five six seven eight nine ten report reports
week weeks day days today here there per its it's us u.s""".split())

SUBCATEGORIES = {
    "tech": [("AI", r"\b(ai|a\.i\.|llm|openai|anthropic|chatgpt|gemini|claude|gpt|model|models|nvidia|machine learning)\b"),
             ("Funding", r"\b(raises|raised|funding|series [a-f]|valuation|valued|ipo|acquire[sd]?|acquisition|buys|merger|investors?)\b"),
             ("Security", r"\b(hack|hacked|hackers|breach|ransomware|vulnerabilit|malware|outage|cyber|security|spyware|leak)"),
             ("People", r"\b(ceo|cfo|cto|founder|steps down|resigns|hires|hired|appoint|executive|chief|fired|ousted)\b"),
             ("Launches", r"\b(launch|launches|launched|unveil|unveils|announces|debuts?|introduces|releases?|rolls out)\b"),
             ("Products", r"\b(iphone|android|app|apps|device|laptop|phone|watch|tablet|update|feature|beta|deal|price|review)\b")],
    "business": [("Deals", r"\b(acquire[sd]?|acquisition|merger|deal|buyout|takeover|stake|ipo)\b"),
                 ("Earnings", r"\b(earnings|revenue|profit|quarter|q[1-4]|sales|forecast|guidance|results)\b"),
                 ("Leadership", r"\b(ceo|cfo|chief|founder|board|steps down|resigns|appoint|executive)\b"),
                 ("Policy", r"\b(tariff|tariffs|regulat|antitrust|ftc|sec|lawsuit|sues|court|ban|tax|government)\w*"),
                 ("Workplace", r"\b(layoffs?|jobs|workers|employees|hiring|remote|union|strike|wages?)\b")],
    "ideas": [("Leadership", r"\b(leader|leaders|leadership|ceo|manager|managers|management|boss)\b"),
              ("Strategy", r"\b(strategy|strategic|competitive|growth|innovation|transformation)\b"),
              ("Workplace", r"\b(work|workers|employees|team|teams|culture|remote|hybrid|career|hiring)\b"),
              ("AI & Technology", r"\b(ai|technology|digital|data|automation|generative)\b")],
    "news": [("Politics", r"\b(trump|biden|congress|senate|house|election|republicans?|democrats?|gop|white house|campaign|vote|voters)\b"),
             ("Courts", r"\b(court|judge|supreme|lawsuit|trial|indicted|charges|ruling)\b"),
             ("Economy", r"\b(economy|inflation|jobs|prices|tariffs?|fed|rates|recession)\b"),
             ("World", r"\b(ukraine|russia|china|israel|gaza|iran|europe|nato|war)\b")],
    "markets": [("Stocks", r"\b(stocks?|shares|s&p|dow|nasdaq|rally|selloff|index|equities)\b"),
                ("Rates & Fed", r"\b(fed|federal reserve|rates?|inflation|powell|warsh|treasury|yields?|bonds?)\b"),
                ("Crypto", r"\b(bitcoin|crypto|ethereum|stablecoin|token|blockchain)\b"),
                ("Economy", r"\b(economy|gdp|jobs report|unemployment|recession|consumer|spending|housing|trade)\b")],
}


def _tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9$%][a-z0-9$%'.-]*", title.lower())
    return {w.strip(".'-") for w in words if w.strip(".'-") not in STOP and (len(w) > 2 or any(c.isdigit() for c in w))}


def _subcategory(topic: str, text: str) -> str:
    t = text.lower()
    for name, rx in SUBCATEGORIES.get(topic, []):
        if re.search(rx, t):
            return name
    return "More"


def _stable_id(url: str) -> str:
    import hashlib
    return hashlib.sha1(url.encode()).hexdigest()[:12]


# Words too general to tie two stories together on their own ("CEO", "deal", ...).
GENERIC = set("""ceo ceos cfo chief executive executives company companies firm firms business deal deals return
returns report reports market markets stock stocks shares sale sales best top big year week day today people
plan plans billion million price prices tech new first launch launches""".split())


def cluster_stories(fetched: list[tuple[dict, list[dict]]], cfg: dict, now: datetime) -> list[dict]:
    """Group recent items from every source into stories, ranked by coverage and recency."""
    # Slow-publishing topics (essays, research) get a longer window.
    hours = cfg.get("story_hours_by_topic", {})
    items = []
    for src, its in fetched:
        cutoff = now - timedelta(hours=hours.get(src["topic"], cfg.get("story_hours", 72)))
        for i in its[:cfg.get("cluster_items_per_source", 20)]:
            if i["published"] and cutoff <= i["published"] <= now + timedelta(hours=2):
                items.append({**i, "source": src["name"], "topic": src["topic"], "toks": _tokens(i["title"])})
    if not items:
        return []
    # Rarer words carry more weight: inverse document frequency over this run's headlines.
    import math
    df: dict[str, int] = {}
    for i in items:
        for t in i["toks"]:
            df[t] = df.get(t, 0) + 1
    n = len(items)
    idf = {t: math.log(1 + n / c) for t, c in df.items()}

    def sim(a: set, b: set) -> float:
        shared = a & b
        if len(shared) < 2:
            return 0.0
        w = lambda s: sum(idf.get(t, 0) for t in s)  # noqa: E731
        return w(shared) / max(1e-9, min(w(a), w(b)))

    clusters: list[dict] = []
    for it in sorted(items, key=lambda x: x["published"]):
        best, best_s = None, 0.0
        for c in clusters:
            s = max(sim(it["toks"], m["toks"]) for m in c["members"][:6])
            if s > best_s:
                best, best_s = c, s
        if best is not None and best_s >= cfg.get("cluster_threshold", 0.55):
            if it["source"] not in {m["source"] for m in best["members"]}:
                best["members"].append(it)
        else:
            clusters.append({"members": [it]})

    out = []
    for c in clusters:
        ms = c["members"]
        lead = next((m for m in ms if m["summary"]), ms[0])      # earliest report with a summary
        newest = max(m["published"] for m in ms)
        n_src = len({m["source"] for m in ms})
        age_h = (now - newest).total_seconds() / 3600
        topics = sorted({m["topic"] for m in ms})
        text = " ".join(m["title"] for m in ms)
        out.append({
            "id": _stable_id(lead["url"]),
            "topics": topics,
            "category": {t: _subcategory(t, text) for t in topics},
            "lead": {"title": lead["title"], "url": lead["url"], "source": lead["source"],
                     "summary": lead["summary"], "published": _iso(lead["published"])},
            "updated": _iso(newest),
            "n_sources": n_src,
            "more": [{"source": m["source"], "title": m["title"], "url": m["url"]} for m in ms if m is not lead],
            "hot": n_src >= cfg.get("hot_sources", 5) and age_h <= 12,
            "score": round(n_src ** 1.2 * 0.5 ** (age_h / cfg.get("half_life_hours", 18)), 4),
            "_toks": set().union(*(m["toks"] for m in ms)),
        })
    out.sort(key=lambda c: c["score"], reverse=True)

    # Related stories: smaller stories that share one of the main story's defining words
    # (used by most of its outlets) hang under it, e.g. other Nvidia stories under the
    # day's Nvidia story. Words common across all of today's headlines don't count.
    taken: set[str] = set()
    for c in out:
        c["related"] = []
    for c in out:
        if c["id"] in taken or c["n_sources"] < 2:
            continue
        members = [c["lead"]["title"]] + [m["title"] for m in c["more"]]
        counts: dict[str, int] = {}
        for t in members:
            for tok in _tokens(t):
                counts[tok] = counts.get(tok, 0) + 1
        limit = len(members) + max(3, n // 40)
        # Defining words: real words (not numbers) in at least half the headlines. A word
        # that is common today (e.g. "Nvidia" on a big Nvidia day) still counts if nearly
        # every headline in the story uses it.
        key = {t for t, k in counts.items()
               if t.isalpha() and len(t) >= 3 and t not in GENERIC and k * 2 >= len(members)
               and (df.get(t, 0) <= limit or k * 5 >= len(members) * 4)}
        for d in out:
            if d is c or d["id"] in taken or d["score"] > c["score"] or d["related"]:
                continue
            shared = key & _tokens(d["lead"]["title"])
            # Two defining words in common, or one the story's headlines nearly all use.
            if (len(shared) >= 2 or any(counts[t] * 5 >= len(members) * 4 for t in shared)) and len(c["related"]) < 4:
                c["related"].append(d["id"])
                taken.add(d["id"])
                d["related_to"] = c["id"]
    for c in out:
        del c["_toks"]
    return out
