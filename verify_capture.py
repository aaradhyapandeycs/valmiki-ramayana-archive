#!/usr/bin/env python3
"""Verify a pinned Sanskrit capture and print its reproducible coverage."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from ingest_sanskrit import BOOK_COUNTS, deva_only, parsed_locators


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def verify(root, commit=None):
    summary = load_json(root / "summary.json")
    if summary["schema_version"] != 1 or summary["scope"] != sum(BOOK_COUNTS.values()):
        raise ValueError("Unexpected Sanskrit capture schema or scope")
    if commit and summary["commit"] != commit:
        raise ValueError("Unexpected Sanskrit capture commit")
    keys = [(slug, sarga) for slug, count in BOOK_COUNTS.items() for sarga in range(1, count + 1)]
    if [(row["slug"], row["sarga"]) for row in summary["chapters"]] != keys:
        raise ValueError("Capture index is incomplete, duplicated or out of order")

    counts = Counter()
    statuses = Counter()
    blocks = Counter()
    for row in summary["chapters"]:
        slug, number = row["slug"], row["sarga"]
        record = load_json(root / slug / f"{number}.json")
        book = list(BOOK_COUNTS).index(slug) + 1
        if row["book"] != book or any(key != "slug" and record[key] != value for key, value in row.items()):
            raise ValueError(f"{slug}/{number}: capture and summary disagree")
        status = record["status"]
        statuses[status] += 1
        if status == "needs_review":
            if record.get("verses") or record["verse_count"]:
                raise ValueError(f"{slug}/{number}: unverified text entered the capture")
            errors = " | ".join(
                ", ".join(row["issues"][:3]) for row in record.get("diagnostics", [])
            )
            print(f"{slug}/{number}: {errors}")
            counts[status] += 1
            continue
        if status not in {"numbering_verified", "source_blocks_verified"}:
            raise ValueError(f"{slug}/{number}: unknown verification status")
        kind = record["kind"]
        if kind not in {"primary", "mirror"}:
            raise ValueError(f"{slug}/{number}: unknown source witness")
        hosts = {"primary": {"valmikiramayan.net", "www.valmikiramayan.net"},
                 "mirror": {"sanskritdocuments.org"}}[kind]
        for field in ("source_url", "final_url"):
            url = urlsplit(record[field])
            if url.scheme not in {"http", "https"} or url.hostname not in hosts:
                raise ValueError(f"{slug}/{number}: unexpected {field}")
        if not re.fullmatch(r"[a-f0-9]{64}", record["source_sha256"]):
            raise ValueError(f"{slug}/{number}: missing source digest")
        verses = record["verses"]
        if not verses or record["verse_count"] != len(verses):
            raise ValueError(f"{slug}/{number}: verse/block count differs")
        if record.get("colophon") and not deva_only(record["colophon"]):
            raise ValueError(f"{slug}/{number}: mixed-language colophon")

        numbered = status == "numbering_verified"
        prefix = "verse" if numbered else "block"
        expected = 1
        for verse in verses:
            text = verse["sanskrit"]
            if not deva_only(text):
                raise ValueError(f"{slug}/{number}: mixed-language verse/block")
            if verse["number"] != expected or verse["anchor"] != f"{prefix}-{book}-{number}-{expected}":
                raise ValueError(f"{slug}/{number}: unexpected verse/block order")
            last = verse.get("last_number", expected)
            if numbered:
                locators = list(loc for _, loc in parsed_locators(text))
                if last < expected or locators != [(book, number, expected, last)]:
                    raise ValueError(f"{slug}/{number}: printed verse locator differs")
                if verse["source_anchor"].lower() != f"verse{expected}":
                    raise ValueError(f"{slug}/{number}: unexpected original verse anchor")
            expected = last + 1
        counts[kind] += 1
        blocks[status] += len(verses)

    if counts != Counter(summary["counts"]) or statuses != Counter(summary["statuses"]):
        raise ValueError("Coverage totals disagree with per-chapter records")
    print(f"Verified capture citations and script containment: {dict(counts)}")
    print(f"Chapter verification status: {dict(statuses)}")
    print(f"Displayed Sanskrit records by status: {dict(blocks)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--commit")
    args = parser.parse_args()
    verify(args.root, args.commit)
