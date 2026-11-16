# tests/test_reaction_art.py — JIT 7/8: reaction mini-polaroid.
"""The reaction illustration pastes in the left margin zone (geometry
from the proven mockup_reaction_only.py) and gates the main polaroid
off. Missing art degrades to no illustration, never a failed render.
Renders run against DejaVu like test_sketchnote.py; art files are
synthetic solid-color JPGs in a tmp dir. No network, no publishing.
"""
import pytest

pytest.importorskip("PIL")

from PIL import Image, ImageChops, ImageStat  # noqa: E402

PAPER_RGB = (247, 243, 232)  # #F7F3E8
MARGIN_CENTER = (102, 359)  # inside the pasted photo (frame at 28,285)
POLAROID_BOX = (980, 110, 1160, 300)  # main polaroid zone, top-right
MARGIN_BOX = (20, 280, 190, 460)  # reaction frame zone


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


def _art(tmp_path, name, color):
    """A synthetic 512x512 illustration JPG."""
    path = tmp_path / name
    Image.new("RGB", (512, 512), color).save(path, format="JPEG")
    return path


def _render(reaction=None, seed=7):
    from schedulers.sketchnote import build_card_data, render_sketchnote_image

    data = build_card_data(_snapshot(), "volume_spike",
                           "Does the tape stay loud?", reaction)
    return render_sketchnote_image(data, seed=seed)


def _mean_diff(img_a, img_b, box):
    diff = ImageChops.difference(img_a.crop(box), img_b.crop(box))
    return sum(ImageStat.Stat(diff.convert("L")).mean)


def _close(pixel, color, tol=25):
    return all(abs(a - b) <= tol for a, b in zip(pixel, color))


@pytest.fixture
def _art_dir(tmp_path, monkeypatch):
    import schedulers.sketchnote as sk

    monkeypatch.setattr(sk, "_ILLUSTRATIONS_DIR", str(tmp_path))
    import prompts.reactions as reactions

    monkeypatch.setattr(reactions, "current_variant", lambda name: "a")
    return tmp_path


# ------------------------------------------------------- card data
def test_build_card_data_carries_reaction():
    from schedulers.sketchnote import build_card_data

    assert build_card_data(_snapshot(), "volume_spike")["reaction"] is None
    data = build_card_data(_snapshot(), "volume_spike", None, "smug")
    assert data["reaction"] == "smug"


# ------------------------------------------------------- with art
def test_reaction_art_pastes_in_margin_zone(_art_dir):
    _art(_art_dir, "smug_a.jpg", (200, 30, 30))
    img = _render(reaction="smug")
    assert _close(img.getpixel(MARGIN_CENTER), (200, 30, 30))


def test_reaction_gates_main_polaroid_off(_art_dir):
    _art(_art_dir, "smug_a.jpg", (200, 30, 30))
    with_reaction = _render(reaction="smug")
    without = _render(reaction=None)
    # The margin zone differs (illustration pasted) AND the
    # top-right zone differs (polaroid present only without one).
    assert _mean_diff(with_reaction, without, MARGIN_BOX) > 5
    assert _mean_diff(with_reaction, without, POLAROID_BOX) > 5
    # And the top-right is paper where the polaroid photo would be.
    assert _close(with_reaction.getpixel((1070, 198)), PAPER_RGB, tol=40)


def test_variant_cursor_selects_the_file(_art_dir, monkeypatch):
    import prompts.reactions as reactions

    _art(_art_dir, "smug_a.jpg", (200, 30, 30))
    _art(_art_dir, "smug_c.jpg", (30, 30, 200))
    monkeypatch.setattr(reactions, "current_variant", lambda name: "c")
    img = _render(reaction="smug")
    assert _close(img.getpixel(MARGIN_CENTER), (30, 30, 200))


# ------------------------------------------------------- without art
def test_missing_art_renders_without_illustration(_art_dir):
    img = _render(reaction="smug")  # no files in the art dir
    assert img.size == (1200, 675)
    assert _close(img.getpixel(MARGIN_CENTER), PAPER_RGB)


def test_unknown_reaction_renders_clean(_art_dir):
    img = _render(reaction="nope")
    assert img.size == (1200, 675)
    assert _close(img.getpixel(MARGIN_CENTER), PAPER_RGB)


def test_corrupt_art_renders_without_illustration(_art_dir):
    (_art_dir / "smug_a.jpg").write_bytes(b"not a jpeg")
    img = _render(reaction="smug")
    assert img.size == (1200, 675)
    assert _close(img.getpixel(MARGIN_CENTER), PAPER_RGB)


# ------------------------------------------------------- threading
def test_render_card_threads_reaction(tmp_path, _art_dir):
    from schedulers.card_renderer import render_card

    _art(_art_dir, "smug_a.jpg", (200, 30, 30))
    out = tmp_path / "cards"
    path = render_card(_snapshot().token, output_dir=str(out),
                       snapshot=_snapshot(), card_type="volume_spike",
                       question="Does the tape stay loud?",
                       style="sketchnote", reaction="smug")
    img = Image.open(path)
    assert _close(img.getpixel(MARGIN_CENTER), (200, 30, 30))


def test_finalize_draft_passes_reaction_to_render(monkeypatch):
    import schedulers.orchestrator as orch

    seen = {}

    def _fake_render(token, snapshot=None, card_type=None, question=None,
                     style=None, reaction=None):
        seen["reaction"] = reaction
        seen["card_type"] = card_type
        return "/tmp/fake_card.png"

    monkeypatch.setattr(orch, "render_card", _fake_render)
    draft = orch.Draft(
        content="$NOVA jumped +18.4% on heavy volume. Does the tape stay loud?",
        fmt="image", title=None, token=_token(), category="GAINERS",
        scores={}, total_score=0.8, snapshot=_snapshot(),
        card_type="volume_spike", reaction="smug")
    content, fmt, title, image_paths = orch.finalize_draft(draft)
    assert fmt == "image"
    assert image_paths == ["/tmp/fake_card.png"]
    assert seen == {"reaction": "smug", "card_type": "volume_spike"}


def test_finalize_draft_without_reaction_passes_none(monkeypatch):
    import schedulers.orchestrator as orch

    seen = {}

    def _fake_render(token, snapshot=None, card_type=None, question=None,
                     style=None, reaction=None):
        seen["reaction"] = reaction
        return "/tmp/fake_card.png"

    monkeypatch.setattr(orch, "render_card", _fake_render)
    draft = orch.Draft(
        content="$NOVA jumped +18.4% on heavy volume. Does the tape stay loud?",
        fmt="image", title=None, token=_token(), category="GAINERS",
        scores={}, total_score=0.8, snapshot=_snapshot(),
        card_type="volume_spike", reaction=None)
    orch.finalize_draft(draft)
    assert seen["reaction"] is None
