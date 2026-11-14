#!/usr/bin/env python3
"""Inventory source links without copying copyrighted page bodies.

Requires network access to valmikiramayan.net. This script is deliberately
separate from the build: network failures never turn into invented content.
"""
import argparse
import collections
import json
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

HERE = Path(__file__).parent
START = "https://valmikiramayan.net/"
INDEX = json.loads((HERE / "chapters.json").read_text())
ALLOWED = {"valmikiramayan.net", "www.valmikiramayan.net"}


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        for attr in ("href", "src"):
            if d.get(attr):
                self.links.append(d[attr])
        if tag == "frame" and d.get("src"):
            self.links.append(d["src"])


def normalize(url):
    url = urldefrag(url)[0]
    p = urlsplit(url)
    if p.hostname not in ALLOWED or p.scheme not in ("http", "https"):
        return None
    return urlunsplit(("https", "valmikiramayan.net", p.path or "/", p.query, ""))


def run(max_pages, delay):
    queue = collections.deque([START] + [
        f"{START}{b['slug']}/{ {'baala':'baala','ayodhya':'ayodhya','aranya':'aranya','kish':'kishkindha','sundara':'sundara','yuddha':'yuddha'}[b['slug']]}_contents.htm"
        for b in INDEX
    ])
    seen = {}
    edges = []
    while queue and len(seen) < max_pages:
        url = normalize(queue.popleft())
        if not url or url in seen:
            continue
        record = {"source_url": url, "status": "unavailable"}
        try:
            with urlopen(Request(url, headers={"User-Agent":"ValmikiDirectoryInventory/1.0 (academic link audit)"}), timeout=15) as response:
                payload = response.read(4_000_000)
                record.update(status=f"http_{response.status}", content_type=response.headers.get_content_type(),
                              final_url=response.url)
                if response.headers.get_content_type() in ("text/html", "application/xhtml+xml"):
                    charset = response.headers.get_content_charset() or "utf-8"
                    parser = Links()
                    parser.feed(payload.decode(charset, errors="replace"))
                    for link in parser.links:
                        target = normalize(urljoin(response.url, link))
                        if target:
                            edges.append([url, target])
                            if target not in seen:
                                queue.append(target)
        except HTTPError as e:
            record.update(status=f"http_{e.code}", final_url=e.url)
        except (URLError, TimeoutError, ValueError) as e:
            record["error"] = str(e)
        seen[url] = record
        if len(seen) % 50 == 0:
            print(f"Visited {len(seen)} URLs; {len(queue)} queued", flush=True)
        time.sleep(delay)
    expected = {
        f"{START}{b['slug']}/sarga{x['n']}/{b['frameprefix']}_{x['n']}_frame.htm"
        for b in INDEX for x in b["rows"]
    }
    found = set(seen) | {target for _, target in edges}
    result = {"visited": list(seen.values()), "edges": edges,
              "indexed_frame_urls": len(expected),
              "indexed_frames_discovered": len(expected & found),
              "indexed_frames_missing_from_crawl": sorted(expected - found),
              "queue_remaining": len(queue), "complete": not queue}
    (HERE / "crawl-report.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(f"Report: {len(seen)} visited, {len(edges)} links, {len(expected & found)}/{len(expected)} indexed frames found")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-pages", type=int, default=10000)
    parser.add_argument("--delay", type=float, default=0.2)
    args = parser.parse_args()
    run(args.max_pages, args.delay)
