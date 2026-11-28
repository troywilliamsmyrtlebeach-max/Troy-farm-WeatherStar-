#!/usr/bin/env python3
"""Stage Battaglia sunset-beach.json for Sunset Beach NC (Latest Observations row swap).

Run by the Channel/International 15-min cron (weatherstar-channel-intl-15min-refresh)
as a staged Battaglia file, alongside farm-data.json, zone-forecast.txt,
regional-metars.xml, regional-map-metars.xml, outlook.json, monthly-precip.json
and hourly-forecast.json.

WHY A STAGED POINT FILE (Troy's decision 2026-11-23 ~9:24 PM): on Latest
Observations the Southport row is replaced by a Sunset Beach row. Sunset
Beach NC (33.88N 78.51W) has NO METAR station, so its row must read LIVE
conditions for that point — never a relabel of KCRE's or the farm's
readings (Troy's farm-only rule, Nov 21: no airport or town decides his
farm's sky; the same spirit applies here — Sunset Beach shows Sunset
Beach's own point weather, from Open-Meteo current weather, the same
source the Battaglia hourly rows already read).

SOURCE (single, Sunset Beach point only): Open-Meteo current weather for
Sunset Beach NC (33.88N 78.51W):
https://api.open-meteo.com/v1/forecast?latitude=33.88&longitude=-78.51
  &current=temperature_2m,apparent_temperature,relative_humidity_2m,
    weather_code,wind_speed_10m,wind_direction_10m
  &temperature_unit=fahrenheit&wind_speed_unit=mph
  &timezone=America%2FNew_York
No key is needed (public API, NOT Troy's credential).

FILE (one current-conditions row):
  { "station": "SUNSET-BEACH", "location": "Sunset Beach, NC",
    "latitude": 33.88, "longitude": -78.51,
    "generatedAt": "2026-11-23T21:30:00-05:00", "updateTime": "<fetch UTC>",
    "source": "Open-Meteo current 33.88,-78.51 (Sunset Beach NC point; no METAR station)",
    "tempF": 64, "feelsLikeF": 64, "relativeHumidity": 96,
    "conditions": "Cloudy", "weatherCode": 3,
    "windDir": "NW", "windSpeedMph": 5 }

WMO weather_code -> conditions word: the SAME map stage_hourly_forecast.py
uses for the farm hourly rows (copied, not re-derived) for PRECIP words
only. The clear/cloudy word comes from Open-Meteo total cloud cover
(fix 2026-11-24 — the WMO code alone reads Fair on overcast nights;
see build()). Only the word is staged here (the app draws the LO row
as text, no icon).

Rules (Troy's standing rules):
  - Whole numbers (temp, feels-like, humidity, wind).
  - "feelsLikeF" is Open-Meteo's own apparent_temperature — NOT a locally
    computed heat index / wind chill. (The LO row shows temp only; the
    feels-like is staged for completeness, same as the hourly rows.)
  - Wind direction always in front of speed; 0 mph reads "Calm" with no
    direction (windDir null — the app renders that, same as hourly).

SAFETY: on any fetch/parse failure, or a missing/unusable current block,
exit non-zero WITHOUT touching the staged file — the cron keeps the
previous file (values up to 15 min stale). A file whose generatedAt is
older than 2 hours is ignored by the app (the Sunset Beach row is simply
omitted and Latest Observations shows the other 6 rows + farm row),
so a stale file can never show old conditions as current, and no other
station's data is ever relabelled as Sunset Beach.

Usage: python3 stage_sunset_beach.py [--out DIR]
  default out = the Battaglia source dir (4000-battaglia/) under
  ~/workspace/github-push/troy-farm-weatherstar.
"""
import argparse, datetime, json, os, sys, urllib.parse, urllib.request

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
LAT, LON = 33.88, -78.51
USER_AGENT = "Muse-WeatherStar-Battaglia (troy farm, contact: KNCCAROL120)"
SRC_DIR = os.environ.get("BATTAGLIA_SRC_DIR",
                         os.path.expanduser("~/workspace/github-push/troy-farm-weatherstar/4000-battaglia"))

# WMO weather_code -> (staged iconCode, conditions word). Copied verbatim
# from stage_hourly_forecast.py's WMO_MAP — do not re-derive; the two
# scripts must agree word-for-word for the same sky.
WMO_MAP = {
    0: ("skc", "Clear"),
    1: ("few", "Mostly Clear"),
    2: ("sct", "Partly Cloudy"),
    3: ("ovc", "Cloudy"),
    45: ("fog", "Fog"),
    48: ("fog", "Fog"),
    51: ("light_drizzle", "Light Drizzle"),
    53: ("rain", "Drizzle"),
    55: ("rain", "Heavy Drizzle"),
    56: ("fzra", "Light Freezing Drizzle"),
    57: ("fzra", "Freezing Drizzle"),
    61: ("rain", "Light Rain"),
    63: ("rain", "Rain"),
    65: ("rain", "Heavy Rain"),
    66: ("fzra", "Light Freezing Rain"),
    67: ("fzra", "Freezing Rain"),
    71: ("light_snow", "Light Snow"),
    73: ("snow", "Snow"),
    75: ("snow", "Heavy Snow"),
    77: ("sleet", "Snow Grains"),
    80: ("rain", "Light Rain Showers"),
    81: ("rain_showers", "Rain Showers"),
    82: ("rain_showers", "Heavy Rain Showers"),
    85: ("snow_showers_lt", "Light Snow Showers"),
    86: ("snow_showers", "Heavy Snow Showers"),
    95: ("tsra", "Thunderstorm"),
    96: ("tsra_hail", "Thunderstorm with Hail"),
    99: ("tsra_hail", "Thunderstorm with Hail"),
}


def deg_to_compass(deg):
    """Wind direction in degrees -> 16-point compass (N, NNE, ...)."""
    if deg is None:
        return None
    pts = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return pts[int((float(deg) + 11.25) // 22.5) % 16]


def fetch_open_meteo():
    params = {
        "latitude": LAT, "longitude": LON,
        "current": ("temperature_2m,apparent_temperature,"
                    "relative_humidity_2m,weather_code,"
                    "cloud_cover,cloud_cover_low,cloud_cover_mid,"
                    "cloud_cover_high,wind_speed_10m,wind_direction_10m"),
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "timezone": "America/New_York",
    }
    url = OPEN_METEO_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def build(data, now):
    cur = data.get("current", {})
    if not cur:
        raise RuntimeError("Open-Meteo response has no current block")
    temp = cur.get("temperature_2m")
    if temp is None:
        raise RuntimeError("Open-Meteo current block has no temperature_2m")
    temp_f = int(round(float(temp)))
    feels = cur.get("apparent_temperature")
    feels_f = (int(round(float(feels))) if feels is not None else temp_f)
    rh = cur.get("relative_humidity_2m")
    rh_val = (int(round(float(rh))) if rh is not None else None)
    speed = cur.get("wind_speed_10m")
    speed_mph = (int(round(float(speed))) if speed is not None else 0)
    # Calm reads no direction (Troy's rule — the app renders "Calm").
    wind_dir = deg_to_compass(cur.get("wind_direction_10m")) if speed_mph > 0 else None
    code_raw = cur.get("weather_code")
    code_int = (int(code_raw) if code_raw is not None else None)
    # Sky word from cloud cover, not the WMO code alone (fix 2026-11-24,
    # same as the Channel script): the WMO code read Fair/Clear at
    # 23:01-23:16 EST Nov 23 while the area was overcast (KCRE BKN018,
    # farm Cloudy, total cloud cover ~95% high cloud the code misses).
    # Precip codes keep their WMO word; fog keeps Fog; the clear/cloudy
    # word maps total cloud cover: >=88% Cloudy, 51-87% Mostly Cloudy,
    # 26-50% Partly Cloudy, 11-25% Fair, <=10% Clear.
    if code_int in (45, 48):
        words = "Fog"
    elif code_int is not None and code_int >= 51:
        _icon_code, words = WMO_MAP.get(code_int, ("sct", "Partly Cloudy"))
    else:
        cover = cur.get("cloud_cover")
        if cover is None:
            raise RuntimeError("Open-Meteo current block has no cloud_cover")
        cover_pct = float(cover)
        if cover_pct >= 88:
            words = "Cloudy"
        elif cover_pct >= 51:
            words = "Mostly Cloudy"
        elif cover_pct >= 26:
            words = "Partly Cloudy"
        elif cover_pct >= 11:
            words = "Fair"
        else:
            words = "Clear"
    fetched_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return {
        "station": "SUNSET-BEACH",
        "location": "Sunset Beach, NC",
        "latitude": LAT,
        "longitude": LON,
        "generatedAt": now.isoformat(timespec="seconds"),
        "updateTime": fetched_utc,
        "source": "Open-Meteo current 33.88,-78.51 (Sunset Beach NC point; no METAR station)",
        "tempF": temp_f,
        "feelsLikeF": feels_f,
        "relativeHumidity": rh_val,
        "conditions": words,
        "weatherCode": code_int,
        "windDir": wind_dir,
        "windSpeedMph": speed_mph,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=SRC_DIR,
                    help="directory to write sunset-beach.json into")
    args = ap.parse_args()
    try:
        from zoneinfo import ZoneInfo
        now = datetime.datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        now = datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=-5)))
    try:
        data = build(fetch_open_meteo(), now)
    except Exception as ex:
        print("stage_sunset_beach: FAILED (%s); staged file untouched" % ex,
              file=sys.stderr)
        return 1
    path = os.path.join(args.out, "sunset-beach.json")
    tmp = path + ".tmp"
    text = json.dumps(data, indent=2)
    with open(tmp, "w") as f:
        f.write(text)
        f.write("\n")
    os.replace(tmp, path)
    print(json.dumps(data, indent=2))
    print("WROTE %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
