#!/usr/bin/env python3
"""Check every rendered Dutt witness against the captured Critical Edition source."""

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re

try:
    import html5lib
except ImportError:
    from pip._vendor import html5lib


BOOKS = (
    ("bala", 76, 1941),
    ("ayodhya", 111, 3160),
    ("aranya", 71, 2060),
    ("kishkindha", 66, 1987),
    ("sundara", 66, 2487),
    ("yuddha", 116, 4436),
    ("uttara", 100, 2690),
)
ARCHIVE_BOOKS = {"baala": 77, "ayodhya": 119, "aranya": 75, "kish": 67, "sundara": 68, "yuddha": 128}
ALIGNMENTS = {"1:1": 12624, "split": 725, "grouped": 5153, "approximate": 259}
BENGALI = re.compile(r"[\u0980-\u09ff]")
FORMATTING = re.compile(r"[\t\r\n\f \u00a0]+")
LOCAL_ANCHOR = re.compile(r"(?:verse|block|source-paragraph)-[0-9]+$")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def contents(node):
    return "".join(node.itertext())


def has_class(node, token):
    return token in node.get("class", "").split()


def parse(contents_bytes):
    return html5lib.parse(
        contents_bytes.decode("utf-8"), treebuilder="etree", namespaceHTMLElements=False
    )


def check_source_file(path, relative, audit, expected):
    bytes_ = (path / relative).read_bytes()
    require(sha256(bytes_).hexdigest() == audit["rawChapterSHA256"][relative],
            f"{relative}: raw published source hash changed")
    source = json.loads(bytes_)
    require(len(source) == len(expected), f"{relative}: original page count changed")
    for raw, record in zip(source, expected):
        coordinate = record["id"]
        for key in ("id", "kanda", "kandaId", "sarga", "verse", "english", "alignment"):
            require(raw[key] == record[key], f"{coordinate}: imported {key} differs from original Site")
        for key in ("englishEdition", "sanskritFile", "sanskritLocator"):
            require(raw["source"][key] == record["source"][key],
                    f"{coordinate}: imported provenance differs from original Site")


def check_chapter(raw, expected, book, sarga, slug, counts):
    expected_url = f"critical/{slug}/{sarga}/"
    document = parse(raw)
    main = next(document.iter("main"), None)
    require(main is not None, f"{expected_url} missing main reader content")
    require(not BENGALI.search(contents(main)), f"{expected_url} contains unwanted Bengali text")

    all_nodes = list(main.iter())
    identifiers = defaultdict(list)
    for node in all_nodes:
        if node.get("id"):
            identifiers[node.get("id")].append(node)
    rows = [node for node in all_nodes if node.get("data-critical-coordinate")]
    targets = [node for node in all_nodes if has_class(node, "critical-english-text")]
    require(len(rows) == len(expected), f"{expected_url} wrong rendered coordinate count")
    require("Dutt" in contents(main), f"{expected_url} missing historical translation attribution")
    require("unreviewed" in contents(main).casefold() or "not reviewed" in contents(main).casefold(),
            f"{expected_url} missing review-status disclosure")

    target_indices = defaultdict(list)
    for index, (row, original) in enumerate(zip(rows, expected), 1):
        coordinate = f"VRCE-{book}-{sarga}-{index}"
        type_ = original["alignment"]["type"]
        require(original["id"] == coordinate, f"{expected_url} source order or coordinate changed")
        require(row.get("id") == coordinate == row.get("data-critical-coordinate")
                and len(identifiers[coordinate]) == 1, f"{coordinate} missing or repeated rendered anchor")
        require(row.get("data-critical-alignment") == type_,
                f"{coordinate} original alignment classification changed")
        require(row.get("data-critical-status", "unreviewed") == original["alignment"]["status"] == "unreviewed",
                f"{coordinate} original review status changed")
        refs = row.get("data-critical-dutt-refs")
        if refs is not None:
            require(refs.split() == original["alignment"]["duttRefs"], f"{coordinate} Dutt refs changed")
        key = row.get("data-critical-text-id")
        require(key and len(identifiers[key]) == 1, f"{coordinate} missing or repeated witness text target")
        witness = identifiers[key][0]
        require(has_class(witness, "critical-english-text"), f"{coordinate} wrong witness target class")
        require(contents(witness) == original["english"], f"{coordinate} verbatim English text changed")
        target_indices[key].append(index - 1)
        counts[type_] += 1

    require(set(target_indices) == {node.get("id") for node in targets},
            f"{expected_url} contains an unassociated or duplicated English passage")
    for key, indices in target_indices.items():
        if len(indices) == 1:
            continue
        require(indices == list(range(indices[0], indices[-1] + 1)),
                f"{expected_url} target {key} joins nonadjacent coordinates")
        signatures = {(expected[i]["alignment"]["type"],
                       tuple(expected[i]["alignment"]["duttRefs"]), expected[i]["english"])
                      for i in indices}
        require(len(signatures) == 1 and next(iter(signatures))[0] == "grouped",
                f"{expected_url} target {key} merged different original witness records")
        counts["shared_passages"] += 1
        counts["shared_coordinates"] += len(indices)

    counts["english_passages"] += len(targets)


def archive_entries(chapter, crosswalk, records):
    entries = {}
    for section, method in (("chapters", "exact_compact"), ("orthographic_candidates", "orthographic_nasal")):
        for group in crosswalk[section].get(chapter, ()):
            refs = tuple(group["refs"])
            require(refs and group["id"] == refs[0] and list(dict.fromkeys(refs)) == list(refs),
                    f"{chapter}: malformed source group coordinates")
            require(group["method"] == method, f"{chapter}: wrong Sanskrit comparison method")
            if group["partially_covers_archive_unit"]:
                continue
            rows = [records[ref] for ref in refs]
            types = {row["alignment"]["type"] for row in rows}
            require(len(types) == 1, f"{chapter}: crosswalk combined different alignment types")
            type_ = next(iter(types))
            if type_ in {"approximate", "split"}:
                continue
            if method == "orthographic_nasal" and (type_ != "1:1" or len(rows) != 1 or
                                              rows[0]["alignment"]["confidence"] < .85):
                continue
            prose = {row["english"] for row in rows}
            require(len(prose) == 1, f"{chapter}: crosswalk combined different English passages")
            require(refs[0] not in entries, f"{chapter}: multiple accepted matches to one source group")
            require(len(set(group["units"])) == len(group["units"]) == len(group["unit_sha256"]),
                    f"{chapter}: malformed archive block evidence")
            entries[refs[0]] = (group, rows[0])
    return entries


def check_archive_chapter(raw, entries, chapter, counts):
    document = parse(raw)
    reader = next((node for node in document.iter("section") if node.get("id") == "sanskrit"), None)
    require(reader is not None, f"{chapter}: missing archive Sanskrit reader")
    ancestors = {child: parent for parent in reader.iter() for child in parent}
    archive_units = {}
    for node in reader.iter():
        identifier = node.get("id")
        if not identifier or not LOCAL_ANCHOR.fullmatch(identifier):
            continue
        is_verse = has_class(node, "verse")
        is_supplement = node.tag == "aside" and node.get("aria-label") == "Source verse passage"
        if not is_verse and not is_supplement:
            continue
        sanskrit = [n for n in node.iter() if n.get("lang") == "sa-Deva"]
        require(len(sanskrit) == 1, f"{chapter}/{identifier}: missing Sanskrit witness")
        normalized = FORMATTING.sub(" ", contents(sanskrit[0])).strip()
        archive_units[identifier] = sha256(normalized.encode("utf-8")).hexdigest()
    positions = {unit: i for i, unit in enumerate(archive_units)}

    observed = set()
    for card in reader.iter():
        if not has_class(card, "critical-inline"):
            continue
        ref = card.get("data-critical-coordinate")
        require(ref in entries and ref not in observed, f"{chapter}: unexpected or duplicate inline Dutt match {ref}")
        group, row = entries[ref]
        require(card.get("data-critical-refs", "").split() == group["refs"], f"{chapter}/{ref}: changed CE refs")
        require(card.get("data-critical-local-units", "").split() == group["units"],
                f"{chapter}/{ref}: changed local units")
        require(card.get("data-critical-method") == group["method"], f"{chapter}/{ref}: changed match method")
        require(card.get("data-critical-alignment") == row["alignment"]["type"],
                f"{chapter}/{ref}: changed Dutt alignment")
        texts = [node for node in card.iter() if has_class(node, "critical-english-text")]
        require(len(texts) == 1 and contents(texts[0]) == row["english"],
                f"{chapter}/{ref}: changed original English")
        require([archive_units.get(unit) for unit in group["units"]] == group["unit_sha256"],
                f"{chapter}/{ref}: archive Sanskrit differs from crosswalk evidence")
        ordered = [positions[unit] for unit in group["units"]]
        require(ordered == list(range(ordered[0], ordered[-1] + 1)),
                f"{chapter}/{ref}: marked archive units are unordered")

        panel = ancestors.get(card)
        while panel is not None and not has_class(panel, "verse-translation"):
            panel = ancestors.get(panel)
        require(panel is not None, f"{chapter}/{ref}: English outside the translation panel")
        pair = ancestors.get(panel)
        require(pair is not None and has_class(pair, "verse-pair") and len(pair) == 2
                and has_class(pair[0], "verse-pair-source") and pair[1] == panel,
                f"{chapter}/{ref}: translation precedes its Sanskrit block")
        first = next((node.get("id") for node in pair[0].iter() if node.get("id") in archive_units), None)
        require(first == group["units"][0],
                f"{chapter}/{ref}: wrong Sanskrit unit is adjacent to English prose")
        observed.add(ref)
        counts[("archive_english_" + group["method"])] += 1
    require(observed == set(entries), f"{chapter}: eligible English mappings omitted from HTML")
    counts["archive_chapters_checked"] += 1
    counts["archive_chapters_with_english"] += bool(observed)
    counts["archive_english_passages"] += len(observed)


def verify_archive(dist, source, records, counts):
    crosswalk = json.loads(source.read_bytes())
    require(crosswalk["schema_version"] == 1, "Unexpected English crosswalk version")
    expected = {f"{slug}/{chapter}" for slug, count in ARCHIVE_BOOKS.items() for chapter in range(1, count + 1)}
    require(set(crosswalk["chapters"]) == expected, "English crosswalk is missing archive chapters")
    require(set(crosswalk["orthographic_candidates"]) <= expected, "English crosswalk contains unknown archive chapters")
    reviewed_path = Path(__file__).resolve().parent / "data" / "dutt-reviewed-passages.json"
    reviewed = json.loads(reviewed_path.read_bytes()) if reviewed_path.is_file() else {}
    for chapter in sorted(expected):
        entries = archive_entries(chapter, crosswalk, records)
        for review in reviewed.get(chapter, {}).get("passages", []):
            refs = review.get("replaces_critical_refs", [])
            if refs:
                original, _ = entries.pop(refs[0])
                require(original["refs"] == refs and original["units"] == review["units"],
                        f"{chapter}: reviewed Dutt correction replaces the wrong crosswalk passage")
        raw = (dist / chapter / "index.html").read_bytes()
        check_archive_chapter(raw, entries, chapter, counts)


def verify(dist, captured, raw_dir=None, crosswalk=None):
    manifest = json.loads((captured / "manifest-all.json").read_bytes())
    audit = json.loads((captured / "capture-audit.json").read_bytes())
    require((manifest["schemaVersion"], manifest["totalSargas"], manifest["totalVerses"]) == (3, 606, 18761),
            "Source manifest coverage changed")
    require(manifest["qa"]["translationReviewStatus"] == "unreviewed", "Source review status changed")
    require(audit["alignmentCounts"] == ALIGNMENTS, "Captured alignment counts differ from original report")
    require((dist / "critical/index.html").is_file(), "No Critical Edition index")
    counts = Counter()
    files = set()
    records = {}
    for book, ((slug, chapter_count, verse_count), kanda) in enumerate(zip(BOOKS, manifest["kandas"]), 1):
        require((kanda["id"], kanda["sargaCount"], kanda["verseCount"]) == (slug, chapter_count, verse_count),
                "Book inventory changed")
        require((dist / f"critical/{slug}/index.html").is_file(), f"Missing {slug} index")
        require(len(kanda["sargas"]) == chapter_count, f"Missing {slug} source sargas")
        for sarga, entry in enumerate(kanda["sargas"], 1):
            require(entry["sarga"] == sarga, f"{slug}: source sarga order changed")
            relative = f"{slug}/sarga-{sarga}.json"
            expected = json.loads((captured / relative).read_bytes())
            require(len(expected) == entry["count"], f"{relative}: source verse count changed")
            if raw_dir:
                check_source_file(raw_dir, relative, audit, expected)
            target = dist / f"critical/{slug}/{sarga}/index.html"
            check_chapter(target.read_bytes(), expected, book, sarga, slug, counts)
            files.add(target)
            records.update((row["id"], row) for row in expected)
    require(len(files) == 606 and len(manifest["kandas"]) == 7, "Incomplete sarga coverage")
    require(files == set((dist / "critical").glob("*/*/index.html")), "Unexpected Critical Edition chapter routes")
    require({type_: counts[type_] for type_ in ALIGNMENTS} == ALIGNMENTS, "Rendered alignment totals changed")
    if crosswalk:
        verify_archive(dist, crosswalk, records, counts)
    result = {"chapters": len(files), "coordinates": sum(ALIGNMENTS.values()),
              "raw_original_site_compared": raw_dir is not None, **dict(counts)}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--captured", type=Path, default=Path("data/critical-site"))
    parser.add_argument("--raw-dir", type=Path, help="Also check untouched original Site chapter responses")
    parser.add_argument("--crosswalk", type=Path, help="Check inline English on every archive chapter against this map")
    args = parser.parse_args()
    verify(args.dist, args.captured, args.raw_dir, args.crosswalk)


if __name__ == "__main__":
    main()
