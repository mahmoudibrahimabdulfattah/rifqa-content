# rifqa-content

Open content for the Rifqa (رفقة) app, prepared for download on demand and served through the jsDelivr CDN.
Nothing here is bundled in the app; the app downloads a collection or a surah when the reader opens it, verifies its
checksum and keeps it offline.

## Build

```bash
python3 tools/build.py                                          # everything, into the repo root
python3 tools/build.py --only hadith:bukhari,tafsir:ar-tafsir-ibn-kathir
python3 tools/build.py --only hadith --out /tmp/content --cache /tmp/cache
```

Python 3 standard library only. `--only` takes `hadith`, `tafsir`, `hadith:<id>` or `tafsir:<slug>`; a subset build
keeps the other entries already in `index.json`. `--cache` keeps downloaded sources for quick reruns. Requests are
sequential, with a short delay and retries. The manual workflow `Build content` runs the full build, commits and tags.

## Layout

```
index.json                              schema, date, every collection with its files, sizes and sha256
hadith/<id>/meta.json                   names, count, books
hadith/<id>/ar/<book>.json              also en/<book>.json
tafsir/<slug>/meta.json                 names, author, death years, 114 surahs
tafsir/<slug>/<surah>.json
```

Files are served at `https://cdn.jsdelivr.net/gh/<owner>/rifqa-content@<tag>/<path>`. Every release is a tag, so the
files under a tag never change. All files are minified JSON, UTF-8, and stay under about 1 MB: a book or surah that
is bigger is split at a hadith or ayah group boundary into `<book>-1.json`, `<book>-2.json` and so on (the `files`
lists in `meta.json` say which file holds which range).

## Schemas

```
index.json   {schema:1, generated:"YYYY-MM-DD", collections:[{id, type:"hadith"|"tafsir", name_ar, name_en,
              counts:{hadith,books} | {surahs,ayahs}, total_bytes, files:[{path, size, sha256}]}]}
hadith meta  {id, name_ar, name_en, hadith_count, has_en, books:[{number, title_ar (null: the source has English
              titles only), title_en, first, last, count, ar:[{f, from, to}], en:[{f, from, to}]}]}
hadith file  [{n, text, grades:[{by, grade}]}]          n = hadith number; grades may be empty
tafsir meta  {id, name_ar, name_en, author_ar, author_en, death_years:[..],
              surahs:[{n, ayahs, files:[{f, from, to}]}]}   f is relative to the tafsir folder
tafsir file  [{a, text} | {a, same}]   same = first ayah of a group that shares one text; text uses \n for paragraphs
```

## Sources and licenses

| Content | Source | License |
|---|---|---|
| Hadith (Arabic, English, grades) | [fawazahmed0/hadith-api](https://github.com/fawazahmed0/hadith-api) | The Unlicense (public domain) |
| Classical tafsir (Ibn Kathir, al-Baghawi, al-Tabari, al-Qurtubi, al-Jalalayn) | [spa5k/tafsir_api](https://github.com/spa5k/tafsir_api), texts from the [Quranic Universal Library](https://qul.tarteel.ai) | MIT repository; public domain texts |

See `CREDITS.md`. The processing scripts in `tools/` are released under the MIT License. See `LICENSE`.
