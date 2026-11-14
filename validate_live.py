#!/usr/bin/env python3
"""Verify every public build file at its deployed URL."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urljoin, urlsplit
from urllib.request import urlopen

RETRYABLE = {429, 500, 502, 503, 504}


def read_bytes(url, *, statuses=(200,), expected_digest=None):
    delays = (0, .5, 2, 5)
    for index, delay in enumerate(delays):
        time.sleep(delay)
        try:
            try:
                response = urlopen(url, timeout=30)
            except HTTPError as error:
                if error.code not in statuses:
                    raise
                response = error
            with response:
                status = response.code
                if status not in statuses:
                    raise ValueError(f"unexpected HTTP {status}")
                data = response.read()
                if expected_digest is None or sha256(data).hexdigest() == expected_digest:
                    return data
                if index == len(delays) - 1:
                    raise ValueError("served bytes differ from the generated file SHA-256")
        except HTTPError as error:
            if error.code not in RETRYABLE or index == len(delays) - 1:
                raise ValueError(f"{url}: HTTP {error.code}") from error
        except (URLError, TimeoutError) as error:
            if index == len(delays) - 1:
                raise ValueError(f"{url}: {error}") from error
    raise RuntimeError(f"Could not read {url}")


def public_path(relative):
    if relative.name == "index.html":
        parent = relative.parent.as_posix()
        return "" if parent == "." else parent + "/"
    return relative.as_posix()


def verify_file(base, dist, path):
    relative = path.relative_to(dist)
    url = urljoin(base, quote(public_path(relative), safe="/"))
    try:
        read_bytes(
            url,
            statuses=(200, 404) if relative.as_posix() == "404.html" else (200,),
            expected_digest=sha256(path.read_bytes()).hexdigest(),
        )
    except (ValueError, RuntimeError) as error:
        return {"url": url, "error": str(error)}
    return {"url": url, "suffix": path.suffix, "matches": True}


def built_chapters(base, dist, expected):
    rows = json.loads((dist / "search.json").read_text(encoding="utf-8"))
    if len(rows) != 534 or len({row["url"] for row in rows}) != 534:
        raise ValueError("Chapter search index does not contain 534 unique URLs.")
    prefix = urlsplit(base).path
    count = 0
    for row in rows:
        url = urlsplit(row["url"])
        if url.netloc or not url.path.startswith(prefix):
            raise ValueError(f"Search result outside the deployed site: {row['url']}")
        relative = unquote(url.path[len(prefix):])
        chapter = Path(dist, relative, "index.html").resolve()
        if not chapter.is_relative_to(dist.resolve()):
            raise ValueError(f"Unexpected chapter path: {row['url']}")
        count += 'id="sanskrit"' in chapter.read_text(encoding="utf-8")
    if count != expected:
        raise ValueError(f"Expected {expected} chapters with Sanskrit, found {count}.")
    return count


def main():
    base = sys.argv[1].rstrip("/") + "/"
    dist = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("dist")
    count = built_chapters(base, dist, int(sys.argv[2]))
    files = sorted(
        path for path in dist.rglob("*") if path.is_file()
        and not any(segment.startswith(".") for segment in path.relative_to(dist).parts)
    )
    if not files:
        raise ValueError(f"No site files found in {dist}")
    with ThreadPoolExecutor(max_workers=8) as pool:
        comparisons = list(pool.map(lambda path: verify_file(base, dist, path), files))
    failures = [row for row in comparisons if not row.get("matches")]
    report = {
        "site": base,
        "files_checked": len(files),
        "matching_by_extension": dict(Counter(row["suffix"] for row in comparisons if row.get("matches"))),
        "sanskrit_chapters": count,
        "failures": failures,
    }
    output = Path(os.environ.get("LIVE_AUDIT_REPORT", "live-audit-report.json"))
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if failures:
        raise SystemExit(f"{len(failures)} deployed files did not match the build.")
    print(f"Live verification passed for {len(files)} files and {count} Sanskrit chapter pages.")


if __name__ == "__main__":
    main()
