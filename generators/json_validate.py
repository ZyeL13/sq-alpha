"""Tolerant JSON parsing + validation for short-form draft replies.

Step 1 (editorial revision, spec §2.3): `generate_post` returns a JSON
object `{"event", "fact", "interpretation", "angle", "post"}`; this
module parses the raw LLM reply and validates the parsed object
(steps 2-5: fields, angle echo, cashtag-first, number check,
forbidden phrases). Parse failure is signalled by `parse_json_reply`
returning None; the caller maps that to "json_invalid".

Number matching is imported from `processors.draft_scoring` (not
copied); the forbidden-phrase check from `generators.quality_gate`.
No imports from `llm` or the orchestrator: this module is imported by
`generators.post_generator`, so it must stay cycle-free.
"""
import json

from generators.quality_gate import has_editorial_violation
from processors.draft_scoring import (
    _match_cited,
    _token_numbers,
    find_unmatched_numbers,
)

# Re-exported for callers that build the snapshot numbers dict the
# same way the scorer does (also marks the imports as used for ruff).
__all__ = [
    "_match_cited",
    "_token_numbers",
    "find_unmatched_numbers",
    "parse_json_reply",
    "validate_draft_json",
]

REQUIRED_FIELDS = ("event", "fact", "interpretation", "angle", "post")


def _strip_fences(text: str) -> str:
    """Remove a surrounding markdown fence (```json ... ``` or
    ``` ... ```, also a lone leading/trailing fence)."""
    s = text.strip()
    if s.startswith("```"):
        s = s[3:].lstrip()
        if s.lower().startswith("json") and (
                len(s) == 4 or s[4] in " \t\r\n{"):
            s = s[4:].lstrip()
    if s.endswith("```"):
        s = s[:-3].rstrip()
    return s


def _first_json_object(text: str):
    """First balanced {...} block in `text`, parsed as a dict.

    Brace scan that respects string literals and backslash escapes.
    A block that does not parse is skipped and scanning continues
    after it; returns None when no block parses as a dict.
    """
    i = text.find("{")
    while i != -1:
        depth = 0
        in_string = False
        escaped = False
        j = i
        while j < len(text):
            ch = text[j]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[i:j + 1])
                    except ValueError:
                        obj = None
                    if isinstance(obj, dict):
                        return obj
                    break
            j += 1
        i = text.find("{", i + 1)
    return None


def parse_json_reply(text: str) -> dict | None:
    """Tolerant JSON extraction from an LLM reply.

    Strip markdown fences, try `json.loads` on the result; if that
    fails, extract the first balanced {...} block (prose around it is
    ignored). Returns the parsed object only when it is a dict, else
    None (unparseable text, or JSON that is not an object).
    """
    if not text or not isinstance(text, str):
        return None
    stripped = _strip_fences(text)
    try:
        obj = json.loads(stripped)
    except ValueError:
        return _first_json_object(stripped)
    return obj if isinstance(obj, dict) else None


def validate_draft_json(d, drawn_angle, numbers, symbol=None):
    """Validation steps 2-5 (spec §2.3), first failure wins.

    (a) dict with all five keys, all strings, post non-empty ->
        "json_missing_field"
    (b) angle == drawn_angle -> "angle_mismatch"
    (c) when `symbol` is given, post starts with f"${symbol}"
        (case-insensitive) -> "cashtag_not_first"
    (d) every unit-carrying number in post matches `numbers` ->
        "number_not_in_snapshot"
    (e) no editorial forbidden phrase -> "forbidden_phrase"
    Returns (True, None) when the draft passes all steps.
    """
    if not isinstance(d, dict):
        return (False, "json_missing_field")
    for key in REQUIRED_FIELDS:
        if key not in d or not isinstance(d[key], str):
            return (False, "json_missing_field")
    if not d["post"].strip():
        return (False, "json_missing_field")
    if d["angle"] != drawn_angle:
        return (False, "angle_mismatch")
    if symbol:
        if not d["post"].lstrip().lower().startswith(f"${symbol}".lower()):
            return (False, "cashtag_not_first")
    if find_unmatched_numbers(d["post"], numbers or {}):
        return (False, "number_not_in_snapshot")
    if has_editorial_violation(d["post"]) is not None:
        return (False, "forbidden_phrase")
    return (True, None)
