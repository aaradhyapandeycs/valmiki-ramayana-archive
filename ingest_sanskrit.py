#!/usr/bin/env python3
"""Capture numbered, tagged Devanagari verses from six source indexes.

Only Devanagari SanSloka blocks with same-chapter locators qualify. Translation,
glosses, notes, and original HTML are never written to the output directory.
A Sanskrit Documents fallback is a separate textual witness.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

SOURCE = "https://valmikiramayan.net"
MIRROR = "https://sanskritdocuments.org/sites/valmikiramayan"
BOOK_COUNTS = {
    "baala": 77, "ayodhya": 119, "aranya": 75,
    "kish": 67, "sundara": 68, "yuddha": 128,
}
DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
LOCATOR = re.compile(
    r"(?:\|\s*\||॥)\s*(\d+)\s*[-–]\s*(\d+)\s*[-–]\s*(\d+)"
    r"(?:\s*[-–]\s*(\d+))?\s*$"
)
ANCHOR = re.compile(r"Verse(\d+)", flags=re.I)
LINE_SPACE = re.compile(r"[\t\xa0 ]+")
MAX_BYTES = 2_000_000


class SlokaPane(HTMLParser):
    """Recognize source-typed blocks, including HTML with unclosed P tags."""

    def __init__(self):
        super().__init__()
        self.parts = None
        self.anchor = None
        self.anchors = []
        self.records = []
        self.ignored_tags = []

    def finish_block(self):
        if self.parts is not None:
            self.records.append(("".join(self.parts), self.anchor))
            self.anchor = None
            self.parts = None

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "audio"}:
            self.ignored_tags.append(tag)
        if self.ignored_tags:
            return
        values = dict(attrs)
        if tag == "p":
            self.finish_block()
            if "sansloka" in (values.get("class") or "").lower().split():
                self.parts = []
        elif tag == "a":
            for attr in ("name", "id"):
                value = values.get(attr) or ""
                if ANCHOR.fullmatch(value):
                    self.anchor = value
                    self.anchors.append(value)
                    break
        elif tag == "br" and self.parts is not None:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.ignored_tags:
            if tag == self.ignored_tags[-1]:
                self.ignored_tags.pop()
            return
        if tag == "p":
            self.finish_block()

    def handle_data(self, data):
        if self.parts is not None and not self.ignored_tags:
            self.parts.append(data)

    def close(self):
        super().close()
        self.finish_block()


def decode_verses(raw, book, sarga):
    pane = SlokaPane()
    try:
        pane.feed(raw.decode("utf-8-sig"))
    except UnicodeDecodeError:
        return [], ["non-UTF-8 source"]
    pane.close()
    verses = []
    errors = []
    next_number = 1
    for text, source_anchor in pane.records:
        lines = [LINE_SPACE.sub(" ", line).strip() for line in text.splitlines()]
        lines = [line for line in lines if line]
        locator = LOCATOR.search(lines[-1].translate(DIGITS)) if lines else None
        if not locator:
            if source_anchor:
                errors.append(f"{source_anchor}: missing printed locator")
            continue
        values = locator.groups()
        if tuple(map(int, values[:2])) != (book, sarga):
            if source_anchor:
                errors.append(f"{source_anchor}: wrong chapter in printed locator")
            continue
        number = int(values[2])
        last = int(values[3] or number)
        if not all(
            (not c.isalpha() or "\u0900" <= c <= "\u097f")
            and c != "\ufffd"
            for line in lines for c in line
        ) or not any("\u0904" <= c <= "\u0939" for line in lines for c in line):
            errors.append(f"{number}: block contains unsupported characters")
            continue
        if number != next_number or last < number:
            errors.append(f"{number}: noncontiguous or reversed numbering")
        if not source_anchor or int(ANCHOR.fullmatch(source_anchor)[1]) != number:
            errors.append(f"{number}: mismatched source anchor {source_anchor!r}")
        verse = {
            "number": number, "sanskrit": "\n".join(lines),
            "anchor": f"verse-{book}-{sarga}-{number}",
            "source_anchor": source_anchor,
        }
        if last != number:
            verse["last_number"] = last
        verses.append(verse)
        next_number = last + 1

    expected = [v["source_anchor"] for v in verses]
    if not verses:
        errors.append("no qualified Devanagari verse blocks")
    if pane.anchors != expected:
        errors.append(f"source anchors do not match captured blocks ({len(pane.anchors)} anchors)")
    return verses, errors


def open_html(url, timeout):
    try:
        with urlopen(url, timeout=timeout) as response:
            host = urlsplit(response.url).hostname
            if host not in {"valmikiramayan.net", "www.valmikiramayan.net", "sanskritdocuments.org"}:
                return None, f"external redirect to {host}"
            if response.headers.get_content_type() not in {"text/html", "application/xhtml+xml"}:
                return None, f"unexpected content type {response.headers.get_content_type()}"
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                return None, "oversize response"
            return (raw, response.url), None
    except HTTPError as exc:
        return None, f"http_{exc.code}"
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def capture(book, slug, prefix, sarga, timeout, delay, allow_mirror):
    pathname = f"{slug}/sarga{sarga}/{prefix}sans{sarga}.htm"
    urls = [("primary", f"{SOURCE}/utf8/{pathname}"),
            ("primary", f"{SOURCE}/{pathname}")]
    if allow_mirror:
        urls.append(("mirror", f"{MIRROR}/{pathname}"))
    diagnostics = []
    for kind, url in urls:
        payload, error = open_html(url, timeout)
        time.sleep(delay)
        if error:
            diagnostics.append({"source_url": url, "issues": [error]})
            continue
        raw, final_url = payload
        final_host = urlsplit(final_url).hostname
        if (kind == "mirror") != (final_host == "sanskritdocuments.org"):
            diagnostics.append({"source_url": url, "issues": ["redirect changed textual witness"]})
            continue
        digest = hashlib.sha256(raw).hexdigest()
        verses, issues = decode_verses(raw, book, sarga)
        if issues:
            diagnostics.append({"source_url": url, "final_url": final_url,
                                "source_sha256": digest,
                                "candidate_blocks": len(verses), "issues": issues})
            continue
        return {
            "book": book, "sarga": sarga, "kind": kind,
            "source_url": url, "final_url": final_url, "source_sha256": digest,
            "status": "numbering_verified", "verse_count": len(verses),
            "verses": verses, "diagnostics": diagnostics,
        }
    return {
        "book": book, "sarga": sarga, "status": "needs_review",
        "verse_count": 0, "diagnostics": diagnostics,
    }


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n",
                    encoding="utf-8")


def fetch_corpus(args):
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Output directory must be empty for a new acquisition")
    indexes = json.loads(args.chapters.read_text(encoding="utf-8"))
    if [entry["slug"] for entry in indexes] != list(BOOK_COUNTS):
        raise ValueError("Expected all six books in canonical index order")
    entries = []
    for book, entry in enumerate(indexes, start=1):
        slug = entry["slug"]
        numbers = [row["n"] for row in entry["rows"]]
        if numbers != list(range(1, BOOK_COUNTS[slug] + 1)):
            raise ValueError(f"Unexpected index sequence: {slug}")
        for sarga in numbers:
            if not args.book or args.book == slug:
                if not args.sarga or args.sarga == sarga:
                    entries.append((book, slug, entry["frameprefix"], sarga))
    if not entries:
        raise ValueError("Selected chapter does not exist")

    def task(entry):
        book, slug, prefix, sarga = entry
        record = capture(book, slug, prefix, sarga, args.timeout, args.delay, not args.primary_only)
        return slug, record

    totals = {"primary": 0, "mirror": 0, "needs_review": 0}
    summary = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for slug, record in pool.map(task, entries):
            write_json(args.output / slug / f"{record['sarga']}.json", record)
            totals[record.get("kind", "needs_review")] += 1
            summary.append({"slug": slug, **{key: record[key] for key in (
                "book", "sarga", "status", "verse_count", "kind", "source_url", "source_sha256"
            ) if key in record}})
            if len(summary) % 25 == 0:
                print(f"{len(summary)} / {len(entries)}: {totals}", flush=True)

    write_json(args.output / "summary.json", {
        "schema_version": 1,
        "commit": args.commit,
        "scope": len(entries),
        "counts": totals,
        "chapters": summary,
    })
    print(f"{len(summary)} / {len(entries)}: {totals}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chapters", type=Path, default=Path("chapters.json"))
    parser.add_argument("--output", type=Path, default=Path("sanskrit"))
    parser.add_argument("--book", choices=BOOK_COUNTS)
    parser.add_argument("--sarga", type=int)
    parser.add_argument("--workers", type=int, choices=range(1, 9), default=4)
    parser.add_argument("--delay", type=float, default=.25)
    parser.add_argument("--timeout", type=float, default=12)
    parser.add_argument("--primary-only", action="store_true")
    parser.add_argument("--commit")
    args = parser.parse_args()
    if args.delay < 0 or args.timeout <= 0 or (args.sarga is not None and args.sarga < 1):
        parser.error("Invalid delay, timeout, or chapter number")
    fetch_corpus(args)


if __name__ == "__main__":
    main()
