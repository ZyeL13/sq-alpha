# generators/quality_gate.py
import re
from generators.style_guard import validate_post_style, record_post

# Existing patterns (keep from before)
REJECT_PATTERNS = [
    r"(?i)^(okay|alright|sure|let's|let me|i need|i will|i'm going|first,|so,|now,|the user)",
    r"(?i)(let me (think|draft|write|craft|analyze|see|check|try))",
    r"(?i)(i need to (write|create|craft|produce|make|do))",
    r"(?i)(the user (wants|asked|gave|provided|said))",
    r"(?i)^draft",
    r"(?i)^let's see",
]

VALID_STARTS = [
    "$", "volume", "price", "the", "a", "this", "that", "these", "those",
    "watching", "tracking", "worth", "market", "crypto", "token", "chart",
    "something", "someone", "nobody", "everyone",
]

def is_reasoning_leak(content: str) -> bool:
    if not content:
        return True
    
    content_lower = content.lower().strip()
    first_part = content_lower[:300]
    
    for pattern in REJECT_PATTERNS:
        if re.search(pattern, first_part):
            return True
    
    first_line = content.split('\n')[0].strip().lower()
    if len(first_line) > 100:
        return True
    
    if first_line.startswith(('okay', 'alright', 'sure', 'let me', 'i need', 'based on')):
        return True
    
    paragraphs = content.split('\n\n')
    if len(paragraphs) < 2:
        return True
    
    if len(content) < 50:
        return True
    
    return False


def validate_post(content: str) -> tuple[bool, str]:
    """
    Full validation including reasoning leak, style, and similarity
    """
    if not content:
        return False, "Empty content"
    
    # Check for reasoning leak
    if is_reasoning_leak(content):
        return False, "Reasoning leak detected"
    
    # Check style (banned phrases, generic patterns, similarity)
    valid, msg = validate_post_style(content)
    if not valid:
        return False, msg
    
    return True, content


def finalize_post(content: str, symbol: str) -> str:
    """Apply final cleanup and record post"""
    content = content.strip()
    
    # Ensure symbol is present
    if f"${symbol}" not in content:
        content = f"${symbol}. " + content
    
    # Record for similarity check
    record_post(content)
    
    return content
