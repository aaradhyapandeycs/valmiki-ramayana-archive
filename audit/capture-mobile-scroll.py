"""Capture both ends of a scrolled verse on the published reader."""
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    directory = Path("audit/verse-screenshots")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
        page.goto("https://aaradhyapandeycs.github.io/valmiki-ramayana-archive/baala/1/#verse-5")
        page.evaluate("""async () => {
            await document.fonts.load('16px "Noto Serif Devanagari"', 'राम');
            await document.fonts.load('16px "Noto Serif"', 'Rāma');
            await document.fonts.ready;
        }""")
        verse = page.locator("#verse-5")
        scroll = verse.locator(".verse-scroll")
        assert scroll.evaluate("el => el.scrollWidth > el.clientWidth && el.tabIndex === 0")
        assert verse.locator('[lang="sa-Latn"] .verse-line').count() == 2
        verse.screenshot(path=directory / "mobile-verse-5-scroll-start.png")
        scroll.focus()
        page.keyboard.press("ArrowRight")
        page.wait_for_function("document.activeElement.scrollLeft > 0")
        scroll.evaluate("el => { el.scrollLeft = el.scrollWidth; }")
        assert scroll.evaluate("el => el.scrollLeft + el.clientWidth >= el.scrollWidth - 1")
        final_row = verse.locator('[lang="sa-Latn"] .verse-line').last
        assert final_row.inner_text().rstrip().endswith("|| 1-1-5")
        verse.screenshot(path=directory / "mobile-verse-5-scroll-end.png")
        browser.close()


if __name__ == "__main__":
    main()
