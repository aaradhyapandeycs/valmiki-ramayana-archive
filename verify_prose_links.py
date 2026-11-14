#!/usr/bin/env python3
"""Independently check every original-English source control in a static build."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit


BOOKS = {"baala": 77, "ayodhya": 119, "aranya": 75, "kish": 67, "sundara": 68, "yuddha": 128}
WITNESSES = {"valmikiramayan.net", "www.valmikiramayan.net"}
BASIS = {"printed_translation_reference", "anchored_sanskrit_reference"}
REF = re.compile(r"([1-6])-([1-9][0-9]{0,2})-([1-9][0-9]{0,2})([a-d]?)")
FRAGMENT = re.compile(r"Verse[0-9]{1,3}", re.I)
UNIT = re.compile(r"(?:verse|block|source-paragraph)-[0-9]+$")
DIGEST = re.compile(r"[0-9a-f]{64}$")
PRINTED_LOCATOR = re.compile(r"(?<![0-9-])([0-9]{1,3}) *[-–] *([0-9]{1,3}) *[-–] *([0-9]{1,3})"
                             r"(?: *[-–] *([0-9]{1,3}))?(?![0-9-])")
DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
# Independent observations from the pinned Sanskrit corpus and Yuddha's
# restored paragraphs. Include the canonical book/chapter and source sequence.
PRINTED_PREFIX = {
    (3, 16): (4, 16, 43),
    (3, 28): (4, 28, 33),
    (3, 39): (4, 39, 25),
    (3, 66): (4, 66, 21),
    (6, 87): (87, 6, 30),
    (6, 88): (88, 6, 79),
    (6, 89): (89, 6, 54),
    (6, 90): (90, 6, 97),
    (6, 91): (91, 6, 28),
    (6, 92): (92, 6, 68),
    (6, 94): (94, 6, 41),
}


def require(condition, error):
    if not condition:
        raise ValueError(error)


def classes(node):
    return node.get("class", "").split()


def meaningful(node):
    return " ".join(part for part in " ".join(node.itertext()).split())


def group_key(group):
    return group["href"], tuple(group["refs"]), group["basis"]


def expanded(refs, book, chapter):
    """Verify complete nonduplicated source references independently of the renderer."""
    intervals = []
    for ref in refs:
        points = [REF.fullmatch(point) for point in ref.split("–")]
        require(1 <= len(points) <= 2 and all(points), f"malformed locator {ref}")
        require(all((int(point[1]), int(point[2])) == (book, chapter) for point in points),
                f"wrong text edition coordinate {ref}")
        first, last = int(points[0][3]), int(points[-1][3])
        a, b = points[0][4], points[-1][4]
        start = first * 4 + ("abcd".index(a) if a else 0)
        finish = last * 4 + ("abcd".index(b) if b else 3)
        require(finish >= start and (not intervals or start > intervals[-1][1]),
                f"out-of-order or repeated locator {ref}")
        intervals.append((start, finish))
    require(bool(intervals), "empty source references")
    return {point // 4 for start, finish in intervals for point in range(start, finish + 1)}


def source_groups(metadata, book, chapter):
    source = urlsplit(metadata["source_url"])
    require(source.scheme == "https" and source.netloc in WITNESSES and not source.fragment,
            f"invalid original witness {source.geturl()}")
    stated = {}
    for group in metadata["groups"]:
        fragment = group["fragment"]
        require(FRAGMENT.fullmatch(fragment), f"invalid witness fragment {fragment}")
        require(group["basis"] in BASIS, f"unrecognized verification basis {group['basis']}")
        require(set(group["verse_numbers"]) == expanded(group["refs"], book, chapter),
                f"group verse list disagrees with its labels {group['refs']}")
        require(DIGEST.fullmatch(group["paragraph_sha256"]), "missing original paragraph digest")
        require(all(key in {"fragment", "refs", "verse_numbers", "source_sanskrit_refs",
                            "source_sanskrit_sha256", "paragraph_sha256", "ordinal", "basis", "label"}
                    for key in group), f"unexpected field in metadata {fragment}")
        label = group.get("label")
        require(label is None or re.fullmatch(r"[1-9][0-9a-d,;\.\s–—&-]*(?:(?:and|to)[0-9a-d,;\.\s–—&-]*)*",
                                              label, re.I),
                f"non-reference data in metadata label: {fragment}")
        href = metadata["source_url"] + "#" + fragment
        stated[href, tuple(group["refs"]), group["basis"]] = group
    return stated


def checked_units(reader):
    return [node for node in reader.iter()
            if (node.get("id") and UNIT.fullmatch(node.get("id"))
                and ("verse" in classes(node) or node.tag == "aside"
                     and node.get("aria-label") == "Source verse passage"))]


def printed_verses(node, book, chapter):
    """Read locator numerals in the already-verified Devanāgarī DOM, never its IDs."""
    script = [p for p in node.iter() if p.get("lang") == "sa-Deva"]
    require(len(script) == 1, f"missing Sanskrit text in {node.get('id')}")
    text = meaningful(script[0]).translate(DEVANAGARI_DIGITS)
    witnesses = set()
    alternate = PRINTED_PREFIX.get((book, chapter))
    order = alternate[:2] if alternate else (book, chapter)
    for b, s, first, final in PRINTED_LOCATOR.findall(text):
        if (int(b), int(s)) == order and 0 < int(first) <= int(final or first) <= int(first) + 75:
            witnesses.update(range(int(first), int(final or first) + 1))
    if not witnesses and (book, chapter) == (4, 54):
        witnesses.update(map(int, re.findall(r"[|।॥] *454([0-9]{1,3})(?![0-9])", text)))
    return witnesses


def inspect_cards(reader, nodes, groups, source, book, chapter):
    ancestors = {child: parent for parent in reader.iter() for child in parent}
    positions = {node.get("id"): i for i, node in enumerate(nodes)}
    observed = {node.get("id"): printed_verses(node, book, chapter) for node in nodes}
    alternate = PRINTED_PREFIX.get((book, chapter))
    if alternate:
        ordered = [number for witnesses in observed.values() for number in sorted(witnesses)]
        require(ordered == list(range(1, alternate[2] + 1)),
                f"reviewed printed sequence has changed in {book}.{chapter}")
    locations = {}
    for unit, witnesses in observed.items():
        for number in witnesses:
            locations.setdefault(number, []).append(unit)
    cards = [node for node in reader.iter() if "verse-translation" in classes(node)]
    links = set()
    coverage = set()
    assigned = {group_key(group): group for group in groups}
    require(len(assigned) == len(groups), "duplicate mapped reference group")
    for card in cards:
        pair = ancestors[card]
        require("verse-pair" in classes(pair) and len(pair) == 2 and pair[1] == card
                and "verse-pair-source" in classes(pair[0]), "Sanskrit must precede its English card")
        require(card.get("lang") == "en" and len(card) == 2
                and card[0].tag == "p" and "verse-translation-label" in classes(card[0])
                and meaningful(card[0]) == "English translation" and card[1].tag == "ul",
                "English card contains unexpected content")
        require(not (card.text or "").strip() and not (card[0].tail or "").strip()
                and not (card[1].text or "").strip(), "unexpected card prose")
        pair_units = checked_units(pair[0])
        require(bool(pair_units), "empty local Sanskrit side")
        local = [node.get("id") for node in pair_units]
        for li in card[1]:
            require(li.tag == "li" and len(li) == 1 and li[0].tag == "a" and not li[0]
                    and not (li.text or "").strip() and not (li[0].tail or "").strip()
                    and not (li.tail or "").strip(),
                    "source card list contains more than a link")
            anchor = li[0]
            key = (anchor.get("href"), tuple(anchor.get("data-source-refs", "").split()),
                   anchor.get("data-prose-basis"))
            require(key in assigned and key in source, f"unrecorded source link {key}")
            require(key not in links, f"repeated source group {key}")
            labels = ", ".join(key[1])
            caption = "Source passage" if key[2] == "anchored_sanskrit_reference" else "Read at the source"
            require(meaningful(anchor) == f"{labels} · {caption} ↗",
                    f"unexpected source link label {key}")
            group = assigned[key]
            intended = group["units"]
            require(bool(intended) and intended[0] == local[0], f"source link has the wrong first Sanskrit block {key}")
            start, end = positions[intended[0]], positions[intended[-1]]
            require(intended == [node.get("id") for node in nodes[start:end + 1]],
                    f"mapped units are not in Sanskrit reading order {key}")
            if intended != local[:len(intended)]:
                # Adjacent source translations can share a final/start half. In
                # such a connected run each link aligns with its own start.
                require(len(local) == 1 and "verse-connected-group" in classes(ancestors[pair]),
                        f"unsplit source group is not in the same reader row {key}")
                connected = {node.get("id") for node in checked_units(ancestors[pair])}
                overlap = any(
                    other["units"] != intended
                    and set(other["units"]) & set(intended)
                    and set(other["units"]) <= connected
                    for other in groups
                )
                require(set(intended) <= connected and overlap,
                        f"short visual group has no overlapping source coverage {key}")
            numbers = source[key]["verse_numbers"]
            require(all(len(locations.get(number, ())) == 1 and locations[number][0] in intended
                        for number in numbers)
                    and all(set(numbers) & observed[unit] for unit in intended),
                    f"source references do not identify the displayed Sanskrit units {key}")
            coverage.update(intended)
            links.add(key)
    require(links == set(assigned), "mapped groups absent from rendered HTML")
    require(len(links) == len([node for node in reader.iter("a") if node.get("data-source-refs")]),
            "found translation references outside English cards")
    return coverage, len(cards)


def verify(args):
    sys.path.insert(0, str(args.build_root))
    from audit_source_text import check_rendered, parse

    source_metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    audit = json.loads((args.dist / "prose-links-audit.json").read_text(encoding="utf-8"))
    snapshot = args.snapshot
    additions = json.loads(args.supplements.read_text(encoding="utf-8"))
    chapters = [f"{slug}/{number}" for slug, count in BOOKS.items() for number in range(1, count + 1)]
    for label, data in (("source index", source_metadata), ("published matching report", audit)):
        require(set(data["chapters"]) == set(chapters), f"{label} is missing or adding chapters")
    counts = Counter()
    examples = {}
    for chapter_path in chapters:
        slug, chapter = chapter_path.split("/")
        book, chapter = list(BOOKS).index(slug) + 1, int(chapter)
        metadata = source_metadata["chapters"][chapter_path]
        report = audit["chapters"][chapter_path]
        record = json.loads((snapshot / chapter_path).with_suffix(".json").read_text(encoding="utf-8"))
        require(metadata["source_url"] == record["source_url"], f"source edition mismatch {chapter_path}")
        if report.get("source_url"):
            require(report["source_url"] == record["source_url"], f"report edition mismatch {chapter_path}")
        original_groups = source_groups(metadata, book, chapter)
        raw = (args.dist / chapter_path / "index.html").read_bytes()
        reported_text = check_rendered(record, raw, additions.get(chapter_path, ()))
        require(reported_text == "matched", f"{chapter_path}: {reported_text}")
        document = parse(raw)
        reader = next(node for node in document.iter("section") if node.get("id") == "sanskrit")
        nodes = checked_units(reader)
        mapped = report["mapped_groups"]
        covered, cards = inspect_cards(reader, nodes, mapped, original_groups, book, chapter)
        unmatched = [node.get("id") for node in nodes if node.get("id") not in covered]
        require(report["unmatched_units"] == unmatched, f"unmatched unit list differs from reader {chapter_path}")
        counts["chapters"] += 1
        counts["chapters_with_links"] += bool(mapped)
        counts["source_groups"] += len(metadata["groups"])
        counts["mapped_groups"] += len(mapped)
        counts["link_panels"] += cards
        counts["local_units"] += len(nodes)
        counts["covered_units"] += len(covered)
        counts["unmatched_units"] += len(unmatched)
        counts["partial_reference_groups"] += sum(any(re.search(r"[a-d]", ref) for ref in group["refs"])
                                                   for group in mapped)
        counts["multi_unit_groups"] += sum(len(group["units"]) > 1 for group in mapped)
        if mapped and slug not in examples:
            examples[slug] = {"chapter": chapter_path, "link": mapped[0]}
    require(len(examples) == 6, "an entire kāṇḍa has no English source controls")
    print(json.dumps({"counts": dict(counts), "examples": examples}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-root", type=Path, default=Path.cwd())
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--metadata", type=Path, default=Path("data/prose-links.json"))
    parser.add_argument("--snapshot", type=Path, default=Path("data/sanskrit"))
    parser.add_argument("--supplements", type=Path, default=Path("data/sanskrit-paratext-reviewed.json"))
    verify(parser.parse_args())


if __name__ == "__main__":
    main()
