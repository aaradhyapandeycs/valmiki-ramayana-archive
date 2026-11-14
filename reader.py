"""Read vetted Sanskrit snapshots and source-link metadata for the static site."""
import html
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

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
    anchor = "verse" if numbered else "block"
    items = []
    for verse in record["verses"]:
        number = verse["number"]
        last = verse.get("last_number", number)
        for n in range(number, last):
            items.append(f'<span id="{anchor}-{n}" class="verse-anchor"></span>')
        label = str(number) if last == number else f"{number}–{last}"
        items.append(f'<div class="verse" id="{anchor}-{last}">'
                     f'<a href="#{anchor}-{last}" aria-label="Link to {anchor} {label}">{label}</a>'
                     f'<p lang="sa-Deva">{escape(verse["sanskrit"])}</p></div>')
    return (f'<section class="reader" id="sanskrit"><h2>Sanskrit verses</h2>'
            f'<p class="source-note"><a href="{provenance}">{witness} source ↗</a>. {note}</p>'
            f'{"".join(items)}</section>')


def render_coverage(records):
    counts = {kind: sum(r["kind"] == kind for r in records.values()) for kind in WITNESSES}
    return (f'{counts["primary"]} chapters with Sanskrit from the primary source · '
            f'{counts["mirror"]} from the Sanskrit Documents mirror · '
            f'{534 - len(records)} with source links')


def load_catalog(name, default):
    path = DATA / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def chapter_sources(slug, number, original, frames, variants):
    frame_links = frames[slug]["chapters"][str(number)]
    entries = [(frame_links[key], label, "") for key, label in [
        ("original", "Original chapter viewer"), ("utf8", "UTF-8 chapter viewer"),
        ("mirror", "Sanskrit Documents mirror"),
    ]]
    entries.extend((entry["url"], entry["label"], entry["status"]) for entry in variants)
    seen = {original}
    links = []
    for url, label, status in entries:
        if url in seen:
            continue
        seen.add(url)
        statuses = {"http_200": "Response checked", "http_404": "Returns 404",
                    "listed_not_fetched": "Listed by source", "soft_block": "Response blocked"}
        note = f" · {escape(statuses.get(status, status.replace('_', ' ')))}" if status else ""
        links.append(f'<li><a href="{source_url(url)}" rel="external">{escape(label)} ↗</a>{note}</li>')
    return f'<details class="chapter-sources"><summary>Source editions and files</summary><ul class="variant-list">{"".join(links)}</ul></details>'


def source_guide(catalog, variants):
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
            f'<li><a href="{source_url(entry["url"])}" rel="external">{escape(entry["label"])} ↗</a>'
            f' · {escape(entry["status"])}</li>'
            for entry in group["entries"]
        )
        sections.append(f'<section class="sources"><h2>{escape(group["title"])}</h2>'
                        f'<p>{escape(group["description"])}</p><ul class="variant-list">{links}</ul></section>')
    return (f'<h1>Source files and editions</h1><p>Resources found on the original site, including both chapter trees '
            f'and files outside the editorial chapter index.</p>{"".join(sections)}')
