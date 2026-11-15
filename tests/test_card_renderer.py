# tests/test_card_renderer.py — V3 Phase 2 local data-card renderer.
"""Render is a pure function of the token dict: valid PNG, expected
dimensions, deterministic bytes, graceful font fallback, 48h prune.
No network, no publishing."""
import os
import time

import pytest

pytest.importorskip("PIL")


def _token(**overrides):
    token = {
        "symbol": "KITE",
        "price": 2.40,
        "price_change_percent": -5.8,
        "volume_24h": 2_800_000,
        "high_24h": 2.80,
        "low_24h": 2.10,
        "timestamp": 1794634800,  # fixed: deterministic footer date
    }
    token.update(overrides)
    return token


def test_renders_valid_png_with_expected_dimensions(tmp_path):
    from PIL import Image
    from schedulers.card_renderer import render_card, CARD_WIDTH, CARD_HEIGHT

    path = render_card(_token(), output_dir=str(tmp_path))
    assert os.path.isfile(path)
    assert path.endswith(".png")
    assert os.path.getsize(path) > 1024  # non-trivial content, not blank
    with Image.open(path) as img:
        assert img.size == (CARD_WIDTH, CARD_HEIGHT)
        assert img.mode == "RGB"
        img.load()  # fully decodable


def test_same_input_renders_identical_bytes(tmp_path):
    from schedulers.card_renderer import render_card

    first = render_card(_token(), output_dir=str(tmp_path))
    second = render_card(_token(), output_dir=str(tmp_path))
    assert first != second  # filenames carry wall-clock time
    with open(first, "rb") as f1, open(second, "rb") as f2:
        assert f1.read() == f2.read()


def test_gain_and_loss_both_render(tmp_path):
    from PIL import Image
    from schedulers.card_renderer import render_card

    for chg in (12.4, -12.4, 0.0):
        path = render_card(_token(price_change_percent=chg), output_dir=str(tmp_path))
        with Image.open(path) as img:
            assert img.size == (1200, 675)


def test_missing_high_low_omits_range_bar_but_still_renders(tmp_path):
    from PIL import Image
    from schedulers.card_renderer import render_card

    token = _token(high_24h=0, low_24h=0)
    path = render_card(token, output_dir=str(tmp_path))
    with Image.open(path) as img:
        assert img.size == (1200, 675)


def test_missing_font_falls_back_to_default_font(tmp_path, monkeypatch):
    """No DejaVu anywhere (patched dirs + empty cwd): still a valid PNG."""
    import schedulers.card_renderer as cr
    from PIL import Image

    monkeypatch.setattr(cr, "_FONT_DIRS", ["/nonexistent-font-dir"])
    monkeypatch.chdir(tmp_path)  # bare "DejaVuSans.ttf" cannot resolve here
    path = cr.render_card(_token(), output_dir=str(tmp_path))
    with Image.open(path) as img:
        assert img.size == (1200, 675)
        img.load()


def test_prune_removes_only_old_cards(tmp_path):
    from schedulers.card_renderer import render_card, _prune_old_cards

    old = tmp_path / "OLD_1.png"
    new = tmp_path / "NEW_1.png"
    keep_txt = tmp_path / "notes.txt"
    old.write_bytes(b"old")
    new.write_bytes(b"new")
    keep_txt.write_bytes(b"keep")
    ancient = time.time() - (49 * 3600)
    os.utime(old, (ancient, ancient))

    _prune_old_cards(str(tmp_path))
    assert not old.exists()
    assert new.exists()
    assert keep_txt.exists()

    # Rendering also prunes: an old card left in the dir disappears.
    old.write_bytes(b"old again")
    os.utime(old, (ancient, ancient))
    render_card(_token(), output_dir=str(tmp_path))
    assert not old.exists()


def test_invalid_data_raises_catchable_error(tmp_path):
    from schedulers.card_renderer import render_card, CardRenderError

    with pytest.raises(CardRenderError):
        render_card(_token(symbol=""), output_dir=str(tmp_path))
    with pytest.raises(CardRenderError):
        render_card(_token(price=0), output_dir=str(tmp_path))
    with pytest.raises(CardRenderError):
        render_card(_token(price_change_percent="n/a"), output_dir=str(tmp_path))


def test_long_symbol_fits_without_error(tmp_path):
    from PIL import Image
    from schedulers.card_renderer import render_card

    path = render_card(_token(symbol="VERYLONGSYMBOLNAME"), output_dir=str(tmp_path))
    with Image.open(path) as img:
        assert img.size == (1200, 675)


def test_filename_is_filesystem_safe(tmp_path):
    from schedulers.card_renderer import render_card

    path = render_card(_token(symbol="A/B:C"), output_dir=str(tmp_path))
    assert os.path.isfile(path)
    assert "/" not in os.path.basename(path)
