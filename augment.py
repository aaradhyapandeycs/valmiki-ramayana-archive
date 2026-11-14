#!/usr/bin/env python3
"""Add audited source variants to the static directory.

Run after build.py. This reads metadata from inventory.py; it never copies
source page bodies, translations, commentary, media, or downloads.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).parent
DEFAULT_AUDIT = ROOT / "audit/original"
DEFAULT_DIST = ROOT / "dist"
BOOKS = {"baala", "ayodhya", "aranya", "kish", "sundara", "yuddha"}
SARGA = re.compile(r"/(?:utf8/)?(baala|ayodhya|aranya|kish|sundara|yuddha)/sarga(\d+)(?:/|$)")


def h(s: object) -> str:
    return html.escape(str(s), quote=True)


def source_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]


def kind(url: str) -> str:
    path = urlsplit(url).path.lower()
    name = path.rsplit("/", 1)[-1]
    if "_frame" in name:
        return "Frame"
    if "_prose" in name:
        return "Prose"
    if "itrans" in name:
        return "ITRANS / English"
    if "roman" in name:
        return "Romanized Sanskrit / English"
    if "sans" in name:
        return "Devanagari Sanskrit / English"
    if path.endswith("/"):
        return "Directory"
    if name.endswith((".pdf", ".zip", ".mp3", ".jpg", ".jpeg", ".png", ".gif", ".woff", ".ttf")):
        return "Download or asset"
    return "Other source page"


def audit_rows(audit: Path) -> tuple[dict[str, dict], dict[str, str]]:
    records = {}
    for part in sorted((audit / "segments").glob("*.json")):
        for row in json.loads(part.read_text(encoding="utf-8")):
            url = row["source_url"]
            if url in records:
                raise ValueError(f"Duplicate audit record: {url}")
            records[url] = row
    discovered_from = {}
    edges = audit / "edges.jsonl"
    if edges.exists():
        for line in edges.read_text(encoding="utf-8").splitlines():
            if line:
                edge = json.loads(line)
                discovered_from.setdefault(edge["to"], edge["from"])
    return records, discovered_from


def source_page() -> str:
    return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Source file · Vālmīki Rāmāyaṇa</title><link rel="stylesheet" href="../style.css">
</head><body><a class="skip" href="#main">Skip to content</a>
<header class="site-head"><a class="brand" href="../index.html">Vālmīki Rāmāyaṇa</a>
<p class="tagline">Source file inventory</p><nav aria-label="Main navigation">
<a href="../index.html">Chapters</a><a href="../index.html#sources">Sources &amp; rights</a>
<a href="../manifest.json">URL manifest</a></nav></header>
<main class="wrap" id="main"><p class="eyebrow">Audited source link</p>
<h1 id="filename">Source file</h1><p id="status" aria-live="polite">Loading audit record…</p>
<dl id="metadata"></dl><p id="chapter-link"></p>
<p><a class="button" id="original" hidden rel="external">Open original source ↗</a></p>
<p class="source-note">This route records the source file and links to it directly.
Its translation, commentary, media, and downloads are not reproduced here.</p>
</main><footer class="wrap"><p>Chapter index and source credit:
<a href="https://valmikiramayan.net/">Valmiki Ramayana</a>.
Source metadata can be incomplete while the crawl is in progress.</p></footer>
<script src="view.js" defer></script></body></html>"""


def view_js() -> str:
    return """const id = new URLSearchParams(location.search).get("id");
const status = document.querySelector("#status");
fetch("../manifest.json").then(r => { if (!r.ok) throw Error("Manifest unavailable"); return r.json(); })
  .then(rows => {
    const row = rows.find(x => x.id === id);
    if (!row) { status.textContent = "No source record matches this link."; return; }
    document.title = row.source_url.split("/").pop() + " · Source file";
    document.querySelector("#filename").textContent =
      decodeURIComponent(new URL(row.source_url).pathname.split("/").pop() || "Source homepage");
    status.textContent = row.status + " · " + (row.kind || "Source file");
    const metadata = document.querySelector("#metadata");
    for (const [label, value] of [["Source URL",row.source_url],["Final URL",row.final_url],
       ["Content type",row.content_type],["SHA-256 of fetched bytes",row.sha256],
       ["Discovered from",row.discovered_from],["Note",row.note]]) {
      if (value == null || value === "") continue;
      const term = document.createElement("dt"), detail = document.createElement("dd");
      term.textContent = label; detail.textContent = value;
      metadata.append(term, detail);
    }
    const original = document.querySelector("#original");
    const url = new URL(row.source_url);
    if (url.protocol === "https:" && ["valmikiramayan.net","www.valmikiramayan.net"].includes(url.hostname)) {
      original.href = url.href; original.hidden = false;
    }
    if (row.chapter_url) {
      const a = document.createElement("a"); a.href = row.chapter_url;
      a.textContent = "Return to the indexed sarga";
      document.querySelector("#chapter-link").append(a);
    }
  }).catch(() => { status.textContent = "Source metadata is unavailable."; });"""


def augment(audit: Path = DEFAULT_AUDIT, dist: Path = DEFAULT_DIST, base: str = "/valmiki-ramayana-archive/") -> dict:
    base = base.rstrip("/") + "/"
    manifest_path = dist / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("Run build.py first")
    existing = {row["source_url"]: row for row in json.loads(manifest_path.read_text(encoding="utf-8"))}
    records, discovered = audit_rows(audit)
    if not records:
        raise ValueError(f"No audited records in {audit}")
    urls = set(existing) | set(records) | set(discovered)
    ids = {url: source_id(url) for url in urls}
    if len(set(ids.values())) != len(ids):
        raise ValueError("Source route hash collision")
    chapters = json.loads((ROOT / "chapters.json").read_text(encoding="utf-8"))
    limits = {b["slug"]: len(b["rows"]) for b in chapters}
    output = []
    variants: dict[str, list[dict]] = {}
    for url in sorted(urls):
        old = existing.get(url, {})
        record = records.get(url)
        match = SARGA.search(urlsplit(url).path)
        chapter_url = None
        chapter_key = None
        if match and match.group(1) in BOOKS:
            slug, n = match.group(1), int(match.group(2))
            if 1 <= n <= limits[slug]:
                chapter_key = f"{slug}/{n}"
                chapter_url = f"{base}{slug}/{n}/"
        if record:
            status = record["status"]
            final = record.get("final_url")
            if status == "http_200" and final and final != url:
                status = "redirected_http_200"
        else:
            status = "discovered_unvisited" if url in discovered else old.get("status", "unverified")
        row = {
            "source_url": url, "new_url": base + "source/?id=" + ids[url],
            "id": ids[url], "status": status, "kind": kind(url),
            "final_url": record.get("final_url") if record else None,
            "content_type": record.get("content_type") if record else None,
            "sha256": record.get("sha256") if record else None,
            "method": record.get("method") if record else None,
            "content_length": record.get("content_length") if record else None,
            "bytes_read": record.get("bytes_read") if record else None,
            "error": record.get("error") if record else None,
            "discovered_from": (record.get("discovered_from") if record else None)
                               or discovered.get(url),
            "chapter_url": chapter_url,
            "note": ("Source response inventoried; original text and assets remain external."
                     if record else old.get("note") or "Link discovered; response not yet checked.")
        }
        output.append(row)
        if chapter_key:
            variants.setdefault(chapter_key, []).append({
                "source_url": url, "new_url": row["new_url"],
                "status": status, "kind": row["kind"], "sha256": row["sha256"]})
    source_dir = dist / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "index.html").write_text(source_page(), encoding="utf-8")
    (source_dir / "view.js").write_text(view_js(), encoding="utf-8")
    (dist / "variants.json").write_text(json.dumps(variants, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for key, items in variants.items():
        path = dist / key / "index.html"
        if not path.is_file():
            continue
        # All exact discovered variants remain visible, including failures and old backups.
        links = "".join(
            f'<li><a href="../../source/?id={h(source_id(item["source_url"]))}">'
            f'{h(urlsplit(item["source_url"]).path.rsplit("/", 1)[-1] or "/")}</a>'
            f' <small>({h(item["kind"])}, {h(item["status"])})</small></li>'
            for item in items
        )
        section = (f'<section id="source-files" class="sources"><h2>Source files and variants</h2>'
                   f'<p>These links record the original files and their checked response status. '
                   f'English, commentary, media, and downloads remain at the source.</p>'
                   f'<ul>{links}</ul></section>')
        text = path.read_text(encoding="utf-8")
        marker = '<nav class="chapter-nav"'
        if marker not in text:
            raise ValueError(f"Navigation marker missing: {path}")
        path.write_text(text.replace(marker, section + marker, 1), encoding="utf-8")
    manifest_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = json.loads((audit / "summary.json").read_text(encoding="utf-8"))
    counts = {"mapped": len(output), "audited": len(records),
              "discovered_unvisited": len(set(discovered) - set(records)),
              "chapter_variant_groups": len(variants),
              "audit_complete": summary.get("complete", False)}
    (dist / "audit-summary.json").write_text(json.dumps(counts, indent=2) + "\n", encoding="utf-8")
    return counts


def self_test() -> None:
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as td:
        root = Path(td)
        dist, audit = root / "dist", root / "audit"
        dist.mkdir()
        (dist / "baala/1").mkdir(parents=True)
        (dist / "baala/1/index.html").write_text('<nav class="chapter-nav"></nav>')
        (dist / "manifest.json").write_text(json.dumps([{
            "source_url": "https://valmikiramayan.net/baala/sarga1/bala_1_frame.htm",
            "new_url": "/valmiki-ramayana-archive/baala/1/", "status": "unverified"}]))
        (audit / "segments").mkdir(parents=True)
        row = {"source_url":"https://valmikiramayan.net/baala/sarga1/bala_1_frame.htm",
               "method":"GET","status":"http_200","final_url":"https://valmikiramayan.net/baala/sarga1/bala_1_frame.htm",
               "sha256":"abc","content_type":"text/html"}
        (audit / "segments/0000.json").write_text(json.dumps([row]))
        (audit / "edges.jsonl").write_text(json.dumps({
            "from":row["source_url"],"to":"https://valmikiramayan.net/baala/sarga1/balaroman1.htm"})+"\n")
        (audit / "summary.json").write_text('{"complete":false}')
        got = augment(audit, dist)
        assert got["mapped"] == 2 and got["discovered_unvisited"] == 1
        assert "Source files and variants" in (dist / "baala/1/index.html").read_text()
        assert all(x["new_url"].startswith("/valmiki-ramayana-archive/source/?id=")
                   for x in json.loads((dist / "manifest.json").read_text()))
    print("Synthetic manifest, source route and chapter-link checks passed")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    p.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    p.add_argument("--base", default="/valmiki-ramayana-archive/")
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args()
    if a.self_test:
        self_test()
    else:
        print(augment(a.audit, a.dist, a.base))
