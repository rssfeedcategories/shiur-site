"""Build the app's master episode list (catalog).

Inputs
  catalog/seed_from_server_db.json   every episode ever seen (3,725, from the old server's DB)
  Libsyn feed (optional, --feed)     adds new episodes and picks up edits; NOTHING is deleted
Output
  assets/catalog.json                bundled into the app

All category / section / ordering rules Izzy decided live here, so they can
change without a new app version once the catalog is hosted.
"""
import json
import pathlib, re, sys, datetime, email.utils, urllib.request, argparse, collections
import xml.etree.ElementTree as ET

FEED_URL = "https://rss.libsyn.com/shows/381893/destinations/3140111.xml"
DEFAULT_IMG = "https://static.libsyn.com/p/assets/b/0/9/5/b0954f30b6f06525e55e3c100dce7605/BA_-_Shuir_App_Profile_1400x140.jpg"

# ---------------------------------------------------------------- text utils
GERESH = re.compile("[׳״'\"`‘’“”]")
def norm(s):
    s = re.sub(r"[֑-ׇ]", "", s or "")
    s = GERESH.sub("", s)
    return re.sub(r"\s+", " ", s).strip()

LET = dict(zip("אבגדהוזחטיכךלמםנןסעפףצץקרשת",
               [1,2,3,4,5,6,7,8,9,10,20,20,30,40,40,50,50,60,70,80,80,90,90,100,200,300,400]))
def heb_num(w):
    w = re.sub("[^\u05D0-\u05EA]", "", w or "")
    if not w or len(w) > 5 or any(c not in LET for c in w):
        return None
    return sum(LET[c] for c in w)

ORD = {"ראשון":1,"ראשונה":1,"שני":2,"שניה":2,"שנייה":2,"שלישי":3,"שלישית":3,"רביעי":4,"רביעית":4,
       "חמישי":5,"חמישית":5,"שישי":6,"ששי":6,"שביעי":7,"שמיני":8,"תשיעי":9,"עשירי":10}
HEB_LETTERS = "אבגדהוזחטיכלמנסעפצקרשת"
def heb_word(n):  # 1..499 -> letters (no geresh), used for canonical names
    out = ""
    for v, ch in [(400,"ת"),(300,"ש"),(200,"ר"),(100,"ק"),(90,"צ"),(80,"פ"),(70,"ע"),(60,"ס"),(50,"נ"),
                  (40,"מ"),(30,"ל"),(20,"כ"),(10,"י"),(9,"ט"),(8,"ח"),(7,"ז"),(6,"ו"),(5,"ה"),(4,"ד"),(3,"ג"),(2,"ב"),(1,"א")]:
        while n >= v:
            if n in (15, 16):
                return out + ("טו" if n == 15 else "טז")
            out += ch; n -= v
    return out
def heb_display(n):  # with geresh/gershayim
    w = heb_word(n)
    return w + "'" if len(w) == 1 else w[:-1] + '"' + w[-1]

# ---------------------------------------------------------------- categories
CATEGORY_ORDER = [
    "שיעור יומי - גמרא", "משנה ברורה", "ספר משלי", "חובות הלבבות", "שערי תשובה",
    "שמירת הלשון", "חפץ חיים", "ספר הכוזרי", "ספר קהלת", "כד הקמח לרבינו בחיי",
    "מבחר הפנינים", "תפילה", "עניני שבת קודש", 'ד"ת על הפרשה', 'הכנה ליו"ט',
    "שיעור כללי", "שלום בית", "general",
]
LABELS = {"general": "שונות"}
CAT_ALIAS = {norm(c): c for c in CATEGORY_ORDER}
CAT_ALIAS.update({"משלי": "ספר משלי", "miscellaneous": "general", "כד הקמח": "כד הקמח לרבינו בחיי",
                  "דת על הפרשה": 'ד"ת על הפרשה', "גמרא": "שיעור יומי - גמרא"})
# Title prefixes for untagged episodes (checked in order).
TITLE_RULES = [
    ("משנה ברורה", "משנה ברורה"), ("דת על הפרשה", 'ד"ת על הפרשה'), ("הכנה ליוט", 'הכנה ליו"ט'),
    ("שיעור כללי", "שיעור כללי"), ("מסכת ", "שיעור יומי - גמרא"), ("ספר משלי", "ספר משלי"),
    ("חובות הלבבות", "חובות הלבבות"), ("שערי תשובה", "שערי תשובה"), ("שמירת הלשון", "שמירת הלשון"),
    ("חפץ חיים", "חפץ חיים"), ("ספר הכוזרי", "ספר הכוזרי"), ("ספר קהלת", "ספר קהלת"),
    ("כד הקמח", "כד הקמח לרבינו בחיי"), ("מבחר הפנינים", "מבחר הפנינים"),
    ("עניני שבת", "עניני שבת קודש"), ("שלום בית", "שלום בית"), ("תפילה", "תפילה"),
]
SHAS = ["ברכות","שבת","עירובין","פסחים","שקלים","יומא","סוכה","ביצה","ראש השנה","תענית","מגילה","מועד קטן",
        "חגיגה","יבמות","כתובות","נדרים","נזיר","סוטה","גיטין","קידושין","בבא קמא","בבא מציעא","בבא בתרא",
        "סנהדרין","מכות","שבועות","עבודה זרה","הוריות","זבחים","מנחות","חולין","בכורות","ערכין","תמורה",
        "כריתות","מעילה","תמיד","נדה"]
CHOVOS = ["הקדמה","שער היחוד","שער הבחינה","שער עבודת האלהים","שער הבטחון","שער יחוד המעשה","שער הכניעה",
          "שער התשובה","שער חשבון הנפש","שער הפרישות","שער אהבת ה'"]
CHOVOS_ALIAS = {"שער הביטחון":"שער הבטחון","שער עבודת האלקים":"שער עבודת האלהים","שער עבודת האלוקים":"שער עבודת האלהים",
                "שער אהבת השם":"שער אהבת ה'","שער אהבת ה":"שער אהבת ה'","שער יחוד ה":"שער היחוד"}
SHAAREI_TESHUVA = ["שער א'","שער ב'","שער ג'","שער ד'","ספר היראה","אגרת התשובה","יסוד התשובה"]
SHMIRAS = ["הקדמה","שער הזכירה","שער התבונה","שער התורה","חלק שני"]
CHAFETZ = ["הלכות לשון הרע","הלכות רכילות"]
HACHANA = ["אלול","ראש השנה",'עשי"ת',"יום כיפור","סוכות","שמחת תורה","חנוכה","פורים","פסח","ספירת העומר","שבועות","בין המצרים"]
MB_RANGES = [(1,127),(128,241),(242,344),(345,428),(429,529),(530,697)]  # חלק א..ו by סימן

def numbered(prefix, lo, hi):
    return [f"{prefix} {heb_display(i)}" for i in range(lo, hi + 1)]

# Fixed section lists (sefer order). None = free sections (handled per category).
FIXED = {
    "שיעור יומי - גמרא": ["מסכת " + m for m in SHAS],
    "משנה ברורה": numbered("חלק", 1, 6),
    "ספר משלי": numbered("פרק", 1, 31),
    "ספר קהלת": numbered("פרק", 1, 12),
    "ספר הכוזרי": ["מאמר ראשון","מאמר שני","מאמר שלישי","מאמר רביעי","מאמר חמישי"],
    "חובות הלבבות": CHOVOS,
    "שערי תשובה": SHAAREI_TESHUVA,
    "שמירת הלשון": SHMIRAS,
    "חפץ חיים": CHAFETZ,
}
FREE = {"כד הקמח לרבינו בחיי", 'הכנה ליו"ט', "שיעור כללי"}
MULTI = {"כד הקמח לרבינו בחיי", 'ד"ת על הפרשה'}  # may sit in several sections

PARSHA_CAT = 'ד"ת על הפרשה'
PARSHIYOS = ["בראשית","נח","לך לך","וירא","חיי שרה","תולדות","ויצא","וישלח","וישב","מקץ","ויגש","ויחי",
             "שמות","וארא","בא","בשלח","יתרו","משפטים","תרומה","תצוה","כי תשא","ויקהל","פקודי",
             "ויקרא","צו","שמיני","תזריע","מצורע","אחרי מות","קדושים","אמור","בהר","בחקתי",
             "במדבר","נשא","בהעלתך","שלח","קרח","חקת","בלק","פינחס","מטות","מסעי",
             "דברים","ואתחנן","עקב","ראה","שופטים","כי תצא","כי תבא","נצבים","וילך","האזינו","וזאת הברכה"]
PARSHA_ALIAS = {"טהרה": "מצורע", "אחרי": "אחרי מות", "שלח לך": "שלח"}

def _pkey(w):
    """Spelling-insensitive key: drop ו/י except as a word's first letter."""
    out = []
    for tok in norm(w).split(" "):
        out.append(tok[:1] + tok[1:].replace("ו", "").replace("י", ""))
    return " ".join(out)

_PKEYS = {_pkey(p): p for p in PARSHIYOS}
_PKEYS.update({_pkey(a): t for a, t in PARSHA_ALIAS.items()})

def parshiyos_from_title(title):
    t = norm(title)
    if "הפרשה -" in t:
        t = t.split("הפרשה -", 1)[1]
    t = t.strip()
    if t.startswith("פרשת "):
        t = t[5:]
    seg = t.split(" - ")[0]
    toks = [x for x in re.split(r"[\s\-]+", seg) if x]
    found, i = [], 0
    while i < len(toks):
        two = _pkey(" ".join(toks[i:i + 2])) if i + 1 < len(toks) else None
        if two and two in _PKEYS:
            p = _PKEYS[two]; i += 2
        elif _pkey(toks[i]) in _PKEYS:
            p = _PKEYS[_pkey(toks[i])]; i += 1
        else:
            i += 1; continue
        if p not in found:
            found.append(p)
    return found

def match_fixed(cat, cand):
    """Map a tag or title fragment to the canonical fixed section name, or None."""
    lst = FIXED[cat]; n = norm(cand)
    if cat == "חובות הלבבות":
        n = norm(CHOVOS_ALIAS.get(n, n))
    for s in lst:
        if norm(s) == n:
            return s
    # numbered sections: "<prefix> <numeral/ordinal>"
    m = re.match(r"^(פרק|חלק|מאמר|שער)\s+(\S+)$", n)
    if m:
        v = ORD.get(m.group(2)) or heb_num(m.group(2))
        if v:
            for s in lst:
                mm = re.match(r"^(\S+)\s+(\S+)$", norm(s))
                if mm and mm.group(1) == m.group(1) and (ORD.get(mm.group(2)) or heb_num(mm.group(2))) == v:
                    return s
    return None

def section_from_title(cat, title):
    t = norm(title)
    if cat == "שיעור יומי - גמרא":
        for m in sorted(SHAS, key=len, reverse=True):
            if "מסכת " + m in t:
                return "מסכת " + m
    if cat == "משנה ברורה":
        m = re.search(r"חלק\s+(\S+)", t)
        if m and heb_num(m.group(1)) and 1 <= heb_num(m.group(1)) <= 6:
            return FIXED[cat][heb_num(m.group(1)) - 1]
        m = re.search(r"סימן\s+(\S+)", t)
        if m and heb_num(m.group(1)):
            v = heb_num(m.group(1))
            for i, (a, b) in enumerate(MB_RANGES):
                if a <= v <= b:
                    return FIXED[cat][i]
    if cat in ("ספר משלי", "ספר קהלת"):
        m = re.search(r"פרק\s+(\S+)", t)
        if m:
            return match_fixed(cat, "פרק " + m.group(1))
    if cat == "ספר הכוזרי":
        m = re.search(r"מאמר\s+(\S+)", t)
        if m:
            return match_fixed(cat, "מאמר " + m.group(1))
    if cat in ("חובות הלבבות", "שמירת הלשון", "שערי תשובה", "חפץ חיים"):
        for s in FIXED[cat]:
            if norm(s) in t:
                return s
        if cat == "חובות הלבבות":
            for a, s in CHOVOS_ALIAS.items():
                if norm(a) in t:
                    return s
        m = re.search(r"שער\s+(\S+)", t)
        if m and cat == "שערי תשובה":
            return match_fixed(cat, "שער " + m.group(1))
    return None

# ---------------------------------------------------------------- third level (דף / סימן / פסוק ...)
# Source-page maps for sefarim printed as HebrewBooks books (catalog/sources/*.json)
MB_SOURCES = {}
for _f in sorted((pathlib.Path(__file__).resolve().parent.parent / "catalog" / "sources").glob("mb_*.json")):
    _d = json.loads(_f.read_text(encoding="utf-8"))
    MB_SOURCES[_d["part"]] = _d

LEVEL3 = {
    "שיעור יומי - גמרא": "דף", "משנה ברורה": "סימן", "ספר משלי": "פסוק", "ספר קהלת": "פסוק",
    "חובות הלבבות": "פרק", "שמירת הלשון": "פרק", "שערי תשובה": "אות", "חפץ חיים": "כלל",
}

def strict_num(tok):
    """A real Hebrew numeral (descending letters, one tens, one unit), else None.
    Rejects ordinary words such as חזרה / שבת."""
    w = re.sub("[^\u05D0-\u05EA]", "", tok or "")
    if not w or len(w) > 5:
        return None
    # hundreds + טו/טז (e.g. קט"ו = 115, רט"ז = 216)
    if w.endswith(("טו", "טז")):
        head = w[:-2]
        if all(c in "קרשת" for c in head) and all(
                LET[a] >= LET[b] for a, b in zip(head, head[1:])):
            return sum(LET[c] for c in head) + (15 if w.endswith("טו") else 16)
    vals = []
    for c in w:
        if c not in LET or c in "ךםןףץ":
            return None
        vals.append(LET[c])
    if any(b > a for a, b in zip(vals, vals[1:])):
        return None
    if sum(1 for v in vals if 10 <= v <= 90) > 1 or sum(1 for v in vals if v < 10) > 1:
        return None
    return sum(vals)

AMUD = {"עא", "עב"}

def loose_num(tok):
    """Hebrew letters in any order summed (רח"צ -> 298). Only used right after
    the word סימן, where a typo'd numeral is the only thing that can appear."""
    w = re.sub("[^\u05D0-\u05EA]", "", tok or "")
    if not 1 <= len(w) <= 4 or any(c not in LET or c in "ךםןףץ" for c in w):
        return None
    n = sum(LET[c] for c in w)
    return n if 1 <= n <= 697 else None

def level3_numbers(title, kw):
    """All numbers that follow `kw` in the title, with ranges (X-Y) expanded."""
    t = norm(title).replace(".", " ").replace(":", " ").replace(",", " ")
    if kw == "פסוק":  # stay inside the first פרק mentioned
        parts = t.split("פרק")
        t = "פרק".join(parts[:2]) if len(parts) > 2 else t
    t = t.replace("-", " - ")
    toks = t.split()
    nums = set()
    i = 0
    while i < len(toks):
        if toks[i] != kw:
            i += 1; continue
        i += 1
        last, pending_range = None, False
        while i < len(toks):
            tk = toks[i]
            if tk in AMUD and kw == "דף":
                i += 1; continue
            if tk in AMUD:  # סימן ע"א / ע"ב are simanim 71 / 72, not amudim
                tk = "עא" if tk == "עא" else "עב"
            if tk == "-":
                pending_range = last is not None; i += 1; continue
            if tk == kw:  # "סימן X - סימן Y"
                i += 1; continue
            n = strict_num(tk)
            if n is None and kw == "סימן" and last is None:
                n = loose_num(tk)  # letters typed out of order, e.g. רח"צ = רצ"ח (298)
            if n is None:
                break
            if pending_range and last is not None and 0 < n - last <= 40:
                nums.update(range(last, n + 1))
            else:
                nums.add(n)
            last, pending_range = n, False
            i += 1
    return sorted(nums)

def gemara_amudim(title):
    """Amudim a Gemara shiur covers, e.g. "דף ה' ע"ב - ו' ע"א" -> ["5b","6a"].
    "." / ":" after the daf also mark amud a / b. No amud given -> both."""
    raw = re.sub(r"[\u0591-\u05C7]", "", title or "")
    m = re.search(r"דף\s+(.*)", raw)
    if not m:
        return []
    t = m.group(1)
    t = t.replace("ע\"א", " עא ").replace("ע\"ב", " עב ").replace("ע׳׳א", " עא ").replace("ע׳׳ב", " עב ")
    t = re.sub(r"([\u05D0-\u05EA\"'׳״]+)\.", r"\1 עא ", t)
    t = re.sub(r"([\u05D0-\u05EA\"'׳״]+):", r"\1 עב ", t)
    t = t.replace("-", " - ")
    marks = []  # sequence of (daf, amud|None)
    daf, saw_range = None, False
    toks = t.split()
    for k, tok in enumerate(toks):
        nxt = toks[k + 1] if k + 1 < len(toks) else ""
        # דף ע"א / ע"ב (71/72) look like amud markers: it's a daf when it comes
        # first, or right after "-" and followed by an amud marker.
        is_daf_word = tok in ("עא", "עב") and (daf is None or (saw_range and nxt in ("עא", "עב")))
        if is_daf_word:
            daf = 71 if tok == "עא" else 72
            marks.append((daf, None)); saw_range = False
            continue
        if tok in ("עא", "עב"):
            if daf is not None:
                if marks and marks[-1][0] == daf and marks[-1][1] is None and saw_range:
                    # "דף ע"א - ע"ב": whole daf, amud a to b
                    marks[-1] = (daf, "a"); marks.append((daf, "a" if tok == "עא" else "b")); saw_range = False
                elif marks and marks[-1][0] == daf and marks[-1][1] is None:
                    marks[-1] = (daf, "a" if tok == "עא" else "b")
                else:
                    marks.append((daf, "a" if tok == "עא" else "b"))
            continue
        if tok == "-":
            saw_range = True; continue
        n = strict_num(tok)
        if n is None or n < 2 or n > 200:
            if marks:
                break
            continue
        daf = n
        marks.append((n, None)); saw_range = False
    if not marks:
        return []
    def idx(d, a): return d * 2 + (1 if a == "b" else 0)
    first, last = marks[0], marks[-1]
    start = idx(first[0], first[1] or "a")
    end = idx(last[0], last[1] or ("b" if last[1] is None and len(marks) == 1 else "a"))
    if last[1] is None and len(marks) > 1:
        end = idx(last[0], "b")
    if end < start:
        end = start
    end = min(end, start + 3)  # at most 4 amudim
    return [f"{i // 2}{'b' if i % 2 else 'a'}" for i in range(start, end + 1)]

def level3_label(kw, n):
    return f"{kw} {heb_display(n)}"

# ---------------------------------------------------------------- parsing helpers
def shiur_num(title):
    m = re.search(r"שיעור\s*#?\s*(\d+)", title or "")
    return int(m.group(1)) if m else None
def cycle(title):
    m = re.search(r"מחזור\s+(\S+)", norm(title))
    return heb_num(m.group(1)) if m else 1
def position(title):
    """Numeric place in the sefer from the title (סימן/סעיף, דף/עמוד, פרק/פסוק)."""
    t = norm(title)
    m = re.search(r"סימן\s+(\S+)(?:\s+(?:סעיף|סיעף)\s+(\S+))?", t)
    if m and heb_num(m.group(1)):
        return heb_num(m.group(1)) * 100 + (heb_num((m.group(2) or "").split("-")[0]) or 0)
    m = re.search(r"דף\s+(\S+)(?:\s+ע([אב]))?", t)
    if m and heb_num(m.group(1)):
        return heb_num(m.group(1)) * 2 + (1 if m.group(2) == "ב" else 0)
    m = re.search(r"פרק\s+(\S+)(?:\s+-?\s*פסוק\s+(\S+))?", t)
    if m and heb_num(m.group(1)):
        return heb_num(m.group(1)) * 100 + (heb_num((m.group(2) or "").split("-")[0]) or 0)
    return None

def parse_date(s):
    if not s:
        return None
    try:
        return email.utils.parsedate_to_datetime(s).astimezone(datetime.timezone.utc)
    except Exception:
        pass
    try:
        d = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return None

def fmt_dur(sec):
    if not sec:
        return None
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def dur_secs(v):
    if v is None:
        return None
    v = str(v).strip()
    try:
        if ":" in v:
            t = 0
            for p in v.split(":"):
                t = t * 60 + int(p)
            return t
        return int(v)
    except ValueError:
        return None

# ---------------------------------------------------------------- load + merge
def load_seed(path):
    eps = {}
    for e in json.load(open(path, encoding="utf8")):
        eps[e["guid"]] = {
            "id": e["guid"], "sid": e.get("server_id"), "t": e["title"] or "",
            "date": parse_date(e.get("published_at")), "a": e.get("audio_url"),
            "ty": e.get("enclosure_type"), "sec": e.get("duration_seconds"),
            "img": e.get("image_url"), "l": e.get("link"), "tags": e.get("categories") or [],
        }
    return eps

def merge_feed(eps, url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 birkas-catalog"})
    root = ET.fromstring(urllib.request.urlopen(req, timeout=90).read())
    ns = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
    added = updated = 0
    for it in root.find("channel").findall("item"):
        guid = (it.findtext("guid") or "").strip()
        enc = it.find("enclosure")
        if not guid:
            continue
        rec = {
            "t": it.findtext("title") or "", "date": parse_date(it.findtext("pubDate")),
            "a": enc.get("url") if enc is not None else None,
            "ty": enc.get("type") if enc is not None else None,
            "sec": dur_secs(it.findtext("itunes:duration", namespaces=ns)),
            "img": (it.find("itunes:image", ns).get("href") if it.find("itunes:image", ns) is not None else None),
            "l": it.findtext("link"), "tags": [c.text.strip() for c in it.findall("category") if c.text and c.text.strip()],
        }
        if guid in eps:
            eps[guid].update({k: v for k, v in rec.items() if v not in (None, "", [])})
            updated += 1
        else:
            eps[guid] = {"id": guid, "sid": None, **rec}
            added += 1
    return added, updated

# ---------------------------------------------------------------- classify
def classify(e):
    tags = [x for x in e["tags"] if x and x.strip()]
    cat = None
    if tags:
        cat = CAT_ALIAS.get(norm(tags[0]))
        if cat is None:
            cat = "general"
    if cat is None:
        t = norm(e["t"])
        for prefix, c in TITLE_RULES:
            if norm(prefix) in t:
                cat = c
                break
        else:
            cat = "general"
    secs = []
    rest = tags[1:]
    if cat in FIXED:
        for tg in rest:
            s = match_fixed(cat, tg)
            if s:
                secs = [s]; break
        if not secs:
            s = section_from_title(cat, e["t"])
            if s:
                secs = [s]
    elif cat == PARSHA_CAT:
        secs = parshiyos_from_title(e["t"])
    elif cat in FREE:
        for tg in rest:
            for part in tg.split("/"):
                p = part.strip().rstrip("'").strip()
                if p and p not in secs:
                    secs.append(p)
        if cat not in MULTI:
            secs = secs[:1]
    # Izzy's rule (Oct 22): Pesach-preparation shiurim belong under
    # הכנה ליו"ט → פסח, even when Libsyn filed them under ד"ת על הפרשה.
    if "הכנה ליו\"ט" in e["t"] and "פסח" in e["t"]:
        cat, secs = 'הכנה ליו"ט', ["פסח"]
    e["c"], e["s"] = cat, secs
    kw = LEVEL3.get(cat)
    e["p"] = level3_numbers(e["t"], kw) if kw else []
    e["n"], e["cy"], e["pos"] = shiur_num(e["t"]), cycle(e["t"]), position(e["t"])

def inherit_sections(eps):
    """Untagged episode with a shiur # gets the section of the previous shiur in the same category."""
    by_cat = collections.defaultdict(list)
    for e in eps:
        if e["n"] is not None and e["c"] in FIXED:
            by_cat[e["c"]].append(e)
    moved = 0
    for cat, lst in by_cat.items():
        lst.sort(key=lambda e: (e["cy"] or 1, e["n"], e["date"] or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)))
        last = None
        for e in lst:
            if e["s"]:
                last = e
            elif last and e["date"] and last["date"] and (e["cy"] or 1) == (last["cy"] or 1) \
                    and datetime.timedelta(0) <= e["date"] - last["date"] <= datetime.timedelta(days=120):
                e["s"] = list(last["s"]); e["inherited"] = True; moved += 1
                last = e
    # Still no section: take the section of the nearest-in-date shiur in the
    # same category (within a week), e.g. a topic shiur in the middle of a chelek.
    for cat in FIXED:
        lst = sorted([e for e in eps if e["c"] == cat and e["date"]], key=lambda e: e["date"])
        tagged = [e for e in lst if e["s"] and not e.get("inherited")]
        for e in lst:
            if e["s"]:
                continue
            best = min(tagged, key=lambda x: abs((x["date"] - e["date"]).total_seconds()), default=None)
            if best and abs(best["date"] - e["date"]) <= datetime.timedelta(days=7):
                e["s"] = list(best["s"]); e["inherited"] = True; moved += 1
    return moved

# ---------------------------------------------------------------- ordering
EPOCH0 = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
def ts(e):
    return (e["date"] or EPOCH0).timestamp()

def order_within(lst, newest_first=False):
    if newest_first:
        return sorted(lst, key=lambda e: -ts(e))
    numbered = [e for e in lst if e["n"] is not None]
    if lst and len(numbered) * 2 >= len(lst):
        rest = [e for e in lst if e["n"] is None]
        return sorted(numbered, key=lambda e: (e["cy"] or 1, e["n"], ts(e))) + sorted(rest, key=ts)
    posd = [e for e in lst if e["pos"] is not None]
    if lst and len(posd) * 2 >= len(lst):
        rest = [e for e in lst if e["pos"] is None]
        return sorted(posd, key=lambda e: (e["pos"], ts(e))) + sorted(rest, key=ts)
    return sorted(lst, key=ts)

def build(eps):
    cats = collections.OrderedDict((c, []) for c in CATEGORY_ORDER)
    for e in eps:
        cats.setdefault(e["c"], []).append(e)
    meta = []
    for cat, lst in cats.items():
        if not lst:
            continue
        # section order
        present = collections.OrderedDict()
        for e in lst:
            for s in e["s"]:
                present.setdefault(s, []).append(e)
        if cat in FIXED:
            sec_order = [s for s in FIXED[cat] if s in present]
        elif cat == "כד הקמח לרבינו בחיי":
            sec_order = sorted(present, key=norm)
        elif cat == 'הכנה ליו"ט':
            known = [s for s in HACHANA if any(norm(s) == norm(p) for p in present)]
            known = [next(p for p in present if norm(p) == norm(s)) for s in known]
            sec_order = known + sorted([p for p in present if p not in known], key=lambda p: -max(ts(e) for e in present[p]))
        elif cat == PARSHA_CAT:
            sec_order = [p for p in PARSHIYOS if p in present]
        elif cat == "שיעור כללי":
            sec_order = sorted(present, key=lambda p: -max(ts(e) for e in present[p]))
        else:
            sec_order = []
        newest_first = cat in ('הכנה ליו"ט', PARSHA_CAT)
        ordered, seen = [], set()
        for s in sec_order:
            for e in order_within(present[s], newest_first):
                if e["id"] not in seen:
                    ordered.append(e); seen.add(e["id"])
        rest = [e for e in lst if e["id"] not in seen]
        if not sec_order:  # categories without sections
            numbered = [e for e in rest if e["n"] is not None]
            rest = order_within(rest) if len(numbered) * 2 >= len(rest) else sorted(rest, key=lambda e: -ts(e))
        else:
            rest = sorted(rest, key=ts)
        ordered += rest
        for i, e in enumerate(ordered):
            e["o"] = i
        counts = {s: len(present[s]) for s in sec_order}
        kw = LEVEL3.get(cat)
        sec_meta = []
        for s in sec_order:
            m = {"name": s, "count": counts[s]}
            if kw:
                pts = sorted({n for e in present[s] for n in e["p"]})
                if pts:
                    m["points"] = [level3_label(kw, n) for n in pts]
            sec_meta.append(m)
        meta.append({"name": cat, "label": LABELS.get(cat, cat), "count": len(lst), "sections": sec_meta})
    return meta

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", default="catalog/seed_from_server_db.json")
    ap.add_argument("--feed", action="store_true", help="merge the live Libsyn feed")
    ap.add_argument("--out", default="assets/catalog.json")
    ap.add_argument("--report", default=None)
    a = ap.parse_args()

    eps = load_seed(a.seed)
    added = updated = 0
    if a.feed:
        added, updated = merge_feed(eps, FEED_URL)
    eps = list(eps.values())
    # Episodes to keep out of the app (catalog/hidden.json): by id or title text.
    hid = {"ids": [], "titles_contain": []}
    try:
        hid.update(json.load(open("catalog/hidden.json", encoding="utf8")))
    except FileNotFoundError:
        pass
    is_hidden = lambda e: e["id"] in hid["ids"] or any(t and t in (e["t"] or "") for t in hid["titles_contain"])
    hidden_ids = sorted(e["id"] for e in eps if is_hidden(e))
    eps = [e for e in eps if not is_hidden(e)]
    for e in eps:
        classify(e)
    inherited = inherit_sections(eps)
    meta = build(eps)

    out_eps = []
    for e in sorted(eps, key=lambda e: -ts(e)):
        r = {"id": e["id"], "t": e["t"], "d": e["date"].isoformat().replace("+00:00", "Z") if e["date"] else None,
             "a": e["a"], "c": e["c"], "s": e["s"], "o": e["o"]}
        if e.get("sid"): r["sid"] = e["sid"]
        if e.get("ty") and e["ty"] != "audio/mpeg": r["ty"] = e["ty"]
        if e.get("sec"): r["dur"] = fmt_dur(e["sec"])
        if e.get("img") and e["img"] != DEFAULT_IMG: r["img"] = e["img"]
        if e.get("l"): r["l"] = e["l"]
        if e["n"] is not None: r["n"] = e["n"]
        if e.get("p") and LEVEL3.get(e["c"]): r["p"] = [level3_label(LEVEL3[e["c"]], n) for n in e["p"]]
        # Source pages: Gemara -> HebrewBooks Vilna Shas (masechta number = Shas order)
        if e["c"] == "שיעור יומי - גמרא" and e["s"]:
            mas = e["s"][0].replace("מסכת ", "")
            if mas in SHAS:
                am = gemara_amudim(e["t"])
                if am:
                    r["pg"] = {"src": "hb-shas", "m": SHAS.index(mas) + 1, "pages": am}
        # Source pages: משנה ברורה -> a HebrewBooks book per חלק, siman -> pages map
        if e["c"] == "משנה ברורה" and "משנת סופרים" in e["t"] and "חלק א'" in MB_SOURCES:
            r["pg"] = {"src": "hb-book", "b": MB_SOURCES["חלק א'"]["book"], "from": 129, "to": 135, "lbl": "משנת סופרים"}
        elif e["c"] == "משנה ברורה" and e["s"] and e.get("p"):
            src = MB_SOURCES.get(e["s"][0])
            if src:
                spans = [src["simanim"][str(n)] for n in e["p"] if str(n) in src["simanim"]]
                if spans:
                    lo, hi = min(a for a, _ in spans), max(b for _, b in spans)
                    lbl = level3_label("סימן", min(n for n in e["p"] if str(n) in src["simanim"]))
                    nums = [n for n in e["p"] if str(n) in src["simanim"]]
                    if len(nums) > 1:
                        lbl += " – " + level3_label("סימן", max(nums)).replace("סימן ", "")
                    r["pg"] = {"src": "hb-book", "b": src["book"], "from": lo, "to": hi, "lbl": lbl}
        out_eps.append(r)

    gen = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    doc = {"version": 1, "generated": gen, "defaultImage": DEFAULT_IMG, "categories": meta, "episodes": out_eps, "hidden": hidden_ids}
    # Leave the file alone when nothing but the timestamp would change, so the
    # app only re-downloads (and the site only commits) when there is news.
    try:
        prev = json.load(open(a.out, encoding="utf8"))
        if {**prev, "generated": None} == {**doc, "generated": None}:
            doc = None
            print("catalog unchanged")
    except Exception:
        pass
    if doc is not None:
        with open(a.out, "w", encoding="utf8") as f:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))

    lines = [f"episodes={len(out_eps)} feed_added={added} feed_updated={updated} inherited_sections={inherited}"]
    for m in meta:
        no_sec = sum(1 for e in eps if e["c"] == m["name"] and not e["s"])
        secs = ", ".join(f"{s['name']}({s['count']})" for s in m["sections"])
        lines.append(f"{m['label']} [{m['count']}]" + (f" no-section:{no_sec}" if m["sections"] else "") + (f" :: {secs}" if secs else ""))
    rep = "\n".join(lines)
    print(rep)
    if a.report:
        open(a.report, "w", encoding="utf8").write(rep)

if __name__ == "__main__":
    main()
