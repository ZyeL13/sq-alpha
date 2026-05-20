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

# Track recent posts for similarity check (simple version)
_recent_posts = []


def is_reasoning_leak(content: str) -> bool:
    """Check if content contains reasoning/planning language."""
    if not content:
        return True
    
    content_lower = content.lower().strip()
    
    # Check first 200 chars for rejection patterns
    first_part = content_lower[:400]
    for pattern in REJECT_PATTERNS:
        if re.search(pattern, first_part):
            return True
    
    # Valid if starts with $SYMBOL (like $lunc, $btc)
    if content_lower.startswith('$'):
        return False
    
    # Valid if starts with common crypto observation starters
    valid_starts = [
        'volume', 'price', 'the', 'a', 'this', 'that', 'these',
        'watching', 'tracking', 'worth', 'market', 'crypto', 'token',
        'dip', 'pump', 'dump', 'bleed',
        'green', 'red',
    ]
    first_word = content_lower.split()[0] if content_lower.split() else ''
    if first_word in valid_starts:
        return False
    
    # If first word is short alphanumeric (like "lunc"), might be valid
    if len(first_word) <= 10 and re.match(r'^[a-z]+$', first_word):
        return False
    
    # Default: if first word is not in valid list and not a symbol, reject
    return True


def validate_post(content: str) -> tuple[bool, str]:
    """Validate post content."""
    if not content:
        return False, "Empty content"
    
    # Reject reasoning leak
    if is_reasoning_leak(content):
        return False, "Reasoning leak detected"
    
    # Reject if too short
    if len(content) < 30:
        return False, "Content too short"
    
    # Reject if too many newlines (empty paragraphs)
    if content.count('\n\n') > 5:
        return False, "Too many line breaks"
    
    if content and not content.rstrip().endswith(('.', '!', '?')):
        return False, "Post ends mid-sentence (incomplete)"
    
    return True, content


def finalize_post(content: str, symbol: str) -> str:
    """Final cleanup and add symbol if missing."""
    content = content.strip()
    
    # Remove existing $SYMBOL at very beginning (if any)
    if content.startswith(f'${symbol}'):
        # Remove the $SYMBOL from start, keep the rest
        content = content[len(f'${symbol}'):].lstrip()
        # Remove leading dot, space, comma
        content = re.sub(r'^[.,\s]+', '', content)
    
    # Ensure symbol is present at beginning (clean)
    content = f"${symbol} " + content
    
    # Fix double spaces
    content = re.sub(r' {2,}', ' ', content)
    
    # Remove multiple consecutive newlines
    content = re.sub(r'\n{3,}', '\n\n', content)
    
    # Ensure last character is not lonely punctuation
    content = re.sub(r'\.\s*$', '.', content)
    
    return content


def is_similar_to_recent(content: str, threshold: float = 0.7) -> bool:
    """Check if content is too similar to recent posts."""
    if not _recent_posts:
        return False
    
    words = set(content.lower().split())
    for prev in _recent_posts[-5:]:  # Check last 5 posts
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
