# Scalable

The top tech and business stories, all in one place. A headline aggregator in the spirit of Alltop, built on the same design as [Electable](https://github.com/pilkingtone/electable).

- **Stories** (home and each topic page): headlines from different outlets about the same event are grouped into one story, ranked by how many outlets cover it and how recently. Each card shows the lead outlet, how many sources, a HOT badge for widely covered breaking stories, a summary, "Why it matters", the other outlets, and related follow-up stories. Below the top stories, "More in <topic>" groups the rest by sub-topic (AI, Funding, Security, Deals, Earnings, ...).
- **Columns**: a box per source with its latest headlines (hover for the publisher's summary).
- **List**: every headline in the topic, newest first.
- **Category chips** (the TechCrunch topic list: AI, Amazon, Apps, Biotech & Health, Climate, ... Venture) filter any page and view; the list and their keyword patterns live in `config/feeds.json` under `categories`.
- **Search** filters everything; a sun button switches light and dark.

AI notes (optional): if the `ANTHROPIC_API_KEY` repository secret is set, each run asks Claude to write a one-sentence summary, a "Why it matters" line and a short label for the stories on screen, using only the outlets' headlines and feed summaries. Notes are cached in `data/ai_cache.json`, so each story is written once. Without the key, cards show the publisher's own feed summary and no "Why it matters".

Sources and topics live in `config/feeds.json` (name, topic, homepage, RSS feed; `urls` gives fallbacks). Scalable uses only what publishers syndicate in their RSS feeds (headline, link, time, short summary) and always links to the original article. Feeds are parsed with `defusedxml`.

```bash
pip install -r requirements.txt
python -m scalable                    # fetch feeds -> web/data/feeds.json
python -m http.server -d web 8000     # open http://localhost:8000
python -m pytest -q
```

`.github/workflows/update.yml` refreshes the headlines hourly and publishes `web/` to GitHub Pages. A feed that fails is skipped and logged; its box disappears until it works again.
