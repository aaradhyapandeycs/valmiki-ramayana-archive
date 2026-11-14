"""Representative WebKit and Firefox audit of the deployed reader."""
import json
import os
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

BASE = 'https://aaradhyapandeycs.github.io/valmiki-ramayana-archive/'
ROUTES = ('baala/1/', 'kish/29/')
PROFILES = ((1440, 900, False), (768, 1024, False), (390, 844, False), (390, 844, True))
GEOMETRY = r'''() => {
    const errors = [];
    const report = {explicit_rows: 0, overflow_groups: 0, errors};
    const layouts = [...document.querySelectorAll('.verse-scroll')];
    const lineElements = [...document.querySelectorAll('#sanskrit .verse-line')];
    if (!layouts.length || !lineElements.length) errors.push('Missing verse layout elements');
    if (document.documentElement.scrollWidth > innerWidth + 1) errors.push('Page-wide overflow');
    report.width = innerWidth;
    report.scrollWidth = document.documentElement.scrollWidth;
    for (const group of layouts) {
        const blocks = [...group.querySelectorAll('[lang]')];
        const counts = [];
        for (const block of blocks) {
            const rows = [...block.querySelectorAll('.verse-line')];
            counts.push(rows.length);
            const expected = block.lang === 'sa-Deva' ? 'rgb(32, 54, 74)' : 'rgb(116, 69, 82)';
            if (getComputedStyle(block).color !== expected) errors.push('Script color mismatch');
            let priorBottom = -Infinity;
            for (const row of rows) {
                report.explicit_rows++;
                const bounds = row.getBoundingClientRect();
                const font = getComputedStyle(row);
                if (font.whiteSpace !== 'nowrap' && font.whiteSpace !== 'pre') errors.push('Explicit row may wrap');
                if (bounds.top + 1 < priorBottom) errors.push('Verse rows overlap');
                priorBottom = bounds.bottom;
                if (!row.textContent.trim()) continue;
                if (/^\s*(?:(?:[|।॥]\s*)+(?:[0-9०-९]+(?:\s*[-–]\s*[0-9०-९]+){1,4})?|[0-9०-९]+(?:\s*[-–]\s*[0-9०-९]+){1,4})\s*$/u.test(row.textContent)) {
                    errors.push('A line ending occupies its own row');
                }
                const range = document.createRange();
                range.selectNodeContents(row);
                const rects = [...range.getClientRects()].filter(r => r.width > 0 && r.height > 0);
                if (rects.length && Math.max(...rects.map(r => r.bottom)) - Math.min(...rects.map(r => r.top)) > parseFloat(font.lineHeight) * 1.45) {
                    errors.push('A source row occupies multiple visual lines');
                }
            }
        }
        if (counts.includes(0) || counts.length === 2 && counts[0] !== counts[1]) {
            errors.push('Language rows differ');
        }
        if (group.scrollWidth <= group.clientWidth + 1) continue;
        report.overflow_groups++;
        if (group.tabIndex !== 0 || !(group.getAttribute('aria-label') || group.getAttribute('aria-labelledby'))) {
            errors.push('Scrollable group is unnamed or cannot be focused');
        }
        group.scrollLeft = group.scrollWidth;
        if (group.scrollLeft + group.clientWidth < group.scrollWidth - 3) errors.push('Line end cannot be scrolled into view');
        group.scrollLeft = 0;
    }
    if (location.pathname.endsWith('/baala/1/')) {
        for (const id of ['verse-2', 'verse-5']) {
            for (const lang of ['sa-Deva', 'sa-Latn']) {
                const rows = document.querySelectorAll(`#${id} [lang="${lang}"] .verse-line`);
                if (rows.length !== 2 || !/(?:\|\||॥)\s*[0-9०-९]+(?:[-–][0-9०-९]+){2,4}\s*$/u.test(rows[1]?.textContent)) {
                    errors.push(`${id} ${lang}: expected two rows with the locator on row two`);
                }
            }
        }
    }
    return report;
}'''


def open_page(page, url, large):
    for attempt in range(3):
        try:
            response = page.goto(url, wait_until='domcontentloaded', timeout=20000)
            if not response or response.status != 200:
                raise RuntimeError(f'HTTP {response.status if response else "no response"}')
            if large:
                page.evaluate("document.documentElement.style.fontSize = '200%'")
            page.evaluate('''async () => {
                await document.fonts.ready;
                for (const [font, sample] of [['Noto Serif Devanagari', 'राम'], ['Noto Serif', 'Rāma']]) {
                    const faces = await document.fonts.load('16px "' + font + '"', sample);
                    if (!faces.some(face => face.status === 'loaded')) throw new Error('Font unavailable: ' + font);
                }
                await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
            }''')
            return
        except Exception:
            if attempt == 2:
                raise
            page.wait_for_timeout(600 * (attempt + 1))


def main():
    browser_name = os.environ['BROWSER']
    results = []
    with sync_playwright() as playwright:
        browser = getattr(playwright, browser_name).launch()
        for width, height, large in PROFILES:
            context = browser.new_context(viewport={'width': width, 'height': height}, reduced_motion='reduce')
            page = context.new_page()
            for route in ROUTES:
                row = {'route': route, 'viewport': [width, height], 'root_text_percent': 200 if large else 100}
                try:
                    open_page(page, urljoin(BASE, route), large)
                    row.update(page.evaluate(GEOMETRY))
                    if row['overflow_groups'] > 0:
                        label = page.evaluate('''() => {
                            const span = [...document.querySelectorAll('.verse-scroll')].find(el => el.scrollWidth > el.clientWidth + 1);
                            span.scrollLeft = 0;
                            span.focus();
                            return document.activeElement === span && span.getAttribute('aria-label');
                        }''')
                        page.keyboard.press('ArrowRight')
                        try:
                            page.wait_for_function('document.activeElement.scrollLeft > 0', timeout=1200)
                            row['keyboard_scrolled'] = bool(label)
                        except Exception:
                            row['keyboard_scrolled'] = False
                        if not row['keyboard_scrolled']:
                            row['errors'].append('Focused group did not scroll with ArrowRight')
                except Exception as error:
                    row['errors'] = [str(error)]
                row['error_count'] = len(row['errors'])
                row['errors'] = list(dict.fromkeys(row['errors']))
                results.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
            context.close()
        browser.close()
    Path('cross-browser-results.json').write_text(json.dumps({'engine': browser_name, 'results': results}, indent=2) + '\n')
    if any(row['errors'] for row in results):
        raise SystemExit('Representative cross-browser checks reported failures.')


if __name__ == '__main__':
    main()
