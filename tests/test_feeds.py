from datetime import datetime, timezone

import pytest

from scalable import feeds

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>
<item><title>Chipmaker beats estimates</title><link>https://a.example/1</link>
<pubDate>Mon, 16 Nov 2026 10:00:00 GMT</pubDate><description>&lt;p&gt;Revenue &lt;b&gt;rose&lt;/b&gt; 20%.&lt;/p&gt;</description></item>
<item><title>Older story</title><link>https://a.example/2</link><pubDate>Mon, 16 Nov 2026 08:00:00 GMT</pubDate></item>
<item><title>Ancient story</title><link>https://a.example/3</link><pubDate>Mon, 02 Nov 2026 08:00:00 GMT</pubDate></item>
<item><title>No link</title><pubDate>Mon, 16 Nov 2026 09:00:00 GMT</pubDate></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>CHIPMAKER BEATS ESTIMATES</title><link href="https://b.example/x"/><updated>2026-11-16T09:00:00Z</updated>
<summary>Same story, other outlet.</summary></entry>
<entry><title>Startup raises $50M</title><link rel="alternate" href="https://b.example/y"/><published>2026-11-16T11:00:00Z</published></entry>
<entry><title>Undated essay</title><link href="https://b.example/z"/></entry>
</feed>"""

NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)
CFG = {"items_per_source": 2, "top_items": 10, "max_age_days": 10}


def test_parse_rss_and_atom():
    rss = feeds.parse_feed(RSS)
    assert [i["title"] for i in rss] == ["Chipmaker beats estimates", "Older story", "Ancient story"]
    assert rss[0]["summary"] == "Revenue rose 20%."
    atom = feeds.parse_feed(ATOM)
    assert atom[0]["title"] == "Startup raises $50M" and atom[0]["url"] == "https://b.example/y"
    assert atom[-1]["published"] is None


def test_boxes_cap_age_and_combined_dedupe():
    a = ({"name": "Outlet A", "topic": "tech", "home": "https://a.example"}, feeds.parse_feed(RSS))
    b = ({"name": "Outlet B", "topic": "business", "home": "https://b.example"}, feeds.parse_feed(ATOM))
    sources, top = feeds.compile_sources([a, b], CFG, NOW)
    assert [i["title"] for i in sources[0]["items"]] == ["Chipmaker beats estimates", "Older story"]
    assert sources[0]["id"] == "outlet-a"
    # Combined list: newest first, one copy of a story carried by two outlets (the newest).
    assert [(i["title"], i["source"]) for i in top] == [
        ("Startup raises $50M", "Outlet B"), ("Chipmaker beats estimates", "Outlet A"), ("Older story", "Outlet A")]


def test_undated_items_stay_in_box_not_combined():
    b = ({"name": "B", "topic": "tech", "home": "https://b.example"}, feeds.parse_feed(ATOM))
    sources, top = feeds.compile_sources([b], {**CFG, "items_per_source": 5}, NOW)
    assert "Undated essay" in [i["title"] for i in sources[0]["items"]]
    assert "Undated essay" not in [i["title"] for i in top]


def test_rejects_entity_expansion():
    bomb = '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;">]><rss><channel><item><title>&b;</title></item></channel></rss>'
    with pytest.raises(Exception):
        feeds.parse_feed(bomb)


def test_tolerates_undeclared_prefix():
    xml = RSS.replace("<description>", '<media:content url="https://a.example/i.jpg"/><description>', 1)
    assert feeds.parse_feed(xml)[0]["title"] == "Chipmaker beats estimates"
