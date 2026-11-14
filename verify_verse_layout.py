#!/usr/bin/env python3
"""Check every rendered Sanskrit line with Chromium after web fonts load."""
import argparse
import asyncio
from collections import Counter
from html.parser import HTMLParser
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urljoin, urlsplit

from playwright.async_api import async_playwright

PROFILES = {
    "desktop": (1440, 900, 1, False),
    "tablet": (768, 1024, 1, False),
    "mobile": (390, 844, 1, False),
    # A 1440px window at 200% browser zoom has a 720 CSS-pixel layout
    # viewport. DPR=2 preserves that relationship for the screenshot.
    "zoom-200": (720, 450, 2, False),
    "mobile-large-text": (390, 844, 1, True),
}

LINE_AUDIT = r"""() => {
    const stats = {
        lines: 0, devanagari: 0, iast: 0, verse_pairs: 0,
        passages: 0, overflowing_regions: 0, multirow_passages: 0
    };
    const errors = [];
    const overflowing = [];
    const passageSelector = '#sanskrit [lang="sa-Deva"], #sanskrit [lang="sa-Latn"]';
    const endingOnly = /^\s*[।॥|]*(?:\s*[0-9०-९]+(?:\s*[-–]\s*[0-9०-९]+){1,4})?\s*[।॥|]*\s*$/u;
    const lineEnding = /(?:\|\||॥)\s*[0-9०-९]+(?:[-–][0-9०-९]+){2,4}\s*$/u;
    const label = el => el.closest('[id]')?.id || 'sanskrit';
    const record = (el, problem) => {
        errors.push({anchor: label(el), problem});
    };
    const texts = [...document.querySelectorAll(passageSelector)];
    if (texts.length === 0) errors.push({problem: 'Sanskrit reader is empty'});
    if (document.documentElement.scrollWidth > innerWidth + 1) {
        errors.push({
            problem: 'page-wide horizontal overflow',
            viewport: innerWidth, width: document.documentElement.scrollWidth,
            protrusions: [...document.querySelectorAll('body *')]
                .filter(el => !el.closest('.verse-scroll') && el.getBoundingClientRect().right > innerWidth + 1)
                .slice(0, 8).map(el => [el.tagName, el.className, Math.round(el.getBoundingClientRect().right)])
        });
    }
    const scrollRegions = new Set();
    const rowsByPassage = new Map();
    for (const text of texts) {
        const lang = text.getAttribute('lang');
        const lines = [...text.querySelectorAll('.verse-line')];
        rowsByPassage.set(text, lines.length);
        stats.passages++;
        if (lines.length > 2) stats.multirow_passages++;
        if (!lines.length) record(text, 'script has no explicit line rows');
        const scroller = text.closest('.verse-scroll');
        if (!scroller) record(text, 'script is outside an explicit scroll region');
        else scrollRegions.add(scroller);
        const color = getComputedStyle(text).color;
        const expected = lang === 'sa-Deva' ? 'rgb(32, 54, 74)' : 'rgb(116, 69, 82)';
        if (color !== expected) record(text, 'unexpected script color: ' + color);
        let lastBottom = -Infinity;
        for (const line of lines) {
            const position = line.getBoundingClientRect();
            const style = getComputedStyle(line);
            const textValue = line.textContent;
            stats.lines++;
            stats[lang === 'sa-Deva' ? 'devanagari' : 'iast']++;
            if (!['nowrap', 'pre'].includes(style.whiteSpace)) {
                record(line, 'explicit line permits wrapping: ' + style.whiteSpace);
            }
            if (textValue.trim() && endingOnly.test(textValue)) record(line, 'orphaned punctuation or locator');
            if (position.top < lastBottom - 1) record(line, 'source rows share a visual row');
            lastBottom = position.bottom;
            if (!textValue.trim()) continue; // Intentional stanza separators.
            const range = new Range();
            range.selectNodeContents(line);
            // Combining marks and fallback glyphs may produce separate
            // rectangles on the same row. Count distinct vertical centres.
            const rects = [...range.getClientRects()].filter(r => r.width > 0 && r.height > 0);
            const centres = [];
            const fontSize = parseFloat(style.fontSize);
            for (const rect of rects) {
                const centre = (rect.top + rect.bottom) / 2;
                if (!centres.some(y => Math.abs(y - centre) <= fontSize * .55)) centres.push(centre);
            }
            if (centres.length !== 1) record(line, 'text Range occupies ' + centres.length + ' visual rows');
            if (scroller && rects.some(rect => rect.right >
                scroller.getBoundingClientRect().left + scroller.scrollWidth + 2)) {
                record(line, 'line extends beyond its scrollable area');
            }
        }
    }
    for (const verse of document.querySelectorAll('.verse, .source-paratext, .verse-closing')) {
        const deva = verse.querySelector('[lang="sa-Deva"]');
        const iast = verse.querySelector('[lang="sa-Latn"]');
        if (deva && iast) {
            stats.verse_pairs++;
            if (rowsByPassage.get(deva) !== rowsByPassage.get(iast)) {
                record(verse, 'Devanāgarī and IAST row counts differ');
            }
        }
    }
    for (const scroller of scrollRegions) {
        const style = getComputedStyle(scroller);
        if (scroller.scrollWidth <= scroller.clientWidth) continue;
        stats.overflowing_regions++;
        overflowing.push(label(scroller));
        if (!['auto', 'scroll'].includes(style.overflowX)) {
            record(scroller, 'overflow lacks horizontal scrolling');
        }
        if (scroller.tabIndex !== 0 || !scroller.getAttribute('aria-label') && !scroller.getAttribute('aria-labelledby')) {
            record(scroller, 'overflow region lacks focus or accessible label');
        }
        const before = scroller.scrollLeft;
        scroller.scrollLeft = scroller.scrollWidth;
        if (scroller.scrollLeft + scroller.clientWidth < scroller.scrollWidth - 2) {
            record(scroller, 'horizontal scrolling cannot reach line end');
        }
        scroller.scrollLeft = before;
    }
    if (/\/baala\/1\/$/.test(location.pathname)) {
        for (const id of ['verse-2', 'verse-5']) {
            const verse = document.getElementById(id);
            if (!verse) {
                errors.push({anchor: id, problem: 'expected example verse absent'});
                continue;
            }
            for (const script of ['sa-Deva', 'sa-Latn']) {
                const lines = [...verse.querySelectorAll('[lang="' + script + '"] .verse-line')];
                if (lines.length !== 2 || !lineEnding.test(lines[1].textContent)) {
                    record(verse, script + ' should have 2 source lines and its locator on line 2');
                }
            }
        }
    }
    return {stats, errors, overflowing, passages: texts.map(node => [
        node.getAttribute('lang'), node.textContent
    ])};
}"""


class BaselinePassages(HTMLParser):
    """Collect the frozen baseline reader's text for independent comparison."""

    def __init__(self):
        super().__init__()
        self.in_reader = False
        self.language = None
        self.container = None
        self.parts = []
        self.passages = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "section" and attributes.get("id") == "sanskrit":
            self.in_reader = True
        if self.in_reader and tag in {"p", "div"}:
            language = attributes.get("lang")
            if language in {"sa-Deva", "sa-Latn"}:
                self.language, self.container = language, tag

    def handle_endtag(self, tag):
        if tag == self.container:
            self.passages.append((self.language, " ".join("".join(self.parts).split())))
            self.parts = []
            self.language = self.container = None
        if tag == "section" and self.in_reader:
            self.in_reader = False

    def handle_data(self, data):
        if self.language:
            self.parts.append(data)


def baseline_passages(directory, route, base):
    prefix = urlsplit(base).path
    path = urlsplit(route).path
    if not path.startswith(prefix):
        raise ValueError("chapter route is outside the site base")
    file = directory / path.removeprefix(prefix) / "index.html"
    parser = BaselinePassages()
    parser.feed(file.read_text(encoding="utf-8"))
    return parser.passages


async def open_route(page, base, route, large_text):
    response = await page.goto(urljoin(base, route), wait_until="domcontentloaded", timeout=40_000)
    if not response or response.status != 200:
        raise RuntimeError(f"HTTP {response.status if response else 'missing response'}")
    if large_text:
        await page.evaluate("document.documentElement.style.fontSize = '200%'")
    await page.evaluate("""async () => {
        await document.fonts.ready;
        for (const [font, sample] of [
            ['Noto Serif Devanagari', 'राम'],
            ['Noto Serif', 'Rāma']
        ]) {
            const faces = await document.fonts.load('16px "' + font + '"', sample);
            if (!faces.some(face => face.status === 'loaded')) {
                throw new Error('reader font not loaded: ' + font);
            }
        }
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    }""")


async def screenshot_examples(context, base, output, label, profile, baseline):
    page = await context.new_page()
    try:
        await open_route(page, base, "baala/1/", profile[-1])
        examples = {}
        for verse in ("verse-2", "verse-5"):
            locator = page.locator("#" + verse)
            await locator.screenshot(path=str(output / f"{label}-{verse}.png"))
            examples[verse] = await locator.evaluate("""node =>
                Object.fromEntries([...node.querySelectorAll('[lang]')].map(script => {
                    const range = document.createRange();
                    range.selectNodeContents(script);
                    const rows = [];
                    const size = parseFloat(getComputedStyle(script).fontSize);
                    for (const rect of range.getClientRects()) {
                        const midpoint = (rect.top + rect.bottom) / 2;
                        if (rect.width && rect.height && !rows.some(row => Math.abs(row-midpoint) <= size*.55)) {
                            rows.push(midpoint);
                        }
                    }
                    const explicit = script.querySelectorAll('.verse-line');
                    return [script.lang, explicit.length || rows.length];
                }))""")
        (output / f"{label}-examples.json").write_text(
            json.dumps(examples, indent=2) + "\n", encoding="utf-8"
        )
        if not baseline:
            await page.locator("#source-paragraph-494").screenshot(
                path=str(output / f"{label}-gayatri-appendix.png")
            )
            await open_route(page, base, "kish/29/", profile[-1])
            await page.locator(".verse").first.screenshot(
                path=str(output / f"{label}-kish-29-first-block.png")
            )
    finally:
        await page.close()


async def keyboard_check(page):
    return await page.evaluate("""() => {
        const scroll = [...document.querySelectorAll('.verse-scroll')]
            .find(node => node.scrollWidth > node.clientWidth);
        if (!scroll) return null;
        scroll.scrollLeft = 0;
        scroll.focus();
        return {focused: document.activeElement === scroll,
            label: scroll.getAttribute('aria-label') || scroll.getAttribute('aria-labelledby')};
    }""")


async def inspect_actual_browser_zoom(playwright, base, output):
    """Use Chromium's native setZoom for representative source blocks."""
    with TemporaryDirectory(prefix="verse-zoom-") as workspace:
        root = Path(workspace)
        extension = root / "extension"
        extension.mkdir()
        manifest = {
            "manifest_version": 3, "name": "Local verse QA zoom", "version": "1.0",
            "permissions": ["tabs"], "background": {"service_worker": "worker.js"},
        }
        (extension / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (extension / "worker.js").write_text(
            "chrome.runtime.onInstalled.addListener(() => {});", encoding="utf-8"
        )
        context = await playwright.chromium.launch_persistent_context(
            root / "profile", channel="chromium", headless=True,
            no_viewport=True, reduced_motion="reduce", locale="en",
            args=["--window-size=1440,900", f"--disable-extensions-except={extension}",
                  f"--load-extension={extension}"],
        )
        try:
            worker = (context.service_workers[0] if context.service_workers else
                      await context.wait_for_event("serviceworker", timeout=8_000))
            page = context.pages[0]
            await open_route(page, base, "baala/1/", False)
            unzoomed = await page.evaluate("({width:innerWidth,dpr:devicePixelRatio})")
            zoom_factor = await worker.evaluate("""async target => {
                const tabs = await chrome.tabs.query({});
                const tab = tabs.find(tab => tab.url === target);
                if (!tab) throw new Error('Reader tab not found by native zoom API');
                await chrome.tabs.setZoom(tab.id, 2);
                return await chrome.tabs.getZoom(tab.id);
            }""", page.url)
            await page.wait_for_function(
                "(before) => innerWidth < before.width * .6 && devicePixelRatio >= before.dpr * 1.95",
                arg=unzoomed, timeout=8_000,
            )
            zoomed = await page.evaluate("({width:innerWidth,dpr:devicePixelRatio})")
            reports = {}
            for route, anchor in [("baala/1/", "verse-2"), ("kish/29/", "block-1")]:
                await open_route(page, base, route, False)
                report = await page.evaluate(LINE_AUDIT)
                reports[route] = {"metrics": report["stats"], "errors": report["errors"]}
                if await page.locator("#" + anchor).count():
                    await page.locator("#" + anchor).screenshot(
                        path=str(output / f"after-native-zoom-{anchor}.png")
                    )
            return {"zoom_factor": zoom_factor, "before": unzoomed, "after": zoomed, "routes": reports}
        finally:
            await context.close()


async def main(args):
    base = args.base.rstrip("/") + "/"
    profile = PROFILES[args.profile]
    width, height, ratio, large_text = profile
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": width, "height": height}, device_scale_factor=ratio,
            reduced_motion="reduce", locale="en",
        )
        if args.baseline:
            await screenshot_examples(context, base, output, f"before-{args.profile}", profile, True)
            await browser.close()
            return
        response = await context.request.get(urljoin(base, "search.json"))
        if not response.ok:
            raise RuntimeError(f"search.json: HTTP {response.status}")
        rows = await response.json()
        routes = {row["url"] for row in rows}
        if len(rows) != 534 or len(routes) != 534:
            raise RuntimeError("Expected 534 distinct chapter URLs.")
        queue = asyncio.Queue()
        for route in sorted(routes):
            queue.put_nowait(route)
        checked = []
        failures = []
        total = Counter()

        async def worker():
            page = await context.new_page()
            try:
                while not queue.empty():
                    route = queue.get_nowait()
                    try:
                        await open_route(page, base, route, large_text)
                        report = await page.evaluate(LINE_AUDIT)
                        total.update(report["stats"])
                        if args.baseline_dist:
                            old_text = baseline_passages(args.baseline_dist, route, base)
                            new_text = [(lang, " ".join(content.split()))
                                        for lang, content in report["passages"]]
                            if old_text != new_text:
                                first = next((i for i, (old, new) in enumerate(zip(old_text, new_text), 1)
                                              if old != new), None)
                                report["errors"].append({
                                    "problem": "script content differs after whitespace normalization",
                                    "baseline_passages": len(old_text), "rendered_passages": len(new_text),
                                    "first_disagreement": first,
                                })
                        checked.append(route)
                        if report["errors"]:
                            failures.append({"route": route, "errors": report["errors"]})
                    except Exception as error:
                        failures.append({"route": route, "errors": [{"problem": str(error)}]})
                    finally:
                        queue.task_done()
            finally:
                await page.close()

        await asyncio.gather(*(worker() for _ in range(args.workers)))
        await screenshot_examples(context, base, output, f"after-{args.profile}", profile, False)
        key_page = await context.new_page()
        await open_route(key_page, base, "baala/1/", large_text)
        keyboard = await keyboard_check(key_page)
        if keyboard:
            await key_page.keyboard.press("ArrowRight")
            try:
                await key_page.wait_for_function("document.activeElement.scrollLeft > 0", timeout=1_000)
                keyboard["arrow_scrolled"] = True
            except Exception:
                keyboard["arrow_scrolled"] = False
            if not keyboard["focused"] or not keyboard["label"] or not keyboard["arrow_scrolled"]:
                failures.append({"route": "baala/1/", "keyboard": keyboard})
        elif total["overflowing_regions"] and args.profile in {"mobile", "mobile-large-text"}:
            failures.append({"route": "baala/1/", "problem": "expected a narrow scrolling example"})
        await key_page.close()
        await browser.close()
        zoom = None
        if args.actual_browser_zoom:
            try:
                zoom = await inspect_actual_browser_zoom(playwright, base, output)
            except Exception as error:
                # The native browser extension is supplemental. Keep the
                # exhaustive CSS viewport and font-zoom measurements.
                zoom = {"error": str(error)}
    report = {
        "profile": args.profile, "viewport": [width, height],
        "device_pixel_ratio": ratio, "root_text_200_percent": large_text,
        "chapter_routes": len(checked), "metrics": dict(total),
        "compared_text_with_frozen_baseline": args.baseline_dist is not None,
        "keyboard": keyboard, "failures": failures,
        "native_browser_zoom": zoom,
    }
    (output / f"{args.profile}-audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: val for key, val in report.items() if key != "failures"}, ensure_ascii=False))
    if failures or len(checked) != 534:
        print(json.dumps(failures[:12], ensure_ascii=False))
        raise SystemExit(f"{len(failures)} failing chapter or interaction checks.")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("base")
    cli.add_argument("profile", choices=PROFILES)
    cli.add_argument("--output", type=Path, default=Path("verse-audit"))
    cli.add_argument("--baseline", action="store_true")
    cli.add_argument("--baseline-dist", type=Path, help="frozen pre-change dist directory for exact passage comparison")
    cli.add_argument("--actual-browser-zoom", action="store_true",
                     help="also check representative pages at Chromium native 200% zoom")
    cli.add_argument("--workers", type=int, default=4, choices=range(1, 9))
    asyncio.run(main(cli.parse_args()))
