#!/usr/bin/env python3
"""
Turns the Libsyn RSS feed into compact JSON files for the website.

The main Libsyn feed carries no per-episode categories, so categories come from
categories.tsv — a filter-word list you can edit directly on GitHub. Each
episode title is checked against every filter word; the LONGEST match wins, so
a short word like דף can't steal a title that belongs somewhere more specific.

Every run prints a report: how many episodes landed in each category, which
titles matched more than one filter, and which fell through to the catch-all.

Run locally:  python3 build_feed.py
Runs automatically via .github/workflows/build.yml
"""

import hashlib
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

HERE = os.path.dirname(os.path.abspath(__file__))
FEED_URL = os.environ.get("FEED_URL", "https://feeds.libsyn.com/381893/rss")
CATS_FILE = os.path.join(HERE, "categories.tsv")
OUT_DIR = os.path.join(HERE, "data")
RECENT_COUNT = 24

NS = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
DASH = r"\-\u2013\u2014\u05be"
TRIM = " -\u2013\u2014\u05be\u00a0\t"

# "<series> - שיעור #<n> - <reference>"
SHIUR_RE = re.compile(
    rf"^(?P<series>.*?)[\s{DASH}]*"
    rf"שיעור\s*[#\u2116]?\s*(?P<num>\d+)"
    rf"\s*[{DASH}]?\s*(?P<ref>.*)$"
)
# Section markers used to split a big category into parts
def section_re(keyword):
    """Captures the name after a keyword, stopping at a dash, שיעור, # or end."""
    return re.compile(
        rf"{keyword}\s+(.+?)(?=\s*[{DASH}]|\s*שיעור|\s*#|$)"
    )

SECTION_RES = {k: section_re(k) for k in ("מסכת", "חלק", "הלכות", "שער", "פרק")}

# A section needs at least this many episodes to exist on its own
MIN_PART = 3
# Label for episodes in a split category that name no section
LEFTOVER = "שיעורים נוספים"
# Strip geresh / gershayim so "חלק ד" and "חלק ד'" are the same section
GERESH = str.maketrans("", "", "'\"\u05f3\u05f4\u2019\u201d")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "birkas-avrohom-builder/3.0"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()


def slug(name):
    return hashlib.md5(name.strip().encode("utf-8")).hexdigest()[:10]


def load_categories():
    """Reads categories.tsv -> (list of (name, [filters]), catch-all name)."""
    if not os.path.exists(CATS_FILE):
        sys.exit(f"Missing {CATS_FILE} — the category list must sit next to this script.")
    cats, fallback = [], None
    with open(CATS_FILE, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split("\t")
            name = parts[0].strip()
            filters = [w.strip() for w in (parts[1] if len(parts) > 1 else "").split("|") if w.strip()]
            if not name:
                continue
            split = parts[2].strip() if len(parts) > 2 else ""
            order = parts[3].strip() if len(parts) > 3 else ""
            if filters:
                cats.append((name, filters, split, order))
            elif fallback is None:
                fallback = name
    if fallback is None:
        fallback = "general"
    # Longest filter word first, so the most specific match wins
    cats.sort(key=lambda c: -max(len(w) for w in c[1]))
    splits = {c[0]: c[2] for c in cats}
    orders = {c[0]: c[3] for c in cats}
    return cats, fallback, splits, orders


def parse_duration(raw):
    if not raw:
        return None
    raw = raw.strip()
    if ":" in raw:
        try:
            secs = 0
            for p in raw.split(":"):
                secs = secs * 60 + int(p)
            return secs
        except ValueError:
            return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def parse_date(raw):
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except Exception:
        return None


def text(el, path, ns=None):
    f = el.find(path, ns) if ns else el.find(path)
    return f.text.strip() if f is not None and f.text else ""


def parse_title(title):
    """title -> (series, shiur number or None, source reference)"""
    m = SHIUR_RE.match(title)
    if not m:
        return title.strip(TRIM), None, ""
    series = m.group("series").strip(TRIM) or title.strip(TRIM)
    return series, int(m.group("num")), m.group("ref").strip(TRIM)


def categorise(title, cats, fallback):
    """Longest matching filter word wins. Returns (category, all matches)."""
    hits = [(name, w) for name, filters, _, _ in cats for w in filters if w in title]
    if not hits:
        return fallback, []
    best = max(hits, key=lambda h: len(h[1]))
    return best[0], hits


def section_for(title, split_by):
    """Every section name the title mentions, in the order they appear.

    SPLIT BY may list several keywords separated by | so a category using
    both הלכות and חלק works. Returning every candidate lets the caller pick
    the one that names a section that actually exists, which rescues titles
    like "מסכת חדשה - מסכת שבת - שיעור #1".
    """
    found = []
    for keyword in [k.strip() for k in split_by.split("|") if k.strip()]:
        rx = SECTION_RES.get(keyword)
        if rx is None:
            rx = SECTION_RES[keyword] = section_re(keyword)
        for m in rx.finditer(title):
            name = m.group(1).strip(TRIM).translate(GERESH)
            if name:
                found.append(f"{keyword} {name}")
    return found


def build():
    cats, fallback, splits, orders = load_categories()
    print(f"Loaded {len(cats)} categories + catch-all “{fallback}” from categories.tsv")
    print(f"Fetching {FEED_URL}")

    root = ET.fromstring(fetch(FEED_URL))
    channel = root.find("channel")
    if channel is None:
        sys.exit("No <channel> in the feed — check the feed URL.")

    img_el = channel.find("itunes:image", NS)
    podcast = {
        "title": text(channel, "title") or "Rabbi Gips Podcasts",
        "description": text(channel, "description"),
        "image": (img_el.get("href", "") if img_el is not None else "") or text(channel, "image/url"),
        "link": text(channel, "link"),
    }

    episodes, skipped, unnumbered, ambiguous = [], 0, [], []
    for item in channel.findall("item"):
        enc = item.find("enclosure")
        url = enc.get("url") if enc is not None else ""
        if not url:
            skipped += 1
            continue

        title = text(item, "title")
        dt = parse_date(text(item, "pubDate"))
        series, num, ref = parse_title(title)
        cat, hits = categorise(title, cats, fallback)

        if len({h[0] for h in hits}) > 1:
            ambiguous.append((title, cat, sorted({h[0] for h in hits})))
        if num is None:
            unnumbered.append(title)

        episodes.append({
            "id": hashlib.md5((text(item, "guid") or url).encode("utf-8")).hexdigest()[:12],
            "t": title,
            "d": dt.strftime("%Y-%m-%d") if dt else "",
            "ts": int(dt.timestamp()) if dt else 0,
            "u": url,
            "s": parse_duration(text(item, "itunes:duration", NS)),
            "c": slug(cat),
            "cat": cat,
            "secs": section_for(title, splits.get(cat, "")),
            "ser": series,
            "n": num,
        })

    if not episodes:
        sys.exit("Feed parsed but no episodes with audio were found.")

    episodes.sort(key=lambda e: e["ts"], reverse=True)

    by_cat = {}
    for e in episodes:
        by_cat.setdefault(e["cat"], []).append(e)

    cat_dir = os.path.join(OUT_DIR, "cat")
    os.makedirs(cat_dir, exist_ok=True)
    for f in os.listdir(cat_dir):
        os.remove(os.path.join(cat_dir, f))

    shelf, parts_report, leftovers, fellback = [], {}, {}, []
    for cat_name, eps in by_cat.items():
        # Pass 1 — how often is each candidate the title's first choice?
        tally = {}
        for e in eps:
            if e["secs"]:
                tally[e["secs"][0]] = tally.get(e["secs"][0], 0) + 1
        real = {k for k, v in tally.items() if v >= MIN_PART}

        # Pass 2 — prefer a candidate that names a section that really exists
        sections = {}
        for e in eps:
            pick = next((c for c in e["secs"] if c in real), None) \
                   or (e["secs"][0] if e["secs"] else None)
            e["sec"] = pick
            sections.setdefault(pick or cat_name, []).append(e)
        # Anything too small to be a real section rejoins the main list
        for sname in [k for k, v in sections.items() if k != cat_name and len(v) < MIN_PART]:
            sections.setdefault(cat_name, []).extend(sections.pop(sname))
        # If real sections exist, the unsorted remainder needs its own label
        if len(sections) > 1 and cat_name in sections:
            leftovers[cat_name] = [x["t"] for x in sections[cat_name]]
            sections[LEFTOVER] = sections.pop(cat_name)

        want_numbers = orders.get(cat_name, "") == "מספר"
        series_out = []
        for sname, seps in sections.items():
            nums = [x["n"] for x in seps if x["n"] is not None]
            usable = (bool(nums) and len(nums) == len(set(nums))
                      and len(nums) >= len(seps) / 2)
            ordered = want_numbers and usable
            if want_numbers and not usable:
                fellback.append((cat_name, sname, len(seps)))
            if ordered:
                seps.sort(key=lambda x: (x["n"] is None, x["n"] or 0))
            else:
                seps.sort(key=lambda x: x["ts"])
            dates = [x["d"] for x in seps if x["d"]]
            series_out.append({
                "name": sname,
                "ordered": ordered,
                "count": len(seps),
                "latest": max(dates) if dates else "",
                "episodes": [{k: v for k, v in x.items() if k not in ("ts", "cat", "sec", "secs")} for x in seps],
            })
        series_out.sort(key=lambda s: s["latest"], reverse=True)
        parts_report[cat_name] = [(s["name"], s["count"]) for s in series_out]

        cslug = slug(cat_name)
        with open(os.path.join(cat_dir, f"{cslug}.json"), "w", encoding="utf-8") as f:
            json.dump({"slug": cslug, "name": cat_name, "series": series_out},
                      f, ensure_ascii=False, separators=(",", ":"))

        dates = [e["d"] for e in eps if e["d"]]
        shelf.append({
            "slug": cslug, "name": cat_name, "count": len(eps),
            "seriesCount": len(series_out), "latest": max(dates) if dates else "",
        })

    shelf.sort(key=lambda c: c["latest"], reverse=True)

    slim = [{k: v for k, v in e.items() if k not in ("ts", "cat", "sec", "secs")} for e in episodes]

    with open(os.path.join(OUT_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump({
            "podcast": podcast,
            "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "episodeCount": len(episodes),
            "categories": shelf,
            "recent": slim[:RECENT_COUNT],
        }, f, ensure_ascii=False, separators=(",", ":"))

    with open(os.path.join(OUT_DIR, "search.json"), "w", encoding="utf-8") as f:
        json.dump([{"i": e["id"], "t": e["t"], "c": e["c"], "d": e["d"],
                    "u": e["u"], "s": e["s"], "ser": e["ser"], "n": e["n"]}
                   for e in slim], f, ensure_ascii=False, separators=(",", ":"))

    # ---------------- report ----------------
    print(f"\n{len(episodes)} episodes ({skipped} skipped — no audio)\n")
    print(f"{'CATEGORY':<26}{'SHIURIM':>9}{'PARTS':>7}   LAST")
    print("-" * 60)
    for c in shelf:
        print(f"{c['name']:<26}{c['count']:>9}{c['seriesCount']:>7}   {c['latest']}")

    print("\nShiur numbering per category:")
    for c in shelf:
        eps = by_cat[c["name"]]
        nums = [e["n"] for e in eps if e["n"] is not None]
        blank = len(eps) - len(nums)
        if not nums:
            print(f"  {c['name']:<26} no shiur numbers — sorted by date")
            continue
        dupes = len(nums) - len(set(nums))
        note = f"repeats {dupes}x — numbering restarts" if dupes else "continuous, no repeats"
        extra = f", {blank} unnumbered" if blank else ""
        print(f"  {c['name']:<26} #{min(nums)}–#{max(nums)}  ({note}{extra})")

    multi = [c for c in shelf if c["seriesCount"] > 1]
    if multi:
        print("\nHow the split categories were divided:")
        for c in multi:
            print(f"\n  {c['name']}  ({c['count']} shiurim, {c['seriesCount']} parts)")
            for pname, pcount in parts_report[c["name"]]:
                print(f"      {pcount:>5}  {pname}")

    if fellback:
        print("\nAsked to order by number, but the numbers repeat — using date order:")
        for cat_name, sname, cnt in fellback:
            label = f"{cat_name} / {sname}" if sname != cat_name else cat_name
            print(f"  {label}  ({cnt} shiurim)")

    if leftovers:
        print("\nEpisodes in a split category that name no section:")
        for cat_name, titles in leftovers.items():
            print(f"\n  {cat_name} — {len(titles)} episode(s) under “{LEFTOVER}”")
            for t in titles[:10]:
                print("      " + t[:70])
            if len(titles) > 10:
                print(f"      … and {len(titles) - 10} more")

    fell = next((c["count"] for c in shelf if c["name"] == fallback), 0)
    if fell:
        print(f"\n{fell} episode(s) matched no filter word and went to “{fallback}”:")
        for e in [x for x in episodes if x["cat"] == fallback][:15]:
            print("  " + e["t"][:72])
        if fell > 15:
            print(f"  … and {fell - 15} more")

    if ambiguous:
        print(f"\n{len(ambiguous)} title(s) matched more than one category — longest filter won:")
        for t, chosen, allc in ambiguous[:15]:
            print(f"  {t[:52]}\n      -> {chosen}   (also matched: {', '.join(x for x in allc if x != chosen)})")
        if len(ambiguous) > 15:
            print(f"  … and {len(ambiguous) - 15} more")

    if unnumbered:
        print(f"\n{len(unnumbered)} episode(s) have no shiur number — these sort by date instead.")

    odd = [e for e in episodes if e["d"] and e["d"] < "2020-01-01"]
    if odd:
        print(f"\n{len(odd)} episode(s) dated before 2020 — probably wrong in Libsyn:")
        for e in odd[:10]:
            print(f"  {e['d']}  {e['t'][:60]}")

    print(f"\nWrote {OUT_DIR}")


if __name__ == "__main__":
    build()
