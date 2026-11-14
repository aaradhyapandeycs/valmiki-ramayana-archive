"""Render the historical English translation under a separate route."""
import gzip
from hashlib import sha256
import html
import json
import re
import unicodedata
from pathlib import Path

from dutt_iast import build_audit, normalize_dutt

BOOKS = (
    ("baala", 77), ("ayodhya", 119), ("aranya", 76),
    ("kish", 67), ("sundara", 68), ("yuddha", 130),
)
PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
MARKUP = re.compile(r"_([^_\n<>]+)_")
EDITION_NOTE = (
    "Manmatha Nath Dutt’s public-domain English prose translation, published in "
    "Calcutta in 1891–1893. Numbering follows the Dutt edition so chapter "
    "identifiers can differ from the source archive."
)
SOURCE_NOTE = (
    "This transcription preserves Dutt’s prose and translator’s notes. Four "
    "unlabelled section boundaries have been restored. In Araṇya, two sections "
    "printed as LVI are shown as 56a and 56b. The reader uses a reviewed IAST glossary "
    "for Sanskrit names and terms. Historical spellings requiring further review remain visible."
)


def paragraphs(text):
    for paragraph in PARAGRAPH_BREAK.split(text):
        segment = html.escape(" ".join(paragraph.split()))
        yield "<p>" + MARKUP.sub(r"<em>\1</em>", segment) + "</p>"


def read_sections(data_dir, slug):
    chunks = [json.loads(gzip.decompress(file.read_bytes()))
              for file in sorted(data_dir.glob(f"{slug}*.json.gz"))]
    if not chunks:
        raise ValueError(f"No Dutt corpus for {slug}")
    return chunks[0]["book"], chunks[0]["source"], [section for chunk in chunks for section in chunk["sections"]]


def reviewed_passages(data_dir, catalog):
    """Resolve reviewed boundaries against the archived Dutt transcription."""
    passages = {}
    for chapter, review in catalog.items():
        book, number = chapter.split("/")
        _, _, sections = read_sections(data_dir, book)
        section = next(s for s in sections if s["id"] == review["section"])
        english = " ".join(section["text"].split())
        if sha256(english.encode("utf-8")).hexdigest() != review["section_sha256"]:
            raise ValueError(f"Reviewed Dutt transcription changed at {book}/{review['section']}")
        passages[chapter] = []
        end = 0
        for group in review["passages"]:
            first, last = group["english_span"]
            if not end <= first < last <= len(english):
                raise ValueError(f"Invalid reviewed Dutt passage boundaries at {book}/{number}")
            text = english[first:last].strip()
            if not text:
                raise ValueError(f"Empty reviewed Dutt passage at {book}/{number}")
            passages[chapter].append({**group, "dutt_text": text, "href": review["href"],
                                      "translator": "M. N. Dutt", "section": review["section"]})
            end = last
    return passages


def render_dutt(page, write, data_dir=None):
    """Render the edition using the parent build's page and write functions."""
    data_dir = data_dir or Path(__file__).resolve().with_name("dutt-corpus")
    summaries = []
    source_texts = []
    for slug, count in BOOKS:
        book, ebook, sections = read_sections(data_dir, slug)
        expected = list(map(str, range(1, count + 1)))
        if slug == "aranya":
            expected = expected[:55] + ["56a", "56b"] + expected[56:-1]
        if [s["id"] for s in sections] != expected:
            raise ValueError(f"Incomplete Dutt corpus: {slug}")
        source_texts.extend(section["text"] for section in sections)
        title = f"{book} Kāṇḍa"
        summaries.append(
            f'<li><a class="counted-link" href="{slug}/"><span>{title}</span> '
            f'<span class="entry-count">{count} sections</span></a></li>'
        )
        links = []
        for i, section in enumerate(sections):
            identifier = section["id"]
            name = f"Section {identifier}"
            links.append(f'<li><a href="{identifier}/">{name}</a></li>')
            before = f'<a href="../{sections[i - 1]["id"]}/">← Previous section</a>' if i else ""
            after = f'<a href="../{sections[i + 1]["id"]}/">Next section →</a>' if i + 1 < count else ""
            label = section["printed_heading"]
            source_label = f'Printed heading: {html.escape(label)}' if label else "Restored section boundary."
            nav = (
                '<nav class="chapter-nav" aria-label="Dutt section sequence">'
                f'{before}<a href="../">All {title} sections</a>{after}</nav>'
            )
            display = unicodedata.normalize("NFC", normalize_dutt(section["text"]))
            text = "".join(paragraphs(display))
            write(f"english/{slug}/{identifier}/index.html", page(
                f"{title} · {name} · M. N. Dutt",
                f'<p class="eyebrow"><a href="../../">M. N. Dutt’s English translation</a></p>'
                f'<h1>{title} · {name}</h1><p class="source-note">{source_label} '
                f'<a href="{ebook}" rel="external">Digital transcription ↗</a></p>'
                f'<article aria-label="{title} {name}">{text}</article>{nav}',
                3,
            ))
        write(f"english/{slug}/index.html", page(
            f"{title} · M. N. Dutt",
            '<p class="eyebrow"><a href="../">M. N. Dutt’s English translation</a></p>'
            f'<h1>{title}</h1><p>{EDITION_NOTE}</p><ol class="chapters">{"".join(links)}</ol>',
            2,
        ))
    audit = build_audit(source_texts)
    if audit["section_count"] != 537:
        raise ValueError("Dutt corpus must retain 537 published sections")
    write("english/iast-audit.json", json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    write("english/index.html", page(
        "M. N. Dutt’s English translation",
        f'<h1>M. N. Dutt’s English translation</h1><p>{EDITION_NOTE}</p><p>{SOURCE_NOTE}</p>'
        f'<p><a href="iast-audit.json">IAST glossary review and unresolved spellings</a></p>'
        f'<ol class="chapters">{"".join(summaries)}</ol>',
        1,
    ))
