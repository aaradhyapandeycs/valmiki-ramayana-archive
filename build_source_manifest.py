#!/usr/bin/env python3
"""Index observed source URLs, published equivalents, and captured text blocks."""
import argparse
from collections import Counter, defaultdict
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

from build_variant_inventory import CHAPTER, file_kind, source_path


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


class Anchors(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        self.ids.update(value for name, value in attrs if name == "id")


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def read_observations(audits):
    observations = defaultdict(list)
    discovered = defaultdict(set)
    inventory = []
    for audit in audits:
        if not (audit / "summary.json").is_file():
            continue
        summary = read_json(audit / "summary.json")
        inventory.append({
            "snapshot": audit.name,
            "scope": summary.get("discovery_scope", "Legacy seed diagnostic"),
            "visited": summary.get("visited"),
            "pending": summary.get("pending"),
            "edges": summary.get("discovered_link_edges"),
        })
        for segment in sorted((audit / "segments").glob("*.json")):
            for row in read_json(segment):
                observations[row["source_url"]].append({
                    key: row[key] for key in (
                        "method", "status", "final_url", "content_type", "content_length", "sha256",
                    ) if row.get(key) is not None
                } | {"snapshot": audit.name})
        with (audit / "edges.jsonl").open(encoding="utf-8") as stream:
            for line in stream:
                edge = json.loads(line)
                if source_path(edge["to"]) is not None:
                    discovered[edge["to"]].add(edge["from"])
        for url in read_json(audit / "pending.json"):
            if source_path(url) is not None:
                discovered[url]
    return observations, discovered, inventory


def sanskrit_inventory(data, base):
    chapters = {}
    blocks = []
    for book in read_json(data.parent / "chapters.json"):
        slug = book["slug"]
        for row in book["rows"]:
            number = row["n"]
            path = data / "sanskrit" / slug / f"{number}.json"
            if not path.is_file():
                continue
            record = read_json(path)
            if record["status"] not in {"numbering_verified", "source_blocks_verified"}:
                continue
            url = record["source_url"]
            chapter = f"{base}{slug}/{number}/"
            match = CHAPTER.match(source_path(url) or "")
            if not match or (match["book"], int(match["number"])) != (slug, number):
                raise ValueError(f"Unexpected Sanskrit source URL for {slug}/{number}: {url}")
            if url in chapters:
                raise ValueError(f"Duplicate Sanskrit witness URL: {url}")
            chapters[url] = {
                "destination": f"{chapter}#sanskrit",
                "source_status": record["status"],
                "source_sha256": record["source_sha256"],
            }
            prefix = "verse" if record["status"] == "numbering_verified" else "block"
            for verse in record["verses"]:
                src_fragment = verse.get("source_anchor")
                first_number = verse["number"]
                last_number = verse.get("last_number", first_number)
                item = {
                    "source_url": url,
                    "source_anchor": src_fragment,
                    "destination_url": f"{chapter}#{prefix}-{last_number}",
                    "type": prefix,
                    "source_glyph_anomaly": bool(verse.get("source_glyph_anomaly")),
                }
                if last_number > first_number:
                    item["destination_aliases"] = [f"{chapter}#{prefix}-{n}" for n in range(first_number, last_number)]
                if src_fragment:
                    item["source_locator_url"] = f"{url}#{src_fragment}"
                blocks.append(item)
            if record.get("colophon"):
                blocks.append({
                    "source_url": url,
                    "destination_url": f"{chapter}#sanskrit",
                    "type": "colophon",
                })
    return chapters, blocks


def asset_type(url):
    path = source_path(url) or unquote(urlsplit(url).path)
    suffix = Path(path).suffix.lower()
    name = Path(path).name.lower()
    if suffix in {".jpg", ".jpeg", ".gif", ".png", ".svg", ".webp", ".ico", ".bmp"}:
        return "image"
    if suffix in {".pdf", ".zip", ".rar", ".gz", ".doc", ".docx", ".epub", ".exe"}:
        return "download"
    if suffix in {".mp3", ".mp4", ".m4a", ".wav", ".swf", ".ogg", ".flv"}:
        return "media"
    if suffix in {".css", ".js", ".ttf", ".woff", ".woff2", ".otf"}:
        return "source_asset"
    if name in {"ramayana.shtml", "vr_index.htm"}:
        return "introduction"
    if "_contents." in name or "_kanda_contents." in name:
        return "kanda_index"
    return file_kind(path)


ACCESS_ISSUE = re.compile(
    r"^(http_[45]|soft_block|unavailable|html_too_large|unsupported_content_type|no_child_listing|HTTP [45])"
)


def audit_source(data, dist, base, audits):
    mapping_rows = read_json(dist / "manifest.json")
    mapping = {row["source_url"]: row for row in mapping_rows}
    if len(mapping) != len(mapping_rows):
        raise ValueError("Existing routing manifest contains duplicate source URLs")
    records, links, summary = read_observations(audits)
    variants_path = dist / "source-variants.json"
    variants = read_json(variants_path) if variants_path.is_file() else {}
    catalog = {entry["url"]: entry for entry in variants.get("other_source_files", [])}
    for entries in variants.get("chapters", {}).values():
        catalog.update((entry["url"], entry) for entry in entries)
    chapters, blocks = sanskrit_inventory(data, base)
    preserved = {}
    intro = dist / "resources" / "vr_intro_ayyangar.json"
    if intro.is_file():
        metadata = read_json(intro)
        preserved[metadata["source"]] = f"{base}resources/vr_intro_ayyangar.pdf"

    resources = []
    supplemental_exists = (dist / "sources/files/index.html").is_file()
    for url in sorted(set(mapping) | set(records) | set(links) | set(catalog) | set(chapters) | set(preserved)):
        observations = records.get(url, [])
        mapped = mapping.get(url, {})
        listed = catalog.get(url, {})
        # A directory pass is a supplement. Prefer the recursive response as
        # the main observation when there is one, and retain conflicting evidence.
        status = observations[0]["status"] if observations else listed.get("status", mapped.get("status", "discovered_not_fetched"))
        kind = asset_type(url)
        destination = mapped.get("new_url")
        disposition = "navigation_or_source_reference"
        if url in chapters:
            destination = chapters[url]["destination"]
            status = chapters[url]["source_status"]
            disposition = "sanskrit_transcription_published"
        elif url in preserved:
            destination = preserved[url]
            disposition = "facsimile_published"
        elif kind in {"devanagari", "roman", "itrans", "prose", "download", "media", "image", "source_asset", "backup"}:
            disposition = "source_link_only"
        if destination is None and supplemental_exists:
            destination = f"{base}sources/files/" if url in catalog else None
        row = {
            "source_url": url,
            "kind": kind,
            "disposition": disposition if destination else "catalog_only",
            "source_status": status,
            "destination_url": destination,
        }
        if observations:
            row["observations"] = observations
        if url in chapters:
            row["capture_source_sha256"] = chapters[url]["source_sha256"]
        parents = sorted(links.get(url, set()))
        if parents:
            row["linked_from"] = parents
        elif listed.get("linked_from"):
            row["linked_from"] = [listed["linked_from"]]
        access_issues = {item["status"] for item in observations if ACCESS_ISSUE.match(item["status"])}
        access_issues.update(value for value in (status, listed.get("status"), mapped.get("status"))
                             if value and ACCESS_ISSUE.match(value))
        if access_issues:
            row["source_access_issues"] = sorted(access_issues)
        if kind in {"devanagari", "roman", "itrans", "prose"}:
            row["content_coverage"] = {
                "modern_english_translation": "source_link_only_where_present",
                "word_meanings": "source_link_only_where_present",
                "commentary": "source_link_only_where_present",
            }
        resources.append(row)

    # Several source navigational anchors designate a grouped text block. Keep
    # every block's actual source label even when it is missing or reused.
    known = {row["source_url"] for row in resources}
    if any(block["source_url"] not in known for block in blocks):
        raise ValueError("Sanskrit block is missing from the source URL inventory")
    render_targets = [b["destination_url"] for b in blocks if b["type"] != "colophon"]
    if len(render_targets) != len(set(render_targets)):
        raise ValueError("Duplicate Sanskrit block destination anchor")
    anchors = {}
    destinations = {row["destination_url"] for row in resources + blocks if row["destination_url"]}
    destinations.update(url for row in blocks for url in row.get("destination_aliases", ()))
    for url in destinations:
        target = urlsplit(url)
        path = target.path
        if not path.startswith(base):
            raise ValueError(f"Source manifest destination outside archive: {url}")
        file = dist / path.removeprefix(base)
        if file.is_dir():
            file /= "index.html"
        if not file.is_file():
            raise ValueError(f"Missing source manifest destination: {url}")
        if target.fragment and file.suffix == ".html":
            if file not in anchors:
                parser = Anchors()
                parser.feed(file.read_text(encoding="utf-8"))
                anchors[file] = parser.ids
            if unquote(target.fragment) not in anchors[file]:
                raise ValueError(f"Missing source manifest anchor: {url}")

    urls = Counter(r["disposition"] for r in resources)
    stats = {
        "total_url_records": len(resources),
        "resource_kinds": Counter(r["kind"] for r in resources),
        "resource_outcomes": urls,
        "source_statuses": Counter(r["source_status"] for r in resources),
        "explicit_access_issues": sum("source_access_issues" in r for r in resources),
        "sanskrit_chapters": len(chapters),
        "chapter_directory_coverage": {
            name: {
                key: values[key] for key in ("chapter_directories_with_observed_children",
                                            "chapters_with_all_four_reading_panes")
            } for name, values in variants.get("coverage", {}).items()
        },
        "text_block_types": Counter(r["type"] for r in blocks),
        "text_blocks_with_source_anchor": sum("source_locator_url" in r for r in blocks),
        "text_blocks_without_source_anchor": sum(r["type"] != "colophon" and "source_locator_url" not in r for r in blocks),
    }
    known_aliases = defaultdict(list)
    for row in resources:
        url = row["source_url"]
        parsed = urlsplit(url)
        if parsed.hostname.removeprefix("www.") == "valmikiramayan.net":
            known_aliases[parsed.path, parsed.query].append(url)
    aliases = [urls for urls in known_aliases.values() if len(urls) > 1]
    source_fragments = Counter(row["source_locator_url"] for row in blocks if "source_locator_url" in row)
    write_json(dist / "source-manifest.json", {
        "schema_version": 1,
        "audit": stats,
        "source_url_alias_candidates": aliases,
        "reused_source_anchor_labels": {url: count for url, count in source_fragments.items() if count > 1},
        "inventory_snapshots": summary,
        "limits": [
            "Observed same-site HTTP(S) URLs and source locators, plus recorded mirror chapter navigation.",
            "A destination can be a viewer page or a linked-resource listing. Its disposition indicates what is hosted.",
            "Reading panes can combine verses, translation, glosses, and commentary. These modern English elements are linked where present.",
            "Source anchor names are labels observed in the captured text. They are not evidence of a separate numbered verse for every source block.",
            "Potential protocol or hostname aliases are retained separately. Their presence does not establish byte equivalence.",
        ],
        "resources": resources,
        "sanskrit_blocks": blocks,
    })
    print(json.dumps(stats, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--audit", action="append", type=Path)
    args = parser.parse_args()
    base = os.environ.get("BASE_PATH", "/valmiki-ramayana-archive/").rstrip("/") + "/"
    audit_source(args.data, args.dist, base, args.audit or [Path("audit/primary"), Path("audit/directories")])


if __name__ == "__main__":
    main()
