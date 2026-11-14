# Vālmīki Rāmāyaṇa chapter directory

A searchable archive of the **534 sargas** listed in the six kāṇḍa indexes
at [valmikiramayan.net](https://valmikiramayan.net/). It includes the six-book
Sanskrit reader, a source file guide, and a separate historical English reader.

## Build

```sh
BASE_PATH=/ python3 build.py
python3 verify_iast.py
BASE_PATH=/ python3 verify.py
python3 -m http.server 8000 --directory dist
```

GitHub Pages builds from `main` and serves under `/valmiki-ramayana-archive/`.
The default build uses that prefix. For local preview, use the root prefix
as shown above.

## Provenance and limits

`chapters.json` records the source chapter headings and order. The chapter
viewer links in `data/frames.json` come from the source tables of contents,
including the literal `5F` filenames. `data/ancillary.json` catalogs files
outside that index. The separate source inventory workflow checks linked
files, directory listings, and available resources.

All Sanskrit chapter records cite the primary textual witness and response
hash. Where source verse locators disagree, the reader numbers the source
blocks in reading order. Nine chapters preserve isolated damaged glyphs with
explicit warnings. The modern English translations, glosses, commentary, and original
media are linked from their sources. See [reuse and attribution](RIGHTS.md).

The source homepage credits **Desiraju Hanumanta Rao** for Bāla, Araṇya,
and Kiṣkindhā, and **K. M. K. Murthy** for Ayodhyā, Sundara, and Yuddha.
Its introduction additionally credits Durga Naaga Devi and Vaasudeva Kishore
for contributions to Sundara. The 142-page Ayyangar introduction PDF is preserved with a provenance record.

## Reader spellings

The original title data stays in `chapters.json`. The reviewed display titles
and Sanskrit glossary are in `data/chapter-iast.json`, pinned to the original
index by a content fingerprint. Diacritic-insensitive search uses displayed
headings and reviewed aliases.

The IAST verse display derives from Devanāgarī. Unsupported source bytes or
characters remain in the Devanāgarī witness and are flagged beside the absent
IAST. The separate Dutt reader changes only terms in its reviewed glossary.
The two publicly available IAST audit files record the checks and the
remaining exceptions.

## Audit evidence

The published coverage manifest distinguishes direct Sanskrit and facsimile
copies from links to original translations, glosses, commentary, and resources.
The separate [textual exception ledger](TEXTUAL_EXCEPTIONS.md) lists
additional or malformed source material with direct links. The independent
source-text workflow fetches the original Sanskrit HTML and compares every
pinned and restored passage against both the generated and published readers.


## Verse-level English source links

The right-hand English panels link to original, reference-checked translation
passages. The same panels follow IAST at narrower widths. A source translation
can cover several verses or partial verses and is linked once as a group.
Chapter-level source links cover pages where the exact verse correspondence
cannot be established. The published `prose-links-audit.json` lists verified
group locators, reader anchors, and unmatched passages.

The source index is built by `collect_prose_links.py`, which recognizes the
detailed panes’ `p.tat` translation paragraphs using their printed references
or a uniquely anchored, complete Sanskrit passage. It excludes introductions,
word meanings and commentary. The collector stores reference metadata and
hashes only.


The original chapter headers and indexes resolve 11 consistently misnumbered
source prefixes. The mapping is tied to exact source response hashes and
requires all printed verse numbers to form an uninterrupted sequence.
The displayed Sanskrit and printed source labels are preserved.


## Critical Edition English

The archive includes a separate Critical Edition English reader at `critical/`.
It preserves the ChatGPT reader’s public-domain Dutt prose, Baroda Edition
coordinates, and original alignment classifications across all seven kāṇḍas.
The original alignment is automated and remains unreviewed. Itihāsa
attribution and its Apache 2.0 license are included with the snapshot.

The six-book archive retains its own edition. Historical English appears next
to a reading block only where the editions can be matched by the actual
Sanskrit text, with a separate label for the reviewed normalization rule for
homorganic nasals. The report retains unresolved mappings and distinguishes
the Indian archive’s numbering from the Baroda Critical Edition.
