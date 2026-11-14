#!/usr/bin/env python3
"""Build a rights-conscious static index of the source edition.

The original chapter indexes and the reviewed IAST display remain separate.
Sanskrit snapshots retain their source witness. Modern translations and
commentary are linked to the original pages.
"""
import hashlib
import html
import json
import os
from pathlib import Path

from chapter_iast import display_chapters, load_title_review, title_aliases
from dutt_reader import render_dutt, reviewed_passages
from critical_reader import inline_groups, read_critical, render_critical
from prose_links import REF, TRANSLATORS, local_units, original_passages, prepare_links
from sanskrit_paratext import load_paratext, render_paratext
from reader import (chapter_sources, load_catalog, load_reviewed_iast, load_sanskrit, render_coverage,
                    render_sanskrit, source_guide, supplemental_files)

ROOT = Path(__file__).parent
OUT = ROOT / "dist"
BASE = os.environ.get("BASE_PATH", "/valmiki-ramayana-archive/").rstrip("/") + "/"
HOST = "https://valmikiramayan.net"
DUTT = ROOT / "dutt-corpus"
CRITICAL = ROOT / "data" / "critical-site"
NAMES = {
    "baala": "Bāla", "ayodhya": "Ayodhyā", "aranya": "Araṇya",
    "kish": "Kiṣkindhā", "sundara": "Sundara", "yuddha": "Yuddha",
}
SOURCE_CHAPTERS = json.loads((ROOT / "chapters.json").read_text(encoding="utf-8"))


def esc(s):
    return html.escape(str(s), quote=True)


def page(title, body, depth=0, *, rooted=False):
    prefix = BASE if rooted else "../" * depth
    home = prefix + "index.html"
    english = (f'<a href="{prefix}english/">Dutt’s English by section</a>'
               if DUTT.is_dir() else "")
    critical = (f'<a href="{prefix}critical/">Critical Edition English</a>'
                if (CRITICAL / "manifest-all.json").is_file() else "")
    historical_credit = "<p>Historical English translation by Manmatha Nath Dutt.</p>" if english or critical else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#09203F">
<meta name="description" content="{esc(title)} · Vālmīki Rāmāyaṇa reader"><title>{esc(title)} · Vālmīki Rāmāyaṇa</title>
<link rel="stylesheet" href="{prefix}style.css"></head>
<body><a class="skip" href="#main">Skip to content</a><header class="site-head">
<a class="brand" href="{home}">Vālmīki Rāmāyaṇa</a>
<p class="tagline">Sanskrit and English reading editions</p>
<nav aria-label="Main navigation">
<a href="{home}">Chapters</a><a href="{home.replace('index.html', 'sources/')}">Source files</a>
<a href="{home.replace('index.html', 'manifest.json')}">URL manifest</a>{english}{critical}</nav></header>
<main id="main" class="wrap" tabindex="-1">{body}</main><footer class="wrap">
<p>The six-book Sanskrit archive follows <a href="{HOST}/">Valmikiramayan.net</a>.
The source credits Desiraju Hanumanta Rao (Bāla, Araṇya, Kiṣkindhā) and
K. M. K. Murthy (Ayodhyā, Sundara, Yuddha) for its modern English translation.
Its introduction also credits Durga Naaga Devi and Vaasudeva Kishore for Sundara contributions.</p>
{historical_credit}
</footer></body></html>"""


def write(path, contents):
    dest = OUT / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(contents, encoding="utf-8")


def main():
    OUT.mkdir(exist_ok=True)
    chapters = display_chapters(SOURCE_CHAPTERS)
    title_review = load_title_review()
    glossary = title_review["glossary"]
    corrections = title_review.get("editorial_heading_corrections", {})
    if corrections:
        write("heading-provenance.json", json.dumps(corrections, ensure_ascii=False, indent=2) + "\n")
    sanskrit = load_sanskrit(SOURCE_CHAPTERS)
    reviewed_iast = load_reviewed_iast(sanskrit)
    paratext = load_paratext(sanskrit)
    prose = load_catalog("prose-links.json", None)
    prose_report = {}
    critical_manifest, critical_books = read_critical(CRITICAL)
    crosswalk = load_catalog("critical-site/archive-links.json", None)
    reviewed = reviewed_passages(DUTT, load_catalog("dutt-reviewed-passages.json", {})) if sanskrit else {}
    original = load_catalog("original-english.json", {}) if sanskrit else {}
    critical_rows = {row["id"]: row for chapters in critical_books.values()
                     for rows in chapters.values() for row in rows}
    shown_english = {}
    english_coverage = {}
    expected_chapters = {f"{slug}/{n}" for slug, n in sanskrit}
    if prose and (prose["schema_version"] != 1 or set(prose["chapters"]) != expected_chapters):
        raise ValueError("English source reference snapshot does not cover the same chapters")
    layout = load_catalog("verse-layout.json", None)
    if layout:
        snapshot = load_catalog("sanskrit/summary.json", None)
        if not snapshot or layout["snapshot_commit"] != snapshot["commit"]:
            raise ValueError("Verse layout is based on a different Sanskrit capture")
        write("verse-layout-audit.json", json.dumps({
            "source_break_chapters": len(layout["chapters"]),
            "unresolved_chapters": layout["unresolved"],
        }, ensure_ascii=False, indent=2) + "\n")
    snapshot = ROOT / "data" / "sanskrit" / "summary.json"
    if snapshot.is_file():
        write("sanskrit-coverage.json", snapshot.read_text(encoding="utf-8"))
    frames = load_catalog("frames.json", None)["books"]
    variants = load_catalog("variants.json", {"chapters": {}})
    ancillary = load_catalog("ancillary.json", {"groups": []})
    introduction = ROOT / "data" / "ayyangar" / "vr_intro_ayyangar.pdf"
    if introduction.is_file():
        provenance_path = introduction.with_suffix(".json")
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        scan = introduction.read_bytes()
        if hashlib.sha256(scan).hexdigest() != provenance["sha256"] or provenance["pages"] != 142:
            raise ValueError("Ayyangar scan does not match its provenance")
        write("resources/vr_intro_ayyangar.json", provenance_path.read_text(encoding="utf-8"))
        (OUT / "resources" / introduction.name).write_bytes(scan)
        ancillary["groups"][0]["entries"].insert(0, {
            "url": "../resources/vr_intro_ayyangar.pdf",
            "label": "Read Ayyangar’s 1910 introduction (PDF)",
            "status": "Preserved facsimile · 142 pages",
            "local": True,
        })
    audit_summary = ROOT / "audit" / "primary" / "summary.json"
    guide = source_guide(ancillary, variants, audit_summary.is_file())
    if prose:
        guide += ('<section class="sources"><h2>English translation reference audit</h2>'
                  '<p><a href="../prose-links-audit.json">Verified source links and verse groups</a> · '
                  '<a href="../english-coverage.json">Inline English coverage and unresolved units</a>.</p></section>')
    write("sources/index.html", page("Source files and editions", guide, 1))
    manifest = []
    cards = []
    search = []
    for book_number, book in enumerate(chapters, 1):
        slug, rows = book["slug"], book["rows"]
        assert [x["n"] for x in rows] == list(range(1, len(rows) + 1))
        name = NAMES[slug]
        for source in frames[slug]["indexes"].values():
            manifest.append({"source_url": source, "new_url": f"{BASE}{slug}/",
                             "status": "index_transcribed", "note": f"{len(rows)} chapter entries"})
        for row in rows:
            n = row["n"]
            new = f"{BASE}{slug}/{n}/"
            links = frames[slug]["chapters"][str(n)]
            source = links["original"]
            pane_links = variants["chapters"].get(f"{slug}/{n}", [])
            observed = {entry["url"]: entry["status"] for entry in pane_links}
            for entry in links.values():
                manifest.append({"source_url": entry, "new_url": new,
                                 "status": observed.get(entry, "toc_link"),
                                 "note": "Recorded from the chapter table of contents"})
            for pane in pane_links:
                if pane["url"] not in links.values():
                    manifest.append({"source_url": pane["url"], "new_url": new,
                                     "status": pane["status"], "note": pane["label"]})
            search.append({"book": name, "number": n, "book_number": book_number, "title": row["title"], "aliases": title_aliases(row["title"], glossary), "url": new})
            before = f'<a href="../{n-1}/">← Previous</a>' if n > 1 else ""
            after = f'<a href="../{n+1}/">Next →</a>' if n < len(rows) else ""
            additions = paratext.get((slug, n), {})
            record = sanskrit.get((slug, n))
            chapter_layout = layout["chapters"].get(f"{slug}/{n}", {}) if layout else {}
            if chapter_layout:
                expected_supplements = {
                    str(item["source_paragraph"])
                    for items in additions.values() for item in items
                }
                if (record is None or chapter_layout["source_sha256"] != record["source_sha256"]
                        or set(chapter_layout["verses"]) != {str(verse["number"]) for verse in record["verses"]}
                        or set(chapter_layout["supplements"]) != expected_supplements
                        or ("colophon" in chapter_layout) != bool(record.get("colophon"))):
                    raise ValueError(f"Verse layout differs from the Sanskrit witness for {slug}/{n}")
            groups, translation_note, witnesses = [], "", []
            key = f"{slug}/{n}"
            if record:
                witnesses = local_units(record, additions)
            if prose and record:
                evidence = prose["chapters"][key]
                groups, issues = prepare_links(record, additions, evidence)
                covered = {anchor for group in groups for anchor in group["units"]}
                units = [anchor for anchor, *_ in witnesses]
                unmatched = [anchor for anchor in units if anchor not in covered]
                prose_report[key] = {
                    "source_url": evidence["source_url"],
                    "status": evidence["status"],
                    "candidate_paragraphs": evidence.get("candidate_paragraphs", 0),
                    "mapped_groups": groups,
                    "unmatched_units": unmatched,
                    "issues": dict(issues),
                    "source_reference_issues": evidence.get("issues", []),
                }
                credit = esc(TRANSLATORS[book_number])
                status = (" Verse-level links appear where the source reference could be verified."
                          if unmatched else "")
                if not groups:
                    status = " Verse-level references could not be verified for this chapter."
                translation_note = (
                    f'<p class="source-note">Modern English at the source by {credit}.{status} '
                    f'<a href="{esc(evidence["source_url"])}" rel="external">Read the chapter’s English at the source ↗</a>.</p>'
                )
            matched_english = inline_groups(crosswalk, key, record, additions, critical_rows) if crosswalk and record else []
            restored_english = reviewed.pop(key, [])
            if crosswalk:
                replacements = {tuple(group["replaces_critical_refs"]): group["units"]
                                for group in restored_english if "replaces_critical_refs" in group}
                for group in matched_english:
                    refs = tuple(group["refs"])
                    if refs in replacements and replacements.pop(refs) != group["units"]:
                        raise ValueError(f"Dutt correction targets a different group at {key}")
                if replacements:
                    raise ValueError(f"Dutt correction targets an unknown matching group at {key}")
                for group in restored_english:
                    if any(critical_rows[ref]["alignment"]["type"] != "split" for ref in group.get("excluded_split_refs", ())):
                        raise ValueError(f"Reviewed Dutt passage refers to a non-split record at {key}")
                replaced = {tuple(group["replaces_critical_refs"]) for group in restored_english if "replaces_critical_refs" in group}
                matched_english = [group for group in matched_english if tuple(group["refs"]) not in replaced]
            if matched_english:
                shown_english[key] = [{name: value for name, value in passage.items() if name != "row"}
                                      for passage in matched_english]
            drafts = original.pop(key, [])
            additional_english = []
            gaps = []
            if record:
                by_anchor = {anchor: (position, numbers, digest)
                             for position, (anchor, numbers, _, digest) in enumerate(witnesses)}
                inline = {anchor for group in matched_english for anchor in group["units"]}
                for group in restored_english:
                    locators = [REF.fullmatch(ref) for ref in group["refs"]]
                    if not all(locators) or not all(tuple(map(int, ref.groups()[:2])) == (book_number, n)
                                                    for ref in locators):
                        raise ValueError(f"Reviewed Dutt references disagree with {key}")
                    targets = [by_anchor[anchor] for anchor in group["units"]]
                    positions = [position for position, _, _ in targets]
                    if (not targets or positions != list(range(positions[0], positions[-1] + 1))
                            or group["unit_sha256"] != [digest for _, _, digest in targets]
                            or {int(ref[3]) for ref in locators} != {number for _, ns, _ in targets for number in ns}
                            or inline.intersection(group["units"])):
                        raise ValueError(f"Reviewed Dutt mapping overlaps or disagrees with Sanskrit at {key}")
                    inline.update(group["units"])
                additional_english, original_units = original_passages(record, witnesses, drafts, inline)
                urls_by_anchor = {}
                for group in groups:
                    for anchor in group["units"]:
                        urls_by_anchor.setdefault(anchor, []).append(group["href"])
                unresolved = []
                for anchor, numbers, _, _ in witnesses:
                    if anchor not in inline and anchor not in original_units:
                        urls = list(dict.fromkeys(urls_by_anchor.get(anchor, ())))
                        unresolved.append({"anchor": anchor, "printed_verse_numbers": sorted(numbers),
                                           "source_urls": urls or [record["source_url"]],
                                           "status": "source_link_only" if urls else "verse_match_unverified"})
                        if not urls:
                            gaps.append({"units": [anchor], "chapter_href": record["source_url"]})
                english_coverage[key] = {
                    "reading_units": len(witnesses),
                    "crosswalk_dutt_passages": len(matched_english),
                    "reviewed_dutt_passages": [
                        {field: group[field] for field in ("translator", "href", "refs", "units", "section", "english_span")}
                        for group in restored_english
                    ],
                    "inline_dutt_reading_units": len(inline),
                    "original_english_reading_units": len(original_units),
                    "original_english_passages": [{key: group[key] for key in ("refs", "units", "href")}
                                                 for group in additional_english],
                    "unresolved": unresolved,
                }
            elif restored_english or drafts:
                raise ValueError(f"English passage has no Sanskrit witness at {key}")
            offsets = chapter_layout.get("supplements")
            passage = render_sanskrit(record, layout=chapter_layout,
                                      groups=groups + matched_english + restored_english + additional_english + gaps,
                                      translation_note=translation_note,
                                      reviewed_iast=reviewed_iast.get((book_number, n)),
                                      before=render_paratext(additions.get("before"), offsets),
                                      after=render_paratext(additions.get("after"), offsets))
            correction = corrections.get(slug, {}).get(str(n))
            heading_note = ""
            if correction:
                refs = " · ".join(
                    f'<a href="{esc(url)}">Source {i} ↗</a>'
                    for i, url in enumerate(correction["sources"], 1)
                )
                heading_note = (f'<details class="chapter-sources"><summary>Editorial heading</summary>'
                                f'<p>Original index heading: {esc(correction["source_index_heading"])}</p>'
                                f'<p>{esc(correction["reason"])} {refs}</p></details>')
            source_materials = "word meanings and commentary" if translation_note else "its English translation, word meanings, and commentary"
            body = f"""<p class="eyebrow">{esc(name)} Kāṇḍa · Sarga {n} of {len(rows)}</p>
<h1>{esc(row['title'])}</h1>
{heading_note}
<p class="source-note">Open the source edition for {source_materials}.</p>
<p><a class="button" href="{esc(source)}" rel="external">Read the original chapter ↗</a></p>
{chapter_sources(slug, n, source, frames, pane_links)}
{passage}
<script src="../../verse-scroll.js" defer></script>
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

    if reviewed or original:
        raise ValueError(f"English data refer to unknown archive chapters: {sorted(reviewed.keys() | original.keys())}")
    if english_coverage:
        write("english-coverage.json", json.dumps({
            "scope": "Six-book Sanskrit archive. A reading unit can contain multiple or partial verses.",
            "fallback_text": "Independently translated and reviewed Sanskrit passages appear where recorded. The modern source translation is linked.",
            "chapters": english_coverage,
        }, ensure_ascii=False, separators=(",", ":")) + "\n")

    if prose:
        write("prose-links-audit.json", json.dumps({
            "method": prose["method"],
            "source_coverage": prose["coverage"],
            "chapters": prose_report,
        }, ensure_ascii=False, separators=(",", ":")) + "\n")

    mapped = {entry["source_url"]: entry for entry in manifest}
    if len(mapped) != len(manifest):
        raise ValueError("A source URL maps to more than one entry")
    original_pdf = f"{HOST}/vr_intro_ayyangar.pdf"
    for group in ancillary["groups"]:
        for entry in group["entries"]:
            src = entry["url"]
            if entry.get("local") or src in mapped:
                continue
            hosted = src == original_pdf and introduction.is_file()
            mapped[src] = {"source_url": src,
                           "new_url": (f"{BASE}resources/{introduction.name}" if hosted
                                       else f"{BASE}sources/"),
                           "status": "hosted_facsimile" if hosted else entry["status"],
                           "note": entry["label"]}
    extra_rows = variants.get("other_source_files", []) + [
        entry for key in variants.get("auxiliary_chapters", []) for entry in variants["chapters"][key]
    ]
    if audit_summary.is_file():
        for entry in extra_rows:
            mapped.setdefault(entry["url"], {
                "source_url": entry["url"], "new_url": f"{BASE}sources/files/",
                "status": entry["status"], "note": entry["label"],
            })
    manifest = list(mapped.values())
    if "coverage" in variants:
        write("source-variants.json", json.dumps(variants, ensure_ascii=False, separators=(",", ":")))
    if audit_summary.is_file():
        write("source-audit.json", audit_summary.read_text(encoding="utf-8"))
        write("sources/files/index.html", page("Additional source files", supplemental_files(ancillary, variants), 2))
    manifest.sort(key=lambda x: x["source_url"])
    assert len({x["source_url"] for x in manifest}) == len(manifest)
    write("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    write("search.json", json.dumps(search, ensure_ascii=False, separators=(",", ":")))
    heading_audit = ' · <a href="heading-provenance.json">Editorial heading sources</a>' if corrections else ""
    text_audit = '<a href="https://github.com/aaradhyapandeycs/valmiki-ramayana-archive/blob/main/TEXTUAL_EXCEPTIONS.md">Textual exceptions</a>'
    sources = f"""<section class="sources" id="sources"><h2>Sources &amp; rights</h2>
<p>Chapter headings use reviewed IAST. They follow the six kāṇḍa indexes of
<a href="{HOST}/">Vālmīki Rāmāyaṇa</a>. The source describes its six-book presentation
and verse numbering in its <a href="{HOST}/utf8/ramayana.shtml">introduction</a>.
The Sanskrit epic is ancient; the particular translation, commentary, editorial layout,
fonts, and downloads have no verified reuse grant for this project. Follow the original links for those materials.</p>
<p><a href="sources/">Source editions and files</a> · <a href="manifest.json">Source URL manifest</a> · <a href="iast-audit.json">IAST audit</a> · <a href="source-manifest.json">Source coverage manifest</a>{heading_audit} · {text_audit}</p>
<p>Source availability can change. A source link may fail or redirect; the manifest records
where each URL was found and which responses were observed.</p></section>"""
    critical_intro = (
        '<p><a href="critical/">Read M. N. Dutt’s English by Critical Edition verse</a>. '
        'The seven-book Critical Edition uses its own numbering.</p>' if critical_manifest else ""
    )
    body = f"""<section class="hero"><p class="eyebrow">An independent reading directory</p>
<h1>Explore the Rāmāyaṇa, chapter by chapter.</h1>
<p>Search all 534 sargas in the six-book Sanskrit archive. The source links include
the modern English translation and commentary.</p>{critical_intro}
<p class="coverage">{render_coverage(sanskrit)}{' · <a href="sanskrit-coverage.json">Capture record</a>' if snapshot.is_file() else ""}</p>
<label class="search-label" for="search">Search chapter headings or sarga number</label>
<input id="search" type="search" placeholder="Try Rāma, forest, or 2-119" autocomplete="off">
<p id="search-count" aria-live="polite"></p></section>
<nav class="book-links" aria-label="Kāṇḍas">{"".join(f'<a href="#{x["slug"]}">{NAMES[x["slug"]]} <small>{len(x["rows"])}</small></a>' for x in chapters)}</nav>
<div id="results" hidden></div><div id="books">{"".join(cards)}</div>{sources}
<script src="app.js" defer></script>"""
    write("index.html", page("Chapter directory", body))
    if DUTT.is_dir():
        render_dutt(page, write, DUTT)
    render_critical(page, write, CRITICAL, critical_manifest, critical_books, has_crosswalk=bool(crosswalk))
    if crosswalk:
        write("critical/archive-matching-audit.json", json.dumps({
            "source_match_report": crosswalk,
            "displayed_inline": shown_english,
        }, ensure_ascii=False, separators=(",", ":")) + "\n")
    write(".nojekyll", "")
    write("404.html", page("Page not found",
                           f'<h1>Page not found</h1><p><a href="{BASE}">Return to the chapter directory</a>.</p>',
                           rooted=True))
    write("style.css", (ROOT / "style.css").read_text())
    write("verse-scroll.js", (ROOT / "verse-scroll.js").read_text(encoding="utf-8"))
    write("app.js", (ROOT / "app.js").read_text().replace("__BASE__", BASE))
    print(f"Built {len(search)} chapter pages and {len(manifest)} source mappings in {OUT}")


if __name__ == "__main__":
    main()
