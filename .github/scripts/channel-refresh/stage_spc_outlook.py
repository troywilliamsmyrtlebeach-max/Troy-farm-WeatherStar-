#!/usr/bin/env python3
"""Stage Battaglia spc-outlook.json for the farm point.

Run by the Channel/International 15-min cron (weatherstar-channel-intl-15min-refresh)
as a staged Battaglia file, alongside farm-data.json, zone-forecast.txt,
regional-metars.xml, regional-map-metars.xml, outlook.json, monthly-precip.json,
hourly-forecast.json.

SOURCE (farm point only): Storm Prediction Center categorical outlook
GeoJSON, Days 1/2/3, for CALABASH-FARM AT BRUNSWICK (33.92N 78.57W):
  https://www.spc.noaa.gov/products/outlook/day1otlk_cat.lyr.geojson
  https://www.spc.noaa.gov/products/outlook/day2otlk_cat.lyr.geojson
  https://www.spc.noaa.gov/products/outlook/day3otlk_cat.lyr.geojson
No key is needed (public SPC feed, NOT Troy's credential).

Each file is a GeoJSON FeatureCollection of categorical risk polygons.
properties include LABEL (TSTM / MRGL / SLGT / ENH / MDT / HIGH), LABEL2
(the plain-words risk), DN (severity rank 2..7), VALID_ISO / EXPIRE_ISO /
ISSUE_ISO, and the polygon's own stroke/fill colors. This script runs a
point-in-polygon test (ray casting, Polygon + MultiPolygon, holes
honored) for the farm point against every polygon; the covering polygon
with the highest DN wins for that day. No polygon covering the farm
means "NONE" — no severe outlook (SPC issues no polygon for that case).

FILE (one entry per day):
  { "station": "KNCCAROL120", "location": "CALABASH-FARM AT BRUNSWICK",
    "generatedAt": "2026-11-23T20:52:00-05:00", "updateTime": "<fetch UTC>",
    "source": "Storm Prediction Center categorical outlooks (Day 1/2/3 GeoJSON) for 33.92,-78.57",
    "sources": { "1": "<day1 url>", "2": "<day2 url>", "3": "<day3 url>" },
    "days": [ { "day": 1, "dateLabel": "Sun Nov 23",
                "riskCode": "NONE", "riskLabel": "No Severe Outlook",
                "color": "#FFFFFF",
                "validFrom": "2026-11-23T20:00:00-05:00",
                "validTo": "2026-11-24T07:00:00-05:00",
                "validLabel": "Sun 8 PM - Mon 7 AM EST",
                "issued": "2026-11-23T19:31:00-05:00",
                "source": "<day1 url>", "matchedPolygon": null }, ... ] }

Risk codes and plain-words labels (SPC LABEL2 wording):
  NONE  No Severe Outlook      (no polygon covers the farm)
  TSTM  General Thunderstorms  (DN 2)
  MRGL  Marginal Risk          (DN 3)
  SLGT  Slight Risk            (DN 4)
  ENH   Enhanced Risk          (DN 5)
  MDT   Moderate Risk          (DN 6)
  HIGH  High Risk              (DN 7)
"color" is the covering polygon's own SPC fill color (white for NONE),
so the screen shows the risk in SPC's own color.

Valid windows are staged in farm-local time (America/New_York) as ISO
plus a preformatted validLabel in plain ASCII (the Star4000 canvas font
has no en-dash/bullet glyphs, so "-" only, never "--" or "•").

SAFETY: on any fetch/parse failure, on a day with zero polygons, or on
a missing/unparseable valid window, exit non-zero WITHOUT touching the
staged file — the cron keeps the previous file. SPC outlooks are issued
on a slower cadence than hourly, so the app ignores a file whose
generatedAt is older than 12 hours (hourly uses 2h); a stale file can
never show an old outlook as current — the screen shows
OUTLOOK UNAVAILABLE instead.

Usage: python3 stage_spc_outlook.py [--out DIR]
  default out = the Battaglia source dir (4000-battaglia/) under
  ~/workspace/github-push/troy-farm-weatherstar.
"""
import argparse
import datetime
import json
import os
import sys
import urllib.request

SPC_URLS = {
    1: "https://www.spc.noaa.gov/products/outlook/day1otlk_cat.lyr.geojson",
    2: "https://www.spc.noaa.gov/products/outlook/day2otlk_cat.lyr.geojson",
    3: "https://www.spc.noaa.gov/products/outlook/day3otlk_cat.lyr.geojson",
}
LAT, LON = 33.92, -78.57
USER_AGENT = "Muse-WeatherStar-Battaglia (troy farm, contact: KNCCAROL120)"
SRC_DIR = os.environ.get("BATTAGLIA_SRC_DIR",
                         os.path.expanduser("~/workspace/github-push/troy-farm-weatherstar/4000-battaglia"))

# SPC categorical risk: code -> plain-words label (SPC LABEL2 wording).
RISK_LABELS = {
    "NONE": "No Severe Outlook",
    "TSTM": "General Thunderstorms",
    "MRGL": "Marginal Risk",
    "SLGT": "Slight Risk",
    "ENH": "Enhanced Risk",
    "MDT": "Moderate Risk",
    "HIGH": "High Risk",
}
# Severity rank (the GeoJSON DN value); the covering polygon with the
# highest rank wins when more than one covers the farm.
SEVERITY = {"TSTM": 2, "MRGL": 3, "SLGT": 4, "ENH": 5, "MDT": 6, "HIGH": 7}


def ring_contains(ring, x, y):
    """Ray-casting point-in-ring test (x=lon, y=lat)."""
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            if x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                inside = not inside
    return inside


def polygon_contains(poly, x, y):
    """Point in a GeoJSON Polygon (first ring exterior, rest holes)."""
    if not poly:
        return False
    if not ring_contains(poly[0], x, y):
        return False
    for hole in poly[1:]:
        if ring_contains(hole, x, y):
            return False
    return True


def geometry_contains(geom, x, y):
    gtype = geom.get("type")
    coords = geom.get("coordinates")
    if not coords:
        return False
    if gtype == "Polygon":
        return polygon_contains(coords, x, y)
    if gtype == "MultiPolygon":
        return any(polygon_contains(p, x, y) for p in coords)
    return False


def fetch_spc(day):
    url = SPC_URLS[day]
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read())
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        raise RuntimeError("day %d: SPC response is not a FeatureCollection" % day)
    features = data.get("features")
    if not isinstance(features, list) or not features:
        raise RuntimeError("day %d: SPC response has no polygons" % day)
    return features


def parse_iso(text, what):
    if not isinstance(text, str) or not text:
        raise RuntimeError("missing %s" % what)
    try:
        dt = datetime.datetime.fromisoformat(text)
    except ValueError:
        raise RuntimeError("unparseable %s: %r" % (what, text))
    if dt.tzinfo is None:
        raise RuntimeError("%s has no timezone: %r" % (what, text))
    return dt


def fmt_day(dt):
    return dt.strftime("%a %b %d").replace(" 0", " ")


def fmt_time(dt):
    # "%a %-I %p" is Linux-only; build it portably.
    hour = dt.hour % 12
    if hour == 0:
        hour = 12
    ap = "AM" if dt.hour < 12 else "PM"
    return "%s %d %s" % (dt.strftime("%a"), hour, ap)


def build_day(day, features, tz):
    if not features:
        raise RuntimeError("day %d: SPC response has no polygons" % day)
    # Reference feature for the valid window / issue time: all polygons
    # in one day's file share the same VALID/EXPIRE/ISSUE.
    ref = features[0].get("properties") or {}
    valid_from = parse_iso(ref.get("VALID_ISO"), "day %d VALID_ISO" % day)
    valid_to = parse_iso(ref.get("EXPIRE_ISO"), "day %d EXPIRE_ISO" % day)
    for f in features:
        p = f.get("properties") or {}
        if p.get("VALID_ISO") != ref.get("VALID_ISO"):
            raise RuntimeError("day %d: polygons disagree on VALID_ISO" % day)
    issued_raw = ref.get("ISSUE_ISO")
    issued = parse_iso(issued_raw, "day %d ISSUE_ISO" % day) if issued_raw else None

    # Highest-severity polygon covering the farm wins.
    best = None
    best_rank = 0
    for f in features:
        p = f.get("properties") or {}
        label = p.get("LABEL")
        if label not in SEVERITY:
            continue
        if not geometry_contains(f.get("geometry") or {}, LON, LAT):
            continue
        if SEVERITY[label] > best_rank:
            best = f
            best_rank = SEVERITY[label]
    if best is not None:
        bp = best.get("properties") or {}
        risk_code = bp.get("LABEL")
        # The polygon's own SPC fill color; fall back to white.
        color = bp.get("fill") or "#FFFFFF"
        matched = risk_code
    else:
        risk_code = "NONE"
        color = "#FFFFFF"
        matched = None

    vf = valid_from.astimezone(tz)
    vt = valid_to.astimezone(tz)
    tzabbr = vf.strftime("%Z") or "ET"
    return {
        "day": day,
        "dateLabel": fmt_day(vf),
        "riskCode": risk_code,
        "riskLabel": RISK_LABELS[risk_code],
        "color": color,
        "validFrom": vf.isoformat(timespec="seconds"),
        "validTo": vt.isoformat(timespec="seconds"),
        "validLabel": "%s - %s %s" % (fmt_time(vf), fmt_time(vt), tzabbr),
        "issued": (issued.astimezone(tz).isoformat(timespec="seconds")
                   if issued is not None else None),
        "source": SPC_URLS[day],
        "matchedPolygon": matched,
    }


def build(now):
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/New_York")
    except Exception:
        tz = datetime.timezone(datetime.timedelta(hours=-5))
    now_local = now.astimezone(tz)
    days = []
    for day in (1, 2, 3):
        days.append(build_day(day, fetch_spc(day), tz))
    fetched_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return {
        "station": "KNCCAROL120",
        "location": "CALABASH-FARM AT BRUNSWICK",
        "generatedAt": now_local.isoformat(timespec="seconds"),
        "updateTime": fetched_utc,
        "source": ("Storm Prediction Center categorical outlooks "
                   "(Day 1/2/3 GeoJSON) for 33.92,-78.57"),
        "sources": {"1": SPC_URLS[1], "2": SPC_URLS[2], "3": SPC_URLS[3]},
        "days": days,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=SRC_DIR,
                    help="directory to write spc-outlook.json into")
    args = ap.parse_args()
    try:
        from zoneinfo import ZoneInfo
        now = datetime.datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        now = datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=-5)))
    data = build(now)
    path = os.path.join(args.out, "spc-outlook.json")
    tmp = path + ".tmp"
    text = json.dumps(data, indent=2)
    with open(tmp, "w") as f:
        f.write(text)
        f.write("\n")
    os.replace(tmp, path)
    print(json.dumps(data, indent=2))
    print("WROTE %s (%d days)" % (path, len(data["days"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
