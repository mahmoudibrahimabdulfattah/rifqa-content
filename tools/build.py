#!/usr/bin/env python3
"""Build the Rifqa content files (hadith, tafsir, index.json) from open sources.

Python 3 standard library only. Examples:

    python3 tools/build.py                                   # everything
    python3 tools/build.py --only hadith:bukhari,tafsir:ar-tafsir-ibn-kathir
    python3 tools/build.py --only hadith --out /tmp/content
"""
import argparse
import datetime
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

SCHEMA_VERSION = 1
HADITH_BASE = "https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/"
TAFSIR_BASE = "https://cdn.jsdelivr.net/gh/spa5k/tafsir_api@main/tafsir/"
MAX_FILE_BYTES = 1_000_000  # soft split threshold; jsDelivr allows 20 MB, the app wants small files
DELAY = 0.25
USER_AGENT = "rifqa-content-build/1"

# id -> Arabic name. English names come from the source's info.min.json.
HADITH = {
    "bukhari": "صحيح البخاري",
    "muslim": "صحيح مسلم",
    "abudawud": "سنن أبي داود",
    "tirmidhi": "جامع الترمذي",
    "nasai": "سنن النسائي",
    "ibnmajah": "سنن ابن ماجه",
    "malik": "موطأ مالك",
    "ahmad": "مسند أحمد",  # not in the source today; skipped with a warning
    "darimi": "سنن الدارمي",  # not in the source today; skipped with a warning
}

TAFSIR = {
    "ar-tafsir-ibn-kathir": dict(
        name_ar="تفسير ابن كثير", name_en="Tafsir Ibn Kathir",
        author_ar="ابن كثير", author_en="Ismail ibn Umar ibn Kathir", death_years=[774]),
    "ar-tafsir-al-baghawi": dict(
        name_ar="معالم التنزيل (تفسير البغوي)", name_en="Ma'alim al-Tanzil (Tafsir al-Baghawi)",
        author_ar="الحسين بن مسعود البغوي", author_en="al-Husayn ibn Mas'ud al-Baghawi", death_years=[516]),
    "ar-tafsir-al-tabari": dict(
        name_ar="جامع البيان (تفسير الطبري)", name_en="Jami' al-Bayan (Tafsir al-Tabari)",
        author_ar="محمد بن جرير الطبري", author_en="Muhammad ibn Jarir al-Tabari", death_years=[310]),
    "ar-tafseer-al-qurtubi": dict(
        name_ar="الجامع لأحكام القرآن (تفسير القرطبي)", name_en="al-Jami' li-Ahkam al-Quran (Tafsir al-Qurtubi)",
        author_ar="محمد بن أحمد القرطبي", author_en="Muhammad ibn Ahmad al-Qurtubi", death_years=[671]),
    "ar-tafsir-al-jalalayn": dict(
        name_ar="تفسير الجلالين", name_en="Tafsir al-Jalalayn",
        author_ar="جلال الدين المحلي وجلال الدين السيوطي",
        author_en="Jalal al-Din al-Mahalli and Jalal al-Din al-Suyuti", death_years=[864, 911]),
}

# Ayah count of each surah (Hafs numbering, 6236 in total); used to validate the source.
AYAHS = [7, 286, 200, 176, 120, 165, 206, 75, 129, 109, 123, 111, 43, 52, 99, 128, 111, 110, 98, 135, 112, 78, 118,
         64, 77, 227, 93, 88, 69, 60, 34, 30, 73, 54, 45, 83, 182, 88, 75, 85, 54, 53, 89, 59, 37, 35, 38, 29, 18, 45,
         60, 49, 62, 55, 78, 96, 29, 22, 24, 13, 14, 11, 11, 18, 12, 12, 30, 52, 52, 44, 28, 28, 20, 56, 40, 31, 50,
         40, 46, 42, 29, 19, 36, 25, 22, 17, 19, 26, 30, 20, 15, 21, 11, 8, 8, 19, 5, 8, 8, 11, 11, 8, 3, 9, 5, 4, 7,
         3, 6, 3, 5, 4, 5, 6]

CACHE_DIR = None


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def fetch_json(url, retries=5):
    """GET a JSON document politely: optional on-disk cache, delay, retries with backoff."""
    cache_path = None
    if CACHE_DIR:
        cache_path = os.path.join(CACHE_DIR, hashlib.sha1(url.encode()).hexdigest() + ".json")
        if os.path.exists(cache_path):
            with open(cache_path, "rb") as f:
                return json.loads(f.read().decode("utf-8"))
    last = None
    for attempt in range(retries):
        time.sleep(DELAY)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
            with urllib.request.urlopen(req, timeout=120) as r:
                raw = r.read()
            data = json.loads(raw.decode("utf-8"))
            if cache_path:
                os.makedirs(CACHE_DIR, exist_ok=True)
                with open(cache_path, "wb") as f:
                    f.write(raw)
            return data
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 404:
                break
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
            last = e
        wait = 2 ** attempt
        log(f"  retry {attempt + 1}/{retries} in {wait}s for {url}: {last}")
        time.sleep(wait)
    raise RuntimeError(f"failed to fetch {url}: {last}")


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


class Writer:
    """Writes files under the output root and remembers their size and sha256."""

    def __init__(self, root):
        self.root = root
        self.files = []

    def write(self, rel, obj):
        data = dumps(obj).encode("utf-8")
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        self.files.append({"path": rel, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})

    def take(self):
        files, self.files = self.files, []
        return files


def num(x):
    return int(x) if float(x) == int(x) else x


def chunk(groups, limit=MAX_FILE_BYTES):
    """Pack lists of items (each group is kept whole) into parts of at most `limit` bytes."""
    parts, cur, size = [], [], 2
    for g in groups:
        gs = sum(len(dumps(i).encode("utf-8")) + 1 for i in g)
        if cur and size + gs > limit:
            parts.append(cur)
            cur, size = [], 2
        cur.extend(g)
        size += gs
    if cur:
        parts.append(cur)
    return parts


# ---------------------------------------------------------------- hadith

def build_hadith(cid, ar_name, info, editions, out):
    meta_src = info.get(cid)
    names = {e["name"] for e in editions.get(cid, {}).get("collection", [])}
    if not meta_src or f"ara-{cid}" not in names:
        log(f"hadith:{cid}: not available in the source, skipped")
        return None
    en_ok = f"eng-{cid}" in names
    log(f"hadith:{cid}: fetching")
    ara = fetch_json(f"{HADITH_BASE}editions/ara-{cid}.min.json")
    eng = fetch_json(f"{HADITH_BASE}editions/eng-{cid}.min.json") if en_ok else None

    grades = {}
    for ed in (ara, eng):
        for h in (ed or {})["hadiths"] if ed else []:
            g = [{"by": x["name"], "grade": x["grade"]} for x in h.get("grades") or [] if x.get("grade")]
            if g and h["hadithnumber"] not in grades:
                grades[h["hadithnumber"]] = g

    # Books come from the source's section ranges of hadith numbers. The source has a few typos in them (a start
    # lower than the previous end), so a start is moved to just after the previous end. Hadith in a gap (unnumbered
    # slots) join the book before them. reference.book is not used: it is 0 for scattered hadith in Bukhari.
    ranges, prev_hi = [], 0
    details = ara["metadata"].get("section_details", {})
    for key in sorted(details, key=int):
        lo, hi = details[key]["hadithnumber_first"], details[key]["hadithnumber_last"]
        if hi < 1:
            continue
        if lo <= prev_hi:
            lo = prev_hi + 1
        if hi < lo:
            continue
        ranges.append((lo, int(key)))
        prev_hi = hi

    def book_of(n):
        book = ranges[0][1]
        for lo, key in ranges:
            if lo > n:
                break
            book = key
        return book

    def by_book(ed):
        books, dropped = {}, 0
        for h in ed["hadiths"]:
            text = (h.get("text") or "").strip()
            if not text:
                dropped += 1
                continue
            item = {"n": num(h["hadithnumber"]), "text": text, "grades": grades.get(h["hadithnumber"], [])}
            books.setdefault(book_of(h["hadithnumber"]), []).append(item)
        if dropped:
            log(f"  note: {dropped} hadith with empty text dropped")
        for items in books.values():
            items.sort(key=lambda i: i["n"])
        return books

    ar_books = by_book(ara)
    en_books = by_book(eng) if eng else {}
    sections = ara["metadata"]["sections"]
    en_sections = (eng or ara)["metadata"]["sections"]
    w = Writer(out)
    books_meta = []
    total = 0
    for b in sorted(ar_books):
        items = ar_books[b]
        entry = {
            "number": b,
            "title_ar": None,  # the source has English book titles only
            "title_en": (en_sections.get(str(b)) or sections.get(str(b)) or "").strip() or None,
            "first": items[0]["n"], "last": items[-1]["n"], "count": len(items),
        }
        total += len(items)
        for lang, src in (("ar", ar_books), ("en", en_books)):
            if b not in src:
                continue
            refs = []
            parts = chunk([[i] for i in src[b]])
            for k, part in enumerate(parts, 1):
                rel = f"{lang}/{b}.json" if len(parts) == 1 else f"{lang}/{b}-{k}.json"
                w.write(f"hadith/{cid}/{rel}", part)
                refs.append({"f": rel, "from": part[0]["n"], "to": part[-1]["n"]})
            entry[lang] = refs
        books_meta.append(entry)
    missing_en = sorted(set(ar_books) - set(en_books)) if eng else []
    if missing_en:
        log(f"  note: books without English text: {missing_en}")
    meta = {
        "id": cid, "name_ar": ar_name, "name_en": meta_src["metadata"]["name"],
        "hadith_count": total, "has_en": bool(eng), "books": books_meta,
    }
    w.write(f"hadith/{cid}/meta.json", meta)
    files = w.take()
    return {
        "id": cid, "type": "hadith", "name_ar": ar_name, "name_en": meta["name_en"],
        "counts": {"hadith": total, "books": len(books_meta)},
        "total_bytes": sum(f["size"] for f in files), "files": files,
    }


# ---------------------------------------------------------------- tafsir

FOOTNOTE = re.compile(r"\[\[.*?\]\]", re.S)
BREAKS = re.compile(r"<\s*br\s*/?\s*>|</\s*(?:p|div|li|h[1-6])\s*>", re.I)
TAGS = re.compile(r"<[^>]+>")


def clean_tafsir(text):
    text = BREAKS.sub("\n\n", text or "")
    text = TAGS.sub("", text)
    text = html.unescape(text)
    text = FOOTNOTE.sub("", text)  # editors' footnotes of the printed edition
    text = text.replace("\r", "")
    text = re.sub(r"[ \t ]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return re.sub(r"[ \t ]{2,}", " ", text).strip()


def build_tafsir(slug, spec, known, out):
    if slug not in known:
        log(f"tafsir:{slug}: not in editions.json, skipped")
        return None
    w = Writer(out)
    surahs, total_ayahs = [], 0
    for s in range(1, 115):
        log(f"tafsir:{slug}: surah {s}/114")
        raw = fetch_json(f"{TAFSIR_BASE}{slug}/{s}.json")
        entries = sorted(raw, key=lambda e: e["ayah"])
        groups, last_text = [], None
        for e in entries:
            text = clean_tafsir(e.get("text"))
            if groups and text == last_text:
                groups[-1].append({"a": e["ayah"], "same": groups[-1][0]["a"]})
            else:
                groups.append([{"a": e["ayah"], "text": text}])
            last_text = text
        ayahs = [i["a"] for g in groups for i in g]
        expected = AYAHS[s - 1]
        covered = {a for a in ayahs if a >= 1}
        if len(covered) != expected or max(covered, default=0) != expected:
            log(f"  warning: surah {s} has {len(covered)} ayahs in the source, expected {expected}")
        refs = []
        parts = chunk(groups)
        for k, part in enumerate(parts, 1):
            rel = f"{s}.json" if len(parts) == 1 else f"{s}-{k}.json"
            w.write(f"tafsir/{slug}/{rel}", part)
            refs.append({"f": rel, "from": part[0]["a"], "to": part[-1]["a"]})
        surahs.append({"n": s, "ayahs": expected, "files": refs})
        total_ayahs += expected
    meta = {
        "id": slug, "name_ar": spec["name_ar"], "name_en": spec["name_en"],
        "author_ar": spec["author_ar"], "author_en": spec["author_en"], "death_years": spec["death_years"],
        "surahs": surahs,
    }
    w.write(f"tafsir/{slug}/meta.json", meta)
    files = w.take()
    return {
        "id": slug, "type": "tafsir", "name_ar": spec["name_ar"], "name_en": spec["name_en"],
        "counts": {"surahs": 114, "ayahs": total_ayahs},
        "total_bytes": sum(f["size"] for f in files), "files": files,
    }


# ---------------------------------------------------------------- main

def parse_only(value):
    """None -> everything; 'hadith' / 'tafsir' -> a whole type; 'hadith:bukhari' -> one item."""
    if not value:
        return None
    want = set()
    for part in value.split(","):
        part = part.strip()
        if part:
            want.add(part)
    return want


def selected(want, kind, cid):
    return want is None or kind in want or f"{kind}:{cid}" in want


def main():
    global CACHE_DIR, DELAY
    here = os.path.dirname(os.path.abspath(__file__))
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default=os.path.dirname(here), help="output directory (default: the repo root)")
    p.add_argument("--only", help="comma list: hadith, tafsir, hadith:<id>, tafsir:<slug>")
    p.add_argument("--cache", help="directory that caches downloaded source files (faster reruns)")
    p.add_argument("--delay", type=float, default=DELAY, help="seconds to wait before each request")
    args = p.parse_args()
    CACHE_DIR, DELAY = args.cache, args.delay
    out = os.path.abspath(args.out)
    want = parse_only(args.only)

    entries = []
    wanted_h = [c for c in HADITH if selected(want, "hadith", c)]
    wanted_t = [s for s in TAFSIR if selected(want, "tafsir", s)]
    if want:
        known = {f"hadith:{c}" for c in HADITH} | {f"tafsir:{s}" for s in TAFSIR} | {"hadith", "tafsir"}
        bad = want - known
        if bad:
            p.error(f"unknown --only entries: {sorted(bad)}")
    if wanted_h:
        info = fetch_json(HADITH_BASE + "info.min.json")
        editions = fetch_json(HADITH_BASE + "editions.min.json")
        for cid in wanted_h:
            e = build_hadith(cid, HADITH[cid], info, editions, out)
            if e:
                entries.append(e)
    if wanted_t:
        known = {t["slug"] for t in fetch_json(TAFSIR_BASE + "editions.json")}
        for slug in wanted_t:
            e = build_tafsir(slug, TAFSIR[slug], known, out)
            if e:
                entries.append(e)

    # A subset build keeps the other entries of an existing index.json.
    index_path = os.path.join(out, "index.json")
    merged = {}
    if os.path.exists(index_path):
        try:
            with open(index_path, encoding="utf-8") as f:
                for e in json.load(f).get("collections", []):
                    if os.path.isdir(os.path.join(out, e["type"], e["id"])):
                        merged[(e["type"], e["id"])] = e
        except (ValueError, KeyError):
            pass
    for e in entries:
        merged[(e["type"], e["id"])] = e
    order = {"hadith": 0, "tafsir": 1}
    collections = [merged[k] for k in sorted(merged, key=lambda k: (order[k[0]], k[1]))]
    index = {
        "schema": SCHEMA_VERSION,
        "generated": datetime.datetime.now(datetime.timezone.utc).date().isoformat(),
        "collections": collections,
    }
    os.makedirs(out, exist_ok=True)
    with open(index_path, "wb") as f:
        f.write(dumps(index).encode("utf-8"))
    all_files = [x for c in collections for x in c["files"]]
    big = max(all_files, key=lambda x: x["size"], default=None)
    log(f"done: {len(collections)} collections, {len(all_files)} files, "
        f"{sum(x['size'] for x in all_files)} bytes"
        + (f", biggest {big['path']} ({big['size']} bytes)" if big else ""))


if __name__ == "__main__":
    main()
