#!/usr/bin/env python3
"""Inspect the public file listings for both editions' chapter directories."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlsplit

from inventory import LinkParser, Record, canonical, fetch, write_output

ROOT = "https://valmikiramayan.net/"


def source_directories():
    frames = json.loads(Path("data/frames.json").read_text(encoding="utf-8"))
    ancillary = json.loads(Path("data/ancillary.json").read_text(encoding="utf-8"))
    directories = {
        urljoin(links[key], "./") for book in frames["books"].values()
        for links in book["chapters"].values() for key in ("original", "utf8")
    }
    directories.update(
        entry["url"] for group in ancillary["groups"] for entry in group["entries"]
        if re.search(r"/sarga[0-9]+/$", urlsplit(entry["url"]).path)
    )
    return sorted(directories)


def check(url):
    record, data, encoding = fetch(url, max_html_bytes=1_000_000)
    if record.status in {"soft_block", "unavailable", "http_429", "http_503"}:
        time.sleep(1)
        record, data, encoding = fetch(url, max_html_bytes=1_000_000)
    time.sleep(.17)
    if data is None:
        return record, []
    parser = LinkParser()
    parser.feed(data.decode(encoding or "utf-8", errors="replace"))
    path = urlsplit(url).path
    links = []
    for raw in parser.links:
        target = canonical(urljoin(record.final_url or url, raw), ROOT)
        if target is not None and urlsplit(target).path.startswith(path) and urlsplit(target).path != path:
            links.append((url, target))
    if not links:
        record.status = "no_child_listing"
    return record, sorted(set(links))


def main():
    from collections import deque
    output = Path("audit/directories")
    records: list[Record] = []
    edges: list[tuple[str, str]] = []
    directories = source_directories()
    with ThreadPoolExecutor(max_workers=3) as pool:
        for record, links in pool.map(check, directories):
            records.append(record)
            edges.extend(links)
            if len(records) % 100 == 0:
                print(f"{len(records)} / {len(directories)} chapter directories inspected", flush=True)
    write_output(output, records, edges, ROOT, deque(), 250)
    summary = json.loads((output / "summary.json").read_text())
    summary["discovery_scope"] = "Chapter directory listings only. Listed child files were not individually fetched."
    summary["directories_with_child_links"] = sum(r.status == "http_200" for r in records)
    summary["directories_by_response"] = dict(Counter(r.status for r in records))
    summary["complete"] = False
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(summary["directories_by_response"], f"{len(edges)} directory edges", flush=True)


if __name__ == "__main__":
    main()
