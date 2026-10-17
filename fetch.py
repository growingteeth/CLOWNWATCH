#!/usr/bin/env python3
"""
ClownWatch fetcher — pulls US clown-sighting news, filters the noise, geocodes
what it can, and builds a self-contained clownwatch.html.

Sources (all free, no API keys):
  1. Google News RSS  (primary — fast, no key; personal/non-commercial use)
  2. GDELT DOC 2.0 API (secondary — free, throttled to ~1 req / 6s)

Usage:  python3 fetch.py
Output: sightings.json + clownwatch.html (in this directory)

Re-run any time to refresh the data baked into the HTML.
"""

import json, re, html, time, difflib, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

UA = {"User-Agent": "ClownWatch/0.1 (personal research project; contact: local)"}

# Data sources to use. Google News RSS asks for personal/non-commercial use;
# every item links back to the original article, which is the polite minimum.
# Set to ("gdelt",) to go GDELT-only on a public site — GDELT explicitly
# supports reuse of its data for public projects.
SOURCES = ("googlenews", "gdelt")

# ---------------------------------------------------------------- queries
GN_QUERIES = [
    '"clown sighting"',
    '"clown sightings"',
    '"clown spotted"',
    '"creepy clown" sighting',
    '"dressed as a clown" police',
]
# GDELT full-text syntax; keep to 1-2 queries, paced 6s+ apart.
GDELT_QUERIES = [
    '("clown sighting" OR "clown sightings" OR "clown spotted" OR "creepy clown") sourcelang:english sourcecountry:US',
]

# ------------------------------------------------------- signal scoring
POSITIVE = {
    "spotted": 3, "sighted": 3, "sighting": 3, "sightings": 3,
    "lurking": 3, "lurks": 3, "lurked": 3,
    "wandering": 2, "reported": 2, "reports": 2, "reporting": 2,
    "police": 2, "sheriff": 2, "deputies": 2, "troopers": 2, "911": 2,
    "arrested": 2, "arrest": 2, "warning": 2, "warned": 2, "warns": 2,
    "residents": 1, "neighborhood": 1, "woods": 1, "playground": 1,
    "terrified": 2, "terrify": 2, "chased": 2, "chasing": 2,
    "masked": 1, "costume": 1, "prowling": 3, "stalking": 2,
}
HARD_NO = [  # never a real sighting report
    "circus", "rodeo clown", "class clown", "clownfish", "clown car",
    "birthday clown", "clown college", "killer klowns",
    "movie review", "film review", "trailer", "box office", "netflix",
    "streaming on", "clown show", "insane clown posse", "juggalo",
    "clown makeup tutorial", "how to draw", "clown emoji", "cat in the hat",
]
SOFT_NO = {  # suspicious, subtract points
    "pennywise": 4, "terrifier": 4, "art the clown": 4, "halloween costume": 2,
    "prank": 1, "hoax": 1,
    "documentary": 3, "docuseries": 3, "revisits": 2, "on this day": 3,
    "look back": 2, "throwback": 2, "remember all those": 2,
}
# "dressed as a clown" in a crime story is clown-involved news, not a sighting —
# worth tracking as a mention, not as a sighting.
POSITIVE_EXTRA = {"dressed as a clown": 2, "clown costume": 2, "clown mask": 2}
POSITIVE.update(POSITIVE_EXTRA)

NON_US = [  # if one of these appears and no US location was found, drop it
    "ireland", "dublin", "united kingdom", "britain", "england", "london",
    "scotland", "wales", "canada", "toronto", "vancouver", "australia",
    "sydney", "melbourne", "spain", "madrid", "france", "paris", "germany",
    "berlin", "japan", "tokyo", "mexico", "brazil", "india", "mumbai",
]

# ------------------------------------------------------------- geocoding
# "City,ST,lat,lon" — major US cities; matched against title+snippet.
CITIES = """\
Birmingham,AL,33.52,-86.80;Huntsville,AL,34.73,-86.59;Mobile,AL,30.69,-88.04;Montgomery,AL,32.38,-86.30;
Anchorage,AK,61.22,-149.90;Phoenix,AZ,33.45,-112.07;Tucson,AZ,32.22,-110.97;Mesa,AZ,33.42,-111.83;
Little Rock,AR,34.75,-92.29;Fayetteville,AR,36.06,-94.16;
Los Angeles,CA,34.05,-118.24;San Francisco,CA,37.77,-122.42;San Diego,CA,32.72,-117.16;Sacramento,CA,38.58,-121.49;San Jose,CA,37.34,-121.89;Fresno,CA,36.74,-119.79;Oakland,CA,37.80,-122.27;Bakersfield,CA,35.37,-119.02;
Denver,CO,39.74,-104.99;Colorado Springs,CO,38.83,-104.82;Aurora,CO,39.73,-104.83;Boulder,CO,40.02,-105.27;
Hartford,CT,41.77,-72.67;Bridgeport,CT,41.17,-73.20;New Haven,CT,41.31,-72.92;
Dover,DE,39.16,-75.53;Wilmington,DE,39.75,-75.55;
Washington,DC,38.91,-77.04;
Miami,FL,25.76,-80.19;Orlando,FL,28.54,-81.38;Tampa,FL,27.95,-82.46;Jacksonville,FL,30.33,-81.66;Tallahassee,FL,30.44,-84.28;Fort Lauderdale,FL,26.12,-80.14;
Atlanta,GA,33.75,-84.39;Savannah,GA,32.08,-81.09;Augusta,GA,33.47,-81.97;
Honolulu,HI,21.31,-157.86;Boise,ID,43.62,-116.20;
Chicago,IL,41.88,-87.63;Springfield,IL,39.78,-89.65;Aurora,IL,41.76,-88.32;
Indianapolis,IN,39.77,-86.16;Fort Wayne,IN,41.08,-85.14;
Des Moines,IA,41.59,-93.62;Cedar Rapids,IA,41.98,-91.67;
Wichita,KS,37.69,-97.34;Topeka,KS,39.05,-95.68;Kansas City,KS,39.11,-94.63;
Louisville,KY,38.25,-85.76;Lexington,KY,38.04,-84.50;Frankfort,KY,38.20,-84.87;
New Orleans,LA,29.95,-90.07;Baton Rouge,LA,30.45,-91.15;Shreveport,LA,32.53,-93.75;
Portland,ME,43.66,-70.26;Augusta,ME,44.31,-69.78;
Baltimore,MD,39.29,-76.61;Annapolis,MD,38.98,-76.49;
Boston,MA,42.36,-71.06;Worcester,MA,42.26,-71.80;Springfield,MA,42.10,-72.59;
Detroit,MI,42.33,-83.05;Grand Rapids,MI,42.96,-85.67;Lansing,MI,42.73,-84.56;Flint,MI,43.01,-83.69;
Minneapolis,MN,44.98,-93.27;St. Paul,MN,44.95,-93.09;Duluth,MN,46.79,-92.10;
Jackson,MS,32.30,-90.18;Gulfport,MS,30.37,-89.09;
Kansas City,MO,39.10,-94.58;St. Louis,MO,38.63,-90.20;Springfield,MO,37.21,-93.29;Columbia,MO,38.95,-92.33;
Billings,MT,45.78,-108.50;Helena,MT,46.59,-112.04;Missoula,MT,46.87,-113.99;
Omaha,NE,41.26,-95.93;Lincoln,NE,40.81,-96.70;
Las Vegas,NV,36.17,-115.14;Reno,NV,39.53,-119.81;Carson City,NV,39.16,-119.77;
Manchester,NH,42.99,-71.46;Concord,NH,43.21,-71.54;
Newark,NJ,40.74,-74.17;Trenton,NJ,40.22,-74.76;Jersey City,NJ,40.72,-74.06;
Albuquerque,NM,35.08,-106.65;Santa Fe,NM,35.69,-105.94;
New York,NY,40.71,-74.01;Buffalo,NY,42.89,-78.88;Rochester,NY,43.16,-77.61;Albany,NY,42.65,-73.76;Syracuse,NY,43.05,-76.15;
Charlotte,NC,35.23,-80.84;Raleigh,NC,35.78,-78.64;Greensboro,NC,36.07,-79.79;Durham,NC,35.99,-78.90;Cary,NC,35.79,-78.78;
Fargo,ND,46.88,-96.79;Bismarck,ND,46.81,-100.78;
Columbus,OH,39.96,-83.00;Cleveland,OH,41.50,-81.69;Cincinnati,OH,39.10,-84.51;Toledo,OH,41.65,-83.54;Akron,OH,43.07,-81.51;Dayton,OH,39.76,-84.19;
Oklahoma City,OK,35.47,-97.52;Tulsa,OK,36.15,-95.99;Norman,OK,35.22,-97.44;
Portland,OR,45.52,-122.68;Salem,OR,44.94,-123.03;Eugene,OR,44.05,-123.09;
Philadelphia,PA,39.95,-75.17;Pittsburgh,PA,40.44,-79.99;Harrisburg,PA,40.27,-76.88;Allentown,PA,40.60,-75.49;
Providence,RI,41.82,-71.41;Charleston,SC,32.78,-79.93;Columbia,SC,34.00,-81.04;Greenville,SC,34.85,-82.39;Myrtle Beach,SC,33.69,-78.88;
Sioux Falls,SD,43.55,-96.73;Pierre,SD,44.37,-100.35;
Nashville,TN,36.16,-86.78;Memphis,TN,35.15,-90.05;Knoxville,TN,35.96,-83.92;Chattanooga,TN,35.05,-85.31;
Houston,TX,29.76,-95.37;Dallas,TX,32.78,-96.80;Austin,TX,30.27,-97.74;San Antonio,TX,29.42,-98.49;Fort Worth,TX,32.76,-97.33;El Paso,TX,31.76,-106.49;Arlington,TX,32.74,-97.11;
Salt Lake City,UT,40.76,-111.89;Provo,UT,40.23,-111.66;
Burlington,VT,44.48,-73.21;Montpelier,VT,44.26,-72.58;
Virginia Beach,VA,36.85,-75.98;Richmond,VA,37.54,-77.44;Norfolk,VA,36.85,-76.29;Arlington,VA,38.88,-77.09;
Seattle,WA,47.61,-122.33;Spokane,WA,47.66,-117.43;Tacoma,WA,47.25,-122.44;Olympia,WA,47.04,-122.90;Bellevue,WA,47.61,-122.20;
Charleston,WV,38.35,-81.63;Huntington,WV,38.42,-82.44;Morgantown,WV,39.63,-79.96;
Milwaukee,WI,43.04,-87.91;Madison,WI,43.07,-89.40;Green Bay,WI,44.51,-88.02;
Cheyenne,WY,41.14,-104.82;Casper,WY,42.87,-106.31;
"""
STATES = {  # name -> (abbr, lat, lon)
    "alabama": ("AL", 32.78, -86.83), "alaska": ("AK", 64.0, -150.0),
    "arizona": ("AZ", 34.27, -111.66), "arkansas": ("AR", 34.90, -92.44),
    "california": ("CA", 37.19, -119.42), "colorado": ("CO", 39.0, -105.55),
    "connecticut": ("CT", 41.62, -72.70), "delaware": ("DE", 39.0, -75.50),
    "florida": ("FL", 28.63, -82.45), "georgia": ("GA", 32.96, -83.44),
    "hawaii": ("HI", 21.11, -157.50), "idaho": ("ID", 44.39, -114.66),
    "illinois": ("IL", 40.10, -89.20), "indiana": ("IN", 39.89, -86.28),
    "iowa": ("IA", 42.08, -93.50), "kansas": ("KS", 38.49, -98.38),
    "kentucky": ("KY", 37.53, -85.30), "louisiana": ("LA", 31.07, -92.00),
    "maine": ("ME", 45.37, -69.45), "maryland": ("MD", 39.05, -76.79),
    "massachusetts": ("MA", 42.26, -71.80), "michigan": ("MI", 44.35, -85.41),
    "minnesota": ("MN", 46.39, -94.37), "mississippi": ("MS", 32.74, -89.67),
    "missouri": ("MO", 38.36, -92.46), "montana": ("MT", 47.05, -109.94),
    "nebraska": ("NE", 41.54, -99.80), "nevada": ("NV", 39.33, -116.63),
    "new hampshire": ("NH", 43.68, -71.58), "new jersey": ("NJ", 40.19, -74.67),
    "new mexico": ("NM", 34.41, -106.11), "new york": ("NY", 42.15, -74.95),
    "north carolina": ("NC", 35.63, -79.81), "north dakota": ("ND", 47.45, -100.47),
    "ohio": ("OH", 40.29, -82.80), "oklahoma": ("OK", 35.57, -97.49),
    "oregon": ("OR", 43.93, -120.55), "pennsylvania": ("PA", 40.88, -77.80),
    "rhode island": ("RI", 41.68, -71.51), "south carolina": ("SC", 33.82, -80.94),
    "south dakota": ("SD", 44.44, -100.23), "tennessee": ("TN", 35.75, -86.35),
    "texas": ("TX", 31.47, -99.33), "utah": ("UT", 39.31, -111.67),
    "vermont": ("VT", 44.07, -72.66), "virginia": ("VA", 37.93, -78.66),
    "washington": ("WA", 47.38, -120.45), "west virginia": ("WV", 38.64, -80.62),
    "wisconsin": ("WI", 44.62, -89.99), "wyoming": ("WY", 42.99, -107.55),
    "district of columbia": ("DC", 38.91, -77.04),
}

def strip_html(s):
    return html.unescape(re.sub(r"<[^>]+>", " ", s or "")).strip()

def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

# ------------------------------------------------------------- collectors
def google_news():
    items = []
    for q in GN_QUERIES:
        url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(q) +
               "&hl=en-US&gl=US&ceid=US:en")
        try:
            root = ET.fromstring(fetch(url))
        except Exception as e:
            print(f"  [warn] Google News query failed {q!r}: {e}")
            continue
        for it in root.iter("item"):
            title = (it.findtext("title") or "").split(" - ")[0]
            link = it.findtext("link") or ""
            desc = strip_html(it.findtext("description") or "")
            src = it.find("source")
            source = src.text if src is not None else ""
            try:
                dt = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc)
            except Exception:
                dt = datetime.now(timezone.utc)
            items.append({"title": title.strip(), "url": link, "snippet": desc,
                          "source": source.strip(), "date": dt.isoformat(),
                          "origin": "googlenews"})
        time.sleep(2)
    return items

def gdelt():
    items = []
    for q in GDELT_QUERIES:
        url = ("https://api.gdeltproject.org/api/v2/doc/doc?query=" +
               urllib.parse.quote(q) +
               "&mode=artlist&maxrecords=100&format=json&sortby=date")
        try:
            data = json.loads(fetch(url))
        except Exception as e:
            print(f"  [warn] GDELT query failed: {e}")
            continue
        for a in data.get("articles", []):
            try:
                dt = datetime.strptime(a.get("seendate", ""),
                                       "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            except Exception:
                dt = datetime.now(timezone.utc)
            items.append({"title": (a.get("title") or "").strip(),
                          "url": a.get("url") or "", "snippet": "",
                          "source": a.get("domain") or "",
                          "date": dt.isoformat(), "origin": "gdelt"})
        time.sleep(6)
    return items

# ------------------------------------------------------- filter + geocode
def score(item):
    text = (item["title"] + " " + item["snippet"]).lower()
    if any(bad in text for bad in HARD_NO):
        return -999
    s = sum(pts for w, pts in POSITIVE.items() if w in text)
    s -= sum(pts for w, pts in SOFT_NO.items() if w in text)
    return s

CITY_RE = [(re.compile(r"\b" + re.escape(c.split(",")[0]) + r"\b", re.I),
            c.split(",")) for c in CITIES.replace("\n", "").split(";") if c.strip()]

def geocode(item):
    text = item["title"] + " " + item["snippet"]
    # "City, ST" pattern first (most precise)
    m = re.search(r"\b([A-Z][a-zA-Z .'-]+),\s*([A-Z]{2})\b", text)
    if m:
        city, st = m.group(1).strip(), m.group(2)
        for pat, parts in CITY_RE:
            if parts[1] == st and pat.search(city):
                return {"place": f"{parts[0]}, {st}", "lat": float(parts[2]),
                        "lon": float(parts[3]), "precision": "city"}
    for pat, parts in CITY_RE:  # bare city name
        if pat.search(text):
            return {"place": f"{parts[0]}, {parts[1]}", "lat": float(parts[2]),
                    "lon": float(parts[3]), "precision": "city"}
    low = text.lower()
    for name, (abbr, lat, lon) in STATES.items():  # state name
        if re.search(r"\b" + re.escape(name) + r"\b", low):
            return {"place": name.title(), "lat": lat, "lon": lon,
                    "precision": "state"}
    return {"place": None, "lat": None, "lon": None, "precision": None}

def norm_title(t):
    return re.sub(r"[^a-z0-9]", "", t.lower())[:80]

def dedupe(items):
    seen, out = set(), []
    for it in sorted(items, key=lambda x: x["date"], reverse=True):
        key = norm_title(it["title"])
        if not key or key in seen:
            continue
        if any(difflib.SequenceMatcher(None, key, s).ratio() > 0.88 for s in seen):
            continue
        seen.add(key)
        out.append(it)
    return out

# ------------------------------------------------------------------ main
def main():
    raw = []
    if "googlenews" in SOURCES:
        print("Fetching Google News RSS...")
        raw = google_news()
        print(f"  got {len(raw)} raw items")
    if "gdelt" in SOURCES:
        print("Fetching GDELT (paced)...")
        raw += gdelt()
    print(f"  total {len(raw)} raw items")

    kept = []
    for it in dedupe(raw):
        s = score(it)
        if s < 4:
            continue
        geo = geocode(it)
        text = (it["title"] + " " + it["snippet"]).lower()
        if geo["place"] is None:
            if any(p in text for p in NON_US):
                continue  # clearly not a US story
            if s < 7:
                continue  # no US location + middling signal = noise
        kept.append({**it, "score": s, **geo,
                     "verdict": "likely sighting" if s >= 9 else
                                "possible sighting" if s >= 6 else "mention"})
    kept.sort(key=lambda x: x["date"], reverse=True)
    print(f"Kept {len(kept)} items after filtering")

    payload = {"updated": datetime.now(timezone.utc).isoformat(),
               "count": len(kept), "items": kept}
    with open("sightings.json", "w") as f:
        json.dump(payload, f, indent=1)

    with open("template.html") as f:
        tpl = f.read()
    html_out = tpl.replace("/*__DATA__*/",
                           "const DATA = " + json.dumps(payload) + ";")
    with open("clownwatch.html", "w") as f:
        f.write(html_out)
    print("Wrote sightings.json and clownwatch.html")

if __name__ == "__main__":
    main()
