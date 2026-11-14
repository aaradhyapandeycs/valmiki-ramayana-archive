"""Render reviewed supplemental Sanskrit from the archived source pane."""
from collections import defaultdict
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re

from transliterate_iast import transliterate


DATA = Path(__file__).with_name("data")
POSITIONS = {"Source invocation": {"before"}, "Source colophon": {"after"},
             "Source verse passage": {"before", "after"}}
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
            actual = sha256(text.encode("utf-8")).hexdigest()
            if item["source_normalized_text_sha256"] != actual:
                raise ValueError(f"Invalid Sanskrit supplement checksum: {key}")
            if kind == "Source colophon" and record.get("colophon"):
                raise ValueError(f"Duplicates an already captured colophon: {key}")
            index[chapter][position].append(item)
    return index


def render_paratext(items):
    if not items:
        return ""
    html = []
    for i, item in enumerate(items):
        kind = item["kind"]
        title = escape(kind)
        text = escape(item["sanskrit"])
        latin = transliterate(item["sanskrit"])
        cite = escape(item["source_url"], quote=True)
        caption = f'<p><a href="{cite}">{title} ↗</a></p>' if i == 0 or kind != items[i - 1]["kind"] else ""
        alternate = (f'<div lang="sa-Latn" class="colophon iast">{escape(latin)}</div>'
                     if latin else '<div class="colophon">IAST unavailable for this source passage.</div>')
        number = item["source_paragraph"]
        permalink = f'<a class="source-paratext-permalink" href="#source-paragraph-{number}" aria-label="Link to source paragraph {number}">¶</a>'
        html.append(f'<aside id="source-paragraph-{number}" class="colophon source-paratext" aria-label="{title}">'
                    f'{caption}{permalink}<div lang="sa-Deva">{text}</div>{alternate}</aside>')
    return "".join(html)
