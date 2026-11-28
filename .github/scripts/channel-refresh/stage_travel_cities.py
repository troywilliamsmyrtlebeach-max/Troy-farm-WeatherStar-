#!/usr/bin/env python3
"""Stage Battaglia travel-cities.json for the 24 Travel Cities.

Run by the Channel/International 15-min cron (weatherstar-channel-intl-15min-refresh)
as a staged Battaglia file, alongside farm-data.json, zone-forecast.txt,
regional-metars.xml, regional-map-metars.xml, outlook.json, monthly-precip.json,
hourly-forecast.json, spc-outlook.json, sunset-beach.json.

WHY STAGED (2026-11-23, ?v=129): the ?v=128 Travel Cities screen fired
24 parallel api.weather.gov gridpoint fetches from every phone at boot.
That burst degrades NWS-side (0.5s sequential -> ~5s each in a 24-way
burst, worse on a cellular connection, and the app also fires its other
NWS calls at the same moment), so on a slow night the requests blow past
the app's 15s $.ajaxCORS timeout and every city honestly renders
NO TRAVEL DATA AVAILABLE — exactly what Troy saw on his phone at 23:29
EST Nov 23, hours after the ?v=128 smoke test passed from the sandbox.
The gridpoints themselves had also gone stale: NWS re-gridded and 21 of
24 stored cells shifted (New York OKX/32,34 now 404s outright; Boston
BOX/71,90 -> 71,101). This script resolves each city's gridpoint fresh
from the NWS points API every run, so gridpoints can never go stale
again, and stages ONE same-origin JSON the app reads instead of 24 live
cross-origin calls. The app keeps its live NWS fetch as the fallback
when the staged file is missing or older than 2 hours.

SOURCE (one city at a time, sequential — no burst): NWS api.weather.gov
  https://api.weather.gov/points/<lat>,<lon>   -> gridId/gridX/gridY
  https://api.weather.gov/gridpoints/<wfo>/<x>,<y>/forecast
No key is needed (public NWS API, NOT Troy's credential).

FILE (one entry per city, raw NWS fields — the app derives the icon
with its own GetWeatherRegionalIconFromIconLink + _TravelIconFromNwsIconLink
code, so there is still exactly ONE icon code path):
  { "station": "KNCCAROL120", "location": "CALABASH-FARM AT BRUNSWICK",
    "generatedAt": "2026-11-23T23:45:00-05:00",
    "source": "NWS api.weather.gov gridpoint forecasts for 24 travel cities",
    "cities": [ { "name": "Atlanta",
                  "iconLink": "https://api.weather.gov/icons/land/day/bkn?size=medium",
                  "shortForecast": "Mostly Cloudy",
                  "highF": 62, "lowF": 43,
                  "isDaytime": true, "dayName": "Monday" }, ... ] }

Day logic mirrors the app's GetTravelWeather exactly: periods[0] is
tonight when it is already night, so the daytime high is periods[1]
then (TodayShift = 0 if periods[0].isDaytime else 1); the overnight low
is periods[TodayShift + 1]. DayName is today when the daytime period is
today, tomorrow when periods[0] was tonight. Temperatures are rounded
whole degrees F, exactly as the app rounds them.

SAFETY: on any fetch/parse failure for a city, that city is simply
absent from the staged list (the app renders NO TRAVEL DATA AVAILABLE
for it, honestly — never a faked value). If fewer than 20 of 24 cities
succeed, exit non-zero WITHOUT touching the staged file — the cron keeps
the previous file and the app falls back to its live fetch. The app
ignores a file whose generatedAt is older than 2 hours (the cron
re-stages it every 15 min, so a stale file means the staging broke).

Usage: python3 stage_travel_cities.py [--out DIR]
  default out = the Battaglia source dir (4000-battaglia/) under
  ~/workspace/github-push/troy-farm-weatherstar.
"""
import argparse
import datetime
import json
import os
import sys
import time
import urllib.request

LAT_LON = [
    ("Atlanta", "33.749", "-84.388"),
    ("Boston", "42.3584", "-71.0598"),
    ("Chicago", "41.9796", "-87.9045"),
    ("Cleveland", "41.4995", "-81.6954"),
    ("Dallas", "32.8959", "-97.0372"),
    ("Denver", "39.7391", "-104.9847"),
    ("Detroit", "42.3314", "-83.0457"),
    ("Hartford", "41.7637", "-72.6851"),
    ("Houston", "29.7633", "-95.3633"),
    ("Indianapolis", "39.7684", "-86.158"),
    ("Los Angeles", "34.0522", "-118.2437"),
    ("Miami", "25.7743", "-80.1937"),
    ("Minneapolis", "44.98", "-93.2638"),
    ("New York", "40.7142", "-74.0059"),
    ("Norfolk", "36.8468", "-76.2852"),
    ("Orlando", "28.5383", "-81.3792"),
    ("Philadelphia", "39.9523", "-75.1638"),
    ("Pittsburgh", "40.4406", "-79.9959"),
    ("St. Louis", "38.6273", "-90.1979"),
    ("San Francisco", "37.7749", "-122.4194"),
    ("Seattle", "47.6062", "-122.3321"),
    ("Syracuse", "43.0481", "-76.1474"),
    ("Tampa", "27.9475", "-82.4584"),
    ("Washington DC", "38.8951", "-77.0364"),
]
MIN_CITIES = 20
USER_AGENT = "Muse-WeatherStar-Battaglia (troy farm, contact: KNCCAROL120)"
SRC_DIR = os.environ.get("BATTAGLIA_SRC_DIR",
                         os.path.expanduser("~/workspace/github-push/troy-farm-weatherstar/4000-battaglia"))


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                              "Accept": "application/geo+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def fetch_city(name, lat, lon, now_local):
    point = fetch_json("https://api.weather.gov/points/%s,%s" % (lat, lon))
    props = point.get("properties") or {}
    wfo, x, y = props.get("gridId"), props.get("gridX"), props.get("gridY")
    if not wfo or x is None or y is None:
        raise RuntimeError("%s: points API returned no gridpoint" % name)
    fc = fetch_json("https://api.weather.gov/gridpoints/%s/%s,%s/forecast"
                    % (wfo, x, y))
    periods = (fc.get("properties") or {}).get("periods")
    if not isinstance(periods, list) or len(periods) < 2:
        raise RuntimeError("%s: forecast has too few periods" % name)
    shift = 0 if periods[0].get("isDaytime") else 1
    day_p, night_p = periods[shift], periods[shift + 1]
    hi, lo = day_p.get("temperature"), night_p.get("temperature")
    if not isinstance(hi, (int, float)) or not isinstance(lo, (int, float)):
        raise RuntimeError("%s: non-numeric temperatures" % name)
    icon = day_p.get("icon")
    short = day_p.get("shortForecast")
    if not isinstance(icon, str) or not icon:
        raise RuntimeError("%s: no icon link" % name)
    if not isinstance(short, str) or not short:
        raise RuntimeError("%s: no shortForecast" % name)
    day_date = now_local.date()
    if shift == 1:
        day_date = day_date + datetime.timedelta(days=1)
    return {
        "name": name,
        "iconLink": icon,
        "shortForecast": short,
        "highF": int(round(hi)),
        "lowF": int(round(lo)),
        "isDaytime": bool(day_p.get("isDaytime")),
        "dayName": day_date.strftime("%A"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=SRC_DIR,
                    help="directory to write travel-cities.json into")
    args = ap.parse_args()
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/New_York")
    except Exception:
        tz = datetime.timezone(datetime.timedelta(hours=-5))
    now_local = datetime.datetime.now(tz)
    cities = []
    failures = []
    for name, lat, lon in LAT_LON:
        try:
            cities.append(fetch_city(name, lat, lon, now_local))
        except Exception as e:  # noqa: BLE001 - per-city: log, keep going
            failures.append("%s: %s" % (name, e))
        time.sleep(0.25)
    if failures:
        print("CITY FAILURES (%d):" % len(failures), file=sys.stderr)
        for f in failures:
            print("  " + f, file=sys.stderr)
    if len(cities) < MIN_CITIES:
        print("only %d/%d cities succeeded (need %d); NOT staging"
              % (len(cities), len(LAT_LON), MIN_CITIES), file=sys.stderr)
        return 1
    data = {
        "station": "KNCCAROL120",
        "location": "CALABASH-FARM AT BRUNSWICK",
        "generatedAt": now_local.isoformat(timespec="seconds"),
        "source": ("NWS api.weather.gov gridpoint forecasts "
                   "for 24 travel cities"),
        "cities": cities,
    }
    path = os.path.join(args.out, "travel-cities.json")
    tmp = path + ".tmp"
    text = json.dumps(data, indent=2)
    with open(tmp, "w") as f:
        f.write(text)
        f.write("\n")
    os.replace(tmp, path)
    print(json.dumps(data, indent=2))
    print("WROTE %s (%d cities)" % (path, len(cities)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
