import random

# ─────────────────────────────────────────────
# HOOKS
# Observable behavior. Short. Mild curiosity only.
# ─────────────────────────────────────────────

HOOKS = {
    "HOT": [
        "volume increased faster than price moved.",
        "activity stayed elevated throughout the session.",
        "price stayed relatively stable despite heavier trading.",
        "participation increased without a major breakout.",
        "volume remained active near current levels.",
    ],
    "GAINERS": [
        "price pushed higher and volume stayed active afterward.",
        "most short-term spikes lose participation quickly. this one didn't.",
        "buyers stayed involved after the initial move.",
        "the move extended without volume fading immediately.",
        "price moved quickly, but activity stayed elevated.",
    ],
    "LOSERS": [
        "selling pressure stayed active through the session.",
        "price continued lower without much relief buying.",
        "the pullback extended with steady volume behind it.",
        "buyers haven't stepped in aggressively yet.",
    ],
    "ALPHA": [
        "low volume name seeing more activity than usual.",
        "trade activity picked up on a quiet chart.",
        "volume increased on a name with little recent action.",
        "more activity here than the past few sessions.",
        "relatively quiet chart, but volume is moving.",
        "activity increased without a visible catalyst.",
        "volume up on a name that's been inactive.",
        "some interest forming in a low-attention token.",
    ],
    "NEW": [
        "early trading is setting the initial range.",
        "first sessions are live.",
        "price discovery is still in early stages.",
        "initial volume is establishing the baseline.",
        "new listing — watching early session behavior.",
        "range is still being established.",
        "early sessions are still active.",
        "no prior reference points yet.",
    ],
    "SIGNAL": [
        "activity picked up before price reacted meaningfully.",
        "volume started increasing ahead of the move.",
        "participation changed before the chart did.",
        "trading activity increased around a quiet range.",
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
        "the move looks real — follow-through is the question.",
    ],
}

# ─────────────────────────────────────────────
# ANGLES
# Observable interpretation only. Low-confidence language required.
# Use: may, appears, looks, seems, still early
# ─────────────────────────────────────────────

ANGLES = {
    "anomaly": [
        "volume appears higher than the price move justifies.",
        "trade activity looks elevated relative to recent sessions.",
        "volume-to-price ratio seems unusual for this range.",
        "activity may be higher than the chart suggests.",
        "flow looks stronger than the move warrants.",
    ],
    "accumulation": [
        "buying activity stayed consistent after the initial move.",
        "dips continued finding buyers during the session.",
        "volume remained active even after the first breakout.",
        "buyers continued showing up near current levels.",
    ],
    "relative_strength": [
        "holding better than similar tokens this session.",
        "appears more stable than comparable names.",
        "price is holding while others pull back.",
        "outperforming nearby names so far.",
        "looks relatively resilient compared to the sector.",
    ],
    "underreaction": [
        "price reaction looks smaller than expected.",
        "market response seems limited so far.",
        "move may not be fully priced in yet.",
        "reaction appears muted relative to the event.",
        "price hasn't moved much despite the news.",
    ],
    "distribution": [
        "upside appears to be meeting selling pressure.",
        "rallies seem to be getting sold into.",
        "supply looks visible near current levels.",
        "price pushes higher appear to be fading.",
        "sellers seem active above current price.",
    ],
    "capitulation": [
        "selling pace appears to be slowing.",
        "downside momentum looks less aggressive.",
        "volume on the way down seems to be declining.",
        "selling pressure may be easing.",
        "fewer sellers appear to be showing up at these levels.",
    ],
    "breakout_watch": [
        "price is approaching a level that previously rejected momentum.",
        "the current range may be close to resolving.",
        "recent sessions have compressed into a tighter range.",
        "momentum is building near a recent breakout area.",
    ],
    "divergence": [
        "price and participation are moving at different speeds.",
        "activity looks stronger than the chart alone suggests.",
        "volume expanded more aggressively than price.",
        "participation increased without a full breakout yet.",
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

def get_closer(probability: float = 0.3) -> str:
    if random.random() > probability:
        return ""
    return random.choice(CLOSERS)

# Helper untuk comparison posts (butuh 2 tokens)
def get_comparison_hook(symbol_a: str, chg_a: float, symbol_b: str, chg_b: float) -> str:
    import random
    templates = [
        f"${symbol_a} +{chg_a:.1f}% while ${symbol_b} moved only +{chg_b:.1f}%.",
        f"${symbol_a} outperforming ${symbol_b} by a wide margin today.",
        f"${symbol_a} and ${symbol_b} diverging — same sector, different tape.",
        f"${symbol_a} moved. ${symbol_b} didn't follow.",
    ]
    return random.choice(templates)
