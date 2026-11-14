#!/usr/bin/env python3
"""Publish an unmodified scan of Ayyangar's 1910 introduction."""

import argparse
import hashlib
import io
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


PRIMARY = "https://valmikiramayan.net/vr_intro_ayyangar.pdf"
MIRROR = "https://sanskritdocuments.org/sites/valmikiramayan/vr_intro_ayyangar.pdf"
EXPECTED_PAGES = 142
MAX_DOWNLOAD = 16 * 1024 * 1024


def download(url):
    request = Request(url)
    with urlopen(request, timeout=45) as response:
        effective_url = response.geturl()
        expected_host = urlsplit(url).hostname.removeprefix("www.")
        host = urlsplit(effective_url).hostname
        if urlsplit(effective_url).scheme != "https" or host.removeprefix("www.") != expected_host:
            raise ValueError(f"Unexpected redirect for {url}: {effective_url}")
        data = response.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD or not data.startswith(b"%PDF-"):
        raise ValueError(f"Invalid PDF response from {url}")
    if not data.rstrip().endswith(b"%%EOF"):
        raise ValueError(f"Truncated or malformed PDF response from {url}")
    return data, effective_url


def page_count(data):
    try:
        from pypdf import PdfReader
    except ModuleNotFoundError:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "introduction.pdf"
            path.write_bytes(data)
            result = subprocess.run(["pdfinfo", str(path)], check=True, capture_output=True, text=True)
        return int(next(line.split(":", 1)[1] for line in result.stdout.splitlines() if line.startswith("Pages:")))
    return len(PdfReader(io.BytesIO(data)).pages)


def preserve(output_dir):
    primary_bytes, primary_url = download(PRIMARY)
    mirror_url = None
    mirror_status = "Unavailable"
    try:
        mirror_bytes, candidate_url = download(MIRROR)
        if primary_bytes == mirror_bytes:
            mirror_url = candidate_url
            mirror_status = "Byte-for-byte match"
        else:
            mirror_status = "Different bytes"
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        mirror_status = str(error)
    print(f"Comparison copy from Sanskrit Documents: {mirror_status}")
    pages = page_count(primary_bytes)
    if pages != EXPECTED_PAGES:
        raise ValueError(f"Expected {EXPECTED_PAGES} pages, found {pages}")
    provenance = {
        "title": "The Ramayana of Valmeeki, introduction",
        "author": "C. R. Srinivasa Ayyangar",
        "publication_year": 1910,
        "pages": pages,
        "bytes": len(primary_bytes),
        "sha256": hashlib.sha256(primary_bytes).hexdigest(),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "source": primary_url,
        "comparison_copy": mirror_url,
        "comparison_status": mirror_status,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "vr_intro_ayyangar.pdf").write_bytes(primary_bytes)
    (output_dir / "vr_intro_ayyangar.json").write_text(json.dumps(provenance, indent=2) + "\n")
    return provenance


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    options = parser.parse_args()
    print(json.dumps(preserve(options.output_dir), indent=2))
