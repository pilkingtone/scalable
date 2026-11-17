# Scalable

The top tech and business stories, all in one place. A headline aggregator in the spirit of Alltop, built on the same design as [Electable](https://github.com/pilkingtone/electable).

- **Topic pages** (Tech, Business, Management & Ideas, Markets & Economy): a box per source with its latest headlines. Hover a headline for the publisher's summary; headlines open on the publisher's site.
- **Top stories**: the newest headlines across every source, with duplicate stories merged.
- **Search** filters headlines everywhere.

Sources and topics live in `config/feeds.json` (name, topic, homepage, RSS feed; `urls` gives fallbacks). Scalable uses only what publishers syndicate in their RSS feeds (headline, link, time, short summary) and always links to the original article. Feeds are parsed with `defusedxml`.

```bash
pip install -r requirements.txt
python -m scalable                    # fetch feeds -> web/data/feeds.json
python -m http.server -d web 8000     # open http://localhost:8000
python -m pytest -q
```

`.github/workflows/update.yml` refreshes the headlines hourly and publishes `web/` to GitHub Pages. A feed that fails is skipped and logged; its box disappears until it works again.
