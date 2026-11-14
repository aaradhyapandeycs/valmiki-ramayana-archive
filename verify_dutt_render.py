#!/usr/bin/env python3
"""Compare all deployed-edition Dutt prose with the pinned textual corpus."""
import argparse
from collections import Counter
import gzip
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unicodedata

from build_dutt import BOOKS, SOURCES, section_ranges, source_lines
from dutt_iast import normalize_dutt


class Article(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_article = False
        self.articles = 0
        self.paragraphs = []
        self.parts = None

    def handle_starttag(self, tag, attrs):
        if tag == "article":
            self.in_article = True
            self.articles += 1
        elif tag == "p" and self.in_article:
            self.parts = []

    def handle_endtag(self, tag):
        if tag == "article":
            self.in_article = False
        elif tag == "p" and self.parts is not None:
            self.paragraphs.append("".join(self.parts))
            self.parts = None

    def handle_data(self, text):
        if self.parts is not None:
            self.parts.append(text)


def display_paragraphs(text):
    text = unicodedata.normalize("NFC", normalize_dutt(text))
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text)]
    # Underscores in the transcription denote source emphasis. Only those
    # paired in a single paragraph outside angle brackets are HTML markup.
    return [re.sub(r"_([^_\n<>]+)_", r"\1", p) for p in paragraphs]


def verify(dist, corpus, transcription):
    snapshots = None
    if transcription is not None:
        snapshots = {
            ebook: source_lines((transcription / f"{ebook}.txt").read_bytes(), ebook, digest)
            for ebook, digest in SOURCES.items()
        }

    checked = set()
    books = Counter()
    for book in BOOKS:
        slug, _, ebook, _, _, count = book
        source = json.loads(gzip.decompress((corpus / f"{slug}.json.gz").read_bytes()))
        sections = source["sections"]
        if len(sections) != count:
            raise ValueError(f"Unexpected corpus count in {slug}")
        if snapshots is not None and sections != list(section_ranges(snapshots[ebook], book)):
            raise ValueError(f"Corpus differs from the pinned Gutenberg transcription: {slug}")
        for section in sections:
            relative = Path(slug) / section["id"] / "index.html"
            if relative in checked:
                raise ValueError(f"Duplicate edition route: {relative}")
            checked.add(relative)
            parser = Article()
            parser.feed((dist / "english" / relative).read_text(encoding="utf-8"))
            expected = display_paragraphs(section["text"])
            if parser.articles != 1 or parser.paragraphs != expected:
                raise ValueError(f"Rendered prose differs from reviewed corpus: /english/{relative.parent}/")
            books[slug] += 1

    generated = {p.relative_to(dist / "english") for p in (dist / "english").glob("*/*/index.html")}
    if generated != checked:
        raise ValueError(f"Generated prose route set differs from corpus: {sorted(generated ^ checked)}")
    report = {
        "edition": "M. N. Dutt, Project Gutenberg",
        "sections_checked": len(checked),
        "book_counts": dict(books),
        "original_transcription_digests_checked": snapshots is not None,
        "rendered_text_mismatches": 0,
        "normalization": ["reviewed glossary", "NFC", "paragraph whitespace", "source italics"],
    }
    print(json.dumps(report, ensure_ascii=False))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--corpus", type=Path, default=Path("dutt-corpus"))
    parser.add_argument("--transcription", type=Path, help="directory of the three pinned Gutenberg .txt files")
    args = parser.parse_args()
    verify(args.dist, args.corpus, args.transcription)
