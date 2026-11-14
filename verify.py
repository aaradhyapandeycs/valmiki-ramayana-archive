#!/usr/bin/env python3
"""Validate generated local routes, chapter order and every internal href."""
import json
import os
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).parent
DIST = ROOT / "dist"
base = os.environ.get("BASE_PATH", "/valmiki-ramayana-archive/").rstrip("/") + "/"
books = json.loads((ROOT / "chapters.json").read_text())
manifest = json.loads((DIST / "manifest.json").read_text())
search = json.loads((DIST / "search.json").read_text())
expected = sum(len(b["rows"]) for b in books)
assert expected == len(search) == 534
assert len({x["source_url"] for x in manifest}) == len(manifest)
assert [len(b["rows"]) for b in books] == [77, 119, 75, 67, 68, 128]


class Audit(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = set()
    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if d.get("id"):
            self.ids.add(d["id"])
        for key in ("href", "src"):
            if d.get(key):
                self.links.append(d[key])


failures = []
documents = {}
for file in DIST.rglob("*.html"):
    doc = Audit()
    doc.feed(file.read_text(encoding="utf-8"))
    documents[file.resolve()] = doc
for file, doc in documents.items():
    for link in doc.links:
        parsed = urlsplit(link)
        if parsed.scheme or parsed.netloc or link.startswith("//"):
            continue
        target = (file.parent / unquote(parsed.path)).resolve() if parsed.path else file
        if target.is_dir():
            target /= "index.html"
        if not target.is_file() or not target.is_relative_to(DIST.resolve()):
            failures.append(f"{file.relative_to(DIST)} → {link}: missing target")
        elif parsed.fragment and target.suffix == ".html":
            if unquote(parsed.fragment) not in documents[target].ids:
                failures.append(f"{file.relative_to(DIST)} → {link}: missing anchor")
for row in manifest:
    path = urlsplit(row["new_url"]).path
    # A repository base path precedes the generated tree.
    relative = path.removeprefix(base)
    target = DIST / relative
    if target.is_dir():
        target /= "index.html"
    if not target.is_file():
        failures.append(f"manifest → {row['new_url']}: missing route")
if failures:
    print("\n".join(failures[:30]))
    raise SystemExit(f"{len(failures)} validation failures")
print(f"Validated {expected} chapter routes, {len(manifest)} mappings, and internal HTML links/anchors.")
