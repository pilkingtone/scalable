"""Optional AI notes for story cards: a one-sentence summary, "why it matters", and a
2-4 word label, written by Claude from the outlets' own headlines and feed summaries.

Runs only when ANTHROPIC_API_KEY is set; otherwise cards show the lead publisher's
feed summary. Results are cached by story id in data/ai_cache.json, so each story
is written once, and a run sends all new stories in a few batched requests.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "ai_cache.json"
MODEL = os.environ.get("SCALABLE_MODEL", "claude-opus-5-5")
BATCH = 20

SYSTEM = """You write the notes on story cards for Scalable, a tech and business news aggregator.
For each story you get its headlines from one or more outlets and the lead outlet's feed summary.

Write, for each story:
- summary: one plain sentence (at most 35 words) saying what happened.
- why_it_matters: one sentence (at most 30 words) on the consequence for the industry, markets, or readers.
- label: 2 to 4 words naming the angle of the story, e.g. "Chip export rules" or "Layoffs at Meta".

Use only facts stated in the headlines and summary; never add numbers, names, dates, or claims they don't contain.
If the sources disagree or the story is unclear, describe what was reported rather than resolving it.
Neutral tone, no hype, no editorializing about people or parties."""

SCHEMA = {
    "type": "object",
    "properties": {
        "stories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "summary": {"type": "string"},
                    "why_it_matters": {"type": "string"},
                    "label": {"type": "string"},
                },
                "required": ["id", "summary", "why_it_matters", "label"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["stories"],
    "additionalProperties": False,
}


def _load_cache() -> dict:
    try:
        return json.loads(CACHE.read_text())
    except (OSError, ValueError):
        return {}


def _payload(story: dict) -> dict:
    heads = [f"{story['lead']['source']}: {story['lead']['title']}"]
    heads += [f"{m['source']}: {m['title']}" for m in story["more"][:6]]
    return {"id": story["id"], "headlines": heads, "lead_summary": story["lead"]["summary"]}


def _shown(stories: list[dict], cfg: dict) -> list[dict]:
    """Stories that appear as cards or related lines: each topic's top stories and their related ones."""
    by_id = {s["id"]: s for s in stories}
    picked: dict[str, dict] = {}
    for topic in [t["id"] for t in cfg["topics"]] + [None]:
        top = [s for s in stories if not s.get("related_to") and (topic is None or topic in s["topics"])]
        for s in top[:cfg.get("ai_stories_per_topic", 12)]:
            picked[s["id"]] = s
            for rid in s["related"]:
                picked[rid] = by_id[rid]
    return list(picked.values())


def enrich(stories: list[dict], cfg: dict) -> dict:
    """Attach story['ai'] where available; returns a short status note for the page."""
    cache = _load_cache()
    for s in stories:
        if s["id"] in cache:
            s["ai"] = {k: cache[s["id"]][k] for k in ("summary", "why_it_matters", "label")}
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {"enabled": False}

    import anthropic
    client = anthropic.Anthropic()
    todo = [s for s in _shown(stories, cfg) if s["id"] not in cache]
    written, errors = 0, []
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        try:
            response = client.beta.messages.create(
                model=MODEL,
                max_tokens=16000,
                system=SYSTEM,
                messages=[{"role": "user", "content": json.dumps({"stories": [_payload(s) for s in batch]})}],
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
                # If the model declines a request, the API retries it on a fallback model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.RateLimitError as e:
            errors.append(f"rate limited: {e.message}")
            break
        except anthropic.APIStatusError as e:
            errors.append(f"API error {e.status_code}: {e.message}")
            continue
        except anthropic.APIConnectionError as e:
            errors.append(f"connection error: {e}")
            break
        if response.stop_reason == "refusal":
            errors.append("a batch was declined")
            continue
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            notes = json.loads(text)["stories"]
        except (ValueError, KeyError):
            errors.append("unparseable response")
            continue
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        ids = {s["id"] for s in batch}
        for n in notes:
            if n["id"] in ids:
                cache[n["id"]] = {**{k: n[k].strip() for k in ("summary", "why_it_matters", "label")}, "at": now}
                written += 1
    # Keep the cache to stories from the last week.
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    cache = {k: v for k, v in cache.items() if v.get("at", "") >= week_ago}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache))
    for s in stories:
        if s["id"] in cache:
            s["ai"] = {k: cache[s["id"]][k] for k in ("summary", "why_it_matters", "label")}
    print(f"[scalable] AI notes: {written} new, {len(todo) - written} pending" + (f"; {'; '.join(errors)}" if errors else ""), flush=True)
    return {"enabled": True, "model": MODEL, "new": written, "errors": errors}
