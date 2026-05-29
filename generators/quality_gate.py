# generators/quality_gate.py
import re

# Patterns that indicate reasoning/planning (HARUS ditolak)
REJECT_PATTERNS = [
    r"(?i)^(okay|alright|sure|let's|let me|i need|i will|i'm going|first,|so,|now,)",
    r"(?i)(let me (think|draft|write|craft|analyze|see|check|try))",
    r"(?i)(i need to (write|create|craft|produce|make|do))",
    r"(?i)(the user (wants|asked|gave|provided|said))",
    r"(?i)^draft",
    r"(?i)^let's see",
    r"(?i)^wait[, ]",
    r"(?i)^the user",
    r"(?i)\(example says\)",
]

# Track recent posts for similarity check
_recent_posts = []


def is_reasoning_leak(content: str) -> bool:
    """Check if content contains reasoning/planning language."""
    if not content:
        return True

    content_lower = content.lower().strip()

    # Check first 400 chars for rejection patterns
    first_part = content_lower[:400]
    for pattern in REJECT_PATTERNS:
        if re.search(pattern, first_part):
            return True

    # Valid if starts with $SYMBOL
    if content_lower.startswith('$'):
        return False

    valid_starts = [
        # generic
        'volume', 'price', 'the', 'a', 'an', 'this', 'that', 'these',
        'watching', 'tracking', 'worth', 'market', 'crypto', 'token',
        # market behavior
        'activity', 'momentum', 'sellers', 'buyers', 'trade', 'flow',
        'early', 'low', 'more', 'some', 'strong', 'clean', 'no',
        'buying', 'selling', 'dip', 'pump', 'dump', 'bleed',
        'green', 'red', 'flat', 'range', 'move', 'session',
        # tradfi / sector
        'chip', 'gold', 'oil', 'equity', 'sector', 'commodities',
        # observation openers
        'holding', 'declining', 'rising', 'down', 'up', 'mixed',
        'consistent', 'notable', 'unusual', 'relative',
        'bid', 'ask', 'spread', 'order', 'book', 'depth',
        'resistance', 'support', 'break', 'reject', 'test',
        'entry', 'exit', 'position', 'size', 'risk',
    ]

    first_word = content_lower.split()[0] if content_lower.split() else ''
    if first_word in valid_starts:
        return False

    # Short alphanumeric word — likely a token name or valid opener
    if len(first_word) <= 10 and re.match(r'^[a-z]+$', first_word):
        return False

    return True


def validate_post(content: str) -> tuple[bool, str]:
    """Validate post content."""
    if not content:
        return False, "Empty content"

    # Keep reasoning leak check (most important)
    if is_reasoning_leak(content):
        return False, "Reasoning leak detected"

    # Minimum length (relaxed)
    if len(content) < 250:
        return False, "Content too short"

    # Relax: allow more line breaks (post panjang bisa punya banyak)
    # if content.count('\n\n') > 5:
    #     return False, "Too many line breaks"  # DISABLED

    # Relax: allow posts without perfect punctuation
    # cleaned = content.rstrip('\n').strip()
    # if cleaned and cleaned[-1] not in '.!?':
    #     return False, "Post ends mid-sentence (incomplete)"  # DISABLED

    return True, content


def finalize_post(content: str, symbol: str) -> str:
    """Final cleanup and add symbol if missing."""
    content = content.strip()

    # Remove existing $SYMBOL at very beginning (if any)
    if content.startswith(f'${symbol}'):
        content = content[len(f'${symbol}'):].lstrip()
        content = re.sub(r'^[.,\s]+', '', content)

    # Prepend $SYMBOL
    content = f"${symbol} " + content

    # Fix double spaces
    content = re.sub(r' {2,}', ' ', content)

    # Collapse excessive newlines
    content = re.sub(r'\n{3,}', '\n\n', content)

    # Normalize trailing punctuation
    content = re.sub(r'\.\s*$', '.', content)

    return content


def is_similar_to_recent(content: str, threshold: float = 0.85) -> bool:
    """Check if content is too similar to recent posts."""
    if not _recent_posts:
        return False

    words = set(content.lower().split())
    for prev in _recent_posts[-5:]:
        prev_words = set(prev.lower().split())
        if not words or not prev_words:
            continue
        intersection = words.intersection(prev_words)
        similarity = len(intersection) / max(len(words), len(prev_words))
        if similarity > threshold:
            return True
    return False


def record_post(content: str):
    """Add post to history."""
    _recent_posts.append(content)
    if len(_recent_posts) > 20:
        _recent_posts.pop(0)

