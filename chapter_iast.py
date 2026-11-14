"""Validate the reviewed IAST headings against their source chapter indexes."""
import hashlib
import json
import re
from pathlib import Path
import unicodedata

ROOT = Path(__file__).parent


def chapter_fingerprint(books):
    payload = json.dumps(books, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_title_review():
    path = ROOT / "data" / "chapter-iast.json"
    return json.loads(path.read_text(encoding="utf-8"))


def title_aliases(heading, glossary):
    return [variant for spelling, item in glossary.items()
            if re.search(rf"(?<!\w){re.escape(spelling)}(?!\w)", heading)
            for variant in item["variants"]]


def display_chapters(books):
    review = load_title_review()
    if review["source_fingerprint"] != chapter_fingerprint(books):
        raise ValueError("The source headings changed. Review the IAST headings before building.")
    if set(review["books"]) != {book["slug"] for book in books}:
        raise ValueError("The IAST review must cover all six kāṇḍas.")
    normalized = []
    for book in books:
        display_titles = review["books"][book["slug"]]
        if set(display_titles) != {str(row["n"]) for row in book["rows"]}:
            raise ValueError(f"Incomplete title review for {book['slug']}")
        rows = []
        for row in book["rows"]:
            title = display_titles[str(row["n"])]
            if not title or title != unicodedata.normalize("NFC", title):
                raise ValueError(f"Heading lacks NFC IAST text: {book['slug']}/{row['n']}")
            rows.append({**row, "title": title})
        normalized.append({**book, "rows": rows})
    return normalized
