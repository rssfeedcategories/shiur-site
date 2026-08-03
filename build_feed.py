#!/usr/bin/env python3
"""
Turns the Libsyn RSS feed into compact JSON files for the website.

Reads:  https://feeds.libsyn.com/381893/rss
Writes: data/index.json          - podcast info, category shelf, recent episodes
        data/cat/<slug>.json     - every episode in one category, grouped by series

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

FEED_URL = os.environ.get("FEED_URL", "https://feeds.libsyn.com/381893/rss")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
RECENT_COUNT = 24

NS = {
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
    "content": "http://purl.org/rss/1.0/modules/content/",
}

# Matches: "מסכת יומא - שיעור #67- דף נ"ה"  /  "משנה ברורה - חלק ד- שיעור #152 - סימן תכ"ח"
SHIUR_RE = re.compile(
    r"^(?P<series>.*?)[\s\-\u2013\u2014\u05be]*"
    r"שיעור\s*[#\u2116]?\s*(?P<num>\d+)"
    r"\s*[\-\u2013\u2014\u05be]?\s*(?P<ref>.*)$"
)

TRIM = " -\u2013\u2014\u05be\u00a0\t"


def fetch(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": "birkas-avrohom-site-builder/1.0"}
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def slug(name):
    """Stable ASCII slug for a Hebrew category name."""
    return hashlib.md5(name.strip().encode("utf-8")).hexdigest()[:10]


def parse_duration(raw):
    """itunes:duration is either seconds, MM:SS, or HH:MM:SS."""
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    if ":" in raw:
        parts = raw.split(":")
        try:
            parts = [int(p) for p in parts]
        except ValueError:
            return None
        secs = 0
        for p in parts:
            secs = secs * 60 + p
        return secs
    try:
        return int(float(raw))
    except ValueError:
        return None


def parse_date(raw):
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def text(el, path, ns=None):
    found = el.find(path, ns) if ns else el.find(path)
    if found is None or found.text is None:
        return ""
    return found.text.strip()


def categories_for(item):
    """Libsyn puts the category in <itunes:category>, <category>, or keywords."""
    out = []
    for el in item.findall("category"):
        if el.text and el.text.strip():
            out.append(el.text.strip())
    for el in item.findall("itunes:category", NS):
        val = el.get("text") or (el.text or "")
        if val.strip():
            out.append(val.strip())
    if not out:
        kw = text(item, "itunes:keywords", NS)
        if kw:
            out = [k.strip() for k in kw.split(",") if k.strip()][:1]
    return out or ["general"]


def parse_title(title):
    """Split a title into series name, shiur number, and source reference."""
    m = SHIUR_RE.match(title)
    if not m:
        return title.strip(TRIM), None, ""
    series = m.group("series").strip(TRIM)
    num = int(m.group("num"))
    ref = m.group("ref").strip(TRIM)
    if not series:
        series = title.strip(TRIM)
    return series, num, ref


def build():
    print(f"Fetching {FEED_URL}")
    root = ET.fromstring(fetch(FEED_URL))
    channel = root.find("channel")
    if channel is None:
        sys.exit("No <channel> in feed - is the feed URL right?")

    image = ""
    img_el = channel.find("itunes:image", NS)
    if img_el is not None:
        image = img_el.get("href", "")
    if not image:
        image = text(channel, "image/url")

    podcast = {
        "title": text(channel, "title") or "Rabbi Gips Podcasts",
        "description": text(channel, "description"),
        "image": image,
        "link": text(channel, "link"),
    }

    episodes = []
    skipped = 0
    for item in channel.findall("item"):
        enc = item.find("enclosure")
        url = enc.get("url") if enc is not None else ""
        if not url:
            skipped += 1
            continue

        title = text(item, "title")
        dt = parse_date(text(item, "pubDate"))
        series, num, ref = parse_title(title)
        cat = categories_for(item)[0]

        guid = text(item, "guid") or url
        episodes.append(
            {
                "id": hashlib.md5(guid.encode("utf-8")).hexdigest()[:12],
                "t": title,
                "d": dt.strftime("%Y-%m-%d") if dt else "",
                "ts": int(dt.timestamp()) if dt else 0,
                "u": url,
                "s": parse_duration(text(item, "itunes:duration", NS)),
                "c": slug(cat),
                "ser": series,
                "n": num,
                "ref": ref,
                "l": text(item, "link"),
            }
        )

    if not episodes:
        sys.exit("Feed parsed but no episodes with audio were found.")

    episodes.sort(key=lambda e: e["ts"], reverse=True)
    print(f"{len(episodes)} episodes ({skipped} skipped - no audio)")

    # Group into categories
    cat_names = {}
    for item in channel.findall("item"):
        name = categories_for(item)[0]
        cat_names[slug(name)] = name

    by_cat = {}
    for ep in episodes:
        by_cat.setdefault(ep["c"], []).append(ep)

    os.makedirs(os.path.join(OUT_DIR, "cat"), exist_ok=True)

    shelf = []
    for cslug, eps in by_cat.items():
        # Group by series, order each series by shiur number when we have one
        series_map = {}
        for ep in eps:
            series_map.setdefault(ep["ser"], []).append(ep)

        series_out = []
        for sname, seps in series_map.items():
            numbered = [e for e in seps if e["n"] is not None]
            if numbered and len(numbered) >= len(seps) / 2:
                seps.sort(key=lambda e: (e["n"] is None, e["n"] or 0))
                ordered = True
            else:
                seps.sort(key=lambda e: e["ts"])
                ordered = False
            series_out.append(
                {
                    "name": sname,
                    "ordered": ordered,
                    "count": len(seps),
                    "latest": max(e["d"] for e in seps if e["d"]) if any(e["d"] for e in seps) else "",
                    "episodes": seps,
                }
            )

        series_out.sort(key=lambda s: s["latest"], reverse=True)

        with open(os.path.join(OUT_DIR, "cat", f"{cslug}.json"), "w", encoding="utf-8") as f:
            json.dump(
                {"slug": cslug, "name": cat_names.get(cslug, "?"), "series": series_out},
                f,
                ensure_ascii=False,
                separators=(",", ":"),
            )

        shelf.append(
            {
                "slug": cslug,
                "name": cat_names.get(cslug, "?"),
                "count": len(eps),
                "seriesCount": len(series_out),
                "latest": max(e["d"] for e in eps if e["d"]) if any(e["d"] for e in eps) else "",
            }
        )

    shelf.sort(key=lambda c: c["latest"], reverse=True)

    # Lightweight search index: every episode, minimal fields
    search = [
        {"i": e["id"], "t": e["t"], "c": e["c"], "d": e["d"], "u": e["u"],
         "s": e["s"], "ser": e["ser"], "n": e["n"]}
        for e in episodes
    ]

    index = {
        "podcast": podcast,
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "episodeCount": len(episodes),
        "categories": shelf,
        "recent": episodes[:RECENT_COUNT],
    }

    with open(os.path.join(OUT_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(OUT_DIR, "search.json"), "w", encoding="utf-8") as f:
        json.dump(search, f, ensure_ascii=False, separators=(",", ":"))

    # Flag suspicious publish dates (the stray 2001 entry)
    odd = [e for e in episodes if e["ts"] and e["d"] < "2020-01-01"]
    if odd:
        print(f"\nHeads up - {len(odd)} episode(s) have a publish date before 2020:")
        for e in odd[:10]:
            print(f"  {e['d']}  {e['t'][:60]}")
        print("  Fix the date in Libsyn and they will move into place on the next build.")

    print(f"\nWrote {len(shelf)} categories to {OUT_DIR}")


if __name__ == "__main__":
    build()
