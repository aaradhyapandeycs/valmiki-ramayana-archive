#!/usr/bin/env python3
"""Convert inspected source URLs into deterministic, provenance-aware chapter groups.

Usage: python3 build_variant_inventory.py audit/primary frames.json variants.json
The result links to original files while reporting whether each file was merely
listed or its response was checked by the inventory.
"""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote, urlsplit

CHAPTER = re.compile(
    r"^/(?P<utf8>utf8/)?(?P<book>baala|ayodhya|aranya|kish|sundara|yuddha)"
    r"/(?P<nested>ayodhya/)?sarga(?P<number>[0-9]+)(?:/|$)"
)
SARGA_DIRECTORY = re.compile(r"/sarga[0-9]+/$")
SOURCE_HOSTS = {"valmikiramayan.net", "www.valmikiramayan.net"}
CURRENT_PANES = {
    "devanagari": "Devanagari Sanskrit and English",
    "roman": "Romanized Sanskrit and English",
    "itrans": "ITRANS and English",
    "prose": "English prose",
}
LABELS = {
    **CURRENT_PANES,
    "frame": "Chapter frame",
    "footer": "Chapter controls",
    "directory": "Source directory",
    "download": "Source download or media",
    "backup": "Source backup",
    "other": "Other source file",
}


def source_path(url):
    """Recognize original-source URLs and ignore directory sort links."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or parts.hostname not in SOURCE_HOSTS:
        return None
    if parts.fragment or re.fullmatch(r"C=[^;]+;O=[^;]+", parts.query):
        return None
    return unquote(parts.path)


def file_kind(path):
    name = path.rsplit("/", 1)[-1].lower()
    if name.endswith((".old", ".bak", ".orig", "~")):
        return "backup"
    if path.endswith("/"):
        return "directory"
    if name.endswith((".htm", ".html", ".shtml")):
        stem = name.rsplit(".", 1)[0]
        for token, kind in (
            ("_frame", "frame"), ("_footer", "footer"), ("_prose", "prose"),
            ("itrans", "itrans"), ("roman", "roman"), ("sans", "devanagari"),
        ):
            if token in stem:
                return kind
    if name.endswith((".pdf", ".zip", ".mp3", ".wav", ".png", ".jpg", ".jpeg", ".gif", ".ttf")):
        return "download"
    return "other"


def read_audit(path):
    segments = sorted((path / "segments").glob("*.json"))
    if not segments:
        raise ValueError(f"No inventory segments in {path}")
    records = {}
    for segment in segments:
        for record in json.loads(segment.read_text(encoding="utf-8")):
            url = record["source_url"]
            if url in records:
                raise ValueError(f"Duplicate inventory response {url}")
            records[url] = record
    from_to = defaultdict(set)
    with (path / "edges.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            edge = json.loads(line)
            source = edge["from"]
            target = edge["to"]
            if source != target and source_path(target):
                from_to[target].add(source)
    return records, from_to


def make_inventory(records, links, frames):
    chapter_frames = frames["books"]
    indexed = {
        f"{book}/{number}": row
        for book, item in chapter_frames.items()
        for number, row in item["chapters"].items()
    }
    groups = defaultdict(list)
    directories = set()
    current_panes = defaultdict(set)
    # A failed guessed request has no discovery evidence unless it also appeared
    # in an actual source link. This avoids treating absent guesses as content.
    checked = {url for url, row in records.items() if row["status"] == "http_200"}
    for url in sorted(set(links) | checked):
        path = source_path(url)
        match = CHAPTER.match(path) if path else None
        if not match:
            continue
        tree = "utf8" if match["utf8"] else "original"
        key = f"{match['book']}/{int(match['number'])}"
        placement = "nested" if match["nested"] else tree
        kind = file_kind(path)
        record = records.get(url, {})
        listed_from = sorted(
            source for source in links.get(url, ())
            if (directory := source_path(source)) and directory.endswith("/")
            and (path.startswith(directory) or directory == path)
        )
        row = {
            "url": url,
            "tree": placement,
            "kind": kind,
            "label": LABELS[kind],
            "status": record.get("status", "listed_not_fetched"),
        }
        if listed_from or url in links:
            row["linked_from"] = (listed_from or sorted(links[url]))[0]
        if record.get("final_url") and record["final_url"] != url:
            row["final_url"] = record["final_url"]
        groups[key].append(row)
        if kind == "directory" and SARGA_DIRECTORY.search(path) and placement == tree:
            # A directory response without any child links may be an HTTP 200
            # soft block. Coverage therefore requires actual listing evidence.
            if record.get("status") == "http_200":
                directories.add((placement, key, url))
        if kind in CURRENT_PANES and (listed_from or record.get("status") == "http_200"):
            current_panes[(placement, key)].add(kind)

    sources_with_children = {
        source
        for target, sources in links.items()
        for source in sources
        if source_path(source) and source_path(target).startswith(source_path(source))
        and source_path(source) != source_path(target)
    }
    present_dirs = {(tree, key) for tree, key, url in directories if url in sources_with_children}
    coverage = {}
    for tree in ("original", "utf8"):
        missing = [key for key in indexed if (tree, key) not in present_dirs]
        coverage[tree] = {
            "chapter_directories_with_observed_children": len(indexed) - len(missing),
            "missing_chapter_directories": missing,
            "chapters_with_all_four_reading_panes": sum(
                CURRENT_PANES.keys() <= current_panes[(tree, key)] for key in indexed
            ),
        }

    return {
        "schema_version": 1,
        "coverage": coverage,
        "chapters": dict(groups),
        "auxiliary_chapters": sorted(set(groups) - set(indexed)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit", type=Path)
    parser.add_argument("frames", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    records, links = read_audit(args.audit)
    frames = json.loads(args.frames.read_text(encoding="utf-8"))
    inventory = make_inventory(records, links, frames)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(inventory, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print({
        "groups": len(inventory["chapters"]),
        "auxiliary_chapters": inventory["auxiliary_chapters"],
        "checked_chapter_directories": {
            tree: row["chapter_directories_with_observed_children"]
            for tree, row in inventory["coverage"].items()
        },
    })


if __name__ == "__main__":
    main()
