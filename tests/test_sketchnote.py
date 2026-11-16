# tests/test_sketchnote.py — Fase 3 sketchnote renderer + style dispatch.
"""Renders run against DejaVu (the Kalam lookup is tested with a
renamed stand-in font in a tmp dir — the suite must not depend on
files outside the repo). No network, no publishing."""
import os
import shutil

import pytest

pytest.importorskip("PIL")

PAPER_RGB = (247, 243, 232)  # #F7F3E8
PLAIN_BG_RGB = (18, 21, 26)  # #12151A


def _token(**overrides):
    token = {
        "symbol": "NOVA",
        "price": 1.29,
        "price_change_percent": 18.4,
        "volume_24h": 3_200_000,
        "high_24h": 1.35,
        "low_24h": 1.08,
        "btc_change_24h": 2.1,
        "timestamp": 1794634800,  # fixed: deterministic footer + seed
    }
    token.update(overrides)
    return token


def _snapshot(token=None, closes=None, volume_7d_avg=1_000_000,
              btc_change=2.1):
    from schedulers.snapshot import CardSnapshot

    token = token or _token()
    closes = closes or [1.09 + i * 0.01 for i in range(24)]
    return CardSnapshot(token=dict(token), closes=list(closes),
                        volume_7d_avg=volume_7d_avg, btc_change=btc_change)


def _render(snapshot, card_type, question=None, tmp_path=None, **kwargs):
    from schedulers.card_renderer import render_card

    return render_card(snapshot.token, output_dir=str(tmp_path),
                       snapshot=snapshot, card_type=card_type,
                       question=question, style="sketchnote", **kwargs)


# ------------------------------------------------------- card data
def test_build_card_data_volume_spike():
    from schedulers.sketchnote import build_card_data

    data = build_card_data(_snapshot(), "volume_spike",
                           "Does the tape stay loud?")
    assert data["label"] == "Volume Spike"
    assert data["symbol"] == "$NOVA"
    assert data["hero"] == "+18.4%"
    assert data["down"] is False
    assert data["stat1"] == ("volume vs 7d avg", "3.2×")
    assert data["stat2"] == ("position in 24h range", "0.78")
    assert data["read"] == "Volume leads, price follows."
    assert data["question"] == "Does the tape stay loud?"
    assert len(data["closes"]) == 24


def test_build_card_data_relative_weakness_down_and_up():
    from schedulers.sketchnote import build_card_data

    down = build_card_data(_snapshot(_token(price_change_percent=-7.9)),
                           "relative_weakness")
    assert down["stat2"] == ("vs BTC, same 24h", "-10.0 pts")
    assert down["read"] == "Weak against BTC, not just down."
    assert down["down"] is True

    up = build_card_data(_snapshot(_token(price_change_percent=3.1)),
                         "relative_weakness")
    assert up["read"] == "Up, but lagging BTC by a wide margin."
    assert up["down"] is False


def test_build_card_data_other_types():
    from schedulers.sketchnote import build_card_data

    assert build_card_data(_snapshot(), "thin_tape")["label"] == "Thin Tape"
    assert build_card_data(_snapshot(), "thin_tape")["read"] == \
        "Quiet tape, barely any volume."
    assert build_card_data(_snapshot(), "range_squeeze")["label"] == \
        "Range Squeeze"
    assert build_card_data(_snapshot(), "range_squeeze")["read"] == \
        "Small range, price mid-way through it."


def test_build_card_data_rejects_unknown_type_and_missing_btc():
    from schedulers.sketchnote import build_card_data

    with pytest.raises(ValueError):
        build_card_data(_snapshot(), "bogus")
    with pytest.raises(ValueError):
        build_card_data(_snapshot(btc_change=None), "relative_weakness")


# ------------------------------------------------------- rendering
@pytest.mark.parametrize("card_type", ["thin_tape", "volume_spike",
                                       "range_squeeze",
                                       "relative_weakness"])
def test_all_four_types_render(tmp_path, card_type):
    from PIL import Image

    path = _render(_snapshot(), card_type,
                   question="Is this the real read?", tmp_path=tmp_path)
    assert os.path.isfile(path)
    with Image.open(path) as img:
        assert img.size == (1200, 675)
        assert img.mode == "RGB"
        img.load()


def test_sketchnote_render_is_deterministic(tmp_path):
    first = _render(_snapshot(), "volume_spike", tmp_path=tmp_path)
    second = _render(_snapshot(), "volume_spike", tmp_path=tmp_path)
    assert first != second  # filenames carry wall-clock time
    with open(first, "rb") as f1, open(second, "rb") as f2:
        assert f1.read() == f2.read()


def test_flat_closes_render(tmp_path):
    from PIL import Image

    snap = _snapshot(closes=[2.0] * 24)
    path = _render(snap, "thin_tape", tmp_path=tmp_path)
    with Image.open(path) as img:
        assert img.size == (1200, 675)


def test_long_symbol_and_long_question_render(tmp_path):
    from PIL import Image

    token = _token(symbol="VERYLONGSYMBOLNAME")
    path = _render(_snapshot(token), "volume_spike",
                   question="What happens next " + "really " * 40 + "?",
                   tmp_path=tmp_path)
    with Image.open(path) as img:
        assert img.size == (1200, 675)


def test_missing_question_omits_row_but_renders(tmp_path):
    from PIL import Image

    path = _render(_snapshot(), "volume_spike", question=None,
                   tmp_path=tmp_path)
    with Image.open(path) as img:
        assert img.size == (1200, 675)


# --------------------------------------------------------- polaroid
def test_polaroid_present_and_failure_degrades(tmp_path, monkeypatch):
    from PIL import Image
    import schedulers.sketchnote as sk
    import schedulers.avatar_b64 as av

    # Healthy avatar: the polaroid corner is photo, not paper.
    monkeypatch.setattr(sk, "_avatar_cache", None)
    good = _render(_snapshot(), "volume_spike", tmp_path=tmp_path)
    with Image.open(good) as img:
        assert img.getpixel((1060, 200)) != PAPER_RGB

    # Corrupt avatar data: render still succeeds, corner stays paper.
    monkeypatch.setattr(av, "AVATAR_JPEG_B64", "not-base64!!!")
    monkeypatch.setattr(sk, "_avatar_cache", None)
    bad = _render(_snapshot(), "volume_spike", tmp_path=tmp_path)
    with Image.open(bad) as img:
        assert img.size == (1200, 675)
        assert img.getpixel((1060, 200)) == PAPER_RGB


# ------------------------------------------------------------ fonts
def test_kalam_dir_is_searched_first(tmp_path, monkeypatch):
    import schedulers.sketchnote as sk

    dejavu = "/usr/share/fonts/truetype/dejavu"
    shutil.copy(os.path.join(dejavu, "DejaVuSans.ttf"),
                tmp_path / "Kalam-Regular.ttf")
    shutil.copy(os.path.join(dejavu, "DejaVuSans-Bold.ttf"),
                tmp_path / "Kalam-Bold.ttf")
    monkeypatch.setenv("KALAM_FONT_DIR", str(tmp_path))
    font = sk._sketch_font(False, 24)
    assert "Kalam-Regular" in getattr(font, "path", "")


def test_missing_fonts_fall_back_to_default(tmp_path, monkeypatch):
    import schedulers.sketchnote as sk
    from PIL import Image

    monkeypatch.setattr(sk, "_KALAM_DIRS", [])
    monkeypatch.setattr(sk, "_DEJAVU_DIRS", ["/nonexistent-font-dir"])
    monkeypatch.delenv("KALAM_FONT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    path = _render(_snapshot(), "volume_spike", tmp_path=tmp_path)
    with Image.open(path) as img:
        assert img.size == (1200, 675)
        img.load()


# --------------------------------------------------- style dispatch
def test_resolve_style():
    import schedulers.card_renderer as cr

    assert cr._resolve_style("plain") == "plain"
    assert cr._resolve_style("sketchnote") == "sketchnote"
    assert cr._resolve_style("annotated") == "plain"  # deferred
    assert cr._resolve_style("bogus") == "sketchnote"
    assert cr._resolve_style("  PLAIN ") == "plain"


def test_resolve_style_reads_config_default(monkeypatch):
    import schedulers.card_renderer as cr

    monkeypatch.setattr(cr, "CARD_STYLE", "plain")
    assert cr._resolve_style(None) == "plain"


def test_sketchnote_without_snapshot_degrades_to_plain(tmp_path, monkeypatch):
    from PIL import Image
    import schedulers.card_renderer as cr

    monkeypatch.setattr(cr, "CARD_STYLE", "sketchnote")
    path = cr.render_card(_token(), output_dir=str(tmp_path))
    with Image.open(path) as img:
        assert img.getpixel((600, 660)) == PLAIN_BG_RGB


def test_sketchnote_without_card_type_degrades_to_plain(tmp_path, monkeypatch):
    from PIL import Image
    import schedulers.card_renderer as cr

    monkeypatch.setattr(cr, "CARD_STYLE", "sketchnote")
    path = cr.render_card(_token(), output_dir=str(tmp_path),
                          snapshot=_snapshot())
    with Image.open(path) as img:
        assert img.getpixel((600, 660)) == PLAIN_BG_RGB


def test_annotated_style_renders_plain(tmp_path):
    from PIL import Image
    from schedulers.card_renderer import render_card

    path = render_card(_token(), output_dir=str(tmp_path),
                       snapshot=_snapshot(), card_type="volume_spike",
                       style="annotated")
    with Image.open(path) as img:
        assert img.getpixel((600, 660)) == PLAIN_BG_RGB


def test_plain_style_ignores_snapshot(tmp_path):
    from PIL import Image
    from schedulers.card_renderer import render_card

    path = render_card(_token(), output_dir=str(tmp_path),
                       snapshot=_snapshot(), card_type="volume_spike",
                       style="plain")
    with Image.open(path) as img:
        assert img.getpixel((600, 660)) == PLAIN_BG_RGB
