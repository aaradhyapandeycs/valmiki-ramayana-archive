"""Render reviewed supplemental Sanskrit from the archived source pane."""
from collections import defaultdict
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re

from transliterate_iast import transliterate
from verse_lines import corresponding_breaks, line_break_offsets, render_lines


DATA = Path(__file__).with_name("data")
POSITIONS = {"Source invocation": {"before"}, "Source colophon": {"after"},
             "Source verse passage": {"before", "after"},
             "Source Gāyatrī Rāmāyaṇa appendix": {"after"}}
DEVANAGARI = re.compile(r"[\u0904-\u0939]")


def load_paratext(source_records):
    reviewed = json.loads((DATA / "sanskrit-paratext-reviewed.json").read_text(encoding="utf-8"))
    index = defaultdict(lambda: defaultdict(list))
    for key, entries in reviewed.items():
        slug, number = key.split("/")
        chapter = (slug, int(number))
        record = source_records.get(chapter)
        if not record:
            continue
        previous = 0
        for item in entries:
            kind, position, text = item["kind"], item["placement"], item["sanskrit"]
            if (item["source_url"] != record["source_url"] or position not in POSITIONS.get(kind, ())
                    or item["source_paragraph"] <= previous or not DEVANAGARI.search(text)
                    or any(c.isalpha() and not "\u0900" <= c <= "\u097f" for c in text)):
                raise ValueError(f"Invalid reviewed Sanskrit supplement: {key}")
            previous = item["source_paragraph"]
            normalized = re.sub(r"[\t\r\n\f \u00a0]+", " ", text).strip()
            actual = sha256(normalized.encode("utf-8")).hexdigest()
            if item["source_normalized_text_sha256"] != actual:
                raise ValueError(f"Invalid Sanskrit supplement checksum: {key}")
            if kind == "Source colophon" and record.get("colophon"):
                raise ValueError(f"Duplicates an already captured colophon: {key}")
            index[chapter][position].append(item)
    return index


def render_paratext(items, offsets=None):
    if not items:
        return ""
    html = []
    for i, item in enumerate(items):
        kind = item["kind"]
        title = escape(kind)
        source = item["sanskrit"]
        number = item["source_paragraph"]
        breaks = (offsets or {}).get(str(number))
        if breaks is None:
            breaks = line_break_offsets(source)
        latin = transliterate(source)
        text = render_lines(source, breaks)
        cite = escape(item["source_url"], quote=True)
        caption = f'<p><a href="{cite}">{title} ↗</a></p>' if i == 0 or kind != items[i - 1]["kind"] else ""
        alternate = (f'<div lang="sa-Latn" class="colophon iast">{render_lines(latin, corresponding_breaks(source, latin, breaks))}</div>'
                     if latin else '<div class="colophon">IAST unavailable for this source passage.</div>')
        permalink = f'<a class="source-paratext-permalink" href="#source-paragraph-{number}" aria-label="Link to source paragraph {number}">¶</a>'
        html.append(f'<aside id="source-paragraph-{number}" class="colophon source-paratext" aria-label="{title}">'
                    f'{caption}{permalink}<div class="verse-scroll" tabindex="0" role="group" aria-label="{title} text">'
                    f'<div lang="sa-Deva">{text}</div>{alternate}</div></aside>')
    return "".join(html)
