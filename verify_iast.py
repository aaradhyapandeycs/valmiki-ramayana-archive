#!/usr/bin/env python3
"""Audit generated headings, verse renderings, and the untouched Sanskrit witness."""
from collections import Counter
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unicodedata

from chapter_iast import display_chapters
from reader import load_reviewed_iast, load_sanskrit
from sanskrit_paratext import load_paratext
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
        self.restored = 0
        self.description = None
        self.supplements = {}
        self.supplement = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        element_id = attrs.get("id", "")
        if tag == "aside" and element_id.startswith("source-paragraph-"):
            self.supplement = int(element_id.removeprefix("source-paragraph-"))
            if self.supplement in self.supplements:
                raise ValueError("Duplicate Sanskrit supplement")
            self.supplements[self.supplement] = {}
        if self.supplement is not None and tag == "div" and attrs.get("lang") in {"sa-Deva", "sa-Latn"}:
            self.current = (attrs["lang"], tag)
            self.parts = []
            return
        if tag == "meta" and attrs.get("name") == "description":
            self.description = attrs["content"]
        if "iast-gap" in attrs.get("class", "").split():
            self.unavailable += 1
        if tag == "p" and attrs.get("lang") == "sa-Latn" and attrs.get("data-iast-restored") == "true":
            self.restored += 1
        name = attrs.get("lang") if tag == "p" else tag
        if name in self.fields:
            self.current = (name, tag)
            self.parts = []

    def handle_endtag(self, tag):
        if self.current and self.current[1] == tag:
            value = "".join(self.parts)
            if self.supplement is not None and tag == "div":
                self.supplements[self.supplement][self.current[0]] = value
            else:
                self.fields[self.current[0]].append(value)
            self.current = None
        if tag == "aside":
            self.supplement = None

    def handle_data(self, data):
        if self.current:
            self.parts.append(data)


def verify():
    raw = json.loads((ROOT / "chapters.json").read_text(encoding="utf-8"))
    reviewed = display_chapters(raw)
    records = load_sanskrit(raw)
    restorations = load_reviewed_iast(records)
    supplements = load_paratext(records)
    search = json.loads((OUT / "search.json").read_text(encoding="utf-8"))
    indexed = {(row["book_number"], row["number"]): row["title"] for row in search}
    if len(indexed) != len(search) or len(search) != 534:
        raise ValueError("Chapter indexes and search do not cover exactly 534 chapters")

    audit = Counter()
    exceptions = []
    supplement_exceptions = []
    exception_characters = Counter()
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
            chapter_html = (OUT / slug / str(n) / "index.html").read_text(encoding="utf-8")
            document.feed(chapter_html)
            if (document.fields["h1"] != [title] or title not in document.fields["title"][0]
                    or not document.description or title not in document.description
                    or indexed[book_number, n] != title or LEGACY.search(title)):
                raise ValueError(f"IAST mismatch in title, search, or metadata for {slug}/{n}")
            additions = supplements.get((slug, n), {})
            expected = {}
            for item in additions.get("before", []) + additions.get("after", []):
                number = item["source_paragraph"]
                source = item["sanskrit"]
                result = transliterate(source)
                expected[number] = {"sa-Deva": source}
                audit["reviewed_supplemental_paragraphs"] += 1
                if result:
                    expected[number]["sa-Latn"] = result
                    audit["supplemental_iast_paragraphs"] += 1
                else:
                    supplement_exceptions.append({"chapter": f"{slug}/{n}", "source_paragraph": number})
                    audit["unsupported_supplemental_paragraphs"] += 1
            if document.supplements != expected:
                raise ValueError(f"Published Sanskrit supplement differs for {slug}/{n}")
            audit["chapter_titles"] += 1
            record = records.get((slug, n))
            if not record:
                continue
            devanagari = [v["sanskrit"] for v in record["verses"]]
            restored, witness = restorations.get((book_number, n), ({}, ""))
            roman = [restored.get(v["number"]) or (None if v.get("source_glyph_anomaly") else transliterate(v["sanskrit"]))
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
            if document.restored != len(restored) or (witness and witness not in chapter_html):
                raise ValueError(f"Missing reviewed IAST attribution for {slug}/{n}")
            audit["sanskrit_chapters"] += 1
            audit["verse_or_source_blocks"] += len(record["verses"])
            audit["iast_blocks_and_colophons"] += len(roman) - len(gaps)
            audit["restored_iast_blocks"] += len(restored)
            audit["unsupported_blocks_and_colophons"] += len(gaps)
            if gaps:
                for i in gaps:
                    exception_characters.update(
                        "U+%04X %s" % (ord(char), unicodedata.name(char, "Unassigned"))
                        for char in set(devanagari[i - 1]) if transliterate(char) is None
                        and not unicodedata.category(char).startswith("M")
                    )
                exceptions.append({"chapter": f"{slug}/{n}", "source_blocks": gaps})

    report = {"counts": dict(audit), "unsupported_characters": dict(exception_characters),
              "iast_exceptions": exceptions, "supplemental_iast_exceptions": supplement_exceptions}
    (OUT / "iast-audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["counts"], ensure_ascii=False))
    print(json.dumps(report["unsupported_characters"], ensure_ascii=False))


if __name__ == "__main__":
    verify()
