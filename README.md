# Vālmīki Rāmāyaṇa chapter directory

A searchable archive of the **534 sargas** listed in the six kāṇḍa indexes
at [valmikiramayan.net](https://valmikiramayan.net/). It includes the six-book
Sanskrit reader, a source file guide, and a separate historical English reader.

## Build

```sh
BASE_PATH=/ python3 build.py
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
