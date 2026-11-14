# Vālmīki Rāmāyaṇa chapter directory

A searchable, mobile-friendly static directory of the **534 sargas** listed in
the six kāṇḍa indexes at [valmikiramayan.net](https://valmikiramayan.net/).
This is an independent navigation project, **not a copy of the complete text**.

## Build

```sh
python3 build.py
python3 verify.py
BASE_PATH=/ python3 build.py
BASE_PATH=/ python3 verify.py
python3 -m http.server 8000 --directory dist
```

GitHub Pages builds from `main` and serves under `/valmiki-ramayana-archive/`.
The default build uses that prefix. For local preview, use the root prefix
as shown above.

## Provenance and limits

`chapters.json` records titles and chapter order transcribed from six live
source indexes on November 13, 2026 (America/New_York). `dist/manifest.json`
maps the indexed frame URLs and a few discovered variants and downloads to
local routes with honest status labels. The frame URL patterns were sampled
at the first/last chapters; each individual response was not checked. The
source's UTF-8 introduction links to five indexes that returned 404.

`crawl.py` inventories links, legacy frames, variant pages, downloads, and
response statuses when network access permits, writing `crawl-report.json`.
Its output must be reviewed and reconciled with `chapters.json`; it does
not copy original page text. The current environment blocks direct source
fetches with HTTP 403, so a complete recursive inventory has **not** run.

The Sanskrit epic is ancient, but reuse rights for this site's English
translations, commentary, PDF files, fonts, and editorial presentation
have not been established. These remain linked to the source. No Sanskrit
verses, transliterations, English translations, commentary, or verse
anchors have been reconstructed here; none should be inferred from chapter
titles. See the source [introduction](https://valmikiramayan.net/utf8/ramayana.shtml)
and home page for edition details and contributor credits.

The source homepage credits **Desiraju Hanumanta Rao** for Bāla, Araṇya,
and Kiṣkindhā, and **K. M. K. Murthy** for Ayodhyā, Sundara, and Yuddha.
Its introduction additionally credits Durga Naaga Devi and Vaasudeva Kishore
for contributions to Sundara. The Ayyangar introduction PDF is linked, not
redistributed.
