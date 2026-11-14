"""Render the historical English translation under a separate route."""
import gzip
import html
import json
import re
from pathlib import Path

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
    "printed as LVI are shown as 56a and 56b."
)


def paragraphs(text):
    for paragraph in PARAGRAPH_BREAK.split(text):
        segment = html.escape(" ".join(paragraph.split()))
        yield "<p>" + MARKUP.sub(r"<em>\1</em>", segment) + "</p>"


def render_dutt(page, write, data_dir=None):
    """Render the edition using the parent build's page and write functions."""
    data_dir = data_dir or Path(__file__).resolve().with_name("dutt-corpus")
    summaries = []
    for slug, count in BOOKS:
        files = sorted(data_dir.glob(f"{slug}*.json.gz"))
        chunks = [json.loads(gzip.decompress(file.read_bytes())) for file in files]
        if not chunks:
            raise ValueError(f"No Dutt corpus for {slug}")
        book = chunks[0]["book"]
        ebook = chunks[0]["source"]
        sections = [section for chunk in chunks for section in chunk["sections"]]
        expected = list(map(str, range(1, count + 1)))
        if slug == "aranya":
            expected = expected[:55] + ["56a", "56b"] + expected[56:-1]
        if [s["id"] for s in sections] != expected:
            raise ValueError(f"Incomplete Dutt corpus: {slug}")
        title = f"{book} Kāṇḍa"
        summaries.append(f'<li><a href="{slug}/">{title}</a> · {count} sections</li>')
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
            text = "".join(paragraphs(section["text"]))
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
    write("english/index.html", page(
        "M. N. Dutt’s English translation",
        f'<h1>M. N. Dutt’s English translation</h1><p>{EDITION_NOTE}</p><p>{SOURCE_NOTE}</p>'
        f'<ol class="chapters">{"".join(summaries)}</ol>',
        1,
    ))
