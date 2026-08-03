# Birkas Avrohom — shiur site

A static website built from the Libsyn RSS feed (show 381893). Libsyn stays the
source of truth: keep publishing exactly as you do now, and this site follows
along within 15 minutes.

## How it works

1. `build_feed.py` pulls the RSS feed and writes compact JSON into `data/`.
2. A GitHub Action runs it every 15 minutes and commits any changes.
3. `index.html` reads that JSON. No server, no database, no build step.

Nothing fetches the feed from the browser, so there is no CORS problem and
the 3,400-episode XML file never touches a phone.

## Setup

**1. Create the repo**

```bash
git init
git add .
git commit -m "Shiur site"
git remote add origin https://github.com/rssfeedcategories/shiur-site.git
git push -u origin main
```

**2. Generate the data once**

```bash
python3 build_feed.py
```

Requires nothing beyond Python 3.9+ — no pip installs.

**3. Deploy to Cloudflare Pages**

In the Cloudflare dashboard: Workers & Pages → Create → Pages → Connect to Git,
pick the repo, then set:

| Setting | Value |
| --- | --- |
| Build command | *(leave empty)* |
| Build output directory | `/` |

Every commit from the Action redeploys automatically. Add a custom domain under
the project's Custom domains tab.

## Day to day

Nothing to do. The Action runs on its own. To force a refresh, open the Actions
tab and press **Run workflow**.

To rebuild locally and preview:

```bash
python3 build_feed.py
python3 -m http.server
```

Then open http://localhost:8000 — opening `index.html` directly from disk won't
work, because browsers block `fetch` on `file://` URLs.

## What the site does

- **The shelf** — every category as a sefer spine. The brass band on each spine
  is thicker for categories with more shiurim, so the shelf shows at a glance
  where the bulk of the archive sits.
- **Series order** — titles like `ספר משלי - שיעור #269 - פרק כ"ז` are parsed
  into series name, shiur number, and source reference, so each series lists in
  learning order rather than newest-first. The badge on a series shows the next
  shiur you haven't finished.
- **Resume** — playback position is saved per episode and surfaced in a
  "pick up where you left off" row. The 60 most recent are kept.
- **Search** — matches Hebrew titles, series names, and shiur numbers like `#152`.
- **Player** — stays put while browsing, remembers speed (1× to 2×), 15s back /
  30s forward, and wires into lock-screen controls on iOS and Android.
- **Installable** — add to home screen and it opens like an app, with the
  interface cached for offline.

## Two things to fix in Libsyn

- One episode is dated **January 2001**. The build prints a warning listing any
  episode dated before 2020. Fix the date in Libsyn and it moves into place on
  the next run.
- The Libsyn site nav shows 17 categories; the Cloudflare worker generates 29
  category feeds. This site builds its shelf from whatever categories the feed
  actually contains, so it's worth confirming the two lists agree.

## Files

| File | Purpose |
| --- | --- |
| `index.html` | The whole site — markup, styles, and player |
| `build_feed.py` | Feed → JSON |
| `.github/workflows/build.yml` | Scheduled rebuild |
| `sw.js`, `manifest.json` | Offline caching and home-screen install |
| `data/` | Generated — don't edit by hand |

## Changing things

The feed URL is at the top of `build_feed.py` (or set a `FEED_URL` env var).
Colours are CSS variables at the top of `index.html`: `--brass` is the accent,
`--ink` the background, `--parchment` the text. The title-parsing rule is
`SHIUR_RE` in `build_feed.py` — if a new series uses a different title format,
that regex is the one place to adjust.
