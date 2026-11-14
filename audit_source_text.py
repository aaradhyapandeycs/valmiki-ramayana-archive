#!/usr/bin/env python3
"""Compare each captured chapter with its primary HTML and rendered reader."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

try:
    import html5lib
except ModuleNotFoundError:
    # The separately installed package is used in CI. The local Mac
    # interpreter includes the same release under pip's vendor directory.
    from pip._vendor import html5lib


PRIMARY_HOSTS = {"valmikiramayan.net", "www.valmikiramayan.net"}
FORMAT_SPACE = re.compile(r"[\t\r\n\f \u00a0]+")
AUXILIARY_SEPARATOR = re.compile(r"^[ .|।॥-]*or[ .|।॥-]*$", flags=re.I)
DEVANAGARI = re.compile(r"[\u0904-\u0939]")
LOCATOR = re.compile(r"(?<![\d-])[\d]{1,2}\s*[-–]\s*[\d]{1,3}\s*[-–]\s*[\d]{1,3}(?!\d)")
EXPECTED = {"baala": 77, "ayodhya": 119, "aranya": 75, "kish": 67, "sundara": 68, "yuddha": 128}
HIDDEN = {"audio", "script", "style", "template"}
RETRYABLE = {429, 500, 502, 503, 504}
MAX_BYTES = 2_000_000


def clean(text):
    """Ignore formatting whitespace only, retaining every other codepoint."""
    return FORMAT_SPACE.sub(" ", text).strip()


def digest(data):
    return sha256(data).hexdigest()


def parse(data):
    return html5lib.parse(
        data.decode("utf-8-sig"), treebuilder="etree", namespaceHTMLElements=False
    )


def plain(element):
    if element.tag in HIDDEN:
        return ""
    if element.tag == "br":
        return " "
    return (element.text or "") + "".join(
        plain(child) + (child.tail or "") for child in element
    )


def source_blocks(root):
    """Read tagged spans using the browser's HTML5 parsing and tree recovery."""
    records = []
    last_anchor = None
    paragraph_index = 0
    for node in root.iter():
        if node.tag == "a":
            target = node.get("name") or node.get("id") or ""
            if re.fullmatch(r"Verse[0-9]+", target, re.I):
                last_anchor = target
        if node.tag != "p":
            continue
        paragraph_index += 1
        if "sansloka" not in node.get("class", "").casefold().split():
            continue
        text = clean(plain(node))
        if text and not AUXILIARY_SEPARATOR.fullmatch(text):
            records.append((paragraph_index, text, last_anchor))
    return records


def extras_category(block, position, whole_paragraph):
    if not whole_paragraph:
        return "partial_source_paragraph"
    if re.match(r"^[ |।॥]*(?:इति|इत्य)", block) and re.search(r"स(?:रग|र्ग)", block):
        return "colophon"
    if position == "before" and re.match(r"^[ |।॥]*(?:ॐ|अथ|श्रीगणेश)", block):
        return "opening_invocation"
    if LOCATOR.search(block):
        return "numbered_appendix_or_alternate_passage"
    if DEVANAGARI.search(block):
        return "unnumbered_quotation_or_appendix"
    return "non_sanskrit_or_malformed_tagged_paragraph"


def outside_blocks(records, start, end, colophon):
    entries = []
    offset = 0
    for index, block, anchor in records:
        block_end = offset + len(block)
        if (offset < start or block_end > end) and block != colophon:
            position = "before" if block_end <= start else "after" if offset >= end else "overlaps"
            whole_paragraph = position != "overlaps"
            entries.append({
                "source_paragraph": index, "nearest_preceding_verse_anchor": anchor,
                "codepoints": len(block), "sha256_normalized_text": digest(block.encode("utf-8")),
                "position": position, "category": extras_category(block, position, whole_paragraph),
                "devanagari_present": bool(DEVANAGARI.search(block)),
                "printed_locator_present": bool(LOCATOR.search(block)),
            })
        offset = block_end + 1
    return entries


def compare_to_primary(record, raw):
    body = parse(raw)
    observed_anchors = Counter(
        identifier for a in body.iter("a")
        if (identifier := a.get("name") or a.get("id")) and re.fullmatch("Verse[0-9]+", identifier, re.I)
    )
    blocks = source_blocks(body)
    stream = " ".join(block for _, block, _ in blocks)
    snapshot = " ".join(clean(verse["sanskrit"]) for verse in record["verses"])
    offset = stream.find(snapshot)
    colophon = clean(record.get("colophon") or "")
    end = offset + len(snapshot)
    if offset < 0:
        return {"status": "passage_mismatch", "source_paragraphs": len(blocks),
                "captured_codepoints": len(snapshot), "source_codepoints": len(stream)}
    if stream.find(snapshot, offset + 1) != -1:
        return {"status": "duplicate_chapter_span", "source_paragraphs": len(blocks)}
    after = stream[end:]
    if colophon:
        colophon_offset = after.find(colophon)
        if colophon_offset < 0:
            return {"status": "colophon_mismatch", "source_paragraphs": len(blocks)}
        end_colophon = end + colophon_offset + len(colophon)
    else:
        end_colophon = end
    extras = outside_blocks(blocks, offset, end, colophon)
    absent_anchors = sorted({verse["source_anchor"] for verse in record["verses"]
                             if verse.get("source_anchor") and not observed_anchors[verse["source_anchor"]]})
    return {"status": "matched" if not absent_anchors else "source_anchor_mismatch",
            "source_paragraphs": len(blocks), "duplicate_source_anchors": sorted(
                anchor for anchor, count in observed_anchors.items() if count > 1
            ), "missing_captured_anchors": absent_anchors,
            "outside_capture": extras, "colophon_matched": bool(colophon),
            "source_end_codepoints": len(stream) - end_colophon}


def check_rendered(record, raw):
    doc = parse(raw)
    sections = [section for section in doc.iter("section") if section.get("id") == "sanskrit"]
    if len(sections) != 1:
        return "missing_or_duplicate_reader"
    paragraphs = [plain(p) for p in sections[0].iter("p") if p.get("lang") == "sa-Deva"]
    expected = [verse["sanskrit"] for verse in record["verses"]]
    if record.get("colophon"):
        expected.append(record["colophon"])
    if paragraphs != expected:
        return "rendered_text_differs_from_snapshot"
    ids = Counter(node.get("id") for node in sections[0].iter() if node.get("id"))
    for verse in record["verses"]:
        prefix = "verse" if record["status"] == "numbering_verified" else "block"
        start = verse["number"]
        end = verse.get("last_number", start)
        if any(ids[f"{prefix}-{n}"] != 1 for n in range(start, end + 1)):
            return "missing_or_duplicate_rendered_verse_anchor"
    source = record["source_url"]
    if not any(a.get("href") == source for a in sections[0].iter("a")):
        return "reader_source_link_mismatch"
    return "matched"


def fetch(url, hosts, timeout):
    if urlsplit(url).scheme != "https" or urlsplit(url).hostname not in hosts:
        raise ValueError(f"URL is outside permitted witness hosts: {url}")
    for delay in (0, .5, 2):
        time.sleep(delay)
        try:
            with urlopen(url, timeout=timeout) as response:
                if urlsplit(response.url).hostname not in hosts:
                    raise ValueError("redirect outside the original witness")
                if response.status != 200 or response.headers.get_content_type() != "text/html":
                    raise ValueError(f"unexpected response {response.status}")
                data = response.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise ValueError("response exceeds audit limit")
                return data
        except HTTPError as error:
            if error.code not in RETRYABLE or delay == 2:
                raise
        except (URLError, TimeoutError):
            if delay == 2:
                raise
    raise AssertionError("retry loop produced no response")


def audit_chapter(item, snapshot_root, destination, build, timeout):
    slug, chapter = item
    record = json.loads((snapshot_root / slug / f"{chapter}.json").read_text(encoding="utf-8"))
    if record.get("kind") != "primary":
        raise ValueError(f"{slug}/{chapter} has no primary snapshot")
    url = record["source_url"]
    row = {"chapter": f"{slug}/{chapter}", "source_url": url,
           "destination_url": f"{destination}{slug}/{chapter}/", "snapshot_sha256": record["source_sha256"],
           "captured_blocks": len(record["verses"]), "capture_status": record["status"]}
    try:
        raw = fetch(url, PRIMARY_HOSTS, timeout)
        row["fetched_sha256"] = digest(raw)
        row["response_unchanged"] = row["fetched_sha256"] == row["snapshot_sha256"]
        row.update(compare_to_primary(record, raw))
        if row["status"] == "matched" and not row["response_unchanged"]:
            row["status"] = "matched_passages_html_changed"
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        row.update(status="primary_unavailable", detail=str(error))
    finally:
        time.sleep(.12)
    if build:
        html = build / slug / str(chapter) / "index.html"
        row["built_reader"] = check_rendered(record, html.read_bytes()) if html.is_file() else "missing_route"
    try:
        html = fetch(row["destination_url"], {urlsplit(destination).hostname}, timeout)
        row["live_reader"] = check_rendered(record, html)
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        row.update(live_reader="unavailable", live_detail=str(error))
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--build", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4, choices=range(1, 7))
    parser.add_argument("--timeout", type=float, default=18)
    args = parser.parse_args()
    destination = args.destination.rstrip("/") + "/"
    pairs = [(slug, i) for slug, count in EXPECTED.items() for i in range(1, count + 1)]
    summary = json.loads((args.snapshot / "summary.json").read_text(encoding="utf-8"))
    if [(r["slug"], r["sarga"]) for r in summary["chapters"]] != pairs:
        raise ValueError("The snapshot chapter list differs from the six primary tables of contents.")
    def audit(pair):
        return audit_chapter(pair, args.snapshot, destination, args.build, args.timeout)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = []
        for row in pool.map(audit, pairs):
            rows.append(row)
            if len(rows) % 100 == 0:
                print(f"{len(rows)} / {len(pairs)} chapters compared", flush=True)
    output = {
        "snapshot_commit": summary["commit"],
        "source_comparison": dict(Counter(r["status"] for r in rows)),
        "source_blocks": sum(r["captured_blocks"] for r in rows),
        "response_hashes_matched": sum(r.get("response_unchanged", False) for r in rows),
        "uncaptured_paragraphs_by_review_category": dict(Counter(
            entry["category"] for row in rows for entry in row.get("outside_capture", [])
        )),
        "source_chapters_with_uncaptured_numbered_paragraphs": sum(
            any(p["printed_locator_present"] for p in r.get("outside_capture", [])) for r in rows
        ),
        "built_reader_comparison": dict(Counter(r.get("built_reader", "not_requested") for r in rows)),
        "live_reader_comparison": dict(Counter(r["live_reader"] for r in rows)),
        "method": (
            "A separate HTML5 tree parser matched every captured Sanskrit codepoint in source order, "
            "with only formatting whitespace collapsed and standalone editorial 'Or' omitted. "
            "Entire built and public Devanagari passages, source links and local anchors were compared "
            "against the pinned snapshot. HTML changes and additional source paragraphs are reported."
        ),
        "chapters": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in output.items() if k != "chapters"}, ensure_ascii=False))
    for row in rows:
        extras = row.get("outside_capture", [])
        if extras or row["status"] != "matched" or row["live_reader"] != "matched":
            print(json.dumps({
                "source_url": row["source_url"], "chapter": row["chapter"],
                "primary_status": row["status"], "live_reader": row["live_reader"],
                "additional_source_paragraphs": extras,
            }, ensure_ascii=False))


if __name__ == "__main__":
    main()
