#!/usr/bin/env python3
"""Recover explicit HTML line divisions against the pinned Sanskrit witness.

The output contains only source offsets for display, never original HTML.
"""

from bisect import bisect_left
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import argparse
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from audit_source_text import parse, clean, fetch, PRIMARY_HOSTS, HIDDEN, AUXILIARY_SEPARATOR
from verse_lines import CLOSING_ROW


ROOT = Path(__file__).resolve().parent
EXPLICIT_BREAK = "\x01"


def collect_parts(node):
    if node.tag in HIDDEN:
        return ""
    if node.tag == "br":
        return EXPLICIT_BREAK
    return (node.text or "") + "".join(
        collect_parts(child) + (child.tail or "") for child in node
    )


def normalize_layout(text):
    # The source parser maps <br> to whitespace for audit identity.  Distinguish
    # which collapsed whitespace characters had an explicit HTML break.
    previous = 0
    write_offset = 0
    parts = []
    jumps = []
    indices = {}
    for run in re.finditer(r"[\t\r\n\f \u00a0\x01]+", text):
        prefix = text[previous:run.start()]
        parts.append(prefix)
        write_offset += len(prefix)
        if write_offset and run.end() < len(text):
            parts.append(" ")
            indices[write_offset] = run.start()
            if EXPLICIT_BREAK in run[0]:
                jumps.append(write_offset)
            write_offset += 1
        previous = run.end()
    parts.append(text[previous:])
    return "".join(parts), jumps, indices


def source_layouts(raw):
    document = parse(raw)
    for number, node in enumerate(document.iter("p"), 1):
        if "sansloka" not in node.get("class", "").casefold().split():
            continue
        text, breaks, _ = normalize_layout(collect_parts(node))
        if text and not AUXILIARY_SEPARATOR.fullmatch(text):
            yield number, text, breaks


def layout_from_paragraphs(paragraphs, record, additions):
    indices = {ordinal: (text, breaks) for ordinal, text, breaks in paragraphs}
    combined = []
    source_offsets = []
    stream_offset = 0
    for _, text, breaks in paragraphs:
        if combined:
            source_offsets.append(stream_offset - 1)
        combined.append(text)
        source_offsets.extend(stream_offset + pos for pos in breaks)
        stream_offset += len(text) + 1
    source_text = " ".join(combined)
    published = " ".join(clean(verse["sanskrit"]) for verse in record["verses"])
    start = source_text.find(published)
    if start < 0 or source_text.find(published, start + 1) >= 0:
        raise ValueError("not a unique matching Sanskrit passage in primary HTML")
    layout = {"source_sha256": record["source_sha256"], "verses": {}, "supplements": {}}
    for verse in record["verses"]:
        text = verse["sanskrit"]
        size = len(clean(text))
        lo, hi = bisect_left(source_offsets, start), bisect_left(source_offsets, start + size)
        offsets = [pos - start for pos in source_offsets[lo:hi]]
        layout["verses"][str(verse["number"])] = offsets_in_snapshot(text, offsets)
        start += size + 1
    if record.get("colophon"):
        text = record["colophon"]
        matching = [(paragraph, cuts) for _, paragraph, cuts in paragraphs
                    if paragraph == clean(text)]
        if len(matching) == 1:
            layout["colophon"] = offsets_in_snapshot(text, matching[0][1])
        else:
            raise ValueError("not a unique source paragraph for the pinned colophon")
    for item in additions:
        source_number = item["source_paragraph"]
        normal = clean(item["sanskrit"])
        candidate = indices.get(source_number)
        if candidate is None or candidate[0] != normal:
            # A separately normalized review fixture may have removed empty
            # paragraphs. Do not choose between duplicate matching text.
            matches = [(text, breaks) for _, text, breaks in paragraphs if text == normal]
            if len(matches) != 1:
                raise ValueError(f"cannot locate exact source supplement paragraph {source_number}")
            candidate = matches[0]
        layout["supplements"][str(source_number)] = offsets_in_snapshot(
            item["sanskrit"], candidate[1],
            preserve_blank_lines=item["kind"] == "Source Gāyatrī Rāmāyaṇa appendix",
        )
    return layout


def collect_map(raw, record, additions):
    if sha256(raw).hexdigest() != record["source_sha256"]:
        raise ValueError("live HTML SHA-256 differs from the pinned Sanskrit witness")
    return layout_from_paragraphs(list(source_layouts(raw)), record, additions)


def offsets_in_snapshot(text, normalized_offsets, preserve_blank_lines=False):
    normalized, _, indices = normalize_layout(text)
    if normalized != clean(text):
        raise ValueError("unexpected source whitespace normalization")
    if preserve_blank_lines:
        return [offset for offset, char in enumerate(text) if char == "\n"]
    rows = []
    for index, offset in enumerate(normalized_offsets):
        end = normalized_offsets[index + 1] if index + 1 < len(normalized_offsets) else len(normalized)
        if not CLOSING_ROW.fullmatch(normalized[offset + 1:end]):
            rows.append(indices[offset])
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=ROOT / "data" / "sanskrit")
    parser.add_argument("--supplements", type=Path, default=ROOT / "data" / "sanskrit-paratext-reviewed.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = json.loads((args.snapshot / "summary.json").read_text(encoding="utf-8"))
    supplements = json.loads(args.supplements.read_text(encoding="utf-8"))

    def collect(row):
        slug, chapter = row["slug"], row["sarga"]
        record = json.loads((args.snapshot / slug / f"{chapter}.json").read_text(encoding="utf-8"))
        key = f"{slug}/{chapter}"
        try:
            raw = fetch(record["source_url"], PRIMARY_HOSTS, timeout=20)
            return key, collect_map(raw, record, supplements.get(key, ())), None
        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            return key, None, {"url": record["source_url"], "reason": str(error)}
        finally:
            time.sleep(.12)

    output = {"snapshot_commit": summary["commit"], "chapters": {}, "unresolved": {}}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for count, (key, layout, issue) in enumerate(pool.map(collect, summary["chapters"]), 1):
            if issue:
                output["unresolved"][key] = issue
            else:
                output["chapters"][key] = layout
            if count % 100 == 0:
                print(f"{count} / {len(summary['chapters'])} source panes inspected", flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"matched_chapters": len(output["chapters"]), "unresolved": output["unresolved"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
