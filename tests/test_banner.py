"""Article banners (spec §5.4–§5.6, §8): all 5 style templates
render from a fixture pack; numbers are recomputed from the snapshot
(formatters, not LLM text); stance-color assertion via the style's
declared accent; select_banner_style AUTO mapping + variety guard;
minimum font sizes; style C with no closes falls through and draws
no chart. No network, no LLM. Renders go to tmp dirs.
"""
import json
import os

import pytest
from PIL import Image

import schedulers.banner as banner
from schedulers.banner import BannerAssertionError, CardRenderError
from schedulers.card_renderer import _fmt_price
from schedulers.snapshot import CardSnapshot
from tests.test_article_redesign import PYR_CLOSES, PYR_TOKEN

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def _pyr_pack():
    with open(os.path.join(FIXTURES, "pyr_research_pack.json")) as f:
        return json.load(f)


@pytest.fixture
def _pyr_article():
    with open(os.path.join(FIXTURES, "pyr_article_good.json")) as f:
        return json.load(f)


@pytest.fixture
def _pyr_snapshot():
    token = dict(PYR_TOKEN)
    token["btc_change_24h"] = -1.7
    return CardSnapshot(token=token, closes=list(PYR_CLOSES),
                        volume_7d_avg=833333.33, btc_change=-1.7)


@pytest.fixture
def _env(monkeypatch, tmp_path):
    """Hermetic banner state: tmp cards dir + tmp history file,
    env override off unless a test sets it."""
    monkeypatch.setattr(banner, "CARDS_DIR", str(tmp_path / "cards"))
    monkeypatch.setattr(banner, "BANNER_STYLES_FILE",
                        str(tmp_path / "banner_styles.json"))
    monkeypatch.delenv("ARTICLE_BANNER_STYLE", raising=False)
    monkeypatch.setattr(banner, "ARTICLE_BANNER_STYLE", "AUTO")
    monkeypatch.setattr(banner, "LAST_BANNER_STYLE", {})
    return tmp_path


# ------------------------------------------------------------ formatters
def test_numbers_recomputed_from_snapshot(_pyr_snapshot):
    # The banner's numbers come from the snapshot via code formatters,
    # never from LLM text: price/change/volume equal the fixture values.
    assert _fmt_price(0.0210) == "$0.0210"
    assert _fmt_price(_pyr_snapshot.token["price"]) == "$0.0210"
    assert f"{_pyr_snapshot.token['price_change_percent']:+.1f}%" == "-48.8%"
    assert banner._fmt_volume_short(500_000) == "$500K"
    assert banner._fmt_volume_short(512_500) == "$512.5K"
    assert banner._fmt_volume_short(2_800_000) == "$2.8M"
    assert banner._fmt_volume_short(1_000_000) == "$1.0M"


def test_stance_color_assertion_declared_accent():
    # BEARISH -> red accent, never green in an accent role (checked
    # via the style's declared accent, not pixel-diffing).
    assert banner._accent_for_stance("BEARISH") == "#C65B5B"
    assert banner._accent_for_stance("BEARISH") != banner.BANNER_GREEN
    assert banner._accent_for_stance("BULLISH") == "#3FA97C"
    assert banner._accent_for_stance("NEUTRAL") == "#57C7C1"


# ------------------------------------------------------- AUTO selection
def test_select_banner_style_auto_mapping(_pyr_pack, _pyr_article, _env):
    pack = dict(_pyr_pack)
    pack["facts"] = {**pack["facts"], "closes": list(PYR_CLOSES)}
    # Crash (-48.8%) -> B.
    assert banner.select_banner_style(pack, _pyr_article) == "B"

    # Volume anomaly (small move, ratio present, closes present) -> C.
    vol_pack = {"facts": {"symbol": "WREN", "price": 0.42,
                          "change_24h": -6.3, "volume_24h": 500_000,
                          "volume_ratio": 1.8, "closes": list(PYR_CLOSES)},
                "stance": "NEUTRAL", "angle": "anomaly",
                "catalyst": None,
                "missing": {"fillable": [], "unavailable": []}}
    assert banner.select_banner_style(vol_pack, {"deck": ""}) == "C"

    # AI news in ALPHA -> D.
    ai_pack = {"facts": {"symbol": "NOVA", "price": 1.29,
                         "change_24h": 4.2, "volume_24h": 3_200_000},
               "stance": "NEUTRAL", "angle": "catalyst follow-through",
               "category": "ALPHA",
               "catalyst": {"text": "Nova Labs ships an AI infra upgrade."},
               "missing": {"fillable": [], "unavailable": []}}
    assert banner.select_banner_style(
        ai_pack, {"deck": "Nova ships the upgrade."}) == "D"

    # Single-metric conclusion (short deck, |chg| >= 10, no catalyst) -> E.
    single = {"facts": {"symbol": "KITE", "price": 1.015,
                        "change_24h": 12.0, "volume_24h": 8_000_000},
              "stance": "BULLISH", "angle": "range edge",
              "catalyst": None,
              "missing": {"fillable": [], "unavailable": []}}
    assert banner.select_banner_style(
        single, {"deck": "One number tells the story."}) == "E"

    # Ordinary -> A.
    ordinary = {"facts": {"symbol": "ORBT", "price": 2.55,
                          "change_24h": 2.0, "volume_24h": 5_000_000},
                "stance": "NEUTRAL", "angle": None, "catalyst": None,
                "missing": {"fillable": [], "unavailable": []}}
    assert banner.select_banner_style(ordinary, {"deck": ""}) == "A"


def test_select_banner_style_tolerates_minimal_pack(_env):
    # Defensive .get with defaults: a bare pack still selects.
    assert banner.select_banner_style({}, {}) == "A"
    assert banner.select_banner_style(None, None) == "A"


def test_select_banner_style_env_override_skips_guard(
        _pyr_pack, _pyr_article, _env, monkeypatch):
    pack = dict(_pyr_pack)
    pack["facts"] = {**pack["facts"], "closes": list(PYR_CLOSES)}
    monkeypatch.setattr(banner, "ARTICLE_BANNER_STYLE", "E")
    assert banner.select_banner_style(pack, _pyr_article) == "E"


def test_variety_guard_falls_through(_pyr_pack, _pyr_article, _env):
    pack = dict(_pyr_pack)
    pack["facts"] = {**pack["facts"], "closes": list(PYR_CLOSES)}
    # Last banner was B: the crash pick falls through to the next
    # fitting style (volume anomaly -> C).
    banner._record_banner_style("B")
    assert banner.select_banner_style(pack, _pyr_article) == "C"
    # Last banner was A and only A fits: rotation moves on, never repeats.
    ordinary = {"facts": {"symbol": "ORBT", "price": 2.55,
                          "change_24h": 2.0, "volume_24h": 5_000_000},
                "stance": "NEUTRAL", "angle": None, "catalyst": None,
                "missing": {"fillable": [], "unavailable": []}}
    banner._record_banner_style("A")
    assert banner.select_banner_style(ordinary, {"deck": ""}) == "B"


def test_history_capped_at_three(_pyr_snapshot, _pyr_article, _env):
    for style in ("A", "B", "C", "D"):
        path = banner.render_article_banner(
            _pyr_snapshot.token, _pyr_snapshot, "BEARISH",
            _pyr_article["deck"], _pyr_article["headline"], style=style)
        assert os.path.exists(path)
    assert banner._read_banner_history() == ["B", "C", "D"]


# ---------------------------------------------------------------- renders
@pytest.mark.parametrize("style", ["A", "B", "C", "D", "E"])
def test_all_five_styles_render(style, _pyr_snapshot, _pyr_article, _env):
    path = banner.render_article_banner(
        _pyr_snapshot.token, _pyr_snapshot, "BEARISH",
        _pyr_article["deck"], _pyr_article["headline"], style=style)
    assert os.path.exists(path)
    with Image.open(path) as img:
        assert img.size == (1200, 675)
    assert banner.LAST_BANNER_STYLE == {"style": style}


def test_render_auto_selects_crash_style_b(
        _pyr_snapshot, _pyr_article, _env):
    path = banner.render_article_banner(
        _pyr_snapshot.token, _pyr_snapshot, "BEARISH",
        _pyr_article["deck"], _pyr_article["headline"])
    assert os.path.exists(path)
    assert banner.LAST_BANNER_STYLE == {"style": "B"}


def test_render_rejects_repeat_of_last_style(
        _pyr_snapshot, _pyr_article, _env):
    banner._record_banner_style("A")
    with pytest.raises(BannerAssertionError):
        banner.render_article_banner(
            _pyr_snapshot.token, _pyr_snapshot, "BEARISH",
            _pyr_article["deck"], _pyr_article["headline"], style="A")
    # The env override escapes the assertion.
    banner.ARTICLE_BANNER_STYLE = "A"
    path = banner.render_article_banner(
        _pyr_snapshot.token, _pyr_snapshot, "BEARISH",
        _pyr_article["deck"], _pyr_article["headline"], style="A")
    assert os.path.exists(path)


def test_headline_minimum_font_size(_pyr_snapshot, _pyr_article, _env):
    # A headline that cannot fit in 2 lines at 54pt raises instead
    # of shrinking below the floor (spec §6.7).
    long_headline = ("PYR COLLAPSES 48.8% WITH NO EXPLANATION " * 8).strip()
    with pytest.raises(CardRenderError):
        banner.render_article_banner(
            _pyr_snapshot.token, _pyr_snapshot, "BEARISH",
            _pyr_article["deck"], long_headline, style="A")
    # The fixture headline fits and renders.
    path = banner.render_article_banner(
        _pyr_snapshot.token, _pyr_snapshot, "BEARISH",
        _pyr_article["deck"], _pyr_article["headline"], style="A")
    assert os.path.exists(path)


def test_style_c_without_closes_falls_through_and_draws_no_chart(
        _pyr_pack, _pyr_article, _env):
    # No closes in the pack facts -> C is not selectable.
    assert banner.select_banner_style(_pyr_pack, _pyr_article) != "C"
    # And a render asked for C with no closes raises instead of
    # drawing a fake chart.
    token = dict(PYR_TOKEN)
    token["btc_change_24h"] = -1.7
    no_closes = CardSnapshot(token=token, closes=[],
                             volume_7d_avg=833333.33, btc_change=-1.7)
    with pytest.raises(BannerAssertionError):
        banner.render_article_banner(
            token, no_closes, "BEARISH", _pyr_article["deck"],
            _pyr_article["headline"], style="C")
    # No chart drawn: no file was written at all.
    assert not os.path.exists(banner.CARDS_DIR) or \
        os.listdir(banner.CARDS_DIR) == []


def test_render_needs_snapshot(_pyr_article, _env):
    with pytest.raises(CardRenderError):
        banner.render_article_banner(
            dict(PYR_TOKEN), None, "BEARISH", _pyr_article["deck"],
            _pyr_article["headline"], style="A")
