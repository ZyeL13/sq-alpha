"""RSS news: timestamp parsing + staleness filter + matching + dedupe.

Regression untuk audit berita Fase 1: parsing pubDate lama
(`published[:25]` + strptime %z) selalu gagal sehingga SEMUA artikel
diberi timestamp "sekarang" — berita 2 hari lalu bisa ditempel sebagai
katalis "hari ini", dan umur berita tidak bisa dihitung.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import feedparser

from collectors import rss_news
from collectors.rss_news import (
    fetch_all_news,
    fetch_feed,
    get_news_for_symbol,
    is_fresh,
    parse_entry_timestamp,
)

EPOCH_2026_11_08_1200_UTC = 1794139200  # 2026-11-08 12:00:00 UTC


def _feed_xml(pub_dates):
    items = "".join(
        f"<item><title>Item {i}</title><link>https://x.example/{i}</link>"
        f"<pubDate>{d}</pubDate><description>crypto bitcoin</description></item>"
        for i, d in enumerate(pub_dates)
    )
    return (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        f"<title>t</title>{items}</channel></rss>"
    ).encode()


class _FakeResp:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        return None


def _patch_get(monkeypatch, content):
    monkeypatch.setattr(
        rss_news.requests, "get", lambda *a, **k: _FakeResp(content)
    )


# ---------- Langkah 1: parsing tanggal ----------

def test_parse_rfc822_date(monkeypatch):
    _patch_get(monkeypatch, _feed_xml(["Sun, 08 Nov 2026 12:00:00 +0000"]))
    articles = fetch_feed("test", "https://x.example/rss", max_articles=5)
    assert articles[0]["timestamp"] == EPOCH_2026_11_08_1200_UTC


def test_parse_gmt_date(monkeypatch):
    _patch_get(monkeypatch, _feed_xml(["Sun, 08 Nov 2026 12:00:00 GMT"]))
    articles = fetch_feed("test", "https://x.example/rss", max_articles=5)
    assert articles[0]["timestamp"] == EPOCH_2026_11_08_1200_UTC


def test_parse_iso8601_date(monkeypatch):
    _patch_get(monkeypatch, _feed_xml(["2026-11-08T12:00:00Z"]))
    articles = fetch_feed("test", "https://x.example/rss", max_articles=5)
    assert articles[0]["timestamp"] == EPOCH_2026_11_08_1200_UTC


def test_missing_date_is_zero_not_now():
    entry = feedparser.parse(
        b'<?xml version="1.0"?><rss version="2.0"><channel>'
        b"<item><title>No date</title></item></channel></rss>"
    ).entries[0]
    assert parse_entry_timestamp(entry) == 0.0


# ---------- Langkah 2: config RSS dipakai orchestrator ----------

def test_refresh_cache_respects_rss_disabled(monkeypatch):
    import schedulers.orchestrator as orch

    calls = []
    monkeypatch.setattr(orch, "fetch_all_news", lambda **k: calls.append(k) or [])
    monkeypatch.setattr(orch, "RSS_ENABLED", False)
    monkeypatch.setattr(orch, "_last_news_refresh", 0)
    monkeypatch.setattr(orch, "_news_cache", ["old"])
    assert orch.refresh_news_cache() == ["old"]
    assert calls == []


def test_refresh_cache_uses_config_values(monkeypatch):
    import schedulers.orchestrator as orch

    calls = []
    monkeypatch.setattr(orch, "fetch_all_news", lambda **k: calls.append(k) or [])
    monkeypatch.setattr(orch, "RSS_ENABLED", True)
    monkeypatch.setattr(orch, "RSS_REFRESH_INTERVAL", 300)
    monkeypatch.setattr(orch, "RSS_MAX_ARTICLES_PER_SOURCE", 2)
    monkeypatch.setattr(orch, "_last_news_refresh", 0)
    monkeypatch.setattr(orch, "_news_cache", [])
    orch.refresh_news_cache()
    assert calls == [{"max_per_source": 2}]


def test_config_rss_values_are_sane():
    import config

    assert config.RSS_ENABLED is True
    assert config.RSS_REFRESH_INTERVAL == 120
    assert config.RSS_MAX_ARTICLES_PER_SOURCE == 5


# ---------- Langkah 1: filter basi ----------

def _article(ts):
    return {"title": "bitcoin news", "summary": "", "timestamp": ts, "source": "t"}


def test_fresh_within_one_hour():
    now = time.time()
    assert is_fresh(_article(now - 30 * 60), now=now) is True


def test_stale_over_one_hour():
    now = time.time()
    assert is_fresh(_article(now - 2 * 3600), now=now) is False


def test_undated_article_is_not_fresh():
    assert is_fresh(_article(0)) is False


def test_fetch_all_news_drops_stale(monkeypatch):
    now = time.time()
    fresh = _article(now - 10 * 60)
    stale = _article(now - 2 * 3600)
    monkeypatch.setattr(
        rss_news, "fetch_feed", lambda *a, **k: [fresh, stale]
    )
    # 5 sumber x 1 artikel segar; yang basi dibuang dari semuanya.
    got = fetch_all_news(max_per_source=5)
    assert len(got) == 5
    assert all(a is fresh for a in got)


# ---------- Langkah 3: matching berbasis skor ----------

def _art(title, summary=""):
    return {"title": title, "summary": summary, "source": "coindesk",
            "timestamp": time.time()}


def _matches(symbol, title, summary=""):
    return get_news_for_symbol(symbol, [_art(title, summary)])


def test_sol_does_not_match_solution():
    assert _matches("SOL", "A new solution for scaling blockchains") == []


def test_sol_matches_via_name_solana():
    # "Solana solution..." cocok karena namanya, bukan karena "sol"
    # di dalam "solution" — alasan yang benar.
    assert len(_matches("SOL", "Solana solution for scaling")) == 1


def test_eth_does_not_match_tether_or_method():
    assert _matches("ETH", "Tether mints $1B as demand grows") == []
    assert _matches("ETH", "A new method for staking rewards") == []


def test_eth_matches_name_and_symbol():
    assert len(_matches("ETH", "ETH price steady as Ethereum upgrade nears")) == 1
    assert len(_matches("ETH", "Ethereum upgrade nears")) == 1


def test_one_does_not_match_someone_or_bare_word():
    assert _matches("ONE", "Someone says Bitcoin to $200k") == []
    # "ONE" sebagai kata biasa ("ONE more reason...") hanya 1.0,
    # di bawah threshold 2.0.
    assert _matches("ONE", "ONE more reason to watch the Fed") == []


def test_apt_does_not_match_adapt_or_bare_adjective():
    assert _matches("APT", "Markets adapt to new rules") == []
    assert _matches("APT", "Apt analysis says Bitcoin to $200k") == []


def test_apt_matches_cashtag_form():
    assert len(_matches("APT", "$APT jumps 12% after upgrade")) == 1


def test_eth_does_not_match_ethereum_classic():
    assert _matches("ETH", "Ethereum Classic upgrade nears") == []
    assert len(_matches("ETC", "Ethereum Classic upgrade nears")) == 1


def test_symbol_in_summary_only_is_below_threshold():
    assert _matches("SOL", "Crypto markets rally", "SOL gained 5% today") == []


def test_non_latin_symbol_matches_and_scores():
    got = _matches("币安人生", "币安人生 launches community event")
    assert len(got) == 1
    assert got[0]["match_score"] == 2.0


def test_results_sorted_by_score_desc():
    arts = [
        _art("Crypto markets rally", "Bitcoin ETF inflows hit a record"),
        _art("Bitcoin surges past $100k"),
    ]
    got = get_news_for_symbol("BTC", arts)
    assert got[0]["title"] == "Bitcoin surges past $100k"
    assert got[0]["match_score"] > got[1]["match_score"]


# ---------- Langkah 4: dedupe berita ----------

def test_assign_news_picks_most_relevant_token_only():
    from collectors.rss_news import assign_news_to_tokens

    arts = [_art("Bitcoin surges", "Ethereum also up today")]
    got = assign_news_to_tokens(["BTC", "ETH"], arts)
    # BTC: nama di judul (3.0). ETH: nama di summary (2.0). Hanya BTC.
    assert list(got.keys()) == ["BTC"]
    assert got["BTC"][0]["match_score"] == 3.0


def test_assign_news_drops_below_threshold():
    from collectors.rss_news import assign_news_to_tokens

    arts = [_art("Crypto markets rally", "SOL gained 5% today")]
    assert assign_news_to_tokens(["SOL", "BTC"], arts) == {}


def test_assign_news_tie_goes_to_first_symbol():
    from collectors.rss_news import assign_news_to_tokens

    arts = [_art("Bitcoin and Ethereum rally")]
    got = assign_news_to_tokens(["BTC", "ETH"], arts)
    assert list(got.keys()) == ["BTC"]


def test_news_dedup_mark_and_seen(tmp_path):
    from storage.news_dedup import NewsDedup

    dedup = NewsDedup(str(tmp_path / "news.json"))
    art = _art("Bitcoin surges")
    art["link"] = "https://www.coindesk.com/bitcoin-surges"
    assert dedup.is_seen(art) is False
    dedup.mark_used(art, "BTC")
    assert dedup.is_seen(art) is True
    assert dedup.is_seen(_art("Totally different news")) is False


def test_news_dedup_same_link_different_query_is_same_event(tmp_path):
    from storage.news_dedup import article_key

    a = {"title": "x", "link": "https://x.example/a?utm_source=rss&x=1"}
    b = {"title": "x", "link": "https://x.example/a?ref=telegram"}
    assert article_key(a) == article_key(b)


def test_news_dedup_clear_old(tmp_path):
    import time as _time

    from storage.news_dedup import NewsDedup

    dedup = NewsDedup(str(tmp_path / "news.json"))
    dedup.mark_used(_art("Old news"), "BTC")
    # Buat entri menua 25 jam, lalu bersihkan.
    for v in dedup.used.values():
        v["timestamp"] = _time.time() - 25 * 3600
    assert dedup.clear_old() == 1
    assert dedup.used == {}


def test_news_dedup_corrupt_file_recovers(tmp_path):
    from storage.news_dedup import NewsDedup

    bad = tmp_path / "news.json"
    bad.write_text("{not json")
    dedup = NewsDedup(str(bad))
    assert dedup.used == {}
    assert bad.with_suffix(".json.bak").exists()


# ---------- Langkah 7: berita besar tanpa match ----------

def test_big_unmatched_macro_news():
    from collectors.rss_news import is_big_unmatched

    assert is_big_unmatched(_art("SEC sues major crypto exchange")) is True
    assert is_big_unmatched(_art("Fed holds interest rates steady")) is True
    assert is_big_unmatched(_art("Exchange suffers $200M hack")) is True
    assert is_big_unmatched(_art("Dogecoin meme goes viral again")) is False
    # "ban" sebagai kata utuh; "bank" tidak boleh memicu.
    assert is_big_unmatched(_art("Bank adopts crypto custody")) is False


def test_suggest_review_cashtag_prefers_explicit_cashtag():
    from collectors.rss_news import suggest_review_cashtag

    assert suggest_review_cashtag(_art("$HYPE rallies on new listing")) == "$HYPE"
    assert suggest_review_cashtag(_art("Fed holds interest rates")) == "$BTC"


def test_find_big_unmatched_only_unassigned():
    from collectors.rss_news import assign_news_to_tokens, find_big_unmatched

    arts = [
        _art("Bitcoin surges past $100k"),
        _art("SEC sues major crypto exchange"),
    ]
    assignment = assign_news_to_tokens(["BTC", "ETH"], arts)
    got = find_big_unmatched(arts, assignment)
    assert [a["title"] for a in got] == ["SEC sues major crypto exchange"]


def test_review_queue_appends_and_dedupes(tmp_path):
    from storage.news_review import load_review_queue, queue_for_review

    path = str(tmp_path / "review.json")
    art = _art("SEC sues major crypto exchange")
    art["link"] = "https://x.example/sec-sues"
    assert queue_for_review(art, "$BTC", storage_file=path) is True
    assert queue_for_review(art, "$BTC", storage_file=path) is False
    items = load_review_queue(path)
    assert len(items) == 1
    assert items[0]["title"] == "SEC sues major crypto exchange"
    assert items[0]["suggested_cashtag"] == "$BTC"
    assert items[0]["link"] == "https://x.example/sec-sues"


# ---------- Langkah 8: sumber baru + bobot ----------

def test_new_sources_registered():
    from collectors.rss_news import RSS_SOURCES

    assert RSS_SOURCES["theblock"] == "https://www.theblock.co/rss.xml"
    assert RSS_SOURCES["cryptoslate"] == "https://cryptoslate.com/feed/"


def test_source_weight_boosts_fast_outlets():
    from collectors.rss_news import get_source_weight, score_article_for_symbol

    assert get_source_weight("theblock") == 1.5
    assert get_source_weight("cryptoslate") == 1.5
    assert get_source_weight("coindesk") == 1.0
    art = _art("Bitcoin surges past $100k")
    assert score_article_for_symbol("BTC", {**art, "source": "theblock"}) == 4.5
    assert score_article_for_symbol("BTC", {**art, "source": "coindesk"}) == 3.0


def test_weight_does_not_admit_weak_match():
    # Sebutan simbol di summary saja dari sumber berbobot tetap di bawah
    # threshold 2.0 (1.0 x 1.5 = 1.5).
    art = _art("Crypto markets rally", "SOL gained 5% today")
    art["source"] = "theblock"
    assert get_news_for_symbol("SOL", [art]) == []
