# ClownWatch v0.1

A US clown-sighting news tracker. One self-contained HTML file, zero hosting needed.

## Files
- `clownwatch.html` — the app (open in any browser; needs internet for the map/timeline libraries)
- `fetch.py` — pulls fresh news, filters it, rebuilds `clownwatch.html`
- `template.html` — the app shell `fetch.py` injects data into
- `sightings.json` — the raw filtered dataset from the last run

## Refresh the data
```
cd ~/workspace/clownwatch && python3 fetch.py
```
Pulls Google News RSS (5 queries) + GDELT DOC 2.0 API (free, no key; throttled ~1 req/6s).
Takes about a minute. Re-open `clownwatch.html` to see the new data.

## Put it on the internet, free (GitHub Pages + auto-refresh)
1. Create a free account at github.com (if you don't have one).
2. Create a new repository named `clownwatch`. Make it **Public** (free Pages
   needs a public repo). Don't add a README.
3. On the new repo page, click "uploading an existing file" and drag in
   **everything** from this folder — including the `.github` folder. Commit.
   (If the file picker hides `.github`, create it manually: Add file → Create
   new file → name it `.github/workflows/refresh.yml` → paste in the contents
   of the workflow file from this folder.)
4. Go to Settings → Pages → Source: "Deploy from a branch", Branch: `main`,
   folder: `/ (root)` → Save.
5. Wait a minute or two: your site is live at
   `https://<your-username>.github.io/clownwatch/`.

The workflow in `.github/workflows/refresh.yml` runs `fetch.py` every 6 hours
and pushes the rebuilt page, so the site stays fresh on its own. The Actions
tab shows each run; there's a "Run workflow" button for manual refreshes.
GitHub may pause the schedule if the repo sits untouched for 60+ days — any
visit or commit re-arms it. A custom domain can be added later under
Settings → Pages at no extra cost (domain registration ~$10–15/yr).

## How filtering works
Each article gets a sighting-signal score from keywords (`spotted`, `lurking`,
`police`, `911`…), minus points for noise (`documentary`, `pennywise`,
`prank`…), and hard-excludes circus/rodeo/movie content. Verdicts:
**likely sighting** (9+), **possible sighting** (6–8), **mention** (4–5).
Locations are extracted from headlines (`City, ST` → state name) and plotted;
~2/3 of items get a location.

## Dispatch tab
Stubbed on purpose: Broadcastify's terms forbid automated access/transcription
of scanner audio without a commercial license. The tab explains this, lists the
honest v2 paths (public PD calls-for-service feeds, SpotCrime-type aggregators,
crowd-sourced tips), and includes a working tip logger (saved in the browser).

## v2 ideas
- Scheduled refresh (cron/GitHub Actions) + hosted page
- GDELT timeline API for a real sightings-volume chart
- SpotCrime API for incident-level dispatch data
- Email/push alerts when a "likely sighting" lands in your state
