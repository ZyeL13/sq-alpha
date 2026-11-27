"""Per-post CSV log (step 1): one row per scheduled post, written at
schedule time, model/provider from llm.last_call_meta (never
hardcoded). No network, no LLM.
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import llm
import schedulers.orchestrator as orch
import storage.posts_csv as posts_csv
from storage.scheduled_post_queue import ScheduledPostQueue


def test_append_post_row_writes_header_once(tmp_path):
    path = str(tmp_path / "posts.csv")
    posts_csv.append_post_row(
        symbol="AAA", angle="smug", card_type="none", word_count=42,
        model="gpt-6-luna", provider="coarena_luna",
        prompt_version="json-v1", csv_path=path)
    posts_csv.append_post_row(
        symbol="BBB", angle="question", card_type="volume_spike",
        word_count=55, model="openai/gpt-oss-120b", provider="groq",
        prompt_version="json-v1", csv_path=path)
    with open(path) as f:
        rows = list(csv.reader(f))
    assert rows[0] == posts_csv.COLUMNS
    assert len(rows) == 3  # header + 2 rows, header written once
    assert rows[1][1] == "AAA"
    assert rows[1][2] == "smug"
    assert rows[1][4] == "42"
    assert rows[1][5] == "gpt-6-luna"
    assert rows[1][6] == "coarena_luna"
    assert rows[1][7] == "json-v1"
    assert rows[1][8] == "" and rows[1][9] == ""  # views/replies blank
    assert rows[2][1] == "BBB"


def test_schedule_winner_writes_csv_row_from_last_call_meta(
        tmp_path, monkeypatch):
    queue = ScheduledPostQueue(db_path=str(tmp_path / "sq.db"))
    monkeypatch.setattr(posts_csv, "POSTS_CSV_PATH",
                        str(tmp_path / "posts.csv"))
    monkeypatch.setattr(orch, "get_post_delay", lambda: 4800)
    monkeypatch.setattr(orch, "record_reaction_used", lambda name: None)
    monkeypatch.setattr(orch, "advance_variant", lambda name: None)
    monkeypatch.setattr(orch, "record_memory", lambda *a: None)
    monkeypatch.setattr(orch, "mark_posted", lambda *a, **k: None)
    monkeypatch.setattr(orch, "mark_news_used", lambda *a: None)
    monkeypatch.setattr(llm, "last_call_meta", {
        "provider": "coarena_luna", "model": "gpt-6-luna", "usage": {}})

    content = ("$AAA jumped +4.2% to $1.35 as volume ran 3.2x the 7-day "
               "average and the move held into the close.")
    draft = orch.Draft(content=content, fmt="short", title=None,
                       token={"symbol": "AAA"}, category="GAINERS",
                       scores={}, total_score=0.8, reaction="smug",
                       angle="smug")
    assert orch._schedule_winner(1, draft, "default", queue) is True
    assert queue.get_post_count() == 1
    with open(str(tmp_path / "posts.csv")) as f:
        rows = list(csv.reader(f))
    assert len(rows) == 2
    row = dict(zip(posts_csv.COLUMNS, rows[1]))
    assert row["symbol"] == "AAA"
    assert row["angle"] == "smug"
    assert row["card_type"] == "none"
    assert row["word_count"] == str(len(content.split()))
    assert row["model"] == "gpt-6-luna"
    assert row["provider"] == "coarena_luna"  # from last_call_meta, not hardcoded
    assert row["prompt_version"] == "json-v1"
    assert row["views_1h"] == "" and row["replies_1h"] == ""
    # Experiment columns (spec §7): appended at the end, blank by
    # default at write time; format defaults to "short".
    assert row["format"] == "short"
    assert row["mode"] == "" and row["hypothesis"] == ""
    assert row["variable_tested"] == ""
    assert row["views_6h"] == "" and row["age_h"] == ""
    assert row["replies_24h"] == ""


def test_schedule_winner_longform_csv_row(tmp_path, monkeypatch):
    import schedulers.banner as banner
    from schedulers.snapshot import CardSnapshot

    queue = ScheduledPostQueue(db_path=str(tmp_path / "sq.db"))
    monkeypatch.setattr(posts_csv, "POSTS_CSV_PATH",
                        str(tmp_path / "posts.csv"))
    monkeypatch.setattr(orch, "get_post_delay", lambda: 4800)
    monkeypatch.setattr(orch, "record_reaction_used", lambda name: None)
    monkeypatch.setattr(orch, "advance_variant", lambda name: None)
    monkeypatch.setattr(orch, "record_memory", lambda *a: None)
    monkeypatch.setattr(orch, "mark_posted", lambda *a, **k: None)
    monkeypatch.setattr(orch, "mark_news_used", lambda *a: None)
    monkeypatch.setattr(orch._banner, "select_banner_style",
                        lambda pack, article: "B")

    def _fake_render(*a, **k):
        banner.LAST_BANNER_STYLE.clear()
        banner.LAST_BANNER_STYLE.update({"style": "B"})
        return str(tmp_path / "banner.png")

    monkeypatch.setattr(orch._banner, "render_article_banner", _fake_render)
    monkeypatch.setattr(llm, "last_call_meta", {
        "provider": "coarena_luna", "model": "gpt-6-luna", "usage": {}})

    token = {"symbol": "PYR", "price": 0.021,
             "price_change_percent": -48.8, "volume_24h": 500_000,
             "high_24h": 0.047, "low_24h": 0.019,
             "btc_change_24h": -1.7, "timestamp": 1794634800}
    snapshot = CardSnapshot(token=dict(token),
                            closes=[0.0408 + i * -0.0008 for i in range(24)],
                            volume_7d_avg=833333.33, btc_change=-1.7)
    article = {"headline": "PYR COLLAPSES 48.8% WITH NO EXPLANATION",
               "deck": "Half the value gone in a day.",
               "stance": "BEARISH"}
    pack = {"facts": {"symbol": "PYR", "change_24h": -48.8},
            "stance": "BEARISH", "angle": "anomaly", "catalyst": None,
            "missing": {"fillable": [], "unavailable": []}}
    body = "THESIS\n\n$PYR collapsed 48.8% to $0.0210. " + "More. " * 100
    draft = orch.Draft(content=body, fmt="longform", title="PYR Halves",
                       token=token, category="LOSERS", scores={},
                       total_score=0.8, snapshot=snapshot,
                       article_json=article, research_pack=pack)
    assert orch._schedule_winner(1, draft, "default", queue) is True
    assert queue.get_post_count() == 1
    with open(str(tmp_path / "posts.csv")) as f:
        rows = list(csv.reader(f))
    assert len(rows) == 2
    row = dict(zip(posts_csv.COLUMNS, rows[1]))
    assert row["symbol"] == "PYR"
    assert row["format"] == "longform"
    assert row["prompt_version"] == "article-v1"
    assert row["card_type"] == "banner:B"
    assert row["mode"] == "" and row["hypothesis"] == ""
    assert row["variable_tested"] == ""
    path = str(tmp_path / "posts.csv")
    posts_csv.append_post_row(
        symbol="PYR", angle="", card_type="banner:B", word_count=583,
        model="gpt-6-luna", provider="coarena_luna",
        prompt_version="article-v1", csv_path=path, format="longform")
    with open(path) as f:
        rows = list(csv.reader(f))
    row = dict(zip(posts_csv.COLUMNS, rows[1]))
    assert row["format"] == "longform"
    assert row["prompt_version"] == "article-v1"
    assert row["card_type"] == "banner:B"
