#!/usr/bin/env python3
"""Stage Battaglia hourly-forecast.json for the farm point (P28).

Run by the Channel/International 15-min cron (weatherstar-channel-intl-15min-refresh)
as a staged Battaglia file, alongside farm-data.json, zone-forecast.txt,
regional-metars.xml, regional-map-metars.xml, outlook.json, monthly-precip.json.

SOURCE (single, farm point only): Open-Meteo hourly forecast for
CALABASH-FARM AT BRUNSWICK (33.92N 78.57W):
https://api.open-meteo.com/v1/forecast?latitude=33.92&longitude=-78.57
  &hourly=temperature_2m,apparent_temperature,relative_humidity_2m,
    dew_point_2m,precipitation_probability,weather_code,
    wind_speed_10m,wind_direction_10m
  &daily=sunrise,sunset&temperature_unit=fahrenheit&wind_speed_unit=mph
  &precipitation_unit=inch&timezone=America%2FNew_York&forecast_days=3
No key is needed (public API, NOT Troy's credential).

WHY OPEN-METEO (Troy's decision 2026-11-23 ~7:52 PM — "Match"): the
Channel/International hourly screen (hourly.mjs parseForecast) reads
this same Open-Meteo forecast, while this script used to read the NWS
hourly forecast (ILM 68,59) — and the two disagreed. On Nov 23 the NWS
called "Slight Chance Rain Showers" (pop 15–17%) at 7/10/11 PM and
midnight while Open-Meteo called overcast with pop 1–4% and no rain
icon anywhere, so Battaglia's hourly showed rain and Channel's did not.
Troy's standing rule (Nov 17) is that Battaglia's hourly matches his
Channel/International emulators exactly 100%, so this script now reads
the SAME source the Channel hourly reads. The NWS stays the source for
the Local Forecast words (zone-forecast.txt) — only the hourly rows
change source, and only so the two hourly screens agree.

FILE (24 hourly rows, next 24 hours from the current hour):
  { "station": "KNCCAROL120", "location": "CALABASH-FARM AT BRUNSWICK",
    "generatedAt": "2026-11-23T19:55:00-05:00", "updateTime": "<fetch UTC>",
    "source": "Open-Meteo hourly 33.92,-78.57 (same source as Channel/International hourly)",
    "hours": [ { "hourLabel": "7 PM", "weekday": "Mon", "tempF": 63,
                 "feelsLikeF": 63, "dewpointF": 63, "relativeHumidity": 100,
                 "shortForecast": "Cloudy", "windDir": null, "windSpeedMph": 0,
                 "pop": 1, "isDaytime": false,
                 "iconCode": "ovc",
                 "iconUrl": "https://battaglia.ddns.net/twc/images/r/Cloudy.gif" }, ... ] }

WMO weather_code -> staged iconCode (the codes _P28HourlyIconUrl in
twc3.js understands) -> the images/r/*.gif the Channel hourly shows
for the same code (icons.mjs getWeatherRegionalIconFromIconLink):
  0 Clear -> skc / Sunny.gif (night Clear-1992.gif)
  1 Mainly clear -> few / Sunny.gif (night Mostly-Clear.gif)
  2 Partly cloudy -> sct / Partly-Cloudy.gif (night Mostly-Clear.gif)
  3 Overcast -> ovc / Cloudy.gif
  45/48 Fog -> fog / Fog.gif
  51 Light drizzle -> light_drizzle / Scattered-Showers-1994-2.gif
    (night Scattered-Showers-Night.gif)
  53/55 Drizzle -> rain / Shower.gif
  56/57 Freezing drizzle -> fzra / Freezing-Rain-1992.gif
  61/63/65 Rain -> rain / Shower.gif
  66/67 Freezing rain -> fzra / Freezing-Rain-1992.gif
  71 Slight snow -> light_snow / Light-Snow.gif
  73/75 Snow -> snow / Heavy-Snow.gif
  77 Snow grains -> sleet / Sleet.gif
  80 Rain showers (slight) -> rain / Shower.gif
  81/82 Rain showers -> rain_showers / Rain-1992.gif
  85 Slight snow showers -> snow_showers_lt /
    Scattered-Snow-Showers-1994-2.gif (night Light-Snow.gif)
  86 Heavy snow showers -> snow_showers /
    Scattered-Snow-Showers-1994-2.gif (night Heavy-Snow.gif)
  95 Thunderstorm -> tsra / Thunderstorm.gif
  96/99 Thunderstorm with hail -> tsra_hail / ThunderSnow.gif

Rules (Troy's standing rules):
  - Whole numbers (temp, feels-like, dewpoint, humidity, wind, PoP);
    wind direction always in front of speed; 0 mph reads "Calm" with no
    direction (the app renders that, windDir null).
  - "feelsLikeF" is Open-Meteo's own apparent_temperature for the hour
    (the same value the Channel hourly shows as LIKE) — NOT a locally
    computed heat index / wind chill. The app shows it as LIKE always
    (Battaglia ?v=125); the Channel shows it only when it differs.
  - "isDaytime" is computed from Open-Meteo's own daily sunrise/sunset
    for the farm (sunrise <= hour < sunset), never from the viewer's
    clock — the same farm-solar rule the Channel hourly uses.
  - "iconUrl" is the images/r/*.gif the app actually draws for the
    hour's code + day/night (see gif_for, mirroring _P28HourlyIconUrl).
  - NWS hourly carries no wind-gust field and neither does Open-Meteo's
    hourly wind_speed_10m, so hourly rows show sustained wind only —
    same as the Channel.

SAFETY: on any fetch/parse failure, or fewer than 24 usable periods,
exit non-zero WITHOUT touching the staged file — the cron keeps the
previous file (values up to 15 min stale). A file whose generatedAt is
older than 2 hours is ignored by the app (screen shows Failed, cycle
skips it), so a stale file can never show old hours as current.

Usage: python3 stage_hourly_forecast.py [--out DIR]
  default out = the Battaglia source dir (4000-battaglia/) under
  ~/workspace/github-push/troy-farm-weatherstar.
"""
import argparse, datetime, json, os, sys, urllib.parse, urllib.request

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
LAT, LON = 33.92, -78.57
USER_AGENT = "Muse-WeatherStar-Battaglia (troy farm, contact: KNCCAROL120)"
SRC_DIR = os.environ.get("BATTAGLIA_SRC_DIR",
                         os.path.expanduser("~/workspace/github-push/troy-farm-weatherstar/4000-battaglia"))
N_HOURS = 24
GIF_BASE = "https://battaglia.ddns.net/twc/images/r/"

# WMO weather_code -> (staged iconCode, shortForecast words).
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


def gif_for(icon_code, is_daytime):
    """Mirror of _P28HourlyIconUrl in twc3.js: staged code + day/night
    -> the images/r/*.gif the Channel hourly shows for the same sky."""
    day = bool(is_daytime)
    if icon_code in ("skc", "cold", "hot"):
        gif = "Sunny.gif" if day else "Clear-1992.gif"
    elif icon_code == "few":
        gif = "Sunny.gif" if day else "Mostly-Clear.gif"
    elif icon_code == "sct":
        gif = "Partly-Cloudy.gif" if day else "Mostly-Clear.gif"
    elif icon_code == "bkn":
        gif = "Mostly-Cloudy.gif" if day else "Mostly-Clear.gif"
    elif icon_code == "ovc":
        gif = "Cloudy.gif"
    elif icon_code == "fog":
        gif = "Fog.gif"
    elif icon_code == "light_drizzle":
        gif = ("Scattered-Showers-1994-2.gif" if day
               else "Scattered-Showers-Night.gif")
    elif icon_code == "rain":
        gif = "Shower.gif"
    elif icon_code in ("rain_showers", "rain_showers_hi"):
        gif = "Rain-1992.gif"
    elif icon_code in ("rain_sleet", "snow_sleet", "sleet"):
        gif = "Sleet.gif"
    elif icon_code in ("snow", "blizzard"):
        gif = "Heavy-Snow.gif"
    elif icon_code == "light_snow":
        gif = "Light-Snow.gif"
    elif icon_code == "snow_showers":
        gif = ("Scattered-Snow-Showers-1994-2.gif" if day
               else "Heavy-Snow.gif")
    elif icon_code == "snow_showers_lt":
        gif = ("Scattered-Snow-Showers-1994-2.gif" if day
               else "Light-Snow.gif")
    elif icon_code in ("tsra", "tsra_sct", "tsra_hi"):
        gif = "Thunderstorm.gif"
    elif icon_code == "tsra_hail":
        gif = "ThunderSnow.gif"
    elif icon_code in ("fzra", "mix"):
        gif = "Freezing-Rain-1992.gif"
    else:
        gif = "Partly-Cloudy.gif" if day else "Mostly-Clear.gif"
    return GIF_BASE + gif


def fmt_hour_12(hour24):
    ap = "AM" if hour24 < 12 else "PM"
    h = hour24 % 12
    if h == 0:
        h = 12
    return "%d %s" % (h, ap)


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
        "hourly": ("temperature_2m,apparent_temperature,"
                   "relative_humidity_2m,dew_point_2m,"
                   "precipitation_probability,weather_code,"
                   "wind_speed_10m,wind_direction_10m"),
        "daily": "sunrise,sunset",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "America/New_York",
        "forecast_days": 3,
    }
    url = OPEN_METEO_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def build(data, now):
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    if not times:
        raise RuntimeError("Open-Meteo response has no hourly times")
    # Sunrise/sunset per date (farm-local) for the isDaytime check.
    daily = data.get("daily", {})
    sun = {}
    for d, sr, ss in zip(daily.get("time", []), daily.get("sunrise", []),
                         daily.get("sunset", [])):
        try:
            sun[d] = (datetime.datetime.fromisoformat(sr),
                      datetime.datetime.fromisoformat(ss))
        except ValueError:
            continue
    # Index of the current hour in the farm-local time array. The API
    # times are naive farm-local ("2026-11-23T19:00"), so compare naive.
    cur = now.replace(tzinfo=None, minute=0, second=0, microsecond=0)
    start_idx = None
    for i, t in enumerate(times):
        try:
            ht = datetime.datetime.fromisoformat(t)
        except ValueError:
            continue
        if ht >= cur:
            start_idx = i
            break
    if start_idx is None:
        raise RuntimeError("Open-Meteo hourly times do not reach the current hour")
    n = len(times)
    cols = {k: hourly.get(k, []) for k in
            ("temperature_2m", "apparent_temperature",
             "relative_humidity_2m", "dew_point_2m",
             "precipitation_probability", "weather_code",
             "wind_speed_10m", "wind_direction_10m")}
    hours = []
    for i in range(start_idx, min(start_idx + N_HOURS, n)):
        try:
            ht = datetime.datetime.fromisoformat(times[i])
        except ValueError:
            continue
        temp = cols["temperature_2m"][i]
        if temp is None:
            continue
        temp_f = int(round(float(temp)))
        feels = cols["apparent_temperature"][i]
        feels_f = (int(round(float(feels))) if feels is not None else temp_f)
        dew = cols["dew_point_2m"][i]
        dew_f = (int(round(float(dew))) if dew is not None else None)
        rh = cols["relative_humidity_2m"][i]
        rh_val = (int(round(float(rh))) if rh is not None else None)
        pop = cols["precipitation_probability"][i]
        pop_val = (int(round(float(pop))) if pop is not None else None)
        speed = cols["wind_speed_10m"][i]
        speed_mph = (int(round(float(speed))) if speed is not None else 0)
        # Calm reads no direction (Troy's rule — the app renders "Calm").
        wind_dir = deg_to_compass(cols["wind_direction_10m"][i]) if speed_mph > 0 else None
        code_raw = cols["weather_code"][i]
        code_int = (int(code_raw) if code_raw is not None else None)
        icon_code, words = WMO_MAP.get(code_int, ("sct", "Partly Cloudy"))
        # Daytime from the farm's own sunrise/sunset for that date
        # (both naive farm-local, like ht).
        daypart = sun.get(ht.date().isoformat())
        if daypart:
            is_day = daypart[0] <= ht < daypart[1]
        else:
            is_day = 6 <= ht.hour < 19
        hours.append({
            "hourLabel": fmt_hour_12(ht.hour),
            "weekday": ht.strftime("%a"),
            "tempF": temp_f,
            "feelsLikeF": feels_f,
            "dewpointF": dew_f,
            "relativeHumidity": rh_val,
            "shortForecast": words,
            "windDir": wind_dir,
            "windSpeedMph": speed_mph,
            "pop": pop_val,
            "isDaytime": bool(is_day),
            "iconCode": icon_code,
            "iconUrl": gif_for(icon_code, bool(is_day)),
        })
    if len(hours) < N_HOURS:
        raise RuntimeError("only %d usable hourly periods (need %d)"
                           % (len(hours), N_HOURS))
    fetched_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return {
        "station": "KNCCAROL120",
        "location": "CALABASH-FARM AT BRUNSWICK",
        "generatedAt": now.isoformat(timespec="seconds"),
        "updateTime": fetched_utc,
        "source": "Open-Meteo hourly 33.92,-78.57 (same source as Channel/International hourly)",
        "hours": hours,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=SRC_DIR,
                    help="directory to write hourly-forecast.json into")
    args = ap.parse_args()
    try:
        from zoneinfo import ZoneInfo
        now = datetime.datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        now = datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=-5)))
    data = build(fetch_open_meteo(), now)
    path = os.path.join(args.out, "hourly-forecast.json")
    tmp = path + ".tmp"
    text = json.dumps(data, indent=2)
    with open(tmp, "w") as f:
        f.write(text)
        f.write("\n")
    os.replace(tmp, path)
    print(json.dumps(data, indent=2))
    print("WROTE %s (%d hours)" % (path, len(data["hours"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
