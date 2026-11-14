#!/usr/bin/env python3
"""Exercise the published site in Chromium and record browser and accessibility findings."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from fontTools.ttLib import TTFont
from playwright.async_api import async_playwright, expect

BASE = os.environ.get(
    "SITE_URL", "https://aaradhyapandeycs.github.io/valmiki-ramayana-archive/"
).rstrip("/") + "/"
OUT = Path(os.environ.get("SMOKE_OUTPUT", "smoke-artifacts"))
AXE_PATH = os.environ.get("AXE_PATH")
TITLE = "Nārada briefs Vālmīki about Rāma and the Rāmāyaṇa in a nutshell"
FONTS = [
    ("Noto Serif", "noto-serif.ttf", "āīūṛṝḷḹṅñṭḍṇṃḥśṣḻ̐"),
    ("Noto Serif Devanagari", "noto-serif-devanagari.ttf", "नारदंवाल्मीकिः"),
    ("Source Sans 3", "source-sans-3.ttf", "āīūṛṝḷḹṅñṭḍṇṃḥśṣḻ̐"),
]
HTTP_RETRYABLE = {429, 500, 502, 503, 504}
LAYOUT_ROUTES = (
    "", "baala/1/", "baala/25/", "yuddha/127/", "sources/", "sources/files/",
    "english/", "english/aranya/56b/",
)
AXE_ROUTES = {"", "baala/1/", "sources/", "english/aranya/56b/"}


def site_url(path):
    return urljoin(BASE, path)


async def open_page(page, path, expected=200):
    url = site_url(path)
    for delay in (0, .75, 2):
        await asyncio.sleep(delay)
        response = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        if response and response.status not in HTTP_RETRYABLE:
            break
    assert response and response.status == expected, f"{url}: expected HTTP {expected}, got {response}"
    return response


def network_log(page, findings, expected_missing):
    def failed_request(request):
        if request.failure != "net::ERR_ABORTED":
            findings.append({"type": "request", "url": request.url, "message": request.failure})

    def error_response(response):
        if (response.status >= 400 and response.url != expected_missing
                and not (response.request.resource_type == "document" and response.status in HTTP_RETRYABLE)):
            findings.append({"type": "http", "url": response.url, "status": response.status})

    def console(message):
        if message.type != "error":
            return
        location = message.location.get("url") or page.url
        # Chromium reports the expected custom-error document as a console
        # entry in addition to the separately checked HTTP response.
        if location == expected_missing and "404" in message.text:
            return
        findings.append({"type": "console", "url": location, "message": message.text})

    page.on("requestfailed", failed_request)
    page.on("response", error_response)
    page.on("console", console)
    page.on("pageerror", lambda error: findings.append({
        "type": "pageerror", "url": page.url, "message": str(error),
    }))


async def audit_accessibility(page, route, findings):
    assert await page.locator("html").get_attribute("lang") == "en", route
    await expect(page.locator("main")).to_have_count(1)
    await expect(page.locator("h1")).to_have_count(1)
    assert await page.title(), route
    duplicate = await page.evaluate("""() => {
      const used = new Set();
      return [...document.querySelectorAll('[id]')].map(el => el.id)
        .filter(id => used.has(id) || !used.add(id));
    }""")
    assert not duplicate, f"{route}: duplicate IDs: {duplicate}"
    if not AXE_PATH or route not in AXE_ROUTES:
        return
    await page.add_script_tag(path=AXE_PATH)
    outcome = await page.evaluate("""async () => {
      await document.fonts.ready;
      const { violations, incomplete } = await axe.run({
        runOnly: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'],
      });
      const describe = result => ({
        id: result.id, impact: result.impact,
        nodes: result.nodes.map(node => node.target),
      });
      return { violations: violations.map(describe), incomplete: incomplete.map(describe) };
    }""")
    findings.append({"route": route, **outcome})


async def inspect_home(page):
    await expect(page.locator(".chapters a")).to_have_count(534)
    await expect(page.get_by_role("searchbox", name="Search chapter headings or sarga number")).to_be_visible()
    await expect(page.locator("#search-count")).to_have_attribute("aria-live", "polite")
    await page.keyboard.press("Tab")
    skip = page.get_by_role("link", name="Skip to content")
    await expect(skip).to_be_focused()
    await page.keyboard.press("Enter")
    assert await page.evaluate("location.hash") == "#main"
    await page.keyboard.press("Tab")
    assert await page.evaluate("document.querySelector('main').contains(document.activeElement)")
    gradient = await page.locator(".site-head").evaluate("(el) => getComputedStyle(el).backgroundImage")
    assert ("9, 32, 63" in gradient or "#09203f" in gradient.lower()), gradient
    assert ("83, 120, 149" in gradient or "#537895" in gradient.lower()), gradient

    search = page.get_by_role("searchbox")
    matched = []
    for query in ("Rama", "Rāma"):
        await search.fill(query)
        await expect(page.locator('#results a[href$="/baala/1/"]')).to_be_visible()
        matched.append(await page.locator("#results a").all_text_contents())
    assert matched[0] == matched[1] and any("Rāma" in row for row in matched[0])
    await search.fill("2-119")
    await expect(page.locator('#results a[href$="/ayodhya/119/"]')).to_be_visible()
    await expect(page.locator("#results a")).to_have_count(1)
    await search.fill("zzzzzz-no-sarga")
    await expect(page.locator("#search-count")).to_have_text("0 matching sargas")
    await search.fill("")
    await expect(page.locator("#books")).to_be_visible()
    return len(matched[0])


async def inspect_verse(page):
    await expect(page.get_by_role("heading", level=1)).to_have_text(TITLE)
    await expect(page.locator(".verse [lang=sa-Deva]").first).to_contain_text("नारद")
    await expect(page.locator(".verse [lang=sa-Latn]").first).to_contain_text("nārada")
    tests = await page.evaluate("""async families => {
      const out = {};
      for (const [family, , sample] of families) {
        const face = await document.fonts.load('16px "' + family + '"', sample);
        out[family] = face.some(entry => entry.status === 'loaded');
      }
      return out;
    }""", FONTS)
    assert all(tests.values()), tests
    verse = page.locator(".verse a").first
    anchor = await verse.get_attribute("href")
    await verse.click()
    assert await page.evaluate("location.hash") == anchor
    assert await page.evaluate("Boolean(document.querySelector(':target'))")
    await page.reload(wait_until="domcontentloaded")
    assert await page.evaluate("Boolean(document.querySelector(':target'))")
    sources = page.locator(".chapter-sources")
    summary = sources.locator("summary")
    await summary.focus()
    await page.keyboard.press("Enter")
    assert await sources.evaluate("(details) => details.open")
    await expect(sources.get_by_role("link", name="UTF-8 chapter viewer", exact=False)).to_be_visible()
    next_chapter = page.get_by_role("link", name="Next →", exact=True)
    await next_chapter.click()
    assert page.url == site_url("baala/2/")
    await page.get_by_role("link", name="← Previous", exact=True).click()
    assert page.url == site_url("baala/1/")
    return tests


async def inspect_viewport(browser, width, height, label):
    expected_missing = site_url("missing-audit-route/deep/path/")
    context = await browser.new_context(viewport={"width": width, "height": height}, reduced_motion="reduce")
    page = await context.new_page()
    errors = []
    accessibility = []
    network_log(page, errors, expected_missing)
    report = {
        "viewport": label, "width": width, "height": height, "routes": {},
        "errors": errors, "accessibility": accessibility,
    }
    try:
        for route in LAYOUT_ROUTES:
            await open_page(page, route)
            await audit_accessibility(page, route, accessibility)
            await page.evaluate("document.fonts.ready")
            overflow = await page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
            assert overflow <= 1, f"{route} at {width}px: horizontal overflow {overflow}px"
            report["routes"][route] = {"horizontal_overflow_px": overflow}
            if route == "":
                report["search_matches"] = await inspect_home(page)
                await page.screenshot(path=str(OUT / f"{label}-home.png"))
            elif route == "baala/1/":
                report["fonts"] = await inspect_verse(page)
                await page.screenshot(path=str(OUT / f"{label}-chapter.png"))
            elif route == "baala/25/":
                href = await page.get_by_role("link", name="Read the original chapter", exact=False).get_attribute("href")
                assert urlsplit(href).path.endswith("/bala_5F25_frame.htm"), href
            elif route == "yuddha/127/":
                await expect(page.locator(".verse [lang=sa-Deva]").first).to_be_visible()
                await expect(page.locator(".iast-gap").first).to_be_visible()
            elif route == "sources/":
                link = page.get_by_role("link", name="Read Ayyangar’s 1910 introduction (PDF)", exact=False)
                assert urljoin(page.url, await link.get_attribute("href")) == site_url("resources/vr_intro_ayyangar.pdf")
            elif route == "english/aranya/56b/":
                await expect(page.locator("article")).to_be_visible()
                await expect(page.get_by_role("heading", level=1)).to_contain_text("56b")
        await open_page(page, "missing-audit-route/deep/path/", 404)
        await expect(page.get_by_role("heading", name="Page not found")).to_be_visible()
        assert await page.locator(".site-head").evaluate("(el) => getComputedStyle(el).backgroundImage") != "none"
        recovery = page.get_by_role("link", name="Return to the chapter directory")
        assert urljoin(page.url, await recovery.get_attribute("href")) in {site_url(""), site_url("index.html")}
        await recovery.click()
        await expect(page.get_by_role("searchbox")).to_be_visible()
        report["custom_404"] = True
    except Exception as error:
        report["failed_assertion"] = str(error)
        await page.screenshot(path=str(OUT / f"{label}-failure.png"))
    finally:
        await context.close()
    return report


async def check_pdf(request):
    relative = "resources/vr_intro_ayyangar"
    info = await request.get(site_url(relative + ".json"), timeout=30000)
    assert info.ok, info.status
    metadata = await info.json()
    pdf = await request.get(site_url(relative + ".pdf"), timeout=30000)
    assert pdf.ok, pdf.status
    assert pdf.headers.get("content-type", "").split(";")[0] == "application/pdf"
    contents = await pdf.body()
    assert contents.startswith(b"%PDF-")
    assert contents.rstrip().endswith(b"%%EOF")
    assert metadata["pages"] == 142
    assert hashlib.sha256(contents).hexdigest() == metadata["sha256"]
    return {"url": pdf.url, "bytes": len(contents), "pages": metadata["pages"], "sha256": metadata["sha256"]}



async def check_font_glyphs(request):
    coverage = {}
    for family, filename, sample in FONTS:
        response = await request.get(site_url("fonts/" + filename), timeout=30000)
        assert response.ok, f"{family}: HTTP {response.status}"
        with TTFont(BytesIO(await response.body())) as font:
            glyphs = font.getBestCmap() or {}
            missing = [f"U+{ord(char):04X}" for char in sample if ord(char) not in glyphs]
        assert not missing, f"{family}: missing required glyphs {missing}"
        coverage[family] = {"characters_checked": len(sample), "url": response.url}
    return coverage


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"site": BASE, "browser": "Chromium", "viewports": []}
    async with async_playwright() as tool:
        browser = await tool.chromium.launch()
        request = await tool.request.new_context()
        try:
            report["pdf"] = await check_pdf(request)
        except Exception as error:
            report["pdf_error"] = str(error)
        try:
            report["glyphs"] = await check_font_glyphs(request)
        except Exception as error:
            report["glyph_error"] = str(error)
        for width, height, name in ((1440, 900, "desktop"), (390, 844, "mobile"), (320, 740, "narrow-mobile")):
            report["viewports"].append(await inspect_viewport(browser, width, height, name))
        await request.dispose()
        await browser.close()
    failures = [
        entry["viewport"] for entry in report["viewports"]
        if entry["errors"] or entry.get("failed_assertion")
        or any(result["violations"] for result in entry["accessibility"])
    ]
    report["failed_viewports"] = failures
    (OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if failures or report.get("pdf_error") or report.get("glyph_error"):
        print(json.dumps(report, indent=2, ensure_ascii=False))
        raise SystemExit("Browser checks failed. See the audit report.")
    print(f"Passed {len(LAYOUT_ROUTES)} browser routes at three viewport widths, PDF integrity, search, navigation, and 404 recovery.")


if __name__ == "__main__":
    asyncio.run(main())
