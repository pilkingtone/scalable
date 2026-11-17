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


def parse_feed(xml: str) -> list[dict]:
    """Items from an RSS 2.0 or Atom feed, newest first."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        if "unbound prefix" not in str(e):
            raise
        # Some feeds use namespace prefixes they never declare (e.g. <media:content>
        # without xmlns:media); rename them so the strict parser accepts the document.
        xml = re.sub(r"<(/?)([A-Za-z_][\w.-]*):", r"<\1\2_", xml)
        xml = re.sub(r"\s(?!xmlns)([A-Za-z_][\w.-]*):([A-Za-z_][\w.-]*)=", r" \1_\2=", xml)
        root = ET.fromstring(xml)
    raw = []
    for it in root.iter("item"):
        raw.append((_text(it, "title"), _text(it, "link", "guid"),
                    _text(it, "pubDate", "{http://purl.org/dc/elements/1.1/}date"),
                    _text(it, "description", "{http://purl.org/rss/1.0/modules/content/}encoded")))
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


def run(out_dir: Path = OUT_DIR, max_age_hours: float = 0.5) -> dict:
    cfg = json.loads(CONFIG.read_text())
    fetched, warnings = [], []
    for src in cfg["sources"]:
        errors = []
        for url in src.get("urls") or [src["url"]]:
            try:
                fetched.append((src, parse_feed(get(url, max_age_hours=max_age_hours, timeout=20))))
                break
            except Exception as e:  # noqa: BLE001 - one bad feed must not sink the page
                errors.append(str(e)[:120])
        else:
            warnings.append(f"{src['name']}: {' | '.join(errors)}")
    now = datetime.now(timezone.utc)
    sources, top = compile_sources(fetched, cfg, now)
    out = {"generated_at": now.replace(tzinfo=None).isoformat(timespec="seconds") + "Z",
           "topics": cfg["topics"], "sources": [s for s in sources if s["items"]],
           "top": top, "warnings": warnings}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "feeds.json").write_text(json.dumps(out))
    ok = sum(1 for s in sources if s["items"])
    print(f"[scalable] {ok}/{len(cfg['sources'])} sources with headlines, {len(top)} top stories", flush=True)
    for w in warnings:
        print(f"[scalable] WARNING {w}", flush=True)
    return out
