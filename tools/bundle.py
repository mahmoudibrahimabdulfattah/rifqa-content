#!/usr/bin/env python3
"""Bundle the built hadith collections into release assets.

The per-book files in hadith/ stay the source of truth. For delivery, each collection becomes one gzip file,
`hadith-<id>.ndjson.gz`, published as a GitHub Release asset (no repository size limit, served from GitHub's CDN,
one request per collection). The app reads it line by line, so it never holds a whole collection in memory:

    line 1      {"id", "name_ar", "name_en", "hadith_count", "books": [{"number", "title_ar", "title_en", "count"}]}
    line 2..n   {"b": <book number>, "ar": [{"n", "text", "grades"?}], "en": [...]}   (one line per book, "en" optional)

`hadith-index.json` lists every bundle with its size and sha256; the app verifies each download against it.

Each tafsir becomes `tafsir-<slug>.ndjson.gz` (release `tafsir-v1`), indexed by `tafsir-index.json`:

    line 1      {"id", "name_ar", "name_en", "author_ar", "author_en", "death_years", "surahs": [{"n", "ayahs"}]}
    line 2..n   {"s": <surah>, "ayahs": [{"a", "text"}]}   (a surah may span several lines; each line stays under 1 MB)

Usage: python3 tools/bundle.py [--out dist]
"""
import argparse
import datetime
import gzip
import hashlib
import io
import json
import os

SCHEMA_VERSION = 2


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def bundle_collection(root, cid, out):
    base = os.path.join(root, "hadith", cid)
    meta = read(os.path.join(base, "meta.json"))
    header = {
        "id": meta["id"],
        "name_ar": meta["name_ar"],
        "name_en": meta["name_en"],
        "hadith_count": meta["hadith_count"],
        "books": [
            {"number": b["number"], "title_ar": b.get("title_ar"), "title_en": b.get("title_en"), "count": b["count"]}
            for b in meta["books"]
        ],
    }
    lines = [dumps(header)]
    for book in meta["books"]:
        line = {"b": book["number"], "ar": [h for part in book.get("ar", []) for h in read(os.path.join(base, part["f"]))]}
        english = [h for part in book.get("en", []) for h in read(os.path.join(base, part["f"]))]
        if english:
            line["en"] = english
        lines.append(dumps(line))
    raw = ("\n".join(lines) + "\n").encode("utf-8")
    buffer = io.BytesIO()
    # mtime=0 keeps the output identical for identical input, so a rebuild never changes a published hash.
    with gzip.GzipFile(fileobj=buffer, mode="wb", compresslevel=9, mtime=0) as gz:
        gz.write(raw)
    data = buffer.getvalue()
    name = f"hadith-{cid}.ndjson.gz"
    with open(os.path.join(out, name), "wb") as f:
        f.write(data)
    return {
        "id": cid,
        "type": "hadith",
        "name_ar": meta["name_ar"],
        "name_en": meta["name_en"],
        "counts": {"hadith": meta["hadith_count"], "books": len(meta["books"])},
        "asset": name,
        "size": len(data),
        "raw_bytes": len(raw),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def gzip_bytes(raw):
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", compresslevel=9, mtime=0) as gz:
        gz.write(raw)
    return buffer.getvalue()


def bundle_tafsir(root, slug, out):
    base = os.path.join(root, "tafsir", slug)
    meta = read(os.path.join(base, "meta.json"))
    header = {k: meta.get(k) for k in ("id", "name_ar", "name_en", "author_ar", "author_en", "death_years")}
    header["surahs"] = [{"n": s["n"], "ayahs": s["ayahs"]} for s in meta["surahs"]]
    lines = [dumps(header)]
    for surah in meta["surahs"]:
        for part in surah["files"]:
            lines.append(dumps({"s": surah["n"], "ayahs": read(os.path.join(base, part["f"]))}))
    raw = ("\n".join(lines) + "\n").encode("utf-8")
    data = gzip_bytes(raw)
    name = f"tafsir-{slug}.ndjson.gz"
    with open(os.path.join(out, name), "wb") as f:
        f.write(data)
    return {
        "id": slug,
        "type": "tafsir",
        "name_ar": meta["name_ar"],
        "name_en": meta["name_en"],
        "author_ar": meta.get("author_ar"),
        "author_en": meta.get("author_en"),
        "asset": name,
        "size": len(data),
        "raw_bytes": len(raw),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default=os.path.join(root, "dist"), help="output directory (default: dist/)")
    args = p.parse_args()
    os.makedirs(args.out, exist_ok=True)
    index = read(os.path.join(root, "index.json"))
    order = ["bukhari", "muslim", "abudawud", "tirmidhi", "nasai", "ibnmajah", "malik"]
    ids = [c["id"] for c in index["collections"] if c["type"] == "hadith"]
    ids.sort(key=lambda i: order.index(i) if i in order else len(order))
    collections = [bundle_collection(root, cid, args.out) for cid in ids]
    result = {
        "schema": SCHEMA_VERSION,
        "generated": datetime.datetime.now(datetime.timezone.utc).date().isoformat(),
        "collections": collections,
    }
    with open(os.path.join(args.out, "hadith-index.json"), "w", encoding="utf-8") as f:
        f.write(dumps(result))
    order_t = ["ar-tafsir-ibn-kathir", "ar-tafsir-al-tabari", "ar-tafseer-al-qurtubi", "ar-tafsir-al-baghawi",
               "ar-tafsir-al-jalalayn"]
    slugs = [c["id"] for c in index["collections"] if c["type"] == "tafsir"]
    slugs.sort(key=lambda i: order_t.index(i) if i in order_t else len(order_t))
    tafsirs = [bundle_tafsir(root, slug, args.out) for slug in slugs]
    with open(os.path.join(args.out, "tafsir-index.json"), "w", encoding="utf-8") as f:
        f.write(dumps({"schema": SCHEMA_VERSION, "generated": result["generated"], "collections": tafsirs}))
    for c in collections + tafsirs:
        print(f"{c['asset']}: {c['size']} bytes gzip, {c['raw_bytes']} raw")


if __name__ == "__main__":
    main()
