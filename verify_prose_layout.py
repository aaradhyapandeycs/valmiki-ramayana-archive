#!/usr/bin/env python3
"""Check representative English source controls at desktop, mobile and enlarged sizes."""
import argparse
import asyncio
import json
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory
from urllib.parse import urljoin

from playwright.async_api import Error as BrowserError, async_playwright


PROFILES = {
    "desktop": (1440, 960, 1, False, True),
    "tablet": (768, 1024, 1, False, False),
    "mobile": (390, 844, 1, False, False),
    "zoom-200": (720, 480, 2, False, False),
    "mobile-large-text": (390, 844, 1, True, False),
    "desktop-large-text": (1440, 960, 1, True, False),
}
SLUGS = ("baala", "ayodhya", "aranya", "kish", "sundara", "yuddha")
GEOMETRY = r"""({wide}) => {
    const errors = [];
    const cards = [...document.querySelectorAll('.verse-pair')];
    const root = document.documentElement;
    if (root.scrollWidth > innerWidth + 1) errors.push('page-wide horizontal overflow');
    if (!cards.length) errors.push('no source link panels');
    for (const row of cards) {
        const [scripts, panel] = row.children;
        const text = scripts.querySelector('[lang=sa-Deva] .verse-line');
        if (!text) { errors.push('Sanskrit side missing'); continue; }
        const first = text.getBoundingClientRect();
        const english = panel.getBoundingClientRect();
        const left = scripts.getBoundingClientRect();
        const outer = row.getBoundingClientRect();
        const name = panel.querySelector('a')?.dataset.sourceRefs || 'unnamed link';
        if (wide) {
            if (english.left < left.right - 1 || Math.abs(english.top - first.top) > 11) {
                errors.push(name + ': English control does not align beside the first Sanskrit line');
            }
        } else if (english.top < left.bottom - 1 || english.right > outer.right + 1) {
            errors.push(name + ': English control does not follow contained Sanskrit–IAST');
        }
        if (english.bottom > outer.bottom + 1 || left.bottom > outer.bottom + 1) {
            errors.push(name + ': row does not contain both sides');
        }
        const font = getComputedStyle(panel);
        if (font.color !== 'rgb(48, 72, 56)' || font.backgroundColor !== 'rgb(250, 249, 244)') {
            errors.push(name + ': right-hand reading colors changed');
        }
        if (panel.scrollWidth > panel.clientWidth + 1) errors.push(name + ': English control overflows');
    }
    const available = [...document.querySelectorAll('.verse-scroll')]
        .filter(node => node.scrollWidth > node.clientWidth);
    if (available.some(node => node.tabIndex !== 0 ||
        !node.getAttribute('aria-label') && !node.getAttribute('aria-labelledby'))) {
        errors.push('some horizontal scroll areas lack keyboard access');
    }
    const affected = [...document.querySelectorAll('.verse-pair .verse-scroll')]
        .filter(node => node.scrollWidth > node.clientWidth).length;
    return {
        errors: errors.slice(0, 15),
        cards: cards.length,
        overflow_regions: available.length,
        linked_overflow_regions: affected,
    };
}"""


def fixture_groups(chapters):
    chosen = {}
    for slug in SLUGS:
        groups = [(key, group) for key, chapter in chapters.items() if key.startswith(f"{slug}/")
                  for group in chapter["mapped_groups"]]
        if not groups:
            raise ValueError(f"No verified English source control in {slug}")
        preferred = next((p for p in groups if p[0] == f"{slug}/1"), groups[0])
        chosen[f"{slug}-opening"] = preferred
    all_groups = [(key, group) for key, chapter in chapters.items() for group in chapter["mapped_groups"]]
    chosen["partial-range"] = next(
        (p for p in all_groups if p[0] == "baala/1" and p[1]["refs"] == ["1-1-52b", "1-1-53a"]),
        next(p for p in all_groups if any(ref.endswith(tuple("abcd")) for ref in p[1]["refs"])
             and len(p[1]["units"]) > 1),
    )
    chosen["longest-group"] = max(all_groups, key=lambda p: len(p[1]["units"]))
    bala_opening = {tuple(group["refs"]): group for group in chapters["baala/77"]["mapped_groups"]}
    for label, refs in (("1", ("1-77-1",)), ("2", ("1-77-2",)), ("3", ("1-77-3",)),
                        ("4-5", ("1-77-4", "1-77-5"))):
        chosen[f"bala-77-{label}"] = ("baala/77", bala_opening[refs])
    no_link = next((key for key, chapter in chapters.items() if not chapter["mapped_groups"]), None)
    return chosen, no_link


async def exact_card(page, group):
    links = page.locator("a[data-source-refs]").filter(
        has_text=", ".join(group["refs"]) + " ·"
    )
    for link in await links.all():
        if (await link.get_attribute("href") == group["href"]
                and await link.get_attribute("data-prose-basis") == group["basis"]):
            return link.locator("xpath=ancestor::div[contains(@class, 'verse-pair')][1]")
    raise ValueError(f"Missing exact link {group}")


async def keyboard_probe(page):
    scroll = page.locator(".verse-scroll[data-overflow][tabindex='0']").first
    # Save and restore the visual styling and reading position before capture.
    await scroll.focus()
    await page.keyboard.press("ArrowRight")
    await page.wait_for_function("document.activeElement.scrollLeft > 0", timeout=1500)
    await scroll.evaluate("node => { node.blur(); node.scrollLeft = 0; }")
    await page.wait_for_function("document.activeElement?.matches('.verse-scroll') === false", timeout=1500)


async def screenshot_panel(page, card, destination):
    """Capture the exact joined unit with both scripts at their scroll origins."""
    await card.locator(".verse-scroll").evaluate_all(
        "nodes => nodes.forEach(node => { node.blur(); node.scrollLeft = 0; })"
    )
    await card.screenshot(path=destination)


async def check_profile(browser, profile, name, args, fixtures, no_link, open_route, line_audit):
    width, height, ratio, enlarged, wide = profile
    options = {"viewport": {"width": width, "height": height}, "device_scale_factor": ratio,
               "reduced_motion": "reduce", "locale": "en"}
    context = await browser.new_context(**options)
    page = await context.new_page()
    screenshot = name in {"desktop", "mobile", "zoom-200"}
    summaries = {}
    last_checked = None
    keyboard_checks = 0
    unmatched_result = None
    try:
        for label, (chapter, group) in fixtures.items():
            if last_checked != chapter:
                await open_route(page, args.after, chapter + "/", enlarged)
                last_checked = chapter
                result = await page.evaluate(GEOMETRY, {"wide": wide})
                script_result = await page.evaluate(line_audit)
                if result["errors"] or script_result["errors"]:
                    raise ValueError(f"{name} {chapter}: {result['errors']} / {script_result['errors'][:8]}")
                result["checked_script_rows"] = script_result["stats"]["lines"]
                if result["overflow_regions"] and name in {"mobile", "mobile-large-text"}:
                    await keyboard_probe(page)
                    keyboard_checks += 1
                summaries[chapter] = result
            card = await exact_card(page, group)
            if label.startswith("bala-77-"):
                dutt = card.locator(".dutt-inline")
                assert await dutt.count() == 1
                assert (await dutt.get_attribute("data-dutt-units")).split() == group["units"]
                assert len((await dutt.locator(".dutt-english-text").inner_text()).split()) >= 15
            if screenshot:
                await screenshot_panel(page, card, args.output / f"after-{name}-{label}.png")
        if no_link:
            await open_route(page, args.after, no_link + "/", enlarged)
            gap = page.locator("#sanskrit .source-note").filter(
                has_text="Verse-level references could not be verified for this chapter."
            )
            if (await page.locator("a[data-source-refs]").count() or await gap.count() != 1
                    or await gap.get_by_role("link", name="Read the chapter’s English at the source ↗").count() != 1):
                raise ValueError(f"{no_link}: source-link gap has an unexpected presentation")
            usable = await page.evaluate(line_audit)
            if usable["errors"]:
                raise ValueError(f"{no_link}: Sanskrit rendering errors beside the gap {usable['errors'][:8]}")
            unmatched_result = {"chapter": no_link, "source_link": await gap.locator("a").get_attribute("href"),
                                "checked_script_rows": usable["stats"]["lines"]}
        for chapter, translated, units in (("baala/5", 12, 14), ("baala/77", 21, 24)):
            await open_route(page, args.after, chapter + "/", enlarged)
            originals = page.locator(".original-translation")
            assert await originals.count() == translated
            anchors = await originals.evaluate_all("nodes => [...new Set(nodes.flatMap(node => node.dataset.originalUnits.split(' ')))]")
            assert len(anchors) == units
            assert not await page.locator('.verse-translation-label:text-is("English translation unavailable here")').count()
            assert not (await page.evaluate(GEOMETRY, {"wide": wide}))["errors"]
            if screenshot:
                await screenshot_panel(page, originals.first.locator("xpath=../.."),
                                       args.output / f"after-{name}-{chapter.replace('/', '-')}-original.png")
        if name in {"mobile", "mobile-large-text"} and not keyboard_checks:
            raise ValueError(f"{name}: no keyboard-scroll probe was available")
        if args.before and name in {"desktop", "mobile"}:
            for label, (chapter, group) in fixtures.items():
                await open_route(page, args.before, chapter + "/", enlarged)
                for index, unit in enumerate(group["units"][:2]):
                    first = page.locator(f"#{unit}")
                    await first.screenshot(path=args.output / f"before-{name}-{label}-{index + 1}.png")
    finally:
        await context.close()
    return {"profile": name, "checked": summaries, "keyboard_checks": keyboard_checks,
            "unmatched_chapter": unmatched_result}


def check_png_size(screenshot, label):
    # A known Chromium native-zoom capture problem returns an entirely blank
    # 720px × 480px PNG. Do not retain it as visual evidence.
    width, height = struct.unpack(">II", screenshot[16:24])
    if width < 100 or height < 50 or len(screenshot) < 5000:
        raise ValueError(f"{label} screenshot did not paint the reader ({width}×{height}, {len(screenshot)} bytes)")


async def native_zoom(playwright, args, fixture, open_route):
    """Test actual desktop Chromium 200%, including engine layout width and DPR."""
    with TemporaryDirectory(prefix="prose-zoom-") as temporary:
        root = Path(temporary)
        extension = root / "extension"
        extension.mkdir()
        (extension / "manifest.json").write_text(
            json.dumps({"manifest_version": 3, "name": "Local reading-layout test", "version": "1.0",
                        "permissions": ["tabs"], "background": {"service_worker": "worker.js"}}),
            encoding="utf-8"
        )
        (extension / "worker.js").write_text(
            "chrome.runtime.onInstalled.addListener(() => {});", encoding="utf-8"
        )
        context = await playwright.chromium.launch_persistent_context(
            root / "profile", channel="chromium", headless=True, no_viewport=True,
            reduced_motion="reduce", locale="en",
            args=["--window-size=1440,960", f"--disable-extensions-except={extension}",
                  f"--load-extension={extension}"],
        )
        try:
            service = context.service_workers[0] if context.service_workers else await context.wait_for_event(
                "serviceworker", timeout=8_000)
            page = context.pages[0]
            chapter, group = fixture
            await open_route(page, args.after, chapter + "/", False)
            before = await page.evaluate("({width:innerWidth,dpr:devicePixelRatio})")
            factor = await service.evaluate("""async target => {
                const tab = (await chrome.tabs.query({})).find(tab => tab.url === target);
                if (!tab) throw new Error('Cannot locate the reader tab');
                await chrome.tabs.setZoom(tab.id, 2);
                return await chrome.tabs.getZoom(tab.id);
            }""", page.url)
            await page.wait_for_function(
                "(before) => innerWidth < before.width * .6 && devicePixelRatio >= before.dpr * 1.95",
                arg=before, timeout=8_000,
            )
            result = await page.evaluate(GEOMETRY, {"wide": False})
            if result["errors"] or factor != 2:
                raise ValueError(f"Actual browser zoom failed: {result}, factor {factor}")
            card = await exact_card(page, group)
            # At native browser zoom CDP's PNG rasterizer instead uses the
            # pre-zoom device origin. Set a viewport-sized clip for the now
            # centered card and verify that the screenshot has painted content.
            location = await card.evaluate("""node => {
                node.scrollIntoView({block: 'center', inline: 'nearest'});
                const rect = node.getBoundingClientRect();
                return {top: rect.top, bottom: rect.bottom, innerHeight, scroll: scrollY};
            }""")
            await page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
            if not location["bottom"] > 0 or not location["top"] < location["innerHeight"]:
                raise ValueError(f"Zoomed card is outside the viewport: {location}")
            output = args.output / "after-native-200-percent.png"
            capture = None
            for image in (lambda: card.screenshot(timeout=5_000),
                          lambda: page.screenshot(timeout=5_000)):
                try:
                    screenshot = await image()
                    check_png_size(screenshot, "native screen")
                    output.write_bytes(screenshot)
                    capture = output.name
                    break
                except (BrowserError, ValueError):
                    continue
            return {"factor": factor, "chapter": chapter, "before": before,
                    "after": await page.evaluate("({width:innerWidth,dpr:devicePixelRatio})"),
                    "geometry": result, "screen_position": location, "screenshot": capture}
        finally:
            await context.close()


async def main_async(args):
    sys.path.insert(0, str(args.build_root))
    from verify_verse_layout import LINE_AUDIT, open_route

    fixtures, unmatched = fixture_groups(json.loads(args.audit.read_text())["chapters"])
    args.output.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            results = [await check_profile(browser, profile, name, args, fixtures, unmatched,
                                           open_route, LINE_AUDIT)
                       for name, profile in PROFILES.items()]
        finally:
            await browser.close()
        zoom = await native_zoom(playwright, args, fixtures["partial-range"], open_route)
    summary = {"profiles": results, "native_browser_zoom": zoom,
               "source_link_examples": {name: [chapter, group["href"], group["refs"]]
                                        for name, (chapter, group) in fixtures.items()}}
    (args.output / "report.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--after", required=True)
    parser.add_argument("--before")
    parser.add_argument("--audit", type=Path, default=Path("dist/prose-links-audit.json"))
    parser.add_argument("--build-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("verse-translation-shots"))
    args = parser.parse_args()
    args.after = urljoin(args.after.rstrip("/") + "/", ".")
    if args.before:
        args.before = urljoin(args.before.rstrip("/") + "/", ".")
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
