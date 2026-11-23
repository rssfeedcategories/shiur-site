r"""Podcast cover art per topic feed (1400x1400 JPEG), app style: navy, gold title,
the Birkas Avrohom logo. Run once locally after build_podcasts.py lists a new
topic:  python3 tools/make_podcast_covers.py   (from app/; needs Pillow with raqm
and a Hebrew font). Existing covers are left alone unless --all is given."""
import json, os, sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
SITE_ROOT = os.path.dirname(os.path.dirname(HERE))
LOGO = os.path.join(SITE_ROOT, "v2", "logo.png")
BG = os.path.join(SITE_ROOT, "v2", "bg.jpg")
FONT = os.environ.get("HEB_FONT", "/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf")
NAVY, GOLD, WHITE = (4, 18, 61), (253, 194, 92), (255, 255, 255)
S = 1400


def fit(draw, text, maxw, start):
    size = start
    while size > 60:
        f = ImageFont.truetype(FONT, size)
        w = draw.textlength(text, font=f, direction="rtl")
        if w <= maxw:
            return f
        size -= 6
    return ImageFont.truetype(FONT, size)


def lines_for(title):
    """Split a long title into up to 2 lines (at ' - ' first, else the middle space)."""
    if len(title) <= 16:
        return [title]
    if " - " in title:
        a, b = title.split(" - ", 1)
        return [a, b]
    words = title.split()
    half = len(words) // 2
    return [" ".join(words[:half]), " ".join(words[half:])]


def cover(title, out):
    # navy with a soft lighter centre (like the logo's background)
    img = Image.new("RGB", (S, S), NAVY)
    glow = Image.new("L", (S, S), 0)
    ImageDraw.Draw(glow).ellipse([150, 150, S - 150, S - 150], fill=255)
    glow = glow.filter(ImageFilter.GaussianBlur(220))
    img = Image.composite(Image.new("RGB", (S, S), (22, 52, 128)), img, glow)
    d = ImageDraw.Draw(img)
    d.rectangle([28, 28, S - 29, S - 29], outline=GOLD, width=14)
    d.rectangle([58, 58, S - 59, S - 59], outline=GOLD, width=3)
    logo = Image.open(LOGO).convert("RGB").resize((480, 480), Image.LANCZOS)
    mask = Image.new("L", logo.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, 479, 479], radius=52, fill=255)
    img.paste(logo, ((S - 480) // 2, 105), mask)
    ls = lines_for(title)
    y = 690 if len(ls) == 1 else 625
    for ln in ls:
        f = fit(d, ln, S - 200, 190 if len(ls) == 1 else 150)
        w = d.textlength(ln, font=f, direction="rtl")
        h = f.getbbox(ln, direction="rtl")[3]
        d.text(((S - w) / 2, y), ln, font=f, fill=GOLD, direction="rtl",
               stroke_width=3, stroke_fill=NAVY)
        y += h + 30
    # the Rav's name on 2 lines (Izzy, Nov 23)
    f = ImageFont.truetype(FONT, 82)
    for sub, sy in (("הרב יצחק זלמן גיפס", S - 330), ('שליט"א', S - 225)):
        w = d.textlength(sub, font=f, direction="rtl")
        d.text(((S - w) / 2, sy), sub, font=f, fill=WHITE, direction="rtl")
    img.save(out, "JPEG", quality=88)


def main():
    os.chdir(os.path.dirname(HERE))          # app/
    idx = json.load(open("podcasts/index.json", encoding="utf8"))
    os.makedirs("podcasts/covers", exist_ok=True)
    for f in idx:
        out = f"podcasts/covers/{f['slug']}.jpg"
        if os.path.exists(out) and "--all" not in sys.argv:
            continue
        cover(f["title"].replace(" - שיעור יומי גמרא", ""), out)
        print("cover:", out)


if __name__ == "__main__":
    main()
