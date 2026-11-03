"""Review days for the Live Stream PDF buttons.

Reads today's emails to birkasshiur@gmail.com whose subject starts with "Live:"
and writes catalog/live_override.json (used for TODAY only by build_catalog.py):
  Live: משלי פרק ג        -> Mishlei button shows the whole perek
  Live: משנה ברורה סימן תמז -> Mishna Berura button shows that siman
  Live: גמרא דף יב        -> Gemara button starts at that daf
  Live: בטל / clear        -> back to automatic
English / digits work too ("Live: Mishlei 3", "Live: MB 447", "Live: daf 12").
Only accepted from LIVE_SENDERS (comma-separated) or the Gmail account itself.
Env: GMAIL_ADDRESS, GMAIL_APP_PASSWORD, LIVE_SENDERS (optional).
"""
import email, email.header, email.utils, imaplib, json, os, pathlib, re, sys, datetime, zoneinfo

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from build_catalog import heb_num  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent.parent / "catalog" / "live_override.json"
NY = zoneinfo.ZoneInfo("America/New_York")


def dec(s):
    return "".join(t.decode(c or "utf-8", "replace") if isinstance(t, bytes) else t
                   for t, c in email.header.decode_header(s or ""))


def number_after(text, words):
    for w in words:
        m = re.search(w + r"\s*[#:]?\s*([0-9]+|[א-ת\"'׳״]+)", text, re.I)
        if m:
            v = m.group(1)
            return int(v) if v.isdigit() else heb_num(re.sub("[\"'׳״]", "", v))
    m = re.search(r"\b([0-9]{1,3})\b", text)
    return int(m.group(1)) if m else None


def parse(subject):
    t = subject.split(":", 1)[1].strip() if ":" in subject else subject
    low = t.lower()
    if re.search(r"בטל|clear|cancel|auto", low):
        return "clear", None
    if "משלי" in t or "mishl" in low:
        return "mishlei", {"perek": number_after(t, ["פרק", "perek", "chapter"])}
    if re.search(r'משנה ברורה|מ"ב|מ״ב|סימן', t) or re.search(r"\bmb\b|mishna|siman", low):
        return "mb", {"siman": number_after(t, ["סימן", "siman", "mb", "berura"])}
    if re.search(r"גמרא|דף", t) or re.search(r"gemara|daf", low):
        return "gemara", {"daf": number_after(t, ["דף", "daf", "gemara"])}
    return None, None


def main():
    user, pw = os.environ.get("GMAIL_ADDRESS"), os.environ.get("GMAIL_APP_PASSWORD")
    if not user or not pw:
        print("live_mail: no Gmail secrets – skipped")
        return
    allowed = {a.strip().lower() for a in (os.environ.get("LIVE_SENDERS", "") + "," + user).split(",") if a.strip()}
    today = datetime.datetime.now(NY).date()
    M = imaplib.IMAP4_SSL("imap.gmail.com")
    M.login(user, pw)
    M.select("INBOX", readonly=True)
    since = (today - datetime.timedelta(days=1)).strftime("%d-%b-%Y")
    typ, data = M.search(None, f'(SINCE {since} SUBJECT "Live")')
    found = []
    for num in (data[0].split() if data and data[0] else []):
        typ, msg = M.fetch(num, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])")
        h = email.message_from_bytes(msg[0][1])
        subj, frm = dec(h.get("Subject")), email.utils.parseaddr(h.get("From"))[1].lower()
        when = email.utils.parsedate_to_datetime(h.get("Date")).astimezone(NY)
        if when.date() != today or not re.match(r"\s*live\s*:", subj, re.I) or frm not in allowed:
            continue
        found.append((when, subj, frm))
    M.logout()

    ov = {"date": today.isoformat()}
    try:
        old = json.loads(OUT.read_text(encoding="utf8"))
        if old.get("date") == today.isoformat():
            ov = old
    except Exception:
        old = None
    for when, subj, frm in sorted(found):
        key, val = parse(subj)
        if key == "clear":
            ov = {"date": today.isoformat()}
        elif key and val and all(v for v in val.values()):
            ov[key] = val
        print(f"live_mail: {when:%H:%M} {frm}: {subj!r} -> {key} {val}")
    if found and ov != old:
        OUT.write_text(json.dumps(ov, ensure_ascii=False, indent=1), encoding="utf8")
        print("live_mail: wrote", OUT.name, ov)


if __name__ == "__main__":
    main()
