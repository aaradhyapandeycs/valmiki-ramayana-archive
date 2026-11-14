"""Read vetted Sanskrit snapshots and source-link metadata for the static site."""
import html
import json
import re
from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote, urlsplit

from prose_links import pair_units
from transliterate_iast import transliterate
from verse_lines import corresponding_breaks, line_break_offsets, render_lines, reviewed_verse_breaks

ROOT = Path(__file__).parent
DATA = ROOT / "data"
HOSTS = {"valmikiramayan.net", "www.valmikiramayan.net", "sanskritdocuments.org",
         "www.sanskritdocuments.org"}
WITNESSES = {"primary": "Valmikiramayan.net", "mirror": "Sanskrit Documents mirror"}


def escape(value):
    return html.escape(str(value), quote=True)


def source_url(value):
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.netloc not in HOSTS:
        raise ValueError(f"Unexpected source URL {value!r}")
    return escape(value)


def load_sanskrit(books):
    records = {}
    for book_number, book in enumerate(books, 1):
        slug = book["slug"]
        for row in book["rows"]:
            n = row["n"]
            path = DATA / "sanskrit" / slug / f"{n}.json"
            if not path.is_file():
                continue
            record = json.loads(path.read_text(encoding="utf-8"))
            if record["status"] not in {"numbering_verified", "source_blocks_verified"}:
                continue
            if (record["book"], record["sarga"]) != (book_number, n):
                raise ValueError(f"Chapter mismatch in {path}")
            if record["kind"] not in WITNESSES or not re.fullmatch(r"[0-9a-f]{64}", record["source_sha256"]):
                raise ValueError(f"Missing provenance in {path}")
            source_url(record["source_url"])
            verses = record["verses"]
            if not verses:
                raise ValueError(f"Empty verified chapter in {path}")
            expected = 1
            for verse in verses:
                text = verse["sanskrit"]
                if verse["number"] != expected or not re.search(r"[\u0900-\u097f]", text):
                    raise ValueError(f"Invalid Sanskrit sequence in {path}, verse {expected}")
                last = verse.get("last_number", expected)
                if last < expected or last - expected > 20:
                    raise ValueError(f"Invalid verse range in {path}, verse {expected}")
                expected = last + 1
            records[slug, n] = record
    return records


def load_reviewed_iast(records):
    """Derive IAST for damaged verse blocks using exact, witness-checked substitutions."""
    by_reference = {(record["book"], record["sarga"]): record for record in records.values()}
    restorations = {}
    for review in load_catalog("verse-iast-reviewed.json", []):
        reference = review["book"], review["sarga"]
        if reference in restorations:
            raise ValueError(f"Repeated reviewed IAST chapter {reference}")
        chapter = by_reference.get(reference)
        if chapter is not None:
            restorations[reference] = restore_iast(chapter, review)
    return restorations


def restore_iast(chapter, review):
    if any(chapter[key] != review[key] for key in ("source_url", "source_sha256")):
        raise ValueError("The reviewed IAST source witness changed")
    witness = review["roman_witness_url"]
    parsed = urlsplit(witness)
    if parsed.scheme != "https" or parsed.netloc not in HOSTS | {"mail.valmikiramayan.net"}:
        raise ValueError("Unrecognized Roman witness URL")
    entries = {v["ref"]: v for v in review["verses"]}
    if len(entries) != len(review["verses"]):
        raise ValueError("Duplicate IAST restoration reference")
    roman = {}
    for verse in chapter["verses"]:
        number = verse["number"]
        ref = f'{chapter["book"]}-{chapter["sarga"]}-{number}'
        entry = entries.pop(ref, None)
        if entry is None:
            continue
        original = verse["sanskrit"]
        if sha256(original.encode("utf-8")).hexdigest() != entry["unit_sha256"]:
            raise ValueError(f"Unverified witness text at {ref}")
        if transliterate(original) is not None:
            raise ValueError(f"Reviewed restoration overlaps generated IAST at {ref}")
        letters = list(original)
        for edit in entry["substitutions"]:
            offset = edit["offset"]
            if (not 0 <= offset < len(letters) or letters[offset] != edit["from"]
                    or len(edit["to"]) != 1 or edit["from"] == edit["to"]
                    or edit["from"].isspace() or edit["to"].isspace()):
                raise ValueError(f"Invalid reviewed glyph position at {ref}")
            letters[offset] = edit["to"]
        text = transliterate("".join(letters))
        if text is None or not entry["substitutions"]:
            raise ValueError(f"Invalid restored IAST at {ref}")
        roman[number] = text
    if entries:
        raise ValueError(f"Reviewed IAST references missing from witness: {', '.join(entries)}")
    return roman, witness


def render_sanskrit(record, *, before=(), after=(), layout=None, groups=(), translation_note="",
                    reviewed_iast=None):
    if record is None:
        return ""
    layout = layout or {}
    provenance = source_url(record["source_url"])
    witness = WITNESSES[record["kind"]]
    numbered = record["status"] == "numbering_verified"
    note = ("Verse numbering checked against the linked source." if numbered else
            "Passages appear in source order. The numbers mark reading blocks where source verse labels disagree.")
    if record["kind"] == "mirror":
        note += " This witness may differ from the current wording on Valmikiramayan.net."
    if any(verse.get("source_glyph_anomaly") for verse in record["verses"]):
        note += " The original contains a few damaged glyphs. They are preserved as printed."
    anchor = "verse" if numbered else "block"
    restored, roman_witness = reviewed_iast or ({}, "")
    iast_note = "IAST is generated from the displayed Devanagari."
    if restored:
        iast_note += (f' For {len(restored)} verses, damaged glyphs were resolved against the '
                      f'<a href="{escape(roman_witness)}">source’s Roman witness ↗</a>.')
    items = []
    for verse in record["verses"]:
        number = verse["number"]
        last = verse.get("last_number", number)
        aliases = "".join(f'<span id="{anchor}-{n}" class="verse-anchor"></span>'
                          for n in range(number, last))
        label = str(number) if last == number else f"{number}–{last}"
        source = verse["sanskrit"]
        breaks = layout.get("verses", {}).get(str(number))
        if breaks is None:
            breaks = line_break_offsets(source)
        breaks = reviewed_verse_breaks(source, breaks, record["book"], record["sarga"], number)
        restored_text = restored.get(number)
        roman = restored_text or (None if verse.get("source_glyph_anomaly") else transliterate(source))
        restoration = ' data-iast-restored="true"' if restored_text else ""
        alternate = (f'<p lang="sa-Latn" class="iast"{restoration}>{render_lines(roman, corresponding_breaks(source, roman, breaks))}</p>' if roman else
                     '<p class="iast-gap">IAST unavailable for this source block.</p>')
        items.append((f"{anchor}-{last}", aliases + f'<div class="verse" id="{anchor}-{last}">'
                     f'<a href="#{anchor}-{last}" aria-label="Link to {anchor} {label}">{label}</a>'
                     f'<div class="verse-scroll" tabindex="0" role="group" aria-label="{anchor.capitalize()} {label} text">'
                     f'<p lang="sa-Deva">{render_lines(source, breaks)}</p>{alternate}</div></div>'))
    colophon = record.get("colophon")
    ending = ""
    if colophon:
        colophon_iast = transliterate(colophon)
        breaks = layout.get("colophon")
        if breaks is None:
            breaks = line_break_offsets(colophon)
        ending = f'<p class="colophon" lang="sa-Deva">{render_lines(colophon, breaks)}</p>' 
        if colophon_iast:
            ending += f'<p class="colophon iast" lang="sa-Latn">{render_lines(colophon_iast, corresponding_breaks(colophon, colophon_iast, breaks))}</p>'
        else:
            ending += '<p class="iast-gap">IAST unavailable for this source colophon.</p>' 
        ending = (f'<div class="verse-scroll verse-closing" tabindex="0" role="group" aria-label="Chapter colophon">{ending}</div>')
    return (f'<section class="reader" id="sanskrit"><h2>Sanskrit verses</h2>'
            f'<p class="source-note"><a href="{provenance}">{witness} source ↗</a>. {note}</p>'
            f'<p class="iast-note">{iast_note}</p>'
            f'{translation_note}{pair_units([*before, *items, *after], groups)}{ending}</section>')


def render_coverage(records):
    if len(records) == 534 and all(record["kind"] == "primary" for record in records.values()):
        return "Sanskrit from the original site in all 534 indexed chapters"
    return f"Sanskrit available for {len(records)} of 534 indexed chapters"


def load_catalog(name, default):
    path = DATA / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def chapter_sources(slug, number, original, frames, variants):
    frame_links = frames[slug]["chapters"][str(number)]
    entries = [(frame_links[key], label, "") for key, label in [
        ("original", "Original chapter viewer"), ("utf8", "UTF-8 chapter viewer"),
        ("mirror", "Sanskrit Documents mirror"),
    ]]
    statuses = {
        "http_200": "Response checked", "http_404": "Returns 404",
        "listed_not_fetched": "Listed by source", "soft_block": "Response blocked",
        "listing_observed": "Directory listing observed",
    }
    entries.extend(
        (entry["url"], f'{entry["label"]} · {unquote(urlsplit(entry["url"]).path.rstrip("/").rsplit("/", 1)[-1])}',
         entry["status"])
        for entry in variants
    )
    seen = {original}
    links = []
    for url, label, status in entries:
        if url in seen:
            continue
        seen.add(url)
        note = f" · {escape(statuses.get(status, status.replace('_', ' ')))}" if status else ""
        links.append(f'<li><a href="{source_url(url)}" rel="external">{escape(label)} ↗</a>{note}</li>')
    return f'<details class="chapter-sources"><summary>Source editions and files</summary><ul class="variant-list">{"".join(links)}</ul></details>'


def supplemental_files(ancillary, variants):
    seen = {entry["url"] for group in ancillary["groups"] for entry in group["entries"]}
    entries = variants.get("other_source_files", []) + [
        entry for key in variants.get("auxiliary_chapters", []) for entry in variants["chapters"][key]
    ]
    sections = {}
    for entry in entries:
        url = entry["url"]
        if url in seen:
            continue
        seen.add(url)
        path = unquote(urlsplit(url).path)
        group = "UTF-8 source tree" if path.startswith("/utf8/") else "Legacy source tree"
        sections.setdefault(group, []).append(
            f'<li><a href="{source_url(url)}" rel="external">{escape(path)} ↗</a></li>'
        )
    return (f'<h1>Additional source files</h1><p><a href="../">Source files and editions</a></p>' +
            "".join(f'<section class="sources"><h2>{escape(group)}</h2><ul class="variant-list">'
                    f'{"".join(items)}</ul></section>' for group, items in sections.items()))


def source_guide(catalog, variants, has_audit=False):
    sections = []
    if variants.get("coverage"):
        cover = variants["coverage"]
        counts = " · ".join(
            f'{label} {cover[key]["chapter_directories_with_observed_children"]}/534'
            for key, label in (("original", "Legacy"), ("utf8", "UTF-8"))
        )
        sections.append(f'<section class="sources"><h2>Chapter directory audit</h2>'
                        f'<p>{escape(counts)} with observed child links. '
                        f'<a href="../source-variants.json">Download the URL inventory</a>.</p></section>')
    for group in catalog["groups"]:
        links = "".join(
            f'<li><a href="{escape(entry["url"]) if entry.get("local") else source_url(entry["url"])}">{escape(entry["label"])} ↗</a>'
            f' · {escape(entry["status"])}</li>'
            for entry in group["entries"]
        )
        sections.append(f'<section class="sources"><h2>{escape(group["title"])}</h2>'
                        f'<p>{escape(group["description"])}</p><ul class="variant-list">{links}</ul></section>')
    if has_audit:
        sections.append('<section class="sources"><h2>Audit details</h2>'
                        '<p><a href="files/">Additional discovered files</a> · '
                        '<a href="../source-audit.json">Audit totals and discovery scope</a></p></section>')
    return (f'<h1>Source files and editions</h1><p>Resources found on the original site, including both chapter trees '
            f'and files outside the editorial chapter index.</p>{"".join(sections)}')
