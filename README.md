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
