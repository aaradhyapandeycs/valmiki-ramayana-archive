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
    r"(?<![\d-])(\d{1,2})[ \t]*[-–][ \t]*(\d{1,3})[ \t]*[-–][ \t]*(\d{1,3})"
    r"(?:[ \t]*[-–][ \t]*(\d{1,3}))?(?![\d-])"
)
COLOPHON = re.compile(r"^[ |।॥]*(?:इति|इत्य)[^\n]{0,170}(?:रामायण|रामायाण)")

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
            text = "".join(self.parts)
            if text.strip():
                self.records.append((text, self.anchor))
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


def deva_only(text):
    return (
        any("\u0904" <= c <= "\u0939" for c in text)
        and all((not c.isalpha() or "\u0900" <= c <= "\u097f") and c != "\ufffd"
                for c in text)
    )


def normalize_lines(text):
    return "\n".join(
        value for line in text.splitlines()
        if (value := LINE_SPACE.sub(" ", line).strip())
    )


def parsed_locators(text):
    for hit in LOCATOR.finditer(text.translate(DIGITS)):
        book, sarga, number, last = hit.groups()
        yield hit, (int(book), int(sarga), int(number), int(last or number))


def verse_record(book, sarga, number, sanskrit, source_anchor, block=False):
    label = "block" if block else "verse"
    return {"number": number, "sanskrit": sanskrit,
            "anchor": f"{label}-{book}-{sarga}-{number}", "source_anchor": source_anchor}


def decode_verses(raw, book, sarga):
    pane = SlokaPane()
    try:
        pane.feed(raw.decode("utf-8-sig"))
    except UnicodeDecodeError:
        return [], "needs_review", ["non-UTF-8 source"], None
    pane.close()
    records = [(normalize_lines(text), anchor) for text, anchor in pane.records]
    anchors = [int(ANCHOR.fullmatch(anchor)[1]) for anchor in pane.anchors]
    if not anchors or anchors != sorted(anchors):
        return [], "needs_review", ["missing or malformed source chapter anchors"], None
    present_anchors = {anchor for _, anchor in records if anchor}
    if not {pane.anchors[0], pane.anchors[-1]} <= present_anchors:
        return [], "needs_review", ["first or last source anchor has no Sanskrit block"], None

    first = next(index for index, (_, anchor) in enumerate(records) if anchor)
    last = max(index for index, (_, anchor) in enumerate(records) if anchor)
    colophon = next((text for text, _ in records[last + 1:]
                     if COLOPHON.search(text)), None)
    blocks = records[first:last + 1]
    for text, _ in records[last + 1:]:
        # Unanchored blocks with the next locator belong to the chapter.
        # The remainder includes unnumbered colophons, quotations and appendices.
        old_last = max((end for _, (b, s, _, end) in parsed_locators(blocks[-1][0])
                        if (b, s) == (book, sarga)), default=0)
        hit = next(parsed_locators(text), None)
        if (not hit or COLOPHON.search(text) or old_last >= anchors[-1]
                or hit[1][:2] != (book, sarga) or hit[1][2] <= old_last):
            break
        blocks.append((text, None))

    # Treat any script leakage as a failed capture. Unsupported blocks must
    # not be silently removed from an otherwise claimed complete transcript.
    if any(not deva_only(text) for text, _ in blocks):
        return [], "needs_review", ["mixed-language or empty chapter block"], None
    if colophon and not deva_only(colophon):
        colophon = None
    full_text = "\n".join(text for text, _ in blocks)
    locators = list(parsed_locators(full_text))
    chapter_locators = sum(s == sarga or (b, s) == (sarga, book) for _, (b, s, _, _) in locators)
    if not locators or chapter_locators * 2 <= len(locators):
        return [], "needs_review", ["printed verse locators do not corroborate this chapter"], colophon

    issues = []
    if anchors[0] != 1 or len(anchors) != len(set(anchors)):
        issues.append("source has missing or duplicate initial anchors")
    verses = []
    offset = 0
    next_number = 1
    source_anchors = {number: label for number, label in zip(anchors, pane.anchors)}
    for hit, (b, s, number, end) in locators:
        if (b, s) != (book, sarga) or number != next_number or end < number:
            issues.append("printed chapter or verse sequence differs from the index")
            break
        text = full_text[offset:hit.end()].strip()
        if not deva_only(text):
            issues.append("printed locators do not delimit Sanskrit text")
            break
        verse = verse_record(book, sarga, number, text, source_anchors.get(number))
        if number != end:
            verse["last_number"] = end
        verses.append(verse)
        next_number = end + 1
        offset = hit.end()
    if offset != len(full_text):
        issues.append("printed locators do not cover all tagged verse text")
    if not verses or next_number - 1 != anchors[-1]:
        issues.append("last printed number does not match the last source anchor")
    if any(v["source_anchor"] is None for v in verses):
        issues.append("some printed verse starts have no source anchor")
    if not issues:
        return verses, "numbering_verified", [], colophon
    return ([verse_record(book, sarga, i, text, label, block=True)
             for i, (text, label) in enumerate(blocks, 1)],
            "source_blocks_verified", issues, colophon)


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
        verses, status, issues, colophon = decode_verses(raw, book, sarga)
        if status == "needs_review":
            diagnostics.append({"source_url": url, "final_url": final_url,
                                "source_sha256": digest,
                                "candidate_blocks": len(verses), "issues": issues})
            continue
        return {
            "book": book, "sarga": sarga, "kind": kind,
            "source_url": url, "final_url": final_url, "source_sha256": digest,
            "status": status, "verse_count": len(verses),
            "verses": verses, "colophon": colophon, "diagnostics": diagnostics,
            "numbering_issues": issues,
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
    statuses = {"numbering_verified": 0, "source_blocks_verified": 0, "needs_review": 0}
    summary = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for slug, record in pool.map(task, entries):
            write_json(args.output / slug / f"{record['sarga']}.json", record)
            totals[record.get("kind", "needs_review")] += 1
            statuses[record["status"]] += 1
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
        "statuses": statuses,
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
