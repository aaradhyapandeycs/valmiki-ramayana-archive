#!/usr/bin/env python3
"""Verify an already deployed archive over HTTP."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from html import unescape
import json
import sys
from urllib.parse import urljoin
from urllib.request import urlopen


def read(url):
    with urlopen(url, timeout=30) as response:
        if response.status != 200:
            raise ValueError(f"{response.status}: {url}")
        return response.read().decode("utf-8")


def main():
    base = sys.argv[1].rstrip("/") + "/"
    headings = json.loads(read(urljoin(base, "search.json")))
    expected_text = int(sys.argv[2])
    assert len(headings) == 534
    assert len({heading["url"] for heading in headings}) == 534

    def review(heading):
        url = urljoin(base, heading["url"])
        text = read(url)
        if heading["title"] not in unescape(text):
            raise ValueError(f"Chapter heading missing: {url}")
        return 'id="sanskrit"' in text

    with ThreadPoolExecutor(max_workers=8) as pool:
        pages_with_text = sum(pool.map(review, headings))
    if pages_with_text != expected_text:
        raise ValueError(f"Expected {expected_text} Sanskrit chapter pages, found {pages_with_text}")
    for path in ["sources/", "manifest.json", "english/", "english/yuddha/130/"]:
        read(urljoin(base, path))
    inventory = json.loads(read(urljoin(base, "source-variants.json")))
    for tree in ("original", "utf8"):
        assert inventory["coverage"][tree]["chapter_directories_with_observed_children"] == 534
    intro = urljoin(base, "resources/vr_intro_ayyangar.pdf")
    metadata = json.loads(read(intro[:-4] + ".json"))
    with urlopen(intro, timeout=30) as response:
        assert sha256(response.read()).hexdigest() == metadata["sha256"]
    print(f"Live delivery verified: {len(headings)} chapter pages, {pages_with_text} with Sanskrit.")


if __name__ == "__main__":
    main()
