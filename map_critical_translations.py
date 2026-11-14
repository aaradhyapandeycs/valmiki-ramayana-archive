#!/usr/bin/env python3
"""Derive a conservative text crosswalk from CE source records to archive reading units."""

from argparse import ArgumentParser
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import json
import re
import unicodedata


ARCHIVE_BOOKS = ("baala", "ayodhya", "aranya", "kish", "sundara", "yuddha")
MINIMUM_FINGERPRINT_LENGTH = 25
LOCATORS = re.compile(r"(?<![\d-])[0-9०-९]{1,3}\s*[-–]\s*[0-9०-९]{1,3}\s*[-–]\s*"
                      r"[0-9०-९]{1,3}(?:\s*[-–]\s*[0-9०-९]{1,3})?(?![\d-])")
FUSED_KISH_LOCATOR = re.compile(r"(?<=[।॥|])\s*(?:454|४५४)[0-9०-९]{1,3}(?![\d-])")
FORMATTING = re.compile(r"[\s।॥|\u200c\u200d\uFEFF]+")
FORMAT_WHITESPACE = re.compile(r"[\t\r\n\f \u00a0]+")
HOMORGANIC_NASALS = (("ङ", "कखगघ"), ("ञ", "चछजझ"), ("ण", "टठडढ"),
                     ("न", "तथदध"), ("म", "पफबभ"))
FRAME = re.compile(r"VRCE-[1-7]-[1-9][0-9]*-[1-9][0-9]*$")
DUTT = re.compile(r"DUTT-[1-7]-[1-9][0-9]*-[1-9][0-9]*$")
ARCHIVE_COUNTS = (77, 119, 75, 67, 68, 128)


@dataclass(frozen=True)
class Unit:
    sarga: int
    anchor: str
    original: str

    @property
    def sha256(self):
        return sha256(FORMAT_WHITESPACE.sub(" ", self.original).strip().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Match:
    first_unit: int
    last_unit: int
    start_in_unit: int
    end_in_unit: int
    partial: bool
    basis: str


def exact_text(text, *, fused_locator=False):
    """Remove only known numbering and layout marks, and retain all Sanskrit letters."""
    text = unicodedata.normalize("NFC", text)
    if fused_locator:
        text = FUSED_KISH_LOCATOR.sub("", text)
    text = FORMATTING.sub("", LOCATORS.sub("", text))
    if any(not (0x900 <= ord(char) <= 0x97F) or char.isdecimal() for char in text):
        return ""
    return text


def orthographic_text(text):
    """Treat syllable-internal homorganic stop nasals and anusvāra as orthographic variants."""
    for nasal, stops in HOMORGANIC_NASALS:
        text = re.sub(f"{nasal}्(?=[{stops}])", "ं", text)
    return text


def read_archive(root, supplements):
    additions = json.loads(supplements.read_text(encoding="utf-8"))
    for book, (slug, count) in enumerate(zip(ARCHIVE_BOOKS, ARCHIVE_COUNTS), 1):
        result = []
        for chapter in range(1, count + 1):
            path = root / slug / f"{chapter}.json"
            row = json.loads(path.read_text(encoding="utf-8"))
            if (row["book"], row["sarga"]) != (book, chapter):
                raise ValueError(f"Archive coordinate mismatch in {path}")
            prefix = "verse" if row["status"] == "numbering_verified" else "block"
            extras = additions.get(f"{slug}/{chapter}", ())
            for v in extras:
                if v["kind"] == "Source verse passage" and v["placement"] == "before":
                    result.append(Unit(chapter, f'source-paragraph-{v["source_paragraph"]}', v["sanskrit"]))
            for v in row["verses"]:
                result.append(Unit(chapter, f'{prefix}-{v.get("last_number", v["number"])}', v["sanskrit"]))
            for v in extras:
                if v["kind"] == "Source verse passage" and v["placement"] == "after":
                    result.append(Unit(chapter, f'source-paragraph-{v["source_paragraph"]}', v["sanskrit"]))
        yield slug, book, result


def read_critical_book(root, spec):
    book, slug = spec["order"], spec["id"]
    rows = []
    for chapter in spec["sargas"]:
        number, count = chapter["sarga"], chapter["count"]
        path = root / slug / f"sarga-{number}.json"
        chapter_rows = json.loads(path.read_text(encoding="utf-8"))
        if len(chapter_rows) != count:
            raise ValueError(f"Incorrect source row count in {path}")
        for verse, row in enumerate(chapter_rows, 1):
            if (row["id"], row["kanda"], row["kandaId"], row["sarga"], row["verse"]) != (
                f"VRCE-{book}-{number}-{verse}", book, slug, number, verse
            ):
                raise ValueError(f"Incorrect source coordinate in {path} row {verse}")
            if not row["english"].strip() or not FRAME.fullmatch(row["id"]):
                raise ValueError(f"Missing source English in {path} row {verse}")
            alignment = row["alignment"]
            if (alignment["type"] not in {"1:1", "grouped", "split", "approximate"}
                    or not alignment["duttRefs"]
                    or any(not DUTT.fullmatch(ref) or not ref.startswith(f"DUTT-{book}-")
                           for ref in alignment["duttRefs"])):
                raise ValueError(f"Invalid source translation alignment in {path} row {verse}")
        rows.extend(chapter_rows)
    return rows


class ArchiveText:
    """Index book text and character spans, with breaks at damaged units and chapters."""

    def __init__(self, units, book, *, orthographic=False):
        self.units = units
        self.boundary = []
        self.sizes = []
        self.segments = []
        chunks = []
        cursor = 0
        previous = None
        for unit in units:
            if unit.sarga != previous:
                chunks.append("\0")
                cursor += 1
                previous = unit.sarga
            value = exact_text(unit.original, fused_locator=(book, unit.sarga) == (4, 54))
            if orthographic:
                value = orthographic_text(value)
            chunk = value or "\0"
            self.boundary.append(cursor)
            self.sizes.append(len(chunk))
            self.segments.append(value)
            chunks.append(chunk)
            cursor += len(chunk)
        self.text = "".join(chunks)

    def find(self, needle, basis):
        if len(needle) < MINIMUM_FINGERPRINT_LENGTH:
            return "short_or_unusable", None
        start = self.text.find(needle)
        if start < 0:
            return "absent", None
        if self.text.find(needle, start + 1) >= 0:
            return "repeated", None
        end = start + len(needle)
        first = bisect_right(self.boundary, start) - 1
        last = bisect_left(self.boundary, end) - 1
        start_in_unit = start - self.boundary[first]
        end_in_unit = end - self.boundary[last]
        partial = start_in_unit != 0 or end_in_unit != self.sizes[last]
        return "matches", Match(first, last, start_in_unit, end_in_unit, partial, basis)


def nonconflicting(positions):
    """Retain only mappings that agree in reading order with all other candidates."""
    starts = [(item.first_unit, item.start_in_unit) if item else None for item in positions]
    ends = [(item.last_unit, item.end_in_unit) if item else None for item in positions]
    earliest_ahead = [None] * len(starts)
    earliest = None
    for index in range(len(starts) - 1, -1, -1):
        earliest_ahead[index] = earliest
        if starts[index] is not None:
            earliest = starts[index] if earliest is None else min(earliest, starts[index])
    latest = None
    safe = []
    for index, (start, end) in enumerate(zip(starts, ends)):
        if start is not None:
            ahead = earliest_ahead[index]
            if (latest is None or latest <= start) and (ahead is None or end <= ahead):
                safe.append(index)
            latest = end if latest is None else max(latest, end)
    return set(safe)


def approximate_source_issues(rows):
    """Find exact-reused Dutt passages flagged approximate or noncontiguous by the source."""
    references = defaultdict(list)
    for i, row in enumerate(rows):
        for ref in row["alignment"]["duttRefs"]:
            references[ref].append(i)
    issues = {}
    for indices in references.values():
        if not all(rows[i]["alignment"]["type"] != "approximate" for i in indices):
            for i in indices:
                issues[i] = "source_approximate"
        elif indices != list(range(indices[0], indices[-1] + 1)):
            for i in indices:
                issues[i] = "source_group_noncontiguous"
    return issues


def source_passages(rows):
    """Keep common Dutt prose shared by consecutive CE coordinates as one passage."""
    uncertain = approximate_source_issues(rows)
    index = 0
    while index < len(rows):
        row = rows[index]
        witness = row["alignment"]
        key = (row["english"], witness["type"], tuple(witness["duttRefs"]))
        end = index + 1
        if witness["type"] == "grouped":
            while end < len(rows):
                following = rows[end]
                alignment = following["alignment"]
                if (following["english"], alignment["type"], tuple(alignment["duttRefs"])) != key:
                    break
                end += 1
        group = rows[index:end]
        issues = sorted({uncertain[i] for i in range(index, end) if i in uncertain})
        if witness["type"] == "grouped" and len(group) == 1 and not issues:
            issues = ["source_group_incomplete"]
        yield group, issues
        index = end


def map_book(units, rows, book, slug):
    exact = ArchiveText(units, book)
    nasal = ArchiveText(units, book, orthographic=True)
    candidates = []
    statuses = []
    entries = list(source_passages(rows))
    for group, issues in entries:
        text = "".join(exact_text(row["sanskrit"]) for row in group)
        if issues:
            status, result = issues[0], None
        elif any(not exact_text(row["sanskrit"]) for row in group):
            status, result = "unusable_sanskrit", None
        else:
            status, result = exact.find(text, "formatting-only Sanskrit match")
            if status == "absent":
                status, result = nasal.find(orthographic_text(text), "homorganic nasal spelling match")
        candidates.append(result)
        statuses.append(status)
    safe = nonconflicting(candidates)
    counts = Counter()
    covered = set()
    mapped = defaultdict(list)
    orthographic = defaultdict(list)
    source_issues = defaultdict(list)
    for i, ((group, _), hit, status) in enumerate(zip(entries, candidates, statuses)):
        coordinates = [row["id"] for row in group]
        if hit is not None and i not in safe:
            hit, status = None, "conflicts_with_reading_order"
        if hit is None:
            for row in group:
                source_issues[str(row["sarga"])].append({"id": row["id"], "reason": status})
            counts[status] += len(group)
            continue
        matching = units[hit.first_unit:hit.last_unit + 1]
        sarga = matching[0].sarga
        if any(row.sarga != sarga for row in matching):
            raise ValueError("Sanskrit match crossed a chapter delimiter")
        row = {
            "id": coordinates[0],
            "refs": coordinates,
            "method": "exact_compact" if hit.basis.startswith("formatting") else "orthographic_nasal",
            "units": [u.anchor for u in matching],
            "unit_sha256": [u.sha256 for u in matching],
            "partially_covers_archive_unit": hit.partial,
        }
        if row["method"] == "orthographic_nasal":
            orthographic[f"{slug}/{sarga}"].append(row)
            counts["orthographic_candidate_verses"] += len(group)
            for source in group:
                source_issues[str(source["sarga"])].append({"id": source["id"], "reason": "nasal_spelling_difference"})
            continue
        counts["matched_source_verses"] += len(group)
        counts["matched_source_passages"] += 1
        counts["partial_matches"] += hit.partial
        covered.update(range(hit.first_unit, hit.last_unit + 1))
        mapped[f"{slug}/{sarga}"].append(row)
    unmatched = defaultdict(list)
    for i, unit in enumerate(units):
        if i not in covered:
            unmatched[f"{slug}/{unit.sarga}"].append(unit.anchor)
    counts["archive_reading_units"] = len(units)
    counts["archive_units_with_witness"] = len(covered)
    counts["archive_units_unmatched"] = len(units) - len(covered)
    return mapped, orthographic, unmatched, source_issues, counts


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--critical-dir", required=True, type=Path)
    parser.add_argument("--archive-snapshot", required=True, type=Path)
    parser.add_argument("--supplements", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.critical_dir / "manifest-all.json").read_text(encoding="utf-8"))
    by_book = {book["order"]: book for book in manifest["kandas"]}
    chapters, orthographic_review, gaps, coverage, exclusions = {}, {}, {}, {}, {}
    for slug, book, units in read_archive(args.archive_snapshot, args.supplements):
        source = read_critical_book(args.critical_dir, by_book[book])
        mapped, orthographic, unmatched, issues, counts = map_book(units, source, book, slug)
        # The public crosswalk contains no Sanskrit and is pinned to existing archive block hashes.
        chapters.update((key, mapped.get(key, []))
                        for key in (f"{slug}/{sarga}" for sarga in range(1, ARCHIVE_COUNTS[book - 1] + 1)))
        orthographic_review.update(orthographic)
        gaps.update(unmatched)
        coverage[slug] = dict(counts)
        exclusions[by_book[book]["id"]] = issues
    result = {
        "schema_version": 1,
        "description": "Historical English witness transferred by unique full Sanskrit text match within one book, subject to source grouping and agreement in reading order.",
        "coverage": coverage,
        "critical_exclusions": exclusions,
        "chapters": chapters,
        "orthographic_candidates": orthographic_review,
        "archive_unmatched_units": gaps,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps(coverage, ensure_ascii=False))


if __name__ == "__main__":
    main()
