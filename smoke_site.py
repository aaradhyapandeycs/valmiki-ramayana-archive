#!/usr/bin/env python3
"""Check the deployed Pages site in Chromium at desktop and mobile widths.

Runner setup:
    python3 -m pip install playwright
    python3 -m playwright install --with-deps chromium
    python3 smoke_site.py

Screenshots and a JSON report are written to the directory in SMOKE_OUTPUT.
This checks delivery, navigation and responsive layout. It does not verify
the original site's text, copyright status or verse-by-verse fidelity.
"""
from __future__ import annotations

import asyncio
import html
import json
import os
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from playwright.async_api import async_playwright

BASE = os.environ.get(
    "SITE_URL", "https://aaradhyapandeycs.github.io/valmiki-ramayana-archive/"
).rstrip("/") + "/"
OUT = Path(os.environ.get("SMOKE_OUTPUT", "smoke-artifacts"))


async def visit_chapter(request, row, semaphore):
    async with semaphore:
        url = row["url"]
        if not url.startswith(urlsplit(BASE).path):
            return {"url": url, "status": "outside-base"}
        response = await request.get(urljoin(BASE, url), timeout=30000)
        text = await response.text() if response.ok else ""
        expected = row["title"]
        return {
            "url": url,
            "http_status": response.status,
            "title_found": expected in html.unescape(text),
            "passed": response.status == 200 and expected in html.unescape(text),
        }


async def inspect_viewport(browser, width, height, label):
    page = await browser.new_page(viewport={"width": width, "height": height},
                                  device_scale_factor=1)
    await page.goto(BASE, wait_until="domcontentloaded", timeout=45000)
    await page.locator("#search").wait_for()
    assert await page.title() == "Chapter directory · Vālmīki Rāmāyaṇa"
    assert await page.locator(".chapters a").count() == 534
    overflow = await page.evaluate(
        "() => document.documentElement.scrollWidth - window.innerWidth"
    )
    assert overflow <= 1, f"{label}: horizontal overflow {overflow}px"
    gradient = await page.locator(".site-head").evaluate(
        "(el) => getComputedStyle(el).backgroundImage"
    )
    assert "#09203f" in gradient.lower() or "9, 32, 63" in gradient, gradient
    assert "#537895" in gradient.lower() or "83, 120, 149" in gradient, gradient
    await page.screenshot(path=str(OUT / f"{label}-home.png"), full_page=False)
    await page.locator("#search").fill("Hanuma")
    await page.locator("#results a").first.wait_for()
    hits = await page.locator("#results a").count()
    assert hits > 0 and await page.locator("#books").is_hidden()
    await page.locator("#search").fill("")
    assert await page.locator("#books").is_visible()
    await page.goto(urljoin(BASE, "baala/1/"), wait_until="domcontentloaded")
    assert await page.locator("h1").count() == 1
    assert await page.locator("a.button").get_attribute("href")
    chapter_overflow = await page.evaluate(
        "() => document.documentElement.scrollWidth - window.innerWidth"
    )
    assert chapter_overflow <= 1, f"{label}: chapter overflow {chapter_overflow}px"
    await page.screenshot(path=str(OUT / f"{label}-chapter.png"), full_page=False)
    await page.close()
    return {"viewport": label, "search_hits": hits,
            "home_overflow_px": overflow, "chapter_overflow_px": chapter_overflow}


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        request = await playwright.request.new_context()
        response = await request.get(urljoin(BASE, "search.json"))
        assert response.status == 200, f"search.json: HTTP {response.status}"
        chapters = await response.json()
        assert len(chapters) == 534, f"Found {len(chapters)} chapter entries"
        semaphore = asyncio.Semaphore(10)
        checked = await asyncio.gather(
            *(visit_chapter(request, row, semaphore) for row in chapters),
            return_exceptions=True,
        )
        failures = [str(result) for result in checked if isinstance(result, Exception)]
        failures.extend(str(result) for result in checked
                        if not isinstance(result, Exception) and not result["passed"])
        counts = Counter(row["book"] for row in chapters)
        views = []
        for width, height, label in ((1440, 900, "desktop"),
                                     (390, 844, "mobile")):
            views.append(await inspect_viewport(browser, width, height, label))
        report = {"site": BASE, "chapter_counts": dict(counts),
                  "routes_checked": len(chapters),
                  "route_failures": failures, "viewports": views,
                  "scope": "Published HTML delivery, title, search and layout only"}
        (OUT / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        await browser.close()
        await request.dispose()
        if failures:
            raise SystemExit(f"{len(failures)} deployed route failures; see {OUT / 'report.json'}")
        print(f"Passed: {len(chapters)} deployed routes, search, desktop and mobile layout")


if __name__ == "__main__":
    asyncio.run(main())
