#!/usr/bin/env python3
"""Capture the published Critical Edition's Dutt English witness and audit evidence."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from math import isfinite
from pathlib import Path
import re
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

HOST = "valmiki-ramayana-path.aaradhyapandeycs.chatgpt.site"
ORIGIN = f"https://{HOST}"
VERSION = "d67bc6bc34071005cf412597865f8f63ba777be3"
KANDAS = (
    ("bala", 76, 1941),
    ("ayodhya", 111, 3160),
    ("aranya", 71, 2060),
    ("kishkindha", 66, 1987),
    ("sundara", 66, 2487),
    ("yuddha", 116, 4436),
    ("uttara", 100, 2690),
)
ALIGNMENTS = {"1:1": 12624, "split": 725, "grouped": 5153, "approximate": 259}
RETRYABLE = {408, 429, 500, 502, 503, 504}
MAX_RESPONSE_BYTES = 2_000_000
SANSKRIT_MARKS = re.compile(r"[।॥|0-9०-९\s]+")
HOMORGANIC_NASALS = re.compile(
    r"(?:ङ्(?=[कखगघङ])|ञ्(?=[चछजझञ])|ण्(?=[टठडढण])|"
    r"न्(?=[तथदधन])|म्(?=[पफबभम]))"
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def fingerprints(sanskrit):
    normalized = unicodedata.normalize("NFC", sanskrit)
    compact = SANSKRIT_MARKS.sub("", normalized)
    nasal = HOMORGANIC_NASALS.sub("ं", compact)
    return {name: sha256(value.encode("utf-8")) for name, value in (
        ("exact", normalized), ("compact", compact), ("nasal", nasal)
    )}


def fetch(relative, local):
    if local:
        return (local / relative).read_bytes()
    url = f"{ORIGIN}/data/{relative}"
    for attempt in range(4):
        try:
            request = Request(url, headers={"Accept": "application/json", "User-Agent": "RamayanaArchive/1.0"})
            with urlopen(request, timeout=22) as response:
                final = urlsplit(response.geturl())
                require(final.scheme == "https" and final.netloc == HOST and
                        final.path == f"/data/{relative}", f"Unexpected redirect from {url}")
                require(response.headers.get_content_type() == "application/json", f"Unexpected media type for {url}")
                data = response.read(MAX_RESPONSE_BYTES + 1)
                require(len(data) <= MAX_RESPONSE_BYTES, f"Oversize response from {url}")
                return data
        except HTTPError as error:
            if error.code not in RETRYABLE or attempt == 3:
                raise
        except (URLError, TimeoutError):
            if attempt == 3:
                raise
        time.sleep(0.5 * (2 ** attempt))
    raise AssertionError(f"No fetch result for {url}")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def load_chapter(item, local, output, raw_dir):
    book, slug, chapter, expected_count = item
    relative = f"{slug}/sarga-{chapter}.json"
    raw = fetch(relative, local)
    decoded = json.loads(raw)
    require(isinstance(decoded, list) and len(decoded) == expected_count, f"Wrong record count: {relative}")
    result = []
    alignment_counts = Counter()
    for verse, row in enumerate(decoded, 1):
        expected_id = f"VRCE-{book}-{chapter}-{verse}"
        require((row["id"], row["kanda"], row["kandaId"], row["sarga"], row["verse"])
                == (expected_id, book, slug, chapter, verse), f"Unexpected coordinate: {relative} #{verse}")
        require(isinstance(row["english"], str) and row["english"].strip(), f"No English text at {expected_id}")
        require(isinstance(row["sanskrit"], str) and row["sanskrit"].strip(), f"No Sanskrit at {expected_id}")
        alignment = row["alignment"]
        kind = alignment["type"]
        require(kind in ALIGNMENTS and alignment["status"] == "unreviewed", f"Invalid review status at {expected_id}")
        confidence = alignment["confidence"]
        require(isinstance(confidence, (int, float)) and isfinite(confidence) and 0 <= confidence <= 1,
                f"Invalid confidence at {expected_id}")
        refs = alignment["duttRefs"]
        require(isinstance(refs, list) and refs and all(
            re.fullmatch(rf"DUTT-{book}-\d+-\d+", ref) for ref in refs
        ), f"Invalid Dutt references at {expected_id}")
        source = row["source"]
        require(source["englishEdition"] == "M. N. Dutt 1891–94", f"Unrecognized English provenance at {expected_id}")
        require(source["sanskritLocator"] == f"{book}{chapter:03d}{verse:03d}"
                and source["sanskritFile"] == f"Ram{book:02d}.txt", f"Wrong source locator at {expected_id}")
        result.append({
            **{key: row[key] for key in ("id", "kanda", "kandaId", "sarga", "verse", "english")},
            "alignment": {key: alignment[key] for key in ("type", "confidence", "method", "duttRefs", "status")},
            "source": {key: source[key] for key in ("sanskritLocator", "sanskritFile", "englishEdition")},
            "sanskrit_fingerprints": fingerprints(row["sanskrit"]),
        })
        alignment_counts[kind] += 1
    write_json(output / relative, result)
    if raw_dir:
        path = raw_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return relative, sha256(raw), alignment_counts, [row["id"] for row in result]


def capture(output, local=None, raw_dir=None, workers=10):
    manifest_raw = fetch("manifest-all.json", local)
    manifest = json.loads(manifest_raw)
    source_manifest_raw = fetch("source-manifest.json", local)
    sources = json.loads(source_manifest_raw)
    require(manifest["schemaVersion"] == 3 and (manifest["totalSargas"], manifest["totalVerses"]) == (606, 18761),
            "Source site's published edition counts changed")
    require((sources["sargaCount"], sources["recordCount"]) == (606, 18761)
            and sources["rawHashes"] == manifest["qa"]["rawSourceHashes"], "Source manifests disagree")
    require(manifest["qa"]["alignmentCounts"] == ALIGNMENTS
            and manifest["qa"]["translationReviewStatus"] == "unreviewed", "Translation QA status or counts changed")
    actual_kandas = [(row["id"], row["sargaCount"], row["verseCount"]) for row in manifest["kandas"]]
    require(actual_kandas == list(KANDAS), "Source site book inventory changed")
    tasks = []
    for index, row in enumerate(manifest["kandas"], 1):
        require(row["order"] == index, f"Unexpected book number: {row['id']}")
        actual_sargas = [c["sarga"] for c in row["sargas"]]
        require(actual_sargas == list(range(1, row["sargaCount"] + 1)), f"Sarga sequence changed: {row['id']}")
        require(sum(c["count"] for c in row["sargas"]) == row["verseCount"], f"Incorrect verse count: {row['id']}")
        tasks.extend((index, row["id"], c["sarga"], c["count"]) for c in row["sargas"])
    hashes, ids, counts = {}, [], Counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for relative, checksum, alignment, coordinates in pool.map(
            lambda task: load_chapter(task, local, output, raw_dir), tasks
        ):
            hashes[relative] = checksum
            ids.extend(coordinates)
            counts.update(alignment)
    require(len(hashes) == 606 and len(ids) == len(set(ids)) == 18761 and counts == ALIGNMENTS,
            "Site data does not agree with its advertised alignment totals")
    coordinate_hash = sha256("\n".join(ids).encode("utf-8"))
    require(coordinate_hash == manifest["qa"]["generatedIdsSha256"],
            "Site data's complete coordinate hash does not match the source manifest")
    if raw_dir:
        (raw_dir / "manifest-all.json").write_bytes(manifest_raw)
        (raw_dir / "source-manifest.json").write_bytes(source_manifest_raw)
    write_json(output / "manifest-all.json", {
        **{key: manifest[key] for key in ("schemaVersion", "totalVerses", "totalSargas", "kandas")},
        "edition": {key: manifest["edition"][key] for key in ("sanskrit", "english")},
        "qa": manifest["qa"],
    })
    write_json(output / "source-manifest.json", {
        **{key: sources[key] for key in ("generatedFrom", "rawHashes", "recordCount", "sargaCount")},
        "statement": "M. N. Dutt's historical English witness aligned to Baroda Critical Edition coordinates; the alignment is unreviewed.",
    })
    audit = {
        "origin": ORIGIN, "sourceSiteCommit": VERSION,
        "source": "local files" if local else "direct original Site HTTP",
        "sargas": 606, "coordinates": 18761, "alignmentCounts": dict(counts),
        "coordinateSHA256": coordinate_hash,
        "rawManifestSHA256": sha256(manifest_raw), "rawSourceManifestSHA256": sha256(source_manifest_raw),
        "rawChapterSHA256": hashes,
        "export": "English witness, coordinates, provenance and Sanskrit fingerprints",
    }
    write_json(output / "capture-audit.json", audit)
    print(json.dumps({key: audit[key] for key in ("sargas", "coordinates", "alignmentCounts")}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--local-data", type=Path)
    parser.add_argument("--raw-dir", type=Path)
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()
    capture(args.output, args.local_data, args.raw_dir, args.workers)


if __name__ == "__main__":
    main()
