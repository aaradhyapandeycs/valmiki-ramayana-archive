"""Read vetted Sanskrit snapshots and source-link metadata for the static site."""
import html
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from transliterate_iast import transliterate

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


def render_sanskrit(record):
    if record is None:
        return ""
    provenance = source_url(record["source_url"])
    witness = WITNESSES[record["kind"]]
    numbered = record["status"] == "numbering_verified"
    note = ("Verse numbering checked against the linked source." if numbered else
            "Passages appear in source order. The numbers mark reading blocks where source verse labels disagree.")
    if record["kind"] == "mirror":
        note += " This witness may differ from the current Valmikiramayan.net wording."
    if any(verse.get("source_glyph_anomaly") for verse in record["verses"]):
        note += " The original contains a few damaged glyphs. They are preserved as printed."
    anchor = "verse" if numbered else "block"
    items = []
    for verse in record["verses"]:
        number = verse["number"]
        last = verse.get("last_number", number)
        for n in range(number, last):
            items.append(f'<span id="{anchor}-{n}" class="verse-anchor"></span>')
        label = str(number) if last == number else f"{number}–{last}"
        roman = None if verse.get("source_glyph_anomaly") else transliterate(verse["sanskrit"])
        alternate = f'<p lang="sa-Latn" class="iast">{escape(roman)}</p>' if roman else ""
        items.append(f'<div class="verse" id="{anchor}-{last}">'
                     f'<a href="#{anchor}-{last}" aria-label="Link to {anchor} {label}">{label}</a>'
                     f'<div><p lang="sa-Deva">{escape(verse["sanskrit"])}</p>{alternate}</div></div>')
    colophon = record.get("colophon")
    ending = f'<p class="colophon" lang="sa-Deva">{escape(colophon)}</p>' if colophon else ""
    return (f'<section class="reader" id="sanskrit"><h2>Sanskrit verses</h2>'
            f'<p class="source-note"><a href="{provenance}">{witness} source ↗</a>. {note}</p>'
            f'<p class="iast-note">IAST is generated from the displayed Devanagari.</p>'
            f'{"".join(items)}{ending}</section>')


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
