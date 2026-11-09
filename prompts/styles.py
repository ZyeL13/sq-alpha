import random

# ─────────────────────────────────────────────
# HOOKS
# Data-first. Fewer generic statements.
# ─────────────────────────────────────────────

HOOKS = {
    "HOT": [
        "volume expanded faster than price reacted.",
        "activity jumped while price stayed near current levels.",
        "participation increased without a major breakout.",
        "volume expanded during the session.",
        "activity increased alongside the move.",
        "price and volume changed together.",
        "trading activity remained active.",
        "volume remained a notable part of the session.",
        "volume picked up without a clear catalyst.",
        "more activity than the price move suggests.",
        "participation higher than the chart shows.",
        "volume running ahead of price.",
        "quiet move, but volume wasn't quiet.",
        "price barely moved. volume did.",
        "session activity above recent average.",
    ],

    "GAINERS": [
        "strong move with volume confirmation.",
        "volume stayed elevated after the move.",
        "this rally attracted more participation than recent attempts.",
        "buyers remained active after the initial move.",
        "price advanced while volume continued expanding.",
        "price continued higher during the session.",
        "volume accompanied the advance.",
        "activity remained active during the move.",
        "price and volume expanded together.",
        "the move continued through the session.",
        "move held. volume stayed with it.",
        "buyers didn't leave after the initial push.",
        "price didn't give back much of the gain.",
        "follow-through looks intact so far.",
        "the advance attracted actual participation.",
    ],

    "LOSERS": [
        "drop accelerated despite relatively light volume.",
        "buyers have yet to respond aggressively.",
        "selling pressure remained active throughout the session.",
        "volume expanded while price continued lower.",
        "the pullback attracted more activity than usual.",
        "price continued lower during the session.",
        "volume accompanied the decline.",
        "the move remained tilted to the downside.",
        "activity continued as price moved lower.",
        "price extended the decline during trading.",
        "sellers showed up consistently through the session.",
        "no real bounce attempt yet.",
        "price kept sliding without much resistance.",
        "volume didn't spike, but selling was steady.",
        "the dip wasn't bought quickly.",
        "lower, with volume confirming the direction.",
    ],

    "ALPHA": [
        "volume expanded faster than price reacted.",
        "volume expanded while price stayed mostly unchanged.",
        "interest increased despite limited price movement.",
        "volume moved. price didn't follow yet.",
        "activity picked up in a quiet token.",
        "volume ahead of price, still early.",
        "low cap, measurable volume change.",
        "interest showing up before price reacts.",
        "volume building without a news catalyst.",
        "something shifted in participation.",
        "not a big move, but volume is worth watching.",
    ],

    "NEW": [
        "early trading is establishing the initial range.",
        "price discovery remains in progress.",
        "volume is beginning to establish a baseline.",
        "the first trading sessions remain active.",
        "first sessions are still setting the range.",
        "early volume establishing initial interest levels.",
        "price finding its level in early trading.",
        "participation is building from a low base.",
        "still too early to read the direction.",
        "initial range hasn't broken convincingly yet.",
    ],

    "SIGNAL": [
        "activity increased before price reacted meaningfully.",
        "volume expanded ahead of the move.",
        "participation changed before the chart followed.",
        "activity picked up inside a relatively quiet range.",
    ],
}

HOOKS_COMMENTARY = {
    "COMMENTARY": [
        "semis diverging while mega-cap tech cools.",
        "crypto volume up, price reaction mixed.",
        "rotation looks sector-specific, not broad.",
        "macro data landed, market response was muted.",
        "correlation between BTC and altcoins breaking down this session.",
        "risk appetite looks selective today.",
        "vol up across the board but leaders and laggards swapped.",
        "this kind of divergence usually resolves within a few sessions.",
    ],
    "OPINION": [
        "worth asking: rotation or temporary noise?",
        "is this a sector shift or just a noisy session?",
        "one of those days where the data and the narrative don't match.",
        "volume says one thing, price says another.",
        "not obvious which way this resolves.",
        "the move looks real, follow-through is the question.",
    ],
}

# ─────────────────────────────────────────────
# ANGLES
# Observable interpretation only. Low-confidence language required.
# Use: may, appears, looks, seems, still early
# ─────────────────────────────────────────────

ANGLES = {
    "anomaly": [
        "volume accompanied the move.",
        "trading activity remained active during the session.",
        "price moved alongside measurable volume.",
        "the move occurred with substantial trading activity.",
    ],

    "divergence": [
        "price and volume did not expand at the same pace.",
        "volume changed more noticeably than price.",
        "activity shifted while price remained relatively contained.",
        "price and volume showed different rates of change.",
    ],
    "momentum": [
        "buyers absorbed the move without much pushback.",
        "price held after the initial move, sellers didn't follow through.",
        "the advance didn't reverse quickly, which may suggest demand is real.",
        "volume stayed with the move rather than fading after the initial push.",
        "sellers haven't been able to push price back to where it started.",
        "price isn't giving back the gain at the same pace it was made.",
    ],
    "hesitation": [
        "the move happened, but follow-through is still unclear.",
        "volume and price aren't telling the same story yet.",
        "price moved, but participation didn't expand in proportion.",
        "activity picked up but didn't sustain at the same level.",
        "the reaction looks smaller than the volume might suggest.",
        "neither buyers nor sellers have committed aggressively yet.",
    ],
}

ANGLES_COMPARISON = {
    "comparison": [
        "$TOKEN_A up {chg_a}% while $TOKEN_B moved only {chg_b}%.",
        "$TOKEN_A outperforming $TOKEN_B by a notable margin this session.",
        "$TOKEN_A volume significantly higher than $TOKEN_B despite similar price moves.",
        "momentum in $TOKEN_A appears stronger than $TOKEN_B so far.",
        "$TOKEN_A holding gains while $TOKEN_B pulled back.",
    ],
}
# ─────────────────────────────────────────────
# CTA
# Click encouragement only. No hype, no calls.
# ─────────────────────────────────────────────

CTA_VARIANTS = [
    "tracking ${symbol}.",
    "watching ${symbol}.",
    "${symbol} on watchlist.",
    "monitoring ${symbol}.",
]

# ─────────────────────────────────────────────
# TRANSITIONS
# Use rarely. Factual connectors only.
# ─────────────────────────────────────────────

TRANSITIONS = [
    "worth noting:",
    "for context:",
    "key detail:",
]

# ─────────────────────────────────────────────
# CLOSERS
# Neutral. No edge, no persona.
# ─────────────────────────────────────────────

CLOSERS = [
    "the next few sessions should clarify the move.",
    "follow-through matters from here.",
    "still needs confirmation from price action.",
    "worth watching if activity stays elevated.",
    "momentum looks active for now.",
    "price remains at current levels.",
    "the move is still developing.",
    "activity remains in focus.",
    "trading remains active.",
    "the session is still unfolding.",

]

ANGLES.update(ANGLES_COMPARISON)
# ─────────────────────────────────────────────
# GETTERS
# ─────────────────────────────────────────────

def get_hook(category: str) -> str:
    return random.choice(HOOKS.get(category, HOOKS["HOT"]))

def get_angle(angle_type: str = None) -> str:
    if angle_type and angle_type in ANGLES:
        return random.choice(ANGLES[angle_type])
    pool = [line for values in ANGLES.values() for line in values]
    return random.choice(pool)

def get_cta(symbol: str) -> str:
    return random.choice(CTA_VARIANTS).replace("${symbol}", f"${symbol}")

def get_transition(probability: float = 0.2) -> str:
    if random.random() > probability:
        return ""
    return random.choice(TRANSITIONS)

from config import CLOSER_ENABLED
def get_closer(probability: float = 0.3) -> str:
    if not CLOSER_ENABLED:
        return ""
    if random.random() > probability:
        return ""
    return random.choice(CLOSERS)

# Helper untuk comparison posts (butuh 2 tokens)
def get_comparison_hook(symbol_a: str, chg_a: float, symbol_b: str, chg_b: float) -> str:
    import random
    templates = [
        f"${symbol_a} +{chg_a:.1f}% while ${symbol_b} moved only +{chg_b:.1f}%.",
        f"${symbol_a} outperforming ${symbol_b} by a wide margin today.",
        f"${symbol_a} and ${symbol_b} diverging, same sector, different tape.",
        f"${symbol_a} moved. ${symbol_b} didn't follow.",
    ]
    return random.choice(templates)

# ========== GETTERS (additions) ==========

# Track recent posts for similarity check
recent_posts = []


def generate_data_anchor(symbol: str, price: float, change_24h: float, volume_24h: float) -> str:
    """Generate a factual data anchor with real numbers."""
    vol_m = volume_24h / 1_000_000
    
    # Format price sesuai range
    if price < 0.001:
        price_str = f"{price:.7f}"
    elif price < 1:
        price_str = f"{price:.4f}"
    else:
        price_str = f"{price:.2f}"
    
    templates = [
        f"${symbol} at ${price_str}, {change_24h:+.1f}% with ${vol_m:.1f}M volume.",
        f"${symbol} moved {change_24h:+.1f}% to ${price_str}, volume ${vol_m:.1f}M.",
        f"${symbol} ${vol_m:.1f}M volume, price ${price_str}, {change_24h:+.1f}%.",
        f"${symbol} {change_24h:+.1f}% on ${vol_m:.1f}M volume, price ${price_str}.",
        f"${symbol} at ${price_str}, volume ${vol_m:.1f}M, {change_24h:+.1f}%.",
        f"${symbol} {change_24h:+.1f}%, ${vol_m:.1f}M traded, price ${price_str}.",
        f"price ${price_str}, ${vol_m:.1f}M volume, ${symbol} {change_24h:+.1f}%.",
    ]
    return random.choice(templates)


def is_too_similar(new_post: str, threshold: float = 0.7) -> bool:
    """Check if new_post is too similar to recent posts using Jaccard similarity."""
    if not recent_posts:
        return False

    new_words = set(new_post.lower().split())
    if not new_words:
        return False

    for prev in recent_posts:
        prev_words = set(prev.lower().split())
        if not prev_words:
            continue
        intersection = len(new_words & prev_words)
        union = len(new_words | prev_words)
        similarity = intersection / union if union > 0 else 0
        if similarity > threshold:
            return True
    return False


def add_to_recent(post: str) -> None:
    """Add post to recent_posts, keep max 10 entries."""
    recent_posts.append(post)
    if len(recent_posts) > 10:
        recent_posts.pop(0)


# ========== EDITORIAL v2 — VOICE CALIBRATION ==========
# Few-shot calibration for SQ-Alpha, The Skeptical Market Observer.
# Learn the VOICE below, not the sentence structure: the examples
# illustrate tone, stance and restraint. Do not copy their paragraph
# shape, length, or phrasing from post to post — a model that
# memorizes the examples produces the same template problem this
# calibration exists to prevent.
# =========================================================

VOICE_CALIBRATION = """
VOICE CALIBRATION — learn the voice, not the sentence structure.
The examples below show tone, stance and restraint. Vary paragraph
shape and length every time; never reproduce an example's structure.

POSITIVE EXAMPLES

1. Analytical Take
$SOL is recovering, but the volume tells a less convincing story. Buyers are showing up, just not aggressively enough to call this a trend reversal. Price improvement is welcome. Confirmation would be better.

2. Contrarian View
Everyone seems focused on the breakout, but the more interesting question is whether buyers can sustain it. A breakout without follow-through is just an expensive way to create excitement.

3. Dry Humor
$BTC moved 2% and crypto Twitter suddenly discovered macroeconomics again. The move is real. The explanations arriving five minutes later deserve a little more skepticism.

4. Data Observation
$XYZ traded $180M in the last 24 hours — roughly 3x its recent average — while price moved less than 1%. Volume at this level with price going nowhere is the anomaly, not the price itself. Either buyers are absorbing supply, or sellers are distributing into strength. The tape will say which, probably within a session or two.

NEGATIVE EXAMPLES

1. Forced Contrarianism
BAD: "Actually, everyone is wrong about $BTC. The market is completely misunderstanding what's happening."
WHY: Disagrees without evidence. Creates artificial controversy.

2. Fake Intellectualism
BAD: "Most traders simply don't understand the deeper mechanics behind this market structure."
WHY: Condescending, vague and unsupported.

3. Forced Sarcasm
BAD: "Another genius breakout prediction from crypto experts. Surely nothing can go wrong."
WHY: Sarcasm replaces analysis instead of supporting it.

4. Manufactured Conviction
BAD: "$SOL is obviously going lower. Anyone expecting a recovery is ignoring reality."
WHY: Overstates certainty and dismisses alternative interpretations.

CALIBRATION RULES
- Skepticism does not require disagreement.
- Contrarian opinions must identify specific evidence.
- Humor must be occasional, relevant and secondary to analysis.
- Never manufacture controversy to attract engagement.
- Never imply superior intelligence over the audience.
- If market evidence supports the consensus, acknowledge it.
- Neutrality is acceptable when evidence is inconclusive.
- Prefer an honest observation over an impressive-sounding conclusion.
"""

# Phrases the editorial quality gate rejects. These are the template
# habits Editorial v2 exists to kill, plus the hype phrases the
# system prompt already forbids. Matched case-insensitively.
EDITORIAL_FORBIDDEN = [
    "watching from here",
    "monitoring the session",
    "market participants are closely watching",
    "only time will tell",
    "tracking the move",
    "under the surface",
    "whispers",
    "hidden accumulation",
    "nobody is noticing",
    "smart money",
    "the tape says",
    "market sleeping",
    "secret signal",
    "quiet before the move",
    "surgical rotation",
    "shadow accumulation",
    "silent wallets",
    "insiders loading",
]

# Per-style guidance injected into the prompt. Short on purpose: the
# style name plus its job. The voice itself comes from VOICE_CALIBRATION.
STYLE_GUIDANCE = {
    "analytical": (
        "ANALYTICAL TAKE (default). State what happened, why it matters, "
        "and what evidence would change the read. Calm, direct, no forced edge."
    ),
    "contrarian": (
        "CONTRARIAN VIEW. The tape contradicts the prevailing story. Name "
        "the story, show the specific evidence against it, and say what "
        "would prove the story right after all."
    ),
    "data_observation": (
        "DATA OBSERVATION. Let the numbers lead. One anomaly, stated plainly, "
        "with the comparison that makes it anomalous. No narrative dressing."
    ),
    "dry_humor": (
        "DRY HUMOR. One dry, observational line about an absurd market "
        "moment, then the analysis. Humor is secondary — never the whole post."
    ),
}


def _chg_since_news(token) -> "float | None":
    """Price change (%) between the news snapshot and now.

    Returns None when there is no catalyst or no usable snapshot, so
    callers never treat a missing snapshot as a 0% move.
    """
    if not token.get("news_catalyst"):
        return None
    price_then = token.get("price_at_news", 0) or 0
    price_now = token.get("price", 0) or 0
    if not price_then or not price_now:
        return None
    return (price_now - price_then) / price_then * 100


def _vol_chg_since_news(token) -> "float | None":
    """Volume change (%) between the news snapshot and now, or None."""
    if not token.get("news_catalyst"):
        return None
    vol_then = token.get("volume_at_news", 0) or 0
    vol_now = token.get("volume_24h", 0) or 0
    if not vol_then or not vol_now:
        return None
    return (vol_now - vol_then) / vol_then * 100


def _anomaly(token, scores=None) -> float:
    """Anomaly signal in 0..1. Prefers the pipeline's own anomaly score
    when the caller passes scores; otherwise mirrors the same thresholds
    from the raw fields (see processors/score.py anomaly_score)."""
    if scores:
        value = scores.get("anomaly")
        if value is not None:
            return float(value)
    vol = token.get("volume_24h", 0) or 0
    chg = abs(token.get("price_change_percent", 0) or 0)
    if vol > 100_000_000 and chg < 1.0:
        return 0.9
    if vol > 50_000_000 and chg < 2.0:
        return 0.7
    if vol > 10_000_000 and chg < 3.0:
        return 0.5
    if vol < 1_000_000 and chg > 10:
        return 0.8
    return 0.2


def select_editorial_style(token, scores=None) -> str:
    """Pick the editorial style from the token's own data — never a draw.

    Deterministic priority, first match wins:
    1. data_observation — a real anomaly: anomaly score >= 0.7, or
       volume moved >= 50% since the news landed.
    2. contrarian — the tape since the catalyst contradicts the day's
       story: price moved >= 3% one way since the news while the 24h
       change is >= 3% the other way.
    3. dry_humor — a phenomenon worth satirizing: a >= 15% move with no
       catalyst at all, or a >= 10% move that ended mid-range (a big
       session that went nowhere).
    4. analytical — the default when nothing above applies.

    Randomisation is only for delivery variation, never for this choice.
    """
    chg = token.get("price_change_percent", 0) or 0
    has_news = bool(token.get("news_catalyst"))
    range_pos = token.get("range_position", 0.5)

    vol_chg_news = _vol_chg_since_news(token)
    if _anomaly(token, scores) >= 0.7:
        return "data_observation"
    if vol_chg_news is not None and abs(vol_chg_news) >= 50:
        return "data_observation"

    chg_news = _chg_since_news(token)
    if chg_news is not None and abs(chg_news) >= 3 and abs(chg) >= 3:
        if (chg_news > 0) != (chg > 0):
            return "contrarian"

    if not has_news and abs(chg) >= 15:
        return "dry_humor"
    if abs(chg) >= 10 and 0.3 <= range_pos <= 0.7:
        return "dry_humor"

    return "analytical"


def insufficient_insight(token, scores=None) -> "str | None":
    """Quality-over-quota pre-check, run before any LLM call.

    Returns a short skip reason, or None when the token is worth a post.
    The bar is deliberately low: a real move, a catalyst, or a notable
    volume story is enough. Only genuinely empty tapes are skipped —
    never skip just because the move is small or the market is boring;
    a short honest post beats no post, and a boring market is itself
    an observation for the analytical style.
    """
    price = token.get("price", 0) or 0
    vol = token.get("volume_24h", 0) or 0
    if price <= 0 or vol <= 0:
        return "no_valid_data"

    chg = abs(token.get("price_change_percent", 0) or 0)
    range_pos = token.get("range_position", 0.5)
    has_news = bool(token.get("news_catalyst"))
    if (
        not has_news
        and chg < 1.0
        and 0.3 <= range_pos <= 0.7
        and _anomaly(token, scores) < 0.5
        and vol < 10_000_000
    ):
        return "no_observation"

    return None
