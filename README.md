# rifqa-content

Open content for the Rifqa (رفقة) app, prepared for download on demand and served through the jsDelivr CDN.
Nothing here is bundled in the app; the app downloads a collection or a surah when the reader opens it, verifies its
checksum and keeps it offline.

## Layout

```
index.json                       every collection, its version, files, sizes and sha256
hadith/<collection>/meta.json    books (sections) with hadith ranges and counts
hadith/<collection>/ar/<book>.json
hadith/<collection>/en/<book>.json
tafsir/<tafsir>/meta.json
tafsir/<tafsir>/<surah>.json     one file per surah
```

Files are served at `https://cdn.jsdelivr.net/gh/<owner>/rifqa-content@<tag>/<path>`. Every release is a tag, so the
files under a tag never change.

## Sources and licenses

| Content | Source | License |
|---|---|---|
| Hadith (Arabic, English, grades) | [fawazahmed0/hadith-api](https://github.com/fawazahmed0/hadith-api) | The Unlicense (public domain) |
| Classical tafsir (Ibn Kathir, al-Baghawi, al-Tabari, al-Qurtubi, al-Jalalayn) | Texts of authors who died centuries ago, from the [Quranic Universal Library](https://qul.tarteel.ai) | Public domain texts |

The processing scripts in `tools/` are released under the MIT License. See `LICENSE`.
