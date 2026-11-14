#!/usr/bin/env python3
"""Inventory the Valmiki Ramayana site without redistributing page content.

Run on a networked GitHub Actions runner:
  python3 inventory.py --output audit/original
  python3 inventory.py --base https://www.sanskritdocuments.org/sites/valmikiramayan/ --output audit/mirror

The output is metadata only: exact discovered URLs, HTTP statuses, redirects,
HTML response hashes, all internal link edges, and reconciliation against the
six chapter indexes. Binary downloads are examined with HEAD, never fetched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import Counter, deque
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urldefrag, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

BOOKS = {
    "baala": ("baala", 77),
    "ayodhya": ("ayodhya", 119),
    "aranya": ("aranya", 75),
    "kish": ("kishkindha", 67),
    "sundara": ("sundara", 68),
    "yuddha": ("yuddha", 128),
}
HTML_EXTENSIONS = {".html", ".htm", ".shtml", ".php", ".cgi", ".old", ".bak", ".orig", ".css"}
RETRYABLE_STATUS = {"http_429", "http_500", "http_502", "http_503", "http_504", "unavailable", "soft_block"}


def canonical(url: str, base: str) -> str | None:
    """Preserve the URL path, query and host; strip fragments and reject escapes."""
    url = urldefrag(url)[0]
    p, root = urlsplit(url), urlsplit(base)
    host = (root.hostname or "").removeprefix("www.")
    if p.scheme not in ("http", "https") or p.hostname not in {host, "www." + host}:
        return None
    # Percent encoding is retained because case-sensitive servers can distinguish it.
    path = p.path or "/"
    if not path.startswith(root.path.rstrip("/") + "/") and path != root.path:
        return None
    query = "" if path.endswith("/") and re.fullmatch(r"C=[NMSD];O=[AD]", p.query) else p.query
    return urlunsplit((p.scheme, p.netloc, path, query, ""))


def likely_html(url: str) -> bool:
    path = urlsplit(url).path
    suffix = Path(path).suffix.lower()
    return path.endswith("/") or suffix in HTML_EXTENSIONS or not suffix


class LinkParser(HTMLParser):
    """Collect links including frames, images, scripts, background and embeds."""
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.anchors: list[tuple[str, str]] = []
        self.current_anchor: list[str] | None = None
        self.current_href: str | None = None
        self.base_href: str | None = None
        self.in_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "base" and self.base_href is None:
            self.base_href = a.get("href")
        self.in_style = self.in_style or tag == "style"
        for key in ("href", "src", "data", "background", "poster", "longdesc", "action", "archive"):
            if tag == "base" and key == "href":
                continue
            if a.get(key):
                self.links.append(a[key])  # type: ignore[arg-type]
        if a.get("srcset"):
            self.links.extend(item.strip().split()[0]
                              for item in a["srcset"].split(",") if item.strip())
        if a.get("style"):
            self.links.extend(css_links(a["style"]))
        if tag == "meta" and (a.get("http-equiv") or "").lower() == "refresh":
            match = re.search(r"url\s*=\s*['\"]?([^'\"]+)", a.get("content") or "", re.I)
            if match:
                self.links.append(match.group(1).strip())
        if tag == "a" and a.get("href"):
            self.current_anchor = []
            self.current_href = a["href"]

    def handle_data(self, data: str) -> None:
        if self.in_style:
            self.links.extend(css_links(data))
        if self.current_anchor is not None:
            self.current_anchor.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self.in_style = False
        if tag == "a" and self.current_anchor is not None:
            self.anchors.append((self.current_href or "", "".join(self.current_anchor).strip()))
            self.current_anchor, self.current_href = None, None


def css_links(css: str) -> list[str]:
    urls = [m.group(2) for m in re.finditer(r"url\(\s*(['\"]?)(.*?)\1\s*\)", css, re.I)]
    urls.extend(m.group(2) for m in re.finditer(r"@import\s+(['\"])(.*?)\1", css, re.I))
    return urls


def soft_block(data: bytes) -> bool:
    sample = data[:200_000].lower()
    return any(mark in sample for mark in (
        b"cf-chl-", b"_cf_chl_opt", b"/cdn-cgi/challenge-platform/", b"verify you are human",
        b"enable javascript and cookies to continue", b"imunify360", b"<title>just a moment",
        b"<title>access denied", b"<title>request blocked", b"bot verification",
    ))


@dataclass
class Record:
    source_url: str
    method: str
    status: str
    final_url: str | None = None
    content_type: str | None = None
    content_length: int | None = None
    sha256: str | None = None
    bytes_read: int | None = None
    error: str | None = None
    discovered_from: str | None = None


def request_url(url: str) -> str:
    """Escape raw whitespace and Unicode in the HTTP request, preserving URL evidence."""
    parts = urlsplit(url)
    path = quote(parts.path, safe="/%:@!$&'()*+,;=-._~")
    query = quote(parts.query, safe="%/?@:!$&'()*+,;=-._~")
    return urlunsplit((parts.scheme, parts.netloc, path, query, ""))


def fetch(url: str, *, max_html_bytes: int) -> tuple[Record, bytes | None, str | None]:
    method = "GET" if likely_html(url) else "HEAD"
    result = Record(url, method, "unavailable")
    try:
        with urlopen(Request(request_url(url), method=method), timeout=15) as response:
            result.status = f"http_{response.status}"
            result.final_url = response.url
            result.content_type = response.headers.get_content_type()
            size = response.headers.get("Content-Length")
            result.content_length = int(size) if size and size.isdigit() else None
            if method == "GET":
                if result.content_type not in ("text/html", "application/xhtml+xml", "text/plain", "text/css"):
                    # An extensionless URL may actually be a binary download.
                    result.method = "HEAD-like GET (headers only)"
                    return result, None, None
                data = response.read(max_html_bytes + 1)
                result.bytes_read = len(data)
                if len(data) > max_html_bytes:
                    result.status = "html_too_large"
                    return result, None, None
                result.sha256 = hashlib.sha256(data).hexdigest()
                if soft_block(data):
                    result.status = "soft_block"
                    return result, None, None
                encoding = response.headers.get_content_charset() or "utf-8"
                return result, data, encoding
    except HTTPError as exc:
        result.status = f"http_{exc.code}"
        result.final_url = exc.url
        result.content_type = exc.headers.get_content_type() if exc.headers else None
    except (URLError, TimeoutError, OSError, ValueError, HTTPException, UnicodeError) as exc:
        result.status = "unavailable"
        result.error = str(exc)[:400]
    return result, None, None


def seeds(base: str) -> list[str]:
    root = base.rstrip("/") + "/"
    paths = ["", "vr_index.htm", "utf8/", "utf8/ramayana.shtml"]
    for slug, (index, _) in BOOKS.items():
        paths += [f"{slug}/", f"{slug}/{index}_contents.htm",
                  f"utf8/{slug}/", f"utf8/{slug}/{index}_contents.htm"]
    return [urljoin(root, path) for path in paths]


def chapter_seeds(base: str) -> list[str]:
    chapter_data = Path(__file__).with_name("chapters.json")
    books = json.loads(chapter_data.read_text(encoding="utf-8"))
    urls = []
    for prefix in ("", "utf8/"):
        for book in books:
            for row in book["rows"]:
                number = row["link"]
                directory = urljoin(base, f"{prefix}{book['slug']}/sarga{number}/")
                urls.extend((directory, urljoin(directory, f"{book['frameprefix']}_{number}_frame.htm")))
    return urls


def chapter_number(url: str) -> int | None:
    match = re.search(r"/sarga(\d+)/[^/]+_frame\.htm$", urlsplit(url).path, re.I)
    return int(match.group(1)) if match else None


def reconcile(records: list[Record], edges: list[tuple[str, str]], base: str) -> dict:
    known = {r.source_url: r for r in records}
    children: dict[str, list[str]] = {}
    for source, target in edges:
        children.setdefault(source, []).append(target)
    report = {}
    root = base.rstrip("/") + "/"
    for slug, (index_name, expected) in BOOKS.items():
        index_url = urljoin(root, f"{slug}/{index_name}_contents.htm")
        numbered = [(chapter_number(url), url) for url in children.get(index_url, [])
                    if re.search(rf"/{re.escape(slug)}/sarga\d+/", urlsplit(url).path)]
        frame_links = [(n, url) for n, url in numbered if n is not None]
        counts = Counter(n for n, _ in frame_links)
        expected_set = set(range(1, expected + 1))
        report[slug] = {
            "expected": expected,
            "index_url": index_url,
            "index_status": known.get(index_url).status if index_url in known else "not_visited",
            "linked_unique_chapters": len(counts),
            "missing_from_index": sorted(expected_set - counts.keys()),
            "duplicate_link_numbers": sorted(n for n, count in counts.items() if count > 1),
            "out_of_range": sorted(set(counts) - expected_set),
            "linked_frame_urls": [url for _, url in frame_links],
            "visited_frame_responses": sum(url in known for _, url in frame_links),
            "successful_frame_responses": sum(
                url in known and known[url].status == "http_200"
                and known[url].final_url == url for _, url in frame_links),
        }
    return report


def write_output(output: Path, records: list[Record], edges: list[tuple[str, str]],
                 base: str, pending: deque[str], segment_size: int) -> None:
    output.mkdir(parents=True, exist_ok=True)
    partdir = output / "segments"
    partdir.mkdir(exist_ok=True)
    for old in partdir.glob("*.json"):
        old.unlink()
    for offset in range(0, len(records), segment_size):
        chunk = [asdict(r) for r in records[offset:offset + segment_size]]
        (partdir / f"{offset // segment_size:04}.json").write_text(
            json.dumps(chunk, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (output / "edges.jsonl").open("w", encoding="utf-8") as stream:
        for source, target in edges:
            stream.write(json.dumps({"from": source, "to": target}, ensure_ascii=False) + "\n")
    (output / "pending.json").write_text(
        json.dumps(list(pending), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    reconciliation = reconcile(records, edges, base)
    (output / "reconciliation.json").write_text(
        json.dumps(reconciliation, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    by_url = {r.source_url: r for r in records}
    missing_seeds = [url for url in seeds(base)
                     if url not in by_url or by_url[url].status != "http_200"]
    incomplete_books = [slug for slug, row in reconciliation.items()
                        if row["missing_from_index"] or row["successful_frame_responses"] != row["expected"]]
    unresolved = [r.source_url for r in records
                  if r.status in RETRYABLE_STATUS or r.status in {"http_403", "html_too_large", "unsupported_content_type"}]
    (output / "summary.json").write_text(json.dumps({
        "base": base,
        "visited": len(records),
        "discovered_link_edges": len(edges),
        "pending": len(pending),
        "crawl_exhausted": not pending,
        "complete": not pending and not incomplete_books and not unresolved,
        "failed_or_unvisited_seeds": missing_seeds,
        "incompletely_verified_books": incomplete_books,
        "unresolved_urls": unresolved,
        "discovery_scope": "Explicit index and frame seeds plus same-site links from fetched HTML and CSS. Unlinked, script-generated, and external pages may be absent.",
        "statuses": dict(Counter(r.status for r in records)),
        "methods": dict(Counter(r.method for r in records)),
        "note": "GET limited to HTML-like paths; binary links are HEAD only. Hashes are of fetched raw HTML bytes."
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def restore(output: Path, base: str) -> tuple[dict[str, Record], list[tuple[str, str]], deque[str]] | None:
    summary = output / "summary.json"
    if not summary.exists():
        return None
    metadata = json.loads(summary.read_text(encoding="utf-8"))
    if metadata.get("base") != base:
        raise ValueError(f"Existing audit base {metadata.get('base')!r} differs from {base!r}")
    records: dict[str, Record] = {}
    for segment in sorted((output / "segments").glob("*.json")):
        for row in json.loads(segment.read_text(encoding="utf-8")):
            rec = Record(**row)
            records[rec.source_url] = rec
    edges = [(item["from"], item["to"]) for line in
             (output / "edges.jsonl").read_text(encoding="utf-8").splitlines()
             if (item := json.loads(line))]
    pending = deque(json.loads((output / "pending.json").read_text(encoding="utf-8")))
    if len(records) != metadata["visited"] or len(edges) != metadata["discovered_link_edges"]:
        raise ValueError("Audit checkpoint is inconsistent; do not resume without inspection")
    return records, edges, pending


def crawl(base: str, output: Path, max_pages: int, max_seconds: int, delay: float, max_html_bytes: int,
          segment_size: int, fresh: bool = False) -> None:
    base = base.rstrip("/") + "/"
    saved = None if fresh else restore(output, base)
    if saved:
        seen, edges, queue = saved
        print(f"Resumed {len(seen)} visited URLs, {len(queue)} pending", flush=True)
    else:
        seen, edges, queue = {}, [], deque(dict.fromkeys(seeds(base) + chapter_seeds(base)))
    queued = set(queue)
    discovered_from = {target: source for source, target in edges if target not in seen}
    start = time.monotonic()
    while queue and len(seen) < max_pages and time.monotonic() - start < max_seconds:
        url = queue.popleft()
        if url in seen:
            continue
        record, data, encoding = fetch(url, max_html_bytes=max_html_bytes)
        for wait in (0.5, 1.5):
            if record.status not in RETRYABLE_STATUS or time.monotonic() - start >= max_seconds:
                break
            time.sleep(wait)
            record, data, encoding = fetch(url, max_html_bytes=max_html_bytes)
        record.discovered_from = discovered_from.get(url)
        seen[url] = record
        if data is not None and record.content_type in ("text/html", "application/xhtml+xml", "text/plain", "text/css"):
            try:
                decoded = data.decode(encoding or "utf-8", errors="replace")
            except (LookupError, ValueError):
                decoded = data.decode("utf-8", errors="replace")
            parser = LinkParser()
            if record.content_type == "text/css":
                discovered = css_links(decoded)
            else:
                parser.feed(decoded)
                discovered = parser.links
            response_url = record.final_url or url
            try:
                document_url = urljoin(response_url, parser.base_href or "")
            except ValueError:
                document_url = response_url
            for raw in discovered:
                try:
                    target = canonical(urljoin(document_url, raw), base)
                except ValueError:
                    print(f"Invalid link at {url}: {raw[:200]!r}", flush=True)
                    continue
                if target is not None:
                    edges.append((url, target))
                    if target not in seen and target not in queued:
                        if urlsplit(target).path.endswith("/"):
                            queue.appendleft(target)
                        else:
                            queue.append(target)
                        queued.add(target)
                        discovered_from[target] = url
        if len(seen) % 100 == 0:
            print(f"{len(seen)} visited, {len(queue)} pending", flush=True)
            write_output(output, list(seen.values()), edges, base, queue, segment_size)
        time.sleep(delay)
    write_output(output, list(seen.values()), edges, base, queue, segment_size)
    print(f"Finished: {len(seen)} visited, {len(queue)} pending; output={output}")


def self_test() -> None:
    p = LinkParser()
    p.feed('<a href="sarga1/bala_1_frame.htm">Sarga 1</a><frameset><frame src="text.htm"></frameset>'
           '<img src="x.jpg"><a href="#v1">Verse 1</a>')
    assert p.links == ["sarga1/bala_1_frame.htm", "text.htm", "x.jpg", "#v1"]
    assert css_links("background:url('../a.png')") == ["../a.png"]
    assert canonical("https://example.org/x#v", "https://example.org/") == "https://example.org/x"
    assert canonical("https://www.example.org/x", "https://example.org/") == "https://www.example.org/x"
    assert canonical("https://other.org/x", "https://example.org/") is None
    assert request_url("https://example.org/21b 22.mp3") == "https://example.org/21b%2022.mp3"
    assert request_url("https://example.org/a%20b?q=x y") == "https://example.org/a%20b?q=x%20y"
    assert request_url("https://example.org/नाम.pdf") == "https://example.org/%E0%A4%A8%E0%A4%BE%E0%A4%AE.pdf"
    assert not likely_html("https://example.org/book.pdf")
    assert likely_html("https://example.org/sarga1/balasans1.htm.old")
    assert likely_html("https://example.org/sarga1/balasans1.htm.bak")
    root = "https://example.org/"
    index = root + "baala/baala_contents.htm"
    row = reconcile([Record(index, "GET", "http_200")],
                    [(index, root + "baala/sarga1/bala_1_frame.htm")], root)["baala"]
    assert row["linked_unique_chapters"] == 1 and row["missing_from_index"] == list(range(2, 78))
    print("Synthetic parser, URL, and reconciliation checks passed")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://valmikiramayan.net/")
    ap.add_argument("--output", type=Path, default=Path("audit/original"))
    ap.add_argument("--max-pages", type=int, default=15000)
    ap.add_argument("--max-seconds", type=int, default=3600)
    ap.add_argument("--delay", type=float, default=0.25)
    ap.add_argument("--max-html-bytes", type=int, default=2_000_000)
    ap.add_argument("--segment-size", type=int, default=250)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--fresh", action="store_true", help="Discard an existing audit checkpoint")
    args = ap.parse_args()
    if args.self_test:
        self_test()
    else:
        crawl(args.base, args.output, args.max_pages, args.max_seconds, args.delay, args.max_html_bytes,
              args.segment_size, args.fresh)
