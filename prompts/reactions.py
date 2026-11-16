# prompts/reactions.py — opening reactions for the JIT path.
#
# Reactions replace the 10 opening angles (prompts/styles.py) on the
# JIT path: instead of a rhetorical device rotated mechanically, the
# opener is a human reaction to the specific data shape — surprise,
# recognition, a shrug, disbelief. Each reaction is an instruction
# block (never verbatim text), data-anchored, and contains none of
# the EDITORIAL_FORBIDDEN phrases. The instruction texts also avoid
# the reasoning-leak trigger phrases the quality gate scans for
# ("hold on", "let me", "i need to", ...): the model echoes
# instruction language, and a post containing one of those phrases
# is hard-rejected.
#
# Deck: same machinery as the angle deck — a rotating deck persisted
# per posting day (07:00 WIB reset), each reaction used once per
# cycle, no adjacent repeats. The difference is record-on-win: pool
# rounds DRAW tentatively (a round's drafts each get a different
# reaction for variety) and only the winning draft's reaction is
# recorded as used. Tentative draws pop the in-memory deck but never
# touch the file, so a discarded draft burns nothing durable.
# All file access is best-effort — a missing/corrupt/unwritable
# state file degrades to the in-memory deck, never a crash.
import json
import os
import random
import threading

from config import REACTIONS_FILE, REACTION_VARIANTS_FILE

REACTIONS = {
    "surprise": (
        "Open with genuine surprise at what the data shows: the move, "
        "the volume, or the combination is not what a normal session "
        "looks like. Lead with the specific thing that defies "
        "expectation, then the number that proves it."
    ),
    "dejavu": (
        "Open with dry recognition: this token has done this before. "
        "The pattern repeating is the hook — name what is repeating "
        "and how this time compares, without pretending the outcome "
        "is already decided."
    ),
    "shrug": (
        "Open by saying plainly that not much happened — and mean it. "
        "A quiet tape is the observation, not a failure of one. Lead "
        "with the calmest true statement the data supports, then the "
        "one number worth noting."
    ),
    "disbelief": (
        "Open with disbelief at the scale of what the data shows: a "
        "move, a volume print, or a combination too large to read as "
        "ordinary. Lead with the extreme number, then what makes it "
        "hard to take at face value."
    ),
    "question": (
        "Open with the one specific question the data raises — the "
        "thing a reader would want answered before anything else. The "
        "question must name something concrete from the data, never a "
        "generic question about what happens next."
    ),
    "contrast": (
        "Open with the contrast between this token and the wider "
        "market: the token moved one way while BTC or the market "
        "moved another. Lead with whichever side of the disagreement "
        "is more surprising."
    ),
    "caution": (
        "Open with a warning read: something about this setup looks "
        "stretched — price at a range edge, a move running ahead of "
        "participation, or follow-through that has not arrived. State "
        "the stretch plainly, without telling readers what to do."
    ),
    "smug": (
        "Open with quiet satisfaction: the last read on this token "
        "played out. The satisfaction is in the observation landing, "
        "never at a reader's expense — no gloating, no told-you-so. "
        "Name what played out and what the data shows now."
    ),
}

_reaction_deck: "list[str]" = []
_reaction_lock = threading.RLock()
_last_reaction: "str | None" = None
# Tests point this at a tmp file; production uses the config path.
REACTION_STATE_FILE: str = REACTIONS_FILE


def _today_key() -> str:
    """Reset-window key for the current posting day. Same 07:00 WIB
    window as storage/post_counter.py (RESET_HOUR stays the single
    source of truth there); the computation is duplicated here so
    prompts/ never imports storage/."""
    from datetime import datetime, timedelta

    from storage.post_counter import RESET_HOUR

    from config import WIB

    now = datetime.now(WIB)
    reset = datetime(now.year, now.month, now.day, RESET_HOUR, 0, 0, tzinfo=WIB)
    if now < reset:
        reset -= timedelta(days=1)
    return reset.strftime("%Y-%m-%d_%H:%M")


def _read_used() -> "list[str]":
    """Reactions already used today, from the state file. Empty on any
    failure or when the stored day is not today."""
    try:
        if not os.path.exists(REACTION_STATE_FILE):
            return []
        with open(REACTION_STATE_FILE, "r") as f:
            data = json.load(f)
        if data.get("reset_key") != _today_key():
            return []
        used = data.get("used", [])
        return [u for u in used if u in REACTIONS]
    except Exception:
        return []


def _write_used(used: "list[str]") -> None:
    """Persist the used list for today. Best-effort; callers hold
    _reaction_lock."""
    try:
        os.makedirs(os.path.dirname(REACTION_STATE_FILE), exist_ok=True)
        with open(REACTION_STATE_FILE, "w") as f:
            json.dump({"reset_key": _today_key(), "used": used}, f)
    except Exception:
        pass


def _refill_deck(rng: "random.Random | None" = None) -> None:
    """Shuffle a fresh deck from the reactions not yet used today. The
    first card drawn (deck pops from the end) is never the reaction
    recorded last, so no two adjacent scheduled posts share a
    reaction — even across a cycle boundary. Callers hold
    _reaction_lock."""
    global _reaction_deck
    used = _read_used()
    names = [n for n in REACTIONS if n not in used]
    if not names:
        # Every reaction used today: fresh cycle, used list restarts.
        _write_used([])
        names = list(REACTIONS)
    (rng or random).shuffle(names)
    if _last_reaction is not None and len(names) > 1 and names[-1] == _last_reaction:
        names[-1], names[0] = names[0], names[-1]
    _reaction_deck = names


def record_reaction_used(name: str) -> None:
    """Record a reaction as used today (no double-record). Called only
    for the winning draft of a pool round — tentative draws never
    reach here. Also marks the reaction as last-used for the
    no-adjacent-repeat guard."""
    global _last_reaction
    with _reaction_lock:
        _last_reaction = name
        used = _read_used()
        if name not in used:
            used.append(name)
            _write_used(used)


def _range_position(token: dict) -> float:
    """Position of price inside the 24h high/low range, 0..1. Same
    derivation as schedulers/snapshot.range_position_of (duplicated:
    prompts/ never imports schedulers/)."""
    high = token.get("high_24h") or 0
    low = token.get("low_24h") or 0
    price = token.get("price") or 0
    if high and low and high > low and price:
        return max(0.0, min(1.0, (price - low) / (high - low)))
    rp = token.get("range_position")
    if rp is not None:
        try:
            return max(0.0, min(1.0, float(rp)))
        except (TypeError, ValueError):
            pass
    return 0.5


def _same_direction(change: float, memory: "dict | None") -> bool:
    """True when a memory record exists and the current move runs the
    same way as the move at the last post. A zero on either side
    establishes no direction."""
    if not memory:
        return False
    try:
        prev = float(memory.get("change") or 0)
    except (TypeError, ValueError):
        return False
    if change == 0 or prev == 0:
        return False
    return (change > 0) == (prev > 0)


def trigger_matches(name: str, token: dict, memory: "dict | None" = None) -> bool:
    """Whether a reaction's data-shape trigger matches this token.

    Pure function of the token + memory record; the deck draw
    prefers matching reactions. `question` always matches (it only
    demands specificity, which the instruction itself enforces).
    """
    try:
        change = float(token.get("price_change_percent") or 0)
    except (TypeError, ValueError):
        change = 0.0
    ratio = token.get("volume_ratio_7d")
    try:
        ratio = float(ratio) if ratio is not None else None
    except (TypeError, ValueError):
        ratio = None
    btc = token.get("btc_change_24h")
    try:
        btc_relative = (change - float(btc)) if btc is not None else None
    except (TypeError, ValueError):
        btc_relative = None

    if name == "surprise":
        return abs(change) >= 5 or (ratio is not None and ratio >= 2.0)
    if name == "dejavu":
        return _same_direction(change, memory)
    if name == "shrug":
        return abs(change) < 3
    if name == "disbelief":
        if abs(change) >= 15:
            return True
        if ratio is not None and ratio >= 3.0 and abs(change) < 3:
            return True
        return abs(change) >= 10 and not token.get("news_catalyst")
    if name == "question":
        return True
    if name == "contrast":
        return btc_relative is not None and abs(btc_relative) >= 3
    if name == "caution":
        rp = _range_position(token)
        return (rp <= 0.15 or rp >= 0.85) and abs(change) >= 5
    if name == "smug":
        return _same_direction(change, memory) and abs(change) >= 3
    return False


def _pick_from_deck(deck: "list[str]", token: dict,
                    memory: "dict | None" = None,
                    exclude: "str | None" = None) -> str:
    """Pick the next reaction from a deck (list, popped from the end).

    Prefers the last trigger-matching name in deck order, skipping
    `exclude` (the last recorded reaction) while alternatives exist;
    falls back to the last non-excluded name, then to the last name
    overall when the deck holds only the excluded one. Pure selection
    — the caller pops the returned name from the deck."""
    for name in reversed(deck):
        if name != exclude and trigger_matches(name, token, memory):
            return name
    for name in reversed(deck):
        if name != exclude:
            return name
    return deck[-1]


def draw_reaction(token: dict, memory: "dict | None" = None) -> "tuple[str, str]":
    """Draw the next (name, instruction) tentatively: popped from the
    in-memory deck, NOT recorded. The pool records only the winner's
    reaction via record_reaction_used."""
    with _reaction_lock:
        if not _reaction_deck:
            _refill_deck()
        name = _pick_from_deck(_reaction_deck, token, memory,
                               exclude=_last_reaction)
        _reaction_deck.remove(name)
    return name, REACTIONS[name]


def reset_reaction_deck(seed: "int | None" = None, clear_file: bool = True) -> None:
    """Empty the deck. Tests pass a seed for a deterministic order.
    clear_file=False keeps the state file (simulates a restart)."""
    global _reaction_deck, _last_reaction
    with _reaction_lock:
        _reaction_deck = []
        _last_reaction = None
        if clear_file:
            _write_used([])
        if seed is not None:
            _refill_deck(random.Random(seed))


# ---------------- variant rotation ----------------
# Each reaction has 4 illustration variants (a/b/c/d). The variants
# exist for rotation — the same emotion must not reuse the same art
# post after post — while the reaction itself still matches the
# post. A persisted per-reaction cursor cycles a -> b -> c -> d -> a
# and advances ONLY when a post with that reaction is scheduled
# (winners only, same rule as the deck). Unlike the deck, the
# cursor is NOT day-scoped: rotation continues across resets.
# Read-through (no in-memory cache): the file is tiny and the
# renderer reads once per card. Best-effort throughout.

VARIANTS = ("a", "b", "c", "d")
# Tests point this at a tmp file; production uses the config path.
VARIANT_STATE_FILE: str = REACTION_VARIANTS_FILE


def _read_cursors() -> dict:
    """Reaction -> next variant index. Empty (all 'a') on any
    failure; out-of-range or non-integer values are ignored."""
    try:
        if not os.path.exists(VARIANT_STATE_FILE):
            return {}
        with open(VARIANT_STATE_FILE, "r") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        cursors = {}
        for name, idx in data.items():
            if name in REACTIONS:
                try:
                    cursors[name] = int(idx) % len(VARIANTS)
                except (TypeError, ValueError):
                    continue
        return cursors
    except Exception:
        return {}


def _write_cursors(cursors: dict) -> None:
    """Persist the cursor map. Best-effort; callers hold
    _reaction_lock."""
    try:
        os.makedirs(os.path.dirname(VARIANT_STATE_FILE), exist_ok=True)
        with open(VARIANT_STATE_FILE, "w") as f:
            json.dump(cursors, f)
    except Exception:
        pass


def current_variant(name: str) -> str:
    """The variant letter to render for a reaction right now. Does
    NOT advance the cursor — the renderer peeks, the scheduler
    advances after the post is scheduled. Unknown names yield 'a'."""
    if name not in REACTIONS:
        return VARIANTS[0]
    with _reaction_lock:
        idx = _read_cursors().get(name, 0)
    return VARIANTS[idx % len(VARIANTS)]


def advance_variant(name: str) -> None:
    """Move a reaction's cursor to the next variant. Called only
    when a post with that reaction is scheduled. Unknown names are
    ignored."""
    if name not in REACTIONS:
        return
    with _reaction_lock:
        cursors = _read_cursors()
        cursors[name] = (cursors.get(name, 0) + 1) % len(VARIANTS)
        _write_cursors(cursors)


def reset_variant_cursors(clear_file: bool = True) -> None:
    """Reset all cursors to 'a'. Tests only; clear_file=False keeps
    the state file (simulates a restart)."""
    if clear_file:
        with _reaction_lock:
            _write_cursors({})
