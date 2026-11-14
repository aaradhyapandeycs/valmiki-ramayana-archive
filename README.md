# Vālmīki Rāmāyaṇa chapter directory

A searchable, mobile-friendly static directory of the **534 sargas** listed in
the six kāṇḍa indexes at [valmikiramayan.net](https://valmikiramayan.net/).
This is an independent navigation project, **not a copy of the complete text**.

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

The Sanskrit reader only displays validated records with a recorded textual
witness. The primary site and Sanskrit Documents mirror can differ. Where
the source's verse locators disagree, the reader identifies its source
blocks. The modern English translations, glosses, commentary, and original
media are linked from their sources. See [reuse and attribution](RIGHTS.md).

The source homepage credits **Desiraju Hanumanta Rao** for Bāla, Araṇya,
and Kiṣkindhā, and **K. M. K. Murthy** for Ayodhyā, Sundara, and Yuddha.
Its introduction additionally credits Durga Naaga Devi and Vaasudeva Kishore
for contributions to Sundara. The Ayyangar introduction PDF is linked, not
redistributed.
