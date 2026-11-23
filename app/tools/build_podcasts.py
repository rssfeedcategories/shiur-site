r"""One podcast feed per topic, for 24Six and podcast apps (Izzy, Nov 23 2026).

Reads app/catalog.json (the app's episode list, rebuilt every 15 min) and
writes app/podcasts/<slug>.xml, one RSS feed per topic:
  - every masechta of שיעור יומי - גמרא is its own feed
  - ספר משלי (מחזור א) and ספר משלי - מחזור ב' are separate feeds
  - every other category is one feed
plus app/podcasts/index.json and index.html (the list of feed links).
Audio stays on Libsyn (the same MP3 links). Covers: app/podcasts/covers/<slug>.jpg
(made once with tools/make_podcast_covers.py; a feed without one uses the default image).

Run: python3 tools/build_podcasts.py   (from the app/ folder)
"""
import json, os, re, hashlib, html
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

SITE = "https://rssfeedcategories.github.io/shiur-site/app/podcasts/"
OUT = "podcasts"
AUTHOR = "Rabbi Yitzchok Zalmen Gips - Birkas Avrohom"
GEMARA = "שיעור יומי - גמרא"

# English slugs for the file names (feed URLs). Unknown names get a short hash.
SLUGS = {
    "מסכת ברכות": "gemara-brachos", "מסכת שבת": "gemara-shabbos", "מסכת עירובין": "gemara-eruvin",
    "מסכת פסחים": "gemara-pesachim", "מסכת שקלים": "gemara-shekalim", "מסכת יומא": "gemara-yoma",
    "מסכת סוכה": "gemara-sukkah", "מסכת קידושין": "gemara-kiddushin", "מסכת ביצה": "gemara-beitzah",
    "מסכת ראש השנה": "gemara-rosh-hashanah", "מסכת תענית": "gemara-taanis", "מסכת מגילה": "gemara-megillah",
    "משנה ברורה": "mishna-berura", "ספר משלי": "mishlei-machzor-1", "ספר משלי - מחזור ב'": "mishlei-machzor-2",
    "חובות הלבבות": "chovos-halevavos", "שערי תשובה": "shaarei-teshuva", "שמירת הלשון": "shmiras-halashon",
    "חפץ חיים": "chofetz-chaim", "ספר הכוזרי": "kuzari", "ספר קהלת": "koheles",
    "כד הקמח לרבינו בחיי": "kad-hakemach", "מבחר הפנינים": "mivchar-hapeninim", "תפילה": "tefillah",
    "עניני שבת קודש": "inyanei-shabbos", 'ד"ת על הפרשה': "dvar-torah-parsha", 'הכנה ליו"ט': "hachana-yom-tov",
    "שיעור כללי": "shiur-klali", "שלום בית": "shalom-bayis", "general": "shonos",
}
# Feed titles (Hebrew), when they differ from the category name.
TITLES = {
    "ספר משלי": "ספר משלי - מחזור א'",
    "general": "שונות",
}


def slug_of(name):
    return SLUGS.get(name) or "topic-" + hashlib.md5(name.encode()).hexdigest()[:8]


def feed_key(e):
    """(name, title) of the topic feed an episode belongs to, or None."""
    c = e.get("c") or "general"
    if c == GEMARA:
        s = (e.get("s") or [None])[0]
        if not s:
            return None
        return s, f"{s} - שיעור יומי גמרא"
    return c, TITLES.get(c, c)


def secs(dur):
    try:
        p = [int(x) for x in str(dur).split(":")]
    except ValueError:
        return None
    t = 0
    for x in p:
        t = t * 60 + x
    return t


def rfc822(iso):
    try:
        d = datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        d = datetime(2020, 1, 1, tzinfo=timezone.utc)
    return format_datetime(d)


def main():
    cat = json.load(open("catalog.json", encoding="utf8"))
    default_img = cat.get("defaultImage")
    feeds = {}
    for e in cat["episodes"]:
        if not e.get("a"):
            continue                      # no audio (e.g. a notice post)
        k = feed_key(e)
        if not k:
            continue
        feeds.setdefault(k, []).append(e)

    os.makedirs(OUT, exist_ok=True)
    index = []
    keep = set()
    for (name, title), eps in sorted(feeds.items(), key=lambda kv: -len(kv[1])):
        slug = slug_of(name)
        keep.add(slug + ".xml")
        eps.sort(key=lambda e: e.get("d") or "", reverse=True)       # newest first
        cover = f"covers/{slug}.jpg"
        img = SITE + cover if os.path.exists(os.path.join(OUT, cover)) else default_img
        full_title = f"{title} | הרב יצחק זלמן גיפס שליט\"א"
        desc = f"שיעורי הרב יצחק זלמן גיפס שליט\"א - {title}. קהל ברכת אברהם."
        items = []
        for e in eps:
            dur = secs(e.get("dur"))
            body = e.get("ds") or e["t"]
            items.append(
                "<item>"
                f"<title>{escape(e['t'])}</title>"
                f"<guid isPermaLink=\"false\">{escape(e['id'])}</guid>"
                f"<pubDate>{rfc822(e.get('d') or '')}</pubDate>"
                f"<enclosure url=\"{escape(e['a'], {chr(34): '&quot;'})}\" length=\"0\" type=\"audio/mpeg\"/>"
                + (f"<link>{escape(e['l'])}</link>" if e.get("l") else "")
                + f"<description>{escape(body)}</description>"
                + f"<itunes:summary>{escape(body)}</itunes:summary>"
                + (f"<itunes:duration>{dur}</itunes:duration>" if dur else "")
                + "<itunes:explicit>false</itunes:explicit>"
                "</item>")
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" '
            'xmlns:atom="http://www.w3.org/2005/Atom">\n<channel>'
            f"<title>{escape(full_title)}</title>"
            f"<link>https://rssfeedcategories.github.io/shiur-site/v2/</link>"
            f"<atom:link href=\"{SITE}{slug}.xml\" rel=\"self\" type=\"application/rss+xml\"/>"
            f"<description>{escape(desc)}</description>"
            "<language>he</language>"
            f"<copyright>{escape(AUTHOR)}</copyright>"
            f"<itunes:author>{escape(AUTHOR)}</itunes:author>"
            f"<itunes:summary>{escape(desc)}</itunes:summary>"
            f"<itunes:owner><itunes:name>{escape(AUTHOR)}</itunes:name><itunes:email>birkasshiur@gmail.com</itunes:email></itunes:owner>"
            f"<itunes:image href=\"{escape(img)}\"/>"
            f"<image><url>{escape(img)}</url><title>{escape(full_title)}</title><link>https://rssfeedcategories.github.io/shiur-site/v2/</link></image>"
            '<itunes:category text="Religion &amp; Spirituality"><itunes:category text="Judaism"/></itunes:category>'
            "<itunes:explicit>false</itunes:explicit><itunes:type>episodic</itunes:type>\n"
            + "\n".join(items) + "\n</channel>\n</rss>\n")
        path = os.path.join(OUT, slug + ".xml")
        old = open(path, encoding="utf8").read() if os.path.exists(path) else None
        if old != xml:
            with open(path, "w", encoding="utf8") as f:
                f.write(xml)
        index.append({"name": name, "title": title, "slug": slug, "url": SITE + slug + ".xml",
                      "episodes": len(eps), "newest": (eps[0].get("d") or "")[:10], "cover": img})

    # feeds for topics that disappeared are left in place (never break a subscribed link)
    idx = json.dumps(index, ensure_ascii=False, indent=1)
    p = os.path.join(OUT, "index.json")
    if not os.path.exists(p) or open(p, encoding="utf8").read() != idx:
        open(p, "w", encoding="utf8").write(idx)
    rows = "\n".join(
        f'<tr><td><img src="{html.escape(f["cover"])}" style="width:56px;height:56px"></td>'
        f'<td dir="rtl"><b>{html.escape(f["title"])}</b><br><small>{f["episodes"]} שיעורים · {f["newest"]}</small></td>'
        f'<td><a href="{html.escape(f["url"])}">{html.escape(f["url"])}</a></td></tr>' for f in index)
    page = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>Podcast feeds</title><style>body{font-family:sans-serif;margin:16px}td{padding:6px;border-bottom:1px solid #ddd;vertical-align:middle}"
            "a{word-break:break-all}</style><h2>Rabbi Gips - podcast feeds by topic</h2><table>" + rows + "</table>")
    p = os.path.join(OUT, "index.html")
    if not os.path.exists(p) or open(p, encoding="utf8").read() != page:
        open(p, "w", encoding="utf8").write(page)
    print(f"podcasts: {len(index)} feeds, {sum(f['episodes'] for f in index)} episodes")


if __name__ == "__main__":
    main()
