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


# ------------------------------------------------------------ story clusters and AI notes

from datetime import timedelta


def _src(name, topic="tech"):
    return {"name": name, "topic": topic, "home": "https://x.example"}


def _it(title, hours_ago, url, summary=""):
    return {"title": title, "url": url, "summary": summary, "published": NOW - timedelta(hours=hours_ago)}


CLUSTER_CFG = {"story_hours": 72, "cluster_threshold": 0.55, "hot_sources": 3, "half_life_hours": 18}


def _fetched():
    return [
        (_src("Outlet A"), [_it("Nvidia board weighs Jensen Huang return as CEO", 3, "https://a/1", "The board is weighing it."),
                            _it("Apple ships new MacBook Air", 5, "https://a/2")]),
        (_src("Outlet B"), [_it("Jensen Huang return as Nvidia CEO considered by board", 2, "https://b/1"),
                            _it("Treasury secretary urges Nvidia shake-up", 4, "https://b/2")]),
        (_src("Outlet C", "business"), [_it("Nvidia board considers Huang return as CEO", 1, "https://c/1")]),
        (_src("Outlet D"), [_it("Old Nvidia board news", 200, "https://d/1")]),
    ]


def test_cluster_groups_same_story_across_outlets():
    stories = feeds.cluster_stories(_fetched(), CLUSTER_CFG, NOW)
    top = stories[0]
    assert top["n_sources"] == 3 and top["hot"]
    assert top["lead"]["url"] == "https://a/1"                 # earliest report with a summary
    assert {m["source"] for m in top["more"]} == {"Outlet B", "Outlet C"}
    assert top["topics"] == ["business"]                       # one home topic: a board/CEO story is business
    assert top["updated"] == feeds._iso(NOW - timedelta(hours=1))
    titles = [s["lead"]["title"] for s in stories]
    assert "Apple ships new MacBook Air" in titles and "Old Nvidia board news" not in titles


def test_related_story_hangs_under_main_story():
    stories = feeds.cluster_stories(_fetched(), CLUSTER_CFG, NOW)
    top = stories[0]
    shakeup = next(s for s in stories if "shake-up" in s["lead"]["title"])
    assert shakeup["id"] in top["related"] and shakeup["related_to"] == top["id"]


def test_subcategory_rules():
    assert feeds._subcategory("tech", "Startup raises $50M Series B") == "Funding"
    assert feeds._subcategory("markets", "Stocks rally as Fed holds rates") == "Stocks"
    assert feeds._subcategory("tech", "A quiet week") == "More"


def test_ai_notes_skip_without_key_and_cache_with_fake_client(monkeypatch, tmp_path):
    from types import SimpleNamespace
    import json as _json
    from scalable import ai
    monkeypatch.setattr(ai, "CACHE", tmp_path / "ai_cache.json")
    cfg = {"topics": [{"id": "tech"}, {"id": "business"}], "ai_stories_per_topic": 12}
    stories = feeds.cluster_stories(_fetched(), CLUSTER_CFG, NOW)

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert ai.enrich(stories, cfg) == {"enabled": False} and "ai" not in stories[0]

    calls = []

    class FakeMessages:
        def create(self, **kw):
            calls.append(kw)
            ids = [s["id"] for s in _json.loads(kw["messages"][0]["content"])["stories"]]
            body = {"stories": [{"id": i, "summary": f"S {i}", "why_it_matters": "W", "label": "L"} for i in ids]}
            return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=_json.dumps(body))])

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda: SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages())))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    note = ai.enrich(stories, cfg)
    assert note["enabled"] and note["new"] >= 1 and stories[0]["ai"]["summary"] == f"S {stories[0]['id']}"
    assert calls[0]["output_config"]["format"]["type"] == "json_schema" and calls[0]["fallbacks"] == "default"
    # A second run finds everything cached and makes no request.
    calls.clear()
    fresh = feeds.cluster_stories(_fetched(), CLUSTER_CFG, NOW)
    ai.enrich(fresh, cfg)
    assert calls == [] and fresh[0]["ai"]["label"] == "L"


def test_repairs_bare_ampersands_and_control_chars():
    xml = '<rss><channel><item><title>AT&T and Q&A \x0b</title><link>https://a/1</link></item></channel></rss>'
    items = feeds.parse_feed(xml)
    assert items[0]["title"].startswith("AT&T and Q&A")


def test_rss1_rdf_feed():
    xml = ('<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/" '
           'xmlns:dc="http://purl.org/dc/elements/1.1/"><item rdf:about="https://a/1"><title>Hello</title>'
           '<link>https://a/1</link><dc:date>2026-11-17T10:00:00+00:00</dc:date></item></rdf:RDF>')
    items = feeds.parse_feed(xml)
    assert items[0]["title"] == "Hello" and items[0]["published"].year == 2026


def test_loose_fallback_for_broken_xml():
    xml = ('<rss><channel><item><title><![CDATA[Fed holds rates]]></title><link>https://a/1</link>'
           '<pubDate>Tue, 17 Nov 2026 10:00:00 GMT</pubDate><description>x < y</description></item>'
           '<item><title>Broken <b>tag</title><link>https://a/2</link></item></channel></rss>')
    items = feeds.parse_feed(xml)
    assert [i["url"] for i in items] == ["https://a/1", "https://a/2"]
    assert items[0]["title"] == "Fed holds rates"


def test_generic_words_do_not_link_related_stories():
    now = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
    def item(t, h):
        return {"title": t, "url": f"https://x/{abs(hash(t))}", "summary": "", "published": now - timedelta(hours=h)}
    fetched = [({"name": n, "topic": "tech"}, [item("Nvidia CEO Jensen Huang says he would return", 1)]) for n in "ABC"]
    fetched.append(({"name": "D", "topic": "news"}, [item("Comedian mocks CEO scandal at retailer", 2)]))
    stories = feeds.cluster_stories(fetched, {"cluster_threshold": 0.55}, now)
    main = max(stories, key=lambda s: s["n_sources"])
    assert main["related"] == []


def test_numbers_do_not_link_related_stories():
    now = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
    def item(t, h):
        return {"title": t, "url": f"https://x/{abs(hash(t))}", "summary": "", "published": now - timedelta(hours=h)}
    fetched = [({"name": n, "topic": "tech"}, [item("Voyager 1 reaches one light-day from Earth", 1)]) for n in "ABC"]
    fetched.append(({"name": "D", "topic": "tech"}, [item("Black Friday deals: 1 console bundle", 2)]))
    stories = feeds.cluster_stories(fetched, {"cluster_threshold": 0.55}, now)
    assert max(stories, key=lambda s: s["n_sources"])["related"] == []


def test_category_patterns_are_valid():
    import json, re
    from pathlib import Path
    cfg = json.loads((Path(__file__).parent.parent / "config" / "feeds.json").read_text())
    pats = {c["id"]: re.compile(c["pattern"], re.I) for c in cfg["categories"]}
    assert pats["ai"].search("OpenAI launches a new model")
    assert pats["gadgets"].search("Apple Watch Series 12 review")
    assert not pats["ai"].search("Said the chairman")  # "ai" only as a whole word



def test_each_story_gets_one_home_topic_by_subject():
    now = NOW
    def it(t, url):
        return {"title": t, "url": url, "summary": "", "published": now - timedelta(hours=1)}
    fetched = [
        (_src("Biz 1", "business"), [it("Nvidia unveils new AI chips for data centers", "https://1/1")]),
        (_src("Tech 1", "tech"), [it("Nvidia unveils new AI chips aimed at data centers", "https://2/1"),
                                  it("Starbucks CEO announces store closures and layoffs", "https://2/2")]),
        (_src("Biz 2", "business"), [it("Starbucks CEO announces store closures, layoffs", "https://3/2")]),
        (_src("Mkt", "markets"), [it("Stocks slide as Fed signals fewer rate cuts", "https://4/1")]),
    ]
    by_title = {s["lead"]["title"]: s["topics"] for s in feeds.cluster_stories(fetched, CLUSTER_CFG, now)}
    assert by_title["Nvidia unveils new AI chips for data centers"] == ["tech"]
    assert by_title["Starbucks CEO announces store closures and layoffs"] == ["business"]
    assert by_title["Stocks slide as Fed signals fewer rate cuts"] == ["markets"]
