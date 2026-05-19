import random

# ─────────────────────────────────────────────
# HOOKS
# Observable behavior. Short. Mild curiosity only.
# ─────────────────────────────────────────────

HOOKS = {
    "HOT": [
        "volume increased while price stayed flat.",
        "activity picked up around current levels.",
        "more volume than the price move suggests.",
        "price held range, volume kept coming in.",
        "volume picked up without a clear catalyst.",
        "activity higher than recent sessions.",
        "volume staying elevated at current levels.",
        "trade activity increased this session.",
    ],
    "GAINERS": [
        "price moved higher, volume stayed active.",
        "stronger move than recent sessions.",
        "momentum held through the session.",
        "price moved and held the gain.",
        "clean move with participation.",
        "volume confirmed the move up.",
        "buyers stayed active after the initial push.",
        "price moved, interest didn't drop off.",
    ],
    "LOSERS": [
        "price pulled back with volume behind it.",
        "selling pressure remained through the session.",
        "price declined steadily this session.",
        "momentum weakened into the close.",
        "consistent selling pressure today.",
        "price dropped with active participation.",
        "volume followed the move down.",
        "decline continued without a clear bounce.",
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
        "volume increased ahead of any price move.",
        "activity picked up before price responded.",
        "volume behavior changed before price did.",
        "trade flow increased without a visible reason.",
        "activity up slightly, price hasn't moved yet.",
        "more volume than expected for a quiet session.",
        "volume shifted before chart structure changed.",
        "early activity increase, price still flat.",
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
        "buyers appear active near current price.",
        "dips seem to be getting absorbed.",
        "demand looks steady at these levels.",
        "price is holding while buying activity continues.",
        "consistent buying activity near support, still early.",
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
        "price is pressing against a recent level.",
        "range looks compressed over the last few sessions.",
        "consolidation near a key area, still early.",
        "price is sitting near a decision point.",
        "range tightening — may resolve soon.",
    ],
    "divergence": [
        "volume and price appear to be moving differently.",
        "price looks stable but volume is increasing.",
        "participation seems inconsistent with the price action.",
        "volume behavior doesn't fully match the chart.",
        "price and activity may not be aligned.",
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
    "still early.",
    "needs follow-through.",
    "worth monitoring from here.",
    "too early to confirm.",
    "watching for continuation.",
    "no clear direction yet.",
    "will need more sessions to confirm.",
    "early stage — monitoring.",
]

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

