"""Render the public-domain Dutt English witness by Critical Edition coordinate."""

from html import escape
from itertools import groupby
import json
from pathlib import Path


ORIGIN = "https://valmiki-ramayana-path.aaradhyapandeycs.chatgpt.site/"
NAMES = {
    "bala": "Bāla", "ayodhya": "Ayodhyā", "aranya": "Araṇya", "kishkindha": "Kiṣkindhā",
    "sundara": "Sundara", "yuddha": "Yuddha", "uttara": "Uttara",
}
LABELS = {"1:1": "Direct match", "grouped": "Grouped passage",
          "split": "Split passage", "approximate": "Approximate match"}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_critical(source_dir):
    manifest_path = source_dir / "manifest-all.json"
    if not manifest_path.is_file():
        return None, {}
    manifest = read_json(manifest_path)
    books = {}
    for book in manifest["kandas"]:
        slug = book["id"]
        if slug not in NAMES:
            raise ValueError(f"Unexpected Critical Edition book {slug}")
        books[slug] = {}
        for chapter in book["sargas"]:
            number = chapter["sarga"]
            rows = read_json(source_dir / slug / f"sarga-{number}.json")
            if len(rows) != chapter["count"]:
                raise ValueError(f"Critical Edition count differs for {slug}/{number}")
            books[slug][number] = rows
    return manifest, books


def verse_attributes(row, text_id=None):
    alignment = row["alignment"]
    parts = {
        "data-critical-coordinate": row["id"],
        "data-critical-alignment": alignment["type"],
        "data-critical-status": alignment["status"],
        "data-critical-dutt-refs": " ".join(alignment["duttRefs"]),
    }
    if text_id:
        parts["data-critical-text-id"] = text_id
    return " ".join(f'{key}="{escape(str(value), quote=True)}"' for key, value in parts.items())


def witness_label(row):
    return LABELS[row["alignment"]["type"]]


def display_group(rows):
    first = rows[0]
    text_id = "english-" + first["id"]
    coordinates = []
    for row in rows:
        identifier = row["id"]
        label = f'{row["kanda"]}.{row["sarga"]}.{row["verse"]}'
        coordinates.append(f'<a id="{identifier}" href="#{identifier}" '
                           f'{verse_attributes(row, text_id)}>{label}</a>')
    book, chapter, verse = (first[key] for key in ("kanda", "sarga", "verse"))
    source = f"{ORIGIN}#kanda-{book}-sarga-{chapter}-verse-{verse}"
    refs = ", ".join(first["alignment"]["duttRefs"])
    return (
        '<article class="critical-passage">'
        f'<header><span class="critical-coordinates">{", ".join(coordinates)}</span>'
        f' · {witness_label(first)} · <a href="{source}" rel="external">Source ↗</a></header>'
        f'<p class="critical-english-text" id="{text_id}">{escape(first["english"])}</p>'
        f'<p class="critical-refs">Dutt reference {escape(refs)}</p></article>'
    )


def passage_key(row):
    alignment = row["alignment"]
    if alignment["type"] == "grouped":
        return alignment["type"], tuple(alignment["duttRefs"]), row["english"]
    return row["id"]


def render_critical(page, write, source_dir, manifest, books, *, has_crosswalk=False):
    if not manifest:
        return
    headings = []
    for slug, chapters in books.items():
        name = NAMES[slug]
        name = f"{name} Kāṇḍa"
        headings.append(
            f'<li><a class="counted-link" href="{slug}/"><span>{name}</span> '
            f'<span class="entry-count">{len(chapters)} sargas</span></a></li>'
        )
        links = []
        for number, rows in chapters.items():
            links.append(
                f'<li><a class="counted-link" href="{number}/"><span>Sarga {number}</span> '
                f'<span class="entry-count">{len(rows)} coordinates</span></a></li>'
            )
            previous = f'<a href="../{number-1}/">← Previous</a>' if number > 1 else ""
            following = f'<a href="../{number+1}/">Next →</a>' if number < len(chapters) else ""
            title = f"{name} · Sarga {number}"
            passages = "".join(display_group(list(group)) for _, group in groupby(rows, key=passage_key))
            body = (
                '<p class="eyebrow"><a href="../../">Critical Edition English</a></p>'
                f'<h1>{title}</h1><p class="source-note">M. N. Dutt’s historical English prose. '
                'The source’s automated alignment to Baroda Critical Edition coordinates is unreviewed.</p>'
                f'<section class="critical-reader" aria-label="English passages">{passages}</section>'
                f'<nav class="chapter-nav" aria-label="Chapter sequence">{previous}'
                f'<a href="../">All {name} chapters</a>{following}</nav>'
            )
            write(f"critical/{slug}/{number}/index.html", page(title, body, 3))
        write(f"critical/{slug}/index.html", page(
            name, f'<p class="eyebrow"><a href="../">Critical Edition English</a></p><h1>{name}</h1>'
                  f'<ol class="chapters">{"".join(links)}</ol>', 2,
        ))
    matching_audit = (' · <a href="archive-matching-audit.json">Six-book archive matching audit</a>'
                      if has_crosswalk else "")
    write("critical/index.html", page("Critical Edition English", (
        '<h1>Critical Edition English</h1>'
        f'<p>M. N. Dutt’s historical prose at {manifest["totalVerses"]:,} Critical Edition coordinates '
        f'in {manifest["totalSargas"]} sargas across seven kāṇḍas.</p>'
        '<p class="source-note">The source automatically aligned Dutt’s prose to the Baroda Critical Edition. '
        'The alignment is unreviewed. A direct match pairs one coordinate with one Dutt reference. '
        'Grouped matches share a Dutt reference across coordinates. Split matches draw on multiple Dutt '
        'references for one coordinate. Approximate matches have uncertain correspondence. '
        'The same English can appear at multiple coordinates in the source alignment.</p>'
        f'<p><a href="{ORIGIN}">Original Critical Edition reader ↗</a> · '
        '<a href="https://huggingface.co/datasets/rahular/itihasa">Itihāsa dataset and Apache 2.0 license ↗</a> · '
        f'<a href="capture-audit.json">Transfer audit</a>{matching_audit}</p>'
        f'<ol class="chapters">{"".join(headings)}</ol>'
    ), 1))
    for item in ("capture-audit.json", "source-manifest.json", "LICENSE"):
        target = source_dir / item
        if target.is_file():
            write("critical/" + item, target.read_text(encoding="utf-8"))


def inline_groups(crosswalk, chapter, record, additions, critical_rows):
    """Use only complete, checked cross-edition passages for inline display."""
    from prose_links import local_units

    candidates = crosswalk["chapters"].get(chapter, []) + crosswalk["orthographic_candidates"].get(chapter, [])
    if not candidates:
        return []
    local = {anchor: digest for anchor, _, _, digest in local_units(record, additions)}
    result = []
    for group in candidates:
        if group["partially_covers_archive_unit"]:
            continue
        rows = [critical_rows[ref] for ref in group["refs"]]
        row = rows[0]
        status = row["alignment"]
        if group["method"] != "exact_compact" and (
                group["method"] != "orthographic_nasal" or len(rows) != 1
                or status["type"] != "1:1" or status["confidence"] < .85):
            continue
        if status["type"] == "split":
            continue
        if status["type"] == "approximate" or any(passage_key(row) != passage_key(other) for other in rows):
            raise ValueError(f"Crosswalk contains an invalid Dutt passage group: {group['refs']}")
        if len(group["units"]) != len(group["unit_sha256"]) or any(
                local.get(unit) != digest for unit, digest in zip(group["units"], group["unit_sha256"])):
            raise ValueError(f"Crosswalk is based on a different archive passage: {chapter}/{group['refs']}")
        result.append({**group, "row": row})
    return result


def inline_panel(group):
    row = group["row"]
    url = f'../../critical/{row["kandaId"]}/{row["sarga"]}/#{row["id"]}'
    labels = ", ".join(ref.removeprefix("VRCE-").replace("-", ".") for ref in group["refs"])
    method = group["method"]
    spelling = " · Nasal spelling variant" if method == "orthographic_nasal" else ""
    refs = escape(" ".join(group["refs"]), quote=True)
    units = escape(" ".join(group["units"]), quote=True)
    return (
        f'<div class="critical-inline" {verse_attributes(row)} data-critical-method="{escape(method)}" '
        f'data-critical-refs="{refs}" data-critical-local-units="{units}">'
        f'<p class="critical-english-text">{escape(row["english"])}</p>'
        f'<p class="critical-refs"><a href="{url}">M. N. Dutt · Critical Edition {escape(labels)}</a>'
        f' · {witness_label(row)}{spelling} · Unreviewed</p></div>'
    )
