#!/usr/bin/env python3
"""Audit generated headings, verse renderings, and the untouched Sanskrit witness."""
from collections import Counter
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unicodedata

from chapter_iast import display_chapters
from reader import load_sanskrit
from transliterate_iast import transliterate

ROOT = Path(__file__).parent
OUT = ROOT / "dist"
LEGACY = re.compile(r"\b(?:Rama|Ravana|Ramayana|Valmiki|Sita|Seetha|Lakshmana|Hanuma|Dasharatha|Dasaratha|Sugreeva|Vibhishana)\b", re.I)


class TextAudit(HTMLParser):
    def __init__(self):
        super().__init__()
        self.current = None
        self.parts = []
        self.fields = {name: [] for name in ("title", "h1", "sa-Deva", "sa-Latn")}
        self.unavailable = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "iast-gap" in attrs.get("class", "").split():
            self.unavailable += 1
        name = attrs.get("lang") if tag == "p" else tag
        if name in self.fields:
            self.current = (name, tag)
            self.parts = []

    def handle_endtag(self, tag):
        if self.current and self.current[1] == tag:
            self.fields[self.current[0]].append("".join(self.parts))
            self.current = None

    def handle_data(self, data):
        if self.current:
            self.parts.append(data)


def verify():
    raw = json.loads((ROOT / "chapters.json").read_text(encoding="utf-8"))
    reviewed = display_chapters(raw)
    records = load_sanskrit(raw)
    search = json.loads((OUT / "search.json").read_text(encoding="utf-8"))
    indexed = {(row["book_number"], row["number"]): row["title"] for row in search}
    if len(indexed) != len(search) or len(search) != 534:
        raise ValueError("Chapter indexes and search do not cover exactly 534 chapters")

    audit = Counter()
    exceptions = []
    for file in sorted(OUT.rglob("*.html")):
        document = TextAudit()
        document.feed(file.read_text(encoding="utf-8"))
        if any(text != unicodedata.normalize("NFC", text)
               for field in ("title", "h1", "sa-Latn") for text in document.fields[field]):
            raise ValueError(f"Non-NFC reader text in {file.relative_to(OUT)}")
        audit["html_pages"] += 1

    for book_number, book in enumerate(reviewed, 1):
        slug = book["slug"]
        for row in book["rows"]:
            n = row["n"]
            title = row["title"]
            document = TextAudit()
            document.feed((OUT / slug / str(n) / "index.html").read_text(encoding="utf-8"))
            if (document.fields["h1"] != [title] or title not in document.fields["title"][0]
                    or indexed[book_number, n] != title or LEGACY.search(title)):
                raise ValueError(f"IAST mismatch in title, search, or metadata for {slug}/{n}")
            audit["chapter_titles"] += 1
            record = records.get((slug, n))
            if not record:
                continue
            devanagari = [v["sanskrit"] for v in record["verses"]]
            roman = [None if v.get("source_glyph_anomaly") else transliterate(v["sanskrit"])
                     for v in record["verses"]]
            if record.get("colophon"):
                devanagari.append(record["colophon"])
                roman.append(transliterate(record["colophon"]))
            if document.fields["sa-Deva"] != devanagari:
                raise ValueError(f"Source Devanagari changed for {slug}/{n}")
            if document.fields["sa-Latn"] != [block for block in roman if block]:
                raise ValueError(f"Generated Latin text changed for {slug}/{n}")
            gaps = [i for i, block in enumerate(roman, 1) if not block]
            if document.unavailable != len(gaps):
                raise ValueError(f"Missing unavailable notice for {slug}/{n}")
            audit["sanskrit_chapters"] += 1
            audit["verse_or_source_blocks"] += len(record["verses"])
            audit["iast_blocks_and_colophons"] += len(roman) - len(gaps)
            audit["unsupported_blocks_and_colophons"] += len(gaps)
            if gaps:
                exceptions.append({"chapter": f"{slug}/{n}", "source_blocks": gaps})

    report = {"counts": dict(audit), "iast_exceptions": exceptions}
    (OUT / "iast-audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["counts"], ensure_ascii=False))


if __name__ == "__main__":
    verify()
