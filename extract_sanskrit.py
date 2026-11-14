#!/usr/bin/env python3
"""Extract only source-tagged Sanskrit sloka paragraphs, never English prose.

The source UTF-8 pages use p.SanSloka and p.RomSloka, preceded by a
p.verloc containing an anchor VerseN. Output is a candidate transcription
with source SHA-256 and validation flags. Contiguous numbering alone does not
prove the source page was complete; review expected verse counts independently.
"""
import argparse
import hashlib
import json
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEVA_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
LOCATOR = re.compile(r"(?:\|\||॥)\s*([०-९0-9]+)[-–]([०-९0-9]+)[-–]([०-९0-9]+)\s*$")
DEVANAGARI = re.compile(r"[\u0900-\u097f]")
LATIN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿĀ-žḀ-ỿ]")


class Slokas(HTMLParser):
    """Keep only tagged verse paragraphs, preserving line boundaries."""
    def __init__(self, kind):
        super().__init__(convert_charrefs=True)
        self.class_name = "SanSloka" if kind == "sanskrit" else "RomSloka"
        self.current = None
        self.parts = []
        self.anchor = None
        self.records = []
        self.anchors_seen = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "p":
            classes = set(d.get("class", "").split())
            if self.class_name in classes:
                self.current = "verse"
                self.parts = []
            elif "verloc" in classes:
                self.current = "locator"
        elif tag == "a" and self.current == "locator":
            if re.fullmatch(r"Verse[0-9]+", d.get("name", "")):
                self.anchor = d["name"]
                self.anchors_seen.append(d["name"])
        elif tag == "br" and self.current == "verse":
            self.parts.append("\n")
        elif tag in ("script", "style", "audio") and self.current == "verse":
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "audio") and self.skip:
            self.skip -= 1
        elif tag == "p":
            if self.current == "verse":
                text = "".join(self.parts)
                if text.strip():
                    self.records.append((text, self.anchor))
                    self.anchor = None
            self.current = None

    def handle_data(self, data):
        if self.current == "verse" and not self.skip:
            self.parts.append(data)


def clean_line(text):
    return re.sub(r"[\t \xa0]+", " ", text).strip()


def script_ok(text, kind):
    if "=" in text or not ("|" in text or "।" in text):
        return False
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    pattern = DEVANAGARI if kind == "sanskrit" else LATIN
    return sum(bool(pattern.fullmatch(c)) for c in letters) / len(letters) >= .85


def extract(raw, book, sarga, kind, expected_count=None):
    parser = Slokas(kind)
    parser.feed(raw.decode("utf-8-sig", errors="replace"))
    verses = {}
    errors = []
    skipped = 0
    for text, anchor in parser.records:
        lines = [clean_line(x) for x in text.replace("\r", "").split("\n") if x.strip()]
        if not lines:
            skipped += 1
            continue
        marker = LOCATOR.search(lines[-1])
        if not marker:
            skipped += 1
            continue
        b, s, n = [int(x.translate(DEVA_DIGITS)) for x in marker.groups()]
        if (b, s) != (book, sarga):
            skipped += 1
            continue
        if not all(script_ok(line, kind) for line in lines):
            errors.append(f"verse {n}: non-verse or mixed-language text in {parser.class_name}")
            continue
        if len(lines) < 2:
            errors.append(f"verse {n}: expected at least two lines")
            continue
        if n in verses:
            errors.append(f"verse {n}: duplicate locator")
            continue
        if anchor != f"Verse{n}":
            errors.append(f"verse {n}: source anchor {anchor!r} does not match Verse{n}")
        verses[n] = {"number": n, "text": "\n".join(lines), "source_anchor": anchor}
    nums = sorted(verses)
    if not nums:
        errors.append("no matching tagged verses")
    elif nums != list(range(1, nums[-1] + 1)):
        errors.append("noncontiguous numbering from verse 1")
    anchor_nums = [int(a[5:]) for a in parser.anchors_seen]
    if len(anchor_nums) != len(set(anchor_nums)):
        errors.append("duplicate VerseN anchors in source")
    if sorted(anchor_nums) != nums:
        errors.append(f"VerseN anchor set differs from extracted verses: "
                      f"{len(anchor_nums)} anchors, {len(nums)} verses")
    if expected_count is not None and len(nums) != expected_count:
        errors.append(f"expected {expected_count} verses, found {len(nums)}")
    return {
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "encoding_assumption": "UTF-8",
        "kind": kind,
        "tagged_paragraphs": len(parser.records),
        "source_anchor_count": len(anchor_nums),
        "skipped_paragraphs": skipped,
        "verses": [verses[n] for n in nums],
        "errors": errors,
        "status": "candidate_contiguous" if not errors else "needs_review",
    }


def fetch(url):
    try:
        # The source host has returned a soft block to custom crawl user agents.
        # Use urllib's ordinary default User-Agent and validate the resulting
        # HTML for actual sloka classes and VerseN anchors before accepting it.
        with urlopen(Request(url), timeout=30) as response:
            content_type = response.headers.get_content_type()
            data = response.read(2_000_001)
            if response.status != 200 or content_type not in ("text/html", "application/xhtml+xml") or len(data) > 2_000_000:
                return None, {"status": f"http_{response.status}", "content_type": content_type,
                              "final_url": response.url, "error": "not a bounded HTML page"}
            return data, {"status": "http_200", "content_type": content_type,
                          "final_url": response.url, "sha256": hashlib.sha256(data).hexdigest()}
    except HTTPError as e:
        return None, {"status": f"http_{e.code}", "final_url": e.url}
    except (URLError, TimeoutError, ValueError) as e:
        return None, {"status": "request_failed", "error": str(e)}


def bulk(chapters_path, output_dir, delay):
    books = json.loads(chapters_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {}
    for book_num, book in enumerate(books, 1):
        slug = book["slug"]
        prefix = book["frameprefix"]
        results = []
        for row in book["rows"]:
            n = row["n"]
            sources = {}
            extracts = {}
            for kind, suffix in (("sanskrit", "sans"), ("roman", "roman")):
                url = f"https://valmikiramayan.net/utf8/{slug}/sarga{n}/{prefix}{suffix}{n}.htm"
                raw, metadata = fetch(url)
                sources[kind] = {"source_url": url, **metadata}
                if raw is not None:
                    extracts[kind] = extract(raw, book_num, n, kind)
                time.sleep(delay)
            issue = []
            for kind in ("sanskrit", "roman"):
                if kind not in extracts:
                    issue.append(f"{kind} source unavailable")
                elif extracts[kind]["status"] != "candidate_contiguous":
                    issue.extend(f"{kind}: {e}" for e in extracts[kind]["errors"])
            if len(extracts) == 2:
                sans_nums = [v["number"] for v in extracts["sanskrit"]["verses"]]
                roman_nums = [v["number"] for v in extracts["roman"]["verses"]]
                if sans_nums != roman_nums:
                    issue.append("Sanskrit/Roman numbering differs")
            record = {"book": book_num, "sarga": n, "source": sources,
                      "verse_count": len(extracts.get("sanskrit", {}).get("verses", [])),
                      "status": "validated_parallel_numbering" if not issue else "needs_review",
                      "issues": issue}
            if not issue:
                # Only ancient Sanskrit and its transliteration are retained.
                # The original HTML's English, glosses and notes are discarded.
                record["verses"] = [
                    {"number": s["number"], "sanskrit": s["text"], "roman": r["text"],
                     "anchor": f"verse-{book_num}-{n}-{s['number']}",
                     "source_anchor": s["source_anchor"]}
                    for s, r in zip(extracts["sanskrit"]["verses"], extracts["roman"]["verses"])
                ]
                path = output_dir / slug / f"{n}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n",
                                encoding="utf-8")
            results.append({k: v for k, v in record.items() if k != "verses"})
            if n % 20 == 0:
                print(f"{slug}: {n}/{len(book['rows'])}", flush=True)
        summary[slug] = results
    (output_dir / "bulk-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Validated:",
          {slug: sum(r["status"] == "validated_parallel_numbering" for r in rows)
           for slug, rows in summary.items()}, flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bulk", type=Path, help="chapters.json for all six indexed books")
    p.add_argument("--output-dir", type=Path, help="validated per-sarga JSON output directory")
    p.add_argument("--delay", type=float, default=.2, help="seconds between source requests")
    p.add_argument("--book", type=int)
    p.add_argument("--sarga", type=int)
    p.add_argument("--sanskrit", type=Path)
    p.add_argument("--roman", type=Path)
    p.add_argument("--expected-count", type=int)
    p.add_argument("--output", type=Path)
    a = p.parse_args()
    if a.bulk:
        if not a.output_dir:
            p.error("--bulk requires --output-dir")
        bulk(a.bulk, a.output_dir, a.delay)
        return
    if not all((a.book, a.sarga, a.sanskrit, a.output)):
        p.error("single-page mode requires --book, --sarga, --sanskrit, --output")
    result = {"book": a.book, "sarga": a.sarga,
              "sanskrit": extract(a.sanskrit.read_bytes(), a.book, a.sarga,
                                  "sanskrit", a.expected_count)}
    if a.roman:
        roman = extract(a.roman.read_bytes(), a.book, a.sarga, "roman", a.expected_count)
        if [v["number"] for v in roman["verses"]] != [v["number"] for v in result["sanskrit"]["verses"]]:
            roman["errors"].append("Roman/Sanskrit verse number mismatch")
            roman["status"] = "needs_review"
        result["roman"] = roman
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{a.book}-{a.sarga}: {len(result['sanskrit']['verses'])} Sanskrit candidates; "
          f"status={result['sanskrit']['status']}")


if __name__ == "__main__":
    main()
