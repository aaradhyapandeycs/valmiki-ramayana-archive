"""Source-preserving line presentation for the Sanskrit and IAST reader."""

from html import escape
import re


DIGITS = r"[0-9०-९]"
REFERENCE = (
    rf"{DIGITS}{{1,2}}\s*[-–]\s*{DIGITS}{{1,3}}\s*[-–]\s*{DIGITS}{{1,3}}"
    rf"(?:\s*[-–]\s*{DIGITS}{{1,3}})?"
)
CLOSING_ROW = re.compile(rf"\s*(?:(?:[|।॥]\s*)+(?:{REFERENCE})?|{REFERENCE})\s*")


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
        if not start <= offset < len(text) or text[offset] != "\n":
            raise ValueError(f"Invalid source line break offset {offset}")
        yield text[start:offset], "\n"
        start = offset + 1
    yield text[start:], ""


def render_lines(text, break_offsets=None):
    """Render nonwrapping intended rows, preserving the literal source text."""
    return "".join(f'<span class="verse-line">{escape(row)}</span>{separator}'
                   for row, separator in line_segments(text, break_offsets))


def corresponding_breaks(source, transliteration, source_offsets):
    """Transfer breaks by newline ordinal because IAST may change row lengths."""
    indices = [index for index, char in enumerate(source) if char == "\n"]
    roman_indices = [index for index, char in enumerate(transliteration) if char == "\n"]
    if len(indices) != len(roman_indices):
        raise ValueError("IAST changed the source newline count")
    translations = dict(zip(indices, roman_indices))
    return [translations[index] for index in source_offsets]
