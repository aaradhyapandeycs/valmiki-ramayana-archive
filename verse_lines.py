"""Source-preserving line presentation for the Sanskrit and IAST reader."""

from hashlib import sha256
from html import escape
import re

from transliterate_iast import transliterate


DIGITS = r"[0-9०-९]"
REFERENCE = (
    rf"{DIGITS}{{1,2}}\s*[-–]\s*{DIGITS}{{1,3}}\s*[-–]\s*{DIGITS}{{1,3}}"
    rf"(?:\s*[-–]\s*{DIGITS}{{1,3}})?"
)
CLOSING_ROW = re.compile(rf"\s*(?:(?:[|।॥]\s*)+(?:{REFERENCE})?|{REFERENCE})\s*")
FORMAT_SPACE = re.compile(r"[\t\r\n\f \u00a0]+")
# Both archive script editions omit these cuts. The verse-layout notes record
# the witnesses used to confirm the cuts and the five similar bars kept inline.
FUSED_VERSE_BREAKS = {
    (2, 106, 35): (65, "9afa643327a9266fe9b3a3185672e7e7aea1dc8a216a3d1c04b1381fed39e179"),
    (4, 1, 18): (41, "9d19b71fc22f9ccfdf8e3f6dea7d12533df69a02cf56de7b854e2c5209b3bdb0"),
    (6, 48, 37): (70, "b31372ee480891ea07ee6b7c0cf774723044d9890c2932de2488a737825a268b"),
}


def reviewed_verse_breaks(text, offsets, book, chapter, verse):
    """Add a source-checked division if this is the exact reviewed verse text."""
    review = FUSED_VERSE_BREAKS.get((book, chapter, verse))
    if review is None:
        return offsets
    offset, source_sha = review
    if sha256(text.encode("utf-8")).hexdigest() != source_sha:
        raise ValueError(f"Reviewed line division needs rechecking at {book}.{chapter}.{verse}")
    return sorted({*offsets, offset})


def line_break_offsets(text):
    """Fallback break offsets from stored lines, attaching marker-only rows.

    Each offset points at an existing newline. Other source newlines stay
    inside the row so the browser collapses them as ordinary whitespace.
    """
    lines = text.split("\n")
    offset = 0
    breaks = []
    for current, following in zip(lines, lines[1:]):
        offset += len(current)
        if not CLOSING_ROW.fullmatch(following):
            breaks.append(offset)
        offset += 1
    return breaks


def line_segments(text, break_offsets=None):
    """Yield (row, separator) pairs whose concatenation exactly reconstructs text."""
    offsets = line_break_offsets(text) if break_offsets is None else break_offsets
    start = 0
    for offset in offsets:
        if not start <= offset < len(text):
            raise ValueError(f"Invalid source line break offset {offset}")
        has_whitespace = FORMAT_SPACE.fullmatch(text[offset])
        if not (has_whitespace or start < offset and text[offset - 1] == "|"):
            raise ValueError(f"Invalid source line break offset {offset}")
        end = offset + 1 if has_whitespace else offset
        yield text[start:offset], text[offset:end]
        start = end
    yield text[start:], ""


def render_lines(text, break_offsets=None):
    """Render nonwrapping intended rows, preserving the literal source text."""
    return "".join(f'<span class="verse-line">{escape(row)}</span>{separator}'
                   for row, separator in line_segments(text, break_offsets))


def corresponding_breaks(source, transliteration, source_offsets):
    """Transfer whitespace and reviewed zero-width divisions to generated IAST."""
    indices = [index for index, char in enumerate(source) if FORMAT_SPACE.fullmatch(char)]
    roman_indices = [index for index, char in enumerate(transliteration) if FORMAT_SPACE.fullmatch(char)]
    if len(indices) != len(roman_indices):
        raise ValueError("IAST changed the source whitespace count")
    translations = dict(zip(indices, roman_indices))
    roman_offsets = []
    for offset in source_offsets:
        if offset in translations:
            roman_offsets.append(translations[offset])
            continue
        if 0 < offset < len(source) and source[offset - 1] == "|":
            prefix = transliterate(source[:offset])
            if prefix and transliteration.startswith(prefix):
                roman_offsets.append(len(prefix))
                continue
        raise ValueError(f"Cannot align source line break offset {offset} with IAST")
    return roman_offsets
