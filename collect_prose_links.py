#!/usr/bin/env python3
"""Record original translation references and source links without storing prose."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.error import HTTPError, URLError

from audit_source_text import AUXILIARY_SEPARATOR, PRIMARY_HOSTS, clean, fetch, parse, plain
from ingest_sanskrit import BOOK_COUNTS, parsed_locators
from prose_coordinates import printed_coordinates, verify_uniform_coordinates


ANCHOR = re.compile(r"Verse[0-9]{1,3}", re.IGNORECASE)
END_BRACKET = re.compile(r"\[([^\[\]]+)\]\s*[.。]?\s*$")
BOOK_CHAPTER = re.compile(r"([1-9][0-9]?)\s*[-–—]\s*(\d{1,3})\s*[-–—]\s*")
NUMBER = re.compile(r"(\d{1,3})([a-d]?)(?![A-Za-z0-9])", re.IGNORECASE)
PART_ONLY = re.compile(r"[a-d](?![A-Za-z0-9])", re.IGNORECASE)
SEPARATOR = re.compile(r"\s*(,|;|\.|[-–—]|\bto\b|\band\b|&)\s*", re.IGNORECASE)
FUSED_KISH_54_SANSKRIT = re.compile(r"(?<=[|।॥])\s*454([1-9][0-9]{0,2})(?![0-9])")
FUSED_KISH_54_PROSE = re.compile(r"^454(?=[1-9][0-9]{0,2}(?![0-9]))")
DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
DEVANAGARI_LETTER = re.compile(r"[\u0904-\u0939]")
MALFORMED_TERMINAL = re.compile(r"\[\s*\d{1,2}\s*[-–—]\s*\d{1,3}\s*[-–—][^\[\]]*$")
OUTPUT_METHOD = "Detailed original UTF-8 reading pane: p.tat, printed references or unambiguous preceding Sanskrit locators; documented chapter-specific numeral formats."


def digest_text(text):
    return sha256(text.encode("utf-8")).hexdigest()


def print_reference(book, chapter, point):
    return f"{book}-{chapter}-{point[0]}{point[1]}"


def parse_reference_label(label, book, chapter, alternate=None):
    """Return ordered, explicit references, and the verse numbers they cover."""
    label = label.strip()
    prefix = BOOK_CHAPTER.match(label)
    if prefix is None or tuple(map(int, prefix.groups())) not in ((book, chapter), alternate):
        raise ValueError("wrong_chapter_reference")
    offset = prefix.end()
    points = []
    ranges = []
    connect = None
    while offset < len(label):
        token = NUMBER.match(label, offset)
        if token:
            point = int(token[1]), token[2].lower()
        else:
            token = PART_ONLY.match(label, offset)
            if token is None or not points:
                raise ValueError("unrecognized_reference")
            point = points[-1][0], token[0].lower()
        if point[0] < 1:
            raise ValueError("unrecognized_reference")
        if points and (point[0] < points[-1][0]
                       or point[0] == points[-1][0]
                       and (not point[1] or not points[-1][1] or point[1] <= points[-1][1])):
            raise ValueError("unordered_or_overlapping_reference")
        points.append(point)
        if connect in {"-", "–", "—", "to"}:
            if ranges[-1][0] != ranges[-1][1]:
                raise ValueError("unrecognized_reference_range")
            if point[0] - ranges[-1][0][0] > 20:
                raise ValueError("unrecognized_reference_range")
            ranges[-1] = (ranges[-1][0], point)
        else:
            ranges.append((point, point))
        offset = token.end()
        if offset == len(label):
            break
        separator = SEPARATOR.match(label, offset)
        if separator is None:
            raise ValueError("unrecognized_reference")
        connect = separator[1].lower()
        offset = separator.end()
        if offset == len(label):
            raise ValueError("unrecognized_reference")
    if not ranges:
        raise ValueError("unrecognized_reference")
    refs = []
    covered = set()
    for start, end in ranges:
        first = print_reference(book, chapter, start)
        last = print_reference(book, chapter, end)
        refs.append(first if first == last else f"{first}–{last}")
        covered.update(range(start[0], end[0] + 1))
    return refs, covered


def chapter_units(document):
    """Group structurally typed paragraphs under their actual named anchors."""
    units = [(None, [], [])]
    ordinal = 0
    for element in document.iter():
        if element.tag == "a":
            value = element.get("name") or element.get("id") or ""
            if ANCHOR.fullmatch(value):
                units.append((value, [], []))
        if element.tag != "p":
            continue
        ordinal += 1
        classes = element.get("class", "").casefold().split()
        if "tat" not in classes and "sansloka" not in classes:
            continue
        content = clean(plain(element))
        if not content or AUXILIARY_SEPARATOR.fullmatch(content):
            continue
        if "tat" in classes and not {"pratipada", "comment", "sansloka"} & set(classes):
            units[-1][2].append((ordinal, content))
        elif "sansloka" in classes:
            units[-1][1].append((ordinal, content))
    return units


def source_evidence(paragraphs, book, chapter, alternate=None):
    refs = []
    verse_numbers = set()
    hashes = []
    foreign = 0
    has_partial_tail = False
    for _, content in paragraphs:
        found = [(match.end(), locators) for match, locators in parsed_locators(content)]
        if (book, chapter) == (4, 54) and not found:
            found.extend((match.end(), (4, 54, int(match[1]), int(match[1])))
                         for match in FUSED_KISH_54_SANSKRIT.finditer(content.translate(DEVANAGARI_DIGITS)))
        if DEVANAGARI_LETTER.search(content):
            hashes.append(digest_text(content))
            remaining = content[found[-1][0]:] if found else content
            has_partial_tail = DEVANAGARI_LETTER.search(remaining) is not None
        if not found:
            continue
        expected = alternate or (book, chapter)
        for _, (kanda, sarga, first, last) in found:
            if (kanda, sarga) != expected:
                foreign += 1
                continue
            if not first <= last <= first + 20:
                continue
            start = f"{book}-{chapter}-{first}"
            end = f"{book}-{chapter}-{last}"
            refs.append(start if start == end else f"{start}–{end}")
            verse_numbers.update(range(first, last + 1))
    return refs, verse_numbers, hashes, foreign, has_partial_tail


def issue(ordinal, fragment, reason, refs=None):
    row = {"ordinal": ordinal, "reason": reason}
    if fragment is not None:
        row["fragment"] = fragment
    if refs:
        row["refs"] = refs
    return row


def link_metadata(document, book, chapter, source_sha256=None):
    units = chapter_units(document)
    alternate = printed_coordinates(book, chapter, source_sha256)
    if alternate:
        # Strip unrelated appendices by using only verse-anchor units. In a
        # few pages the final colophon or an editorial label also uses this
        # class but has no full verse coordinate.
        passages = (text for fragment, sanskrit, _ in units if fragment
                    for _, text in sanskrit)
        alternate = verify_uniform_coordinates(book, chapter, source_sha256, passages)
    anchor_counts = Counter(fragment.casefold() for fragment, _, _ in units if fragment)
    groups, unresolved = [], []
    seen_partial = False
    for fragment, sanskrit, translations in units:
        partial_start = seen_partial
        if fragment is not None:
            seen_partial = source_evidence(sanskrit, book, chapter, alternate)[-1]
        previous_prose = 0
        for ordinal, content in translations:
            preceding = [(position, text) for position, text in sanskrit if previous_prose < position < ordinal]
            source_refs, source_numbers, source_hashes, foreign, partial_tail = source_evidence(preceding, book, chapter, alternate)
            previous_prose = ordinal
            has_partial_start = partial_start
            if preceding:
                partial_start = partial_tail
            if fragment is None:
                unresolved.append(issue(ordinal, fragment, "no_verse_anchor"))
                continue
            if anchor_counts[fragment.casefold()] != 1:
                unresolved.append(issue(ordinal, fragment, "duplicated_verse_anchor"))
                continue
            final_bracket = END_BRACKET.search(content)
            label = final_bracket[1].strip() if final_bracket else None
            parsed_label = label
            if label and (book, chapter) == (4, 54):
                # Both Sanskrit and prose in this source chapter concatenate
                # book, sarga, and first verse digits. Preserve the source label.
                parsed_label = FUSED_KISH_54_PROSE.sub("4-54-", label, count=1)
            if parsed_label and BOOK_CHAPTER.match(parsed_label):
                try:
                    refs, numbers = parse_reference_label(parsed_label, book, chapter, alternate)
                except ValueError as error:
                    unresolved.append(issue(ordinal, fragment, str(error)))
                    continue
                if not sources_align(source_numbers, numbers, refs, partial_tail, book, chapter):
                    unresolved.append(issue(ordinal, fragment, "printed_reference_disagrees_with_unit", refs))
                    continue
                basis = "printed_translation_reference"
            elif MALFORMED_TERMINAL.search(content):
                unresolved.append(issue(ordinal, fragment, "malformed_translation_reference"))
                continue
            elif source_numbers and len(translations) == 1 and foreign == 0:
                if has_partial_start or partial_tail:
                    unresolved.append(issue(ordinal, fragment, "unlabelled_partial_boundary", source_refs))
                    continue
                if source_numbers != set(range(min(source_numbers), max(source_numbers) + 1)):
                    unresolved.append(issue(ordinal, fragment, "noncontiguous_enclosing_sanskrit_references"))
                    continue
                refs, numbers = source_refs, source_numbers
                basis = "anchored_sanskrit_reference"
                label = None
            else:
                unresolved.append(issue(ordinal, fragment, "no_unambiguous_translation_reference"))
                continue
            group = {
                "fragment": fragment,
                "refs": refs,
                "verse_numbers": sorted(numbers),
                "source_sanskrit_refs": source_refs,
                "source_sanskrit_sha256": source_hashes,
                "paragraph_sha256": digest_text(content),
                "ordinal": ordinal,
                "basis": basis,
            }
            if label is not None:
                group["label"] = label
            groups.append(group)
    return groups, unresolved, sum(len(translations) for _, _, translations in units)


def sources_align(source_numbers, translated_numbers, refs, partial_tail, book, chapter):
    """Allow an explicitly identified first half before its printed verse ending."""
    if not source_numbers or not source_numbers & translated_numbers:
        return False
    if min(translated_numbers) < min(source_numbers):
        return False
    extra = translated_numbers - source_numbers
    if not extra:
        return True
    next_number = max(source_numbers) + 1
    half = f"{book}-{chapter}-{next_number}a"
    return extra == {next_number} and partial_tail and refs[-1].split("–")[-1] == half


def capture_chapter(item, root, timeout):
    slug, chapter = item
    record = json.loads((root / slug / f"{chapter}.json").read_text(encoding="utf-8"))
    url = record["source_url"]
    result = {"source_url": url, "source_sha256": record["source_sha256"], "groups": []}
    try:
        raw = fetch(url, PRIMARY_HOSTS, timeout)
    except HTTPError as error:
        return item, result | {"status": f"http_{error.code}"}
    except (URLError, TimeoutError, ValueError):
        return item, result | {"status": "source_unavailable"}
    observed = sha256(raw).hexdigest()
    if observed != record["source_sha256"]:
        return item, result | {"status": "source_hash_changed", "observed_sha256": observed}
    groups, issues, count = link_metadata(parse(raw), record["book"], record["sarga"], observed)
    result.update(status="checked" if groups else "no_confirmed_group",
                  candidate_paragraphs=count, groups=groups, issues=issues)
    return item, result


def build_index(snapshot_root, output, workers, timeout):
    chapters = [(slug, n) for slug, count in BOOK_COUNTS.items() for n in range(1, count + 1)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = dict(pool.map(lambda item: capture_chapter(item, snapshot_root, timeout), chapters))
    coverage = Counter()
    for chapter in results.values():
        coverage[chapter["status"]] += 1
        coverage["groups"] += len(chapter["groups"])
        coverage["candidate_paragraphs"] += chapter.get("candidate_paragraphs", 0)
        for group in chapter["groups"]:
            coverage[group["basis"]] += 1
        for row in chapter.get("issues", []):
            coverage[row["reason"]] += 1
    report = {
        "schema_version": 1,
        "method": OUTPUT_METHOD,
        "coverage": dict(coverage),
        "chapters": {f"{slug}/{number}": row for (slug, number), row in results.items()},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps(coverage, ensure_ascii=False))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--snapshot", type=Path, default=Path("data/sanskrit"))
    cli.add_argument("--output", type=Path, default=Path("data/prose-links.json"))
    cli.add_argument("--workers", type=int, default=6)
    cli.add_argument("--timeout", type=int, default=20)
    args = cli.parse_args()
    build_index(args.snapshot, args.output, args.workers, args.timeout)


if __name__ == "__main__":
    main()
