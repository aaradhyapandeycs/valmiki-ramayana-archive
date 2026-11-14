"""Render reviewed supplemental Sanskrit from the archived source pane."""
from collections import defaultdict
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re

from transliterate_iast import transliterate


DATA = Path(__file__).with_name("data")
LABELS = {"opening_invocation": "Source invocation", "colophon": "Source colophon"}
TYPES = {"Source invocation": "before", "Source colophon": "after"}
DEVANAGARI = re.compile(r"[\u0904-\u0939]")


def load_paratext(source_records):
    path = DATA / "sanskrit-paratext-reviewed.json"
    reviewed = json.loads(path.read_text(encoding="utf-8"))
    index = defaultdict(dict)
    for key, entries in reviewed.items():
        slug, number = key.split("/")
        chapter = (slug, int(number))
        record = source_records.get(chapter)
        if not record:
            continue
        for item in entries:
            kind, position, text = item["kind"], item["placement"], item["sanskrit"]
            if (item["source_url"] != record["source_url"] or TYPES.get(kind) != position
                    or position in index[chapter] or item["source_paragraph"] < 1
                    or not DEVANAGARI.search(text)
                    or any(c.isalpha() and not "\u0900" <= c <= "\u097f" for c in text)):
                raise ValueError(f"Invalid reviewed Sanskrit paratext: {key}")
            actual = sha256(text.encode("utf-8")).hexdigest()
            if item["source_normalized_text_sha256"] != actual:
                raise ValueError(f"Invalid Sanskrit paratext checksum: {key}")
            if kind == "Source colophon" and record.get("colophon"):
                raise ValueError(f"Duplicates an already captured colophon: {key}")
            index[chapter][position] = item
    return index


def render_paratext(item):
    if item is None:
        return ""
    title = escape(item["kind"])
    text = escape(item["sanskrit"])
    latin = transliterate(item["sanskrit"])
    cite = escape(item["source_url"], quote=True)
    caption = f'<a href="{cite}">{title} ↗</a>'
    alternate = (f'<div lang="sa-Latn" class="colophon iast">{escape(latin)}</div>'
                 if latin else '<div class="colophon">IAST unavailable for this source passage.</div>')
    return (f'<aside class="colophon source-paratext" aria-label="{title}">'
            f'{caption}<div lang="sa-Deva">{text}</div>{alternate}</aside>')
