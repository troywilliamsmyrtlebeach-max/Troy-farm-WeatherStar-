#!/usr/bin/env python3
"""Stage sunset-beach.json for Channel / International / stream (P29).

Run by the Channel/International 15-min cron
(weatherstar-channel-intl-15min-refresh) as a staged data file,
alongside farm-data.json and the Battaglia files.

WHY (Troy's decision 2026-11-23 ~9:24 PM): on Latest Observations,
Southport is replaced by Sunset Beach and Wilmington by Calabash.
Sunset Beach has no METAR station, so its readings come from
Open-Meteo current weather at its own point (33.88N 78.51W) — never
relabeled KCRE or farm readings. Calabash needs no staged file: it
reads the farm's own live conditions (farm-data.json) in the app,
because the farm IS in Calabash.

SOURCE (single, Sunset Beach point only): Open-Meteo current weather
for Sunset Beach NC (33.88N 78.51W):
https://api.open-meteo.com/v1/forecast?latitude=33.88&longitude=-78.51
  &current=temperature_2m,wind_speed_10m,wind_direction_10m,weather_code
  &temperature_unit=celsius&wind_speed_unit=kmh
  &timezone=America%2FNew_York
No key is needed (public API, NOT Troy's credential).

FILE (one small JSON, staged into all three app dirs):
  { "station": "Sunset Beach", "latitude": 33.88, "longitude": -78.51,
    "generatedAt": "2026-11-23T21:35:00-05:00", "updateTime": "<fetch UTC>",
    "source": "Open-Meteo current 33.88,-78.51",
    "temperatureC": 18.3, "windSpeedKph": 11.0,
    "windDirectionDeg": 270, "sky": "Cloudy" }

The app (latestobservations.mjs) reads temperatureC / windSpeedKph /
windDirectionDeg / sky straight into an LO row, in the same units the
NWS rows arrive in (Celsius, kph, degrees-from) — the row renderer
converts to F/mph and shows "Calm" at 0, direction + speed otherwise.

Sky word uses the farm's own graded word set, so the row agrees with
the farm row's words. Precip words come from the WMO code; the
clear/cloudy word comes from Open-Meteo total cloud cover (fix
2026-11-24 — the WMO code alone reads Fair on overcast nights):
>=88% Cloudy, 51-87% Mostly Cloudy, 26-50% Partly Cloudy, 11-25%
Fair, <=10% Clear. WMO codes for reference: 0 Clear, 1 Fair,
2 Partly Cloudy, 3 Cloudy,
45/48 Fog, 51 Light Rain, 53/55 Rain, 56/57 Freezing Rain,
61/63 Rain, 65 Heavy Rain, 66/67 Freezing Rain, 71 Light Snow,
73/75 Snow, 77 Snow, 80/81 Rain, 82 Heavy Rain, 85/86 Snow,
95/96/99 Thunderstorm.

SAFETY: on any fetch/parse failure, or any missing numeric field,
exit non-zero WITHOUT touching any staged file — the cron keeps the
previous files. The app ignores a file whose generatedAt is older
than 2 hours (the row is then omitted this cycle), so a stale file
can never show old conditions as current.

Usage: python3 stage_sunset_beach.py
  writes sunset-beach.json into 4000-myrtle-intl/, 4000-exact/ and
  4000-myrtle-stream/ under ~/workspace/github-push/troy-farm-weatherstar.
"""
import datetime
import json
import os
import sys
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
LAT, LON = 33.88, -78.51
USER_AGENT = "Muse-WeatherStar-Channel (troy farm, contact: KNCCAROL120)"
SRC_BASE = os.environ.get("CHANNEL_SRC_BASE", os.path.expanduser("~/workspace/github-push/troy-farm-weatherstar"))
DIRS = ["4000-myrtle-intl", "4000-exact", "4000-myrtle-stream"]

# WMO weather_code -> Channel sky word (same graded set as the farm row).
WMO_SKY = {
    0: "Clear",
    1: "Fair",
    2: "Partly Cloudy",
    3: "Cloudy",
    45: "Fog",
    48: "Fog",
    51: "Light Rain",
    53: "Rain",
    55: "Rain",
    56: "Freezing Rain",
    57: "Freezing Rain",
    61: "Rain",
    63: "Rain",
    65: "Heavy Rain",
    66: "Freezing Rain",
    67: "Freezing Rain",
    71: "Light Snow",
    73: "Snow",
    75: "Snow",
    77: "Snow",
    80: "Rain",
    81: "Rain",
    82: "Heavy Rain",
    85: "Snow",
    86: "Snow",
    95: "Thunderstorm",
    96: "Thunderstorm",
    99: "Thunderstorm",
}


def fetch_open_meteo():
    params = {
        "latitude": LAT, "longitude": LON,
        "current": ("temperature_2m,wind_speed_10m,wind_direction_10m,"
                    "weather_code,cloud_cover,cloud_cover_low,"
                    "cloud_cover_mid,cloud_cover_high"),
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
        "timezone": "America/New_York",
    }
    url = OPEN_METEO_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def build(data, now):
    cur = data.get("current", {})
    temp = cur.get("temperature_2m")
    speed = cur.get("wind_speed_10m")
    wdir = cur.get("wind_direction_10m")
    code = cur.get("weather_code")
    if temp is None or speed is None or wdir is None or code is None:
        raise RuntimeError("Open-Meteo current response missing a field: %r" % (cur,))
    try:
        code_int = int(code)
    except (TypeError, ValueError):
        raise RuntimeError("Open-Meteo weather_code not an int: %r" % (code,))
    # Sky from cloud cover, not the WMO code alone (fix 2026-11-24):
    # the WMO code read Fair/Clear at 23:01-23:16 EST Nov 23 while the
    # area was overcast (KCRE BKN018, farm Cloudy, total cloud cover
    # ~95% high cloud the code misses). Precip codes still use the WMO
    # word (rain/snow/thunderstorm); fog keeps Fog; anything else maps
    # total cloud cover to the graded word.
    cover = cur.get("cloud_cover")
    if code_int in (45, 48):
        sky = "Fog"
    elif code_int >= 51:
        sky = WMO_SKY.get(code_int, "Partly Cloudy")
    else:
        if cover is None:
            raise RuntimeError("Open-Meteo current response missing cloud_cover: %r" % (cur,))
        cover_pct = float(cover)
        if cover_pct >= 88:
            sky = "Cloudy"
        elif cover_pct >= 51:
            sky = "Mostly Cloudy"
        elif cover_pct >= 26:
            sky = "Partly Cloudy"
        elif cover_pct >= 11:
            sky = "Fair"
        else:
            sky = "Clear"
    fetched_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return {
        "station": "Sunset Beach",
        "latitude": LAT,
        "longitude": LON,
        "generatedAt": now.isoformat(timespec="seconds"),
        "updateTime": fetched_utc,
        "source": "Open-Meteo current 33.88,-78.51",
        "temperatureC": round(float(temp), 1),
        "windSpeedKph": round(float(speed), 1),
        "windDirectionDeg": int(round(float(wdir))) % 360,
        "sky": sky,
    }


def main():
    now = datetime.datetime.now(ZoneInfo("America/New_York"))
    try:
        data = fetch_open_meteo()
        payload = build(data, now)
    except Exception as exc:
        print("ERROR: sunset-beach stage failed (%s); files untouched" % (exc,),
              file=sys.stderr)
        return 1
    text = json.dumps(payload, indent=2) + "\n"
    for d in DIRS:
        path = os.path.join(SRC_BASE, d, "sunset-beach.json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    temp_f = payload["temperatureC"] * 9 / 5 + 32
    wind_mph = payload["windSpeedKph"] * 0.621371
    print("Sunset Beach staged: %.1fF (%.1fC), wind %.0f mph, %s, "
          "generatedAt %s" % (temp_f, payload["temperatureC"], wind_mph,
                              payload["sky"], payload["generatedAt"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
