#!/usr/bin/env python3
"""Build a rights-conscious static index of the source edition.

Source titles are transcribed from the six kanda indexes in chapters.json.
Text is deliberately linked at the source until permission and exact bytes
can be verified. No verses are generated or inferred.
"""
import html
import json
import os
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "dist"
BASE = os.environ.get("BASE_PATH", "/valmiki-ramayana-archive/").rstrip("/") + "/"
HOST = "https://valmikiramayan.net"
NAMES = {
    "baala": "Bāla", "ayodhya": "Ayodhyā", "aranya": "Araṇya",
    "kish": "Kiṣkindhā", "sundara": "Sundara", "yuddha": "Yuddha",
}
CHAPTERS = json.loads((ROOT / "chapters.json").read_text())


def esc(s):
    return html.escape(str(s), quote=True)


def page(title, body, depth=0):
    home = "../" * depth + "index.html"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#09203F"><title>{esc(title)} · Vālmīki Rāmāyaṇa</title>
<link rel="stylesheet" href="{'../' * depth}style.css"></head>
<body><a class="skip" href="#main">Skip to content</a><header class="site-head">
<a class="brand" href="{home}">Vālmīki Rāmāyaṇa</a>
<p class="tagline">A searchable directory of the six kāṇḍas</p>
<nav aria-label="Main navigation">
<a href="{home}">Chapters</a><a href="{home}#sources">Sources &amp; rights</a>
<a href="{home.replace('index.html', 'manifest.json')}">URL manifest</a></nav></header>
<main id="main" class="wrap">{body}</main><footer class="wrap">
<p>Chapter titles and order: <a href="{HOST}/">Valmiki Ramayana</a>.
Translation credits: Desiraju Hanumanta Rao (Bāla, Araṇya, Kiṣkindhā);
K. M. K. Murthy (Ayodhyā, Sundara, Yuddha), as credited on the source homepage.
The source introduction also credits Durga Naaga Devi and Vaasudeva Kishore for Sundara contributions.</p>
<p>The original edition hosts the verses, translation, and commentary.</p>
</footer></body></html>"""


def write(path, contents):
    dest = OUT / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(contents, encoding="utf-8")


def chapter_url(book, row):
    n = row["n"]
    return f"{HOST}/{book['slug']}/sarga{n}/{book['frameprefix']}_{n}_frame.htm"


def main():
    OUT.mkdir(exist_ok=True)
    manifest = []
    cards = []
    search = []
    for book_number, book in enumerate(CHAPTERS, 1):
        slug, rows = book["slug"], book["rows"]
        assert [x["n"] for x in rows] == list(range(1, len(rows) + 1))
        name = NAMES[slug]
        index_src = f"{HOST}/{slug}/" + ({"baala":"baala", "ayodhya":"ayodhya", "aranya":"aranya", "kish":"kishkindha", "sundara":"sundara", "yuddha":"yuddha"}[slug]) + "_contents.htm"
        manifest.append({"source_url": index_src, "new_url": f"{BASE}index.html#{slug}",
                         "status": "index_transcribed", "note": f"{len(rows)} chapter entries"})
        for row in rows:
            n = row["n"]
            new = f"{BASE}{slug}/{n}/"
            source = chapter_url(book, row)
            manifest.append({"source_url": source, "new_url": new,
                             "status": "source_link_only_unverified",
                             "note": "Frame URL pattern sampled at first/last chapters; individual response and rights not verified"})
            search.append({"book": name, "number": n, "book_number": book_number, "title": row["title"], "url": new})
            before = f'<a href="../{n-1}/">← Previous</a>' if n > 1 else ""
            after = f'<a href="../{n+1}/">Next →</a>' if n < len(rows) else ""
            body = f"""<p class="eyebrow">{esc(name)} Kāṇḍa · Sarga {n} of {len(rows)}</p>
<h1>{esc(row['title'])}</h1>
<p class="source-note">The source chapter is available through its original frame page.
Open the source edition for Sanskrit, transliteration, English translation, and commentary.</p>
<p><a class="button" href="{esc(source)}" rel="external">Read the original chapter ↗</a></p>
<nav class="chapter-nav" aria-label="Chapter sequence">{before}
<a href="../">All {esc(name)} chapters</a>{after}</nav>"""
            write(f"{slug}/{n}/index.html", page(f"{name} {n}: {row['title']}", body, 2))
        items = "".join(
            f'<li><a href="{slug}/{x["n"]}/"><span class="num">{x["n"]:03}</span><span>{esc(x["title"])}</span></a></li>'
            for x in rows
        )
        book_items = "".join(
            f'<li><a href="{x["n"]}/"><span class="num">{x["n"]:03}</span><span>{esc(x["title"])}</span></a></li>'
            for x in rows
        )
        write(f"{slug}/index.html", page(
            f"{name} Kāṇḍa",
            f'<section class="book"><div class="book-heading"><div><h1>{name} Kāṇḍa</h1></div>'
            f'<span>{len(rows)} sargas</span></div><ol class="chapters">{book_items}</ol></section>',
            1,
        ))
        cards.append(f'<section class="book" id="{slug}"><div class="book-heading"><div><p class="eyebrow">Book {len(cards)+1}</p>'
                     f'<h2><a href="{slug}/">{name} Kāṇḍa</a></h2></div><span>{len(rows)} sargas</span></div>'
                     f'<ol class="chapters">{items}</ol></section>')

    extras = [
        (f"{HOST}/", "index.html", "source_link_only", "Original landing page"),
        (f"{HOST}/utf8/ramayana.shtml", "index.html#sources", "source_link_only", "UTF-8 introduction"),
        (f"{HOST}/utf8/vr_intro_ayyangar.pdf", "index.html#sources", "external_download", "C. R. Srinivasa Ayyangar introduction PDF"),
        (f"{HOST}/ValmikiRamayanFNL.pdf", "index.html#sources", "external_download", "Additional linked PDF; rights unverified"),
        (f"{HOST}/sans2003.zip", "index.html#sources", "external_download", "Source font archive; binary not retrieved or redistributed"),
        (f"{HOST}/utf8/baala/baala_contents.htm", "index.html#baala", "index_variant", "UTF-8 chapter index"),
        (f"{HOST}/utf8/baala/sarga1/balaitrans1.htm", "baala/1/", "text_variant_link_only", "ITRANS and English"),
        (f"{HOST}/utf8/baala/sarga1/balaroman1.htm", "baala/1/", "text_variant_link_only", "Romanized Sanskrit"),
        (f"{HOST}/utf8/baala/sarga1/balasans1.htm.old", "baala/1/", "text_variant_link_only", "Legacy Devanagari"),
        (f"{HOST}/utf8/baala/sarga4/bala_4_prose.htm", "baala/4/", "prose_link_only", "Prose variant"),
        (f"{HOST}/utf8/baala/sarga4/balasans4.htm", "baala/4/", "text_variant_link_only", "Devanagari variant"),
    ]
    for src, target, status, note in extras:
        manifest.append({"source_url": src, "new_url": BASE + target, "status": status, "note": note})
    for slug, full in [("ayodhya", "ayodhya"), ("aranya", "aranya"),
                       ("kish", "kishkindha"), ("sundara", "sundara"), ("yuddha", "yuddha")]:
        manifest.append({"source_url": f"https://www.valmikiramayan.net/utf8/{full}_kanda_contents.html",
                         "new_url": f"{BASE}index.html#{slug}", "status": "source_404",
                         "note": "Linked from UTF-8 introduction; web retrieval returned 404"})
    manifest.sort(key=lambda x: x["source_url"])
    assert len({x["source_url"] for x in manifest}) == len(manifest)
    write("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    write("search.json", json.dumps(search, ensure_ascii=False, separators=(",", ":")))
    sources = f"""<section class="sources" id="sources"><h2>Sources &amp; rights</h2>
<p>Chapter headings and sequence were transcribed from the six kāṇḍa indexes of
<a href="{HOST}/">Valmiki Ramayana</a>. The source describes its six-book presentation
and verse numbering in its <a href="{HOST}/utf8/ramayana.shtml">introduction</a>.
The Sanskrit epic is ancient; the particular translation, commentary, editorial layout,
fonts, and downloads have no verified reuse grant for this project. Follow the original links for those materials.</p>
<p><a href="{HOST}/utf8/vr_intro_ayyangar.pdf">Ayyangar introduction (PDF) ↗</a> ·
<a href="{HOST}/ValmikiRamayanFNL.pdf">Additional source PDF ↗</a> ·
<a href="{HOST}/sans2003.zip">Source font archive ↗</a> ·
<a href="manifest.json">Source URL manifest</a></p>
<p>Source availability can change. A source link may fail or redirect; the manifest records
which individual responses have yet to be verified.</p></section>"""
    body = f"""<section class="hero"><p class="eyebrow">An independent reading directory</p>
<h1>Explore the Rāmāyaṇa, chapter by chapter.</h1>
<p>All 534 sargas in the six-book index, in source order. Search chapter headings, then follow
the source edition for exact verses, translation, and commentary.</p>
<label class="search-label" for="search">Search chapter headings or sarga number</label>
<input id="search" type="search" placeholder="Try Hanuma, forest, or 2-119" autocomplete="off">
<p id="search-count" aria-live="polite"></p></section>
<nav class="book-links" aria-label="Kāṇḍas">{"".join(f'<a href="#{x["slug"]}">{NAMES[x["slug"]]} <small>{len(x["rows"])}</small></a>' for x in CHAPTERS)}</nav>
<div id="results" hidden></div><div id="books">{"".join(cards)}</div>{sources}
<script src="app.js" defer></script>"""
    write("index.html", page("Chapter directory", body))
    write(".nojekyll", "")
    write("404.html", page("Page not found", '<h1>Page not found</h1><p><a href="index.html">Return to the chapter directory</a>.</p>'))
    write("style.css", (ROOT / "style.css").read_text())
    write("app.js", (ROOT / "app.js").read_text().replace("__BASE__", BASE))
    print(f"Built {len(search)} chapter pages and {len(manifest)} source mappings in {OUT}")


if __name__ == "__main__":
    main()
