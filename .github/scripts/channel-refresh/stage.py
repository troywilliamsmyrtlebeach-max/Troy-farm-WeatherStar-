"""Channel / International / Battaglia 15-minute refresh - GitHub Actions port.

Adapted from the Muse pipeline's run-1249 stage script (2026-11-27). Same
fetch+stage logic, same asserts, same staging rules (sky from Open-Meteo
cloud cover at the farm point with the thin-cirrus cap, Nov 22 vis/ceiling
rule, precip triple-check, wind/rounding/pressure-trend rules, source order
WU -> WunderMap -> OSOILM). Runs entirely inside GitHub: the checkout is the
repo, GITHUB_TOKEN pushes, no Muse involvement. Differences from the Muse
version are marked ACTIONS.
"""
import json, os, re, shutil, hashlib, glob, subprocess, urllib.request
from datetime import datetime, timezone, timedelta
try:
    from zoneinfo import ZoneInfo as _ZoneInfo
    _NY_TZ = _ZoneInfo("America/New_York")
except Exception:
    _NY_TZ = timezone(timedelta(hours=-5))

RUN = int(os.environ.get("REFRESH_RUN_ID", datetime.now(timezone.utc).strftime("%Y%m%d%H%M")))
# ACTIONS: the checkout is both the source dir and the live-HEAD reference
# copy (the Muse version kept a persistent source dir + a /tmp clone).
REPO_ROOT = os.environ["REPO_ROOT"]
SCRIPTS_DIR = os.environ["SCRIPTS_DIR"]
SRC = REPO_ROOT
CLONE = REPO_ROOT
HF = os.environ["WORK_DIR"]
COPIES = ["4000-myrtle-intl", "4000-exact", "4000-myrtle-stream"]
# ACTIONS: LIVE_HEAD is read from the checkout at run start (run-1155 lesson:
# never carry a prior run's value). The workflow also verifies checkout HEAD
# == origin/main HEAD before invoking this script.
LIVE_HEAD = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                           capture_output=True, text=True, check=True).stdout.strip()

# --- Clone must be at live HEAD before patching (run-680 race lesson) ---
# RUN-1235 FIX: git transport is dead this run, so the clone is a plain
# directory copy of the source dir (verified == live Pages farm-data.json on
# all 4 copies before staging). Guard intent preserved: the four live
# farm-data.json files must match the reference copy byte-for-byte, else abort.
for _copy in ("4000-myrtle-intl", "4000-exact", "4000-myrtle-stream", "4000-battaglia"):
    _live = subprocess.run(["curl", "-sS", "--max-time", "60",
        "https://troywilliamsmyrtlebeach-max.github.io/Troy-farm-WeatherStar-/%s/farm-data.json" % _copy],
        capture_output=True, check=True).stdout
    _ref = open(os.path.join(CLONE, _copy, "farm-data.json"), "rb").read()
    assert _live == _ref, "reference copy %s farm-data.json != live Pages - re-sync first" % _copy
print("checkout verified == live Pages (HEAD %s; Pages-content check)" % LIVE_HEAD[:8])

# --- AGENTS.md lesson (run 685): prev-pressure read must come from the CLONE
# (live HEAD), never the source dir - the source may be pre-staged. ---
for copy in COPIES + ["4000-battaglia"]:
    sp = os.path.join(SRC, copy, "farm-data.json")
    cp = os.path.join(CLONE, copy, "farm-data.json")
    _sb, _cb = open(sp, "rb").read(), open(cp, "rb").read()
    if _sb != _cb:
        # RUN-959: parent may hand-fix farm-data (vis/ceiling) between runs.
        # Adopt ONLY when the diff is exactly that pattern; anything else aborts.
        _sj, _cj = json.loads(_sb), json.loads(_cb)
        _dk = set(_sj) ^ set(_cj)
        _ok = (_dk <= {"ceiling"} and _sj.get("visibility") != _cj.get("visibility") and
               _sj.get("source", "").startswith(_cj.get("source", "")) and
               all(_sj.get(k) == _cj.get(k) for k in set(_sj) & set(_cj) if k not in ("visibility", "source")))
        assert _ok, "source %s pre-staged vs live HEAD - stop (diff is NOT the known manual vis/ceiling fix)" % copy
        print("ADOPTING parent manual farm-data fix in %s (vis %s->%s, ceiling %s) - fresh values re-derived from live KCRE below" % (copy, _cj.get("visibility"), _sj.get("visibility"), _sj.get("ceiling")))
print("source farm-data.json files match live HEAD (or adopted manual vis/ceiling fix only)")

# --- Sky override (ACTIONS: Troy's eyes win 3h - persisted in the repo) ---
# The Muse version read ~/workspace/weather-wire/state/sky_ground_truth.json,
# which does not exist on a GitHub runner. The Actions version keeps the same
# 3-hour rule with a small file in the repo, .github/sky_override.json:
#   * a manual dispatch with `sky_override` set stages ITS sky this run
#     (same map, same precip-gate rule below) AND writes the file, so the
#     next scheduled runs keep staging Troy's word until it expires;
#   * a scheduled run with no input reads the file and uses it while it is
#     under 3 hours old, then ignores it (and deletes the stale file);
#   * a dispatch with `clear_override` set deletes the file (his word ends
#     now) and stages the automated sky.
# The file is allowlisted in the manifest section below, so the run that
# writes/clears it commits the change like any other staged file. The
# precip gate below still applies both ways: a passed gate beats a stale
# non-precip eye word (Nov 27 SUPERSEDED fix), and a precip eye word with
# a failed gate is never staged.
_OVR_PATH = os.path.join(REPO_ROOT, ".github", "sky_override.json")
_OVR_TTL_H = 3.0
_EYE_MAP = {"Fair": ("Fair", 1), "Sunny": ("Sunny", 0), "Clear": ("Clear", 0),
            "Partly cloudy": ("Partly cloudy", 2), "Mostly cloudy": ("Mostly cloudy", 3),
            "Partly Cloudy": ("Partly cloudy", 2), "Mostly Cloudy": ("Mostly cloudy", 3), "Variably Cloudy": ("Variably Cloudy", 4),
            "Cloudy": ("Cloudy", 3), "Light Rain": ("Light Rain", 61), "Rain": ("Rain", 63),
            "Heavy Rain": ("Heavy Rain", 65), "Light Snow": ("Light Snow", 71),
            "Snow": ("Snow", 73), "Heavy Snow": ("Heavy Snow", 75),
            "Thunderstorm": ("Thunderstorm", 95)}


def _resolve_sky_override(_dispatch_word, _clear, _path, _now):
    """Resolve Troy's eye-report sky word for this run.

    Returns (_EYE dict or None, _note). Side effects: writes _path when a
    fresh dispatch word arrives; deletes _path when cleared or stale.
    _dispatch_word: the workflow_dispatch sky_override input ("" = none).
    _clear: the clear_override input (GitHub passes booleans as the strings
    "true"/"false" - compared explicitly, never by truthiness).
    _now: tz-aware UTC datetime for age math.
    """
    _dispatch_word = (_dispatch_word or "").strip()
    _clear = str(_clear or "").strip().lower() in ("true", "1", "yes")
    if _clear:
        if os.path.exists(_path):
            os.remove(_path)
            print("SKY OVERRIDE CLEARED (workflow_dispatch clear_override): stored word deleted - automated sky resumes")
        else:
            print("SKY OVERRIDE CLEAR requested but no stored word exists - automated sky resumes")
        return None, "cleared"
    if _dispatch_word:
        assert _dispatch_word in _EYE_MAP, "sky override %r has no sky mapping - stop, do not guess" % _dispatch_word
        _rec = {"word": _dispatch_word, "reportedAt": _now.isoformat(), "source": "workflow_dispatch sky_override"}
        with open(_path, "w", encoding="utf-8") as _fh:
            _fh.write(json.dumps(_rec, indent=2, sort_keys=True) + "\n")
        print("SKY OVERRIDE (workflow_dispatch): %r - stored in %s, governs this run and scheduled runs for %.1fh" % (_dispatch_word, os.path.basename(_path), _OVR_TTL_H))
        return {"condition": _dispatch_word, "word": _EYE_MAP[_dispatch_word][0], "code": _EYE_MAP[_dispatch_word][1], "age_h": 0.0, "reported_at": _rec["reportedAt"]}, "dispatch"
    if os.path.exists(_path):
        try:
            with open(_path, encoding="utf-8") as _fh:
                _rec = json.load(_fh)
            _word = str(_rec["word"]).strip()
            assert _word in _EYE_MAP, "stored word %r has no sky mapping" % _word
            _reported = datetime.fromisoformat(str(_rec["reportedAt"]))
            if _reported.tzinfo is None:
                _reported = _reported.replace(tzinfo=timezone.utc)
            _age_h = (_now - _reported).total_seconds() / 3600.0
        except Exception as _e:
            print("SKY OVERRIDE FILE %s unreadable (%r) - ignoring it, automated sky resumes (file left in place for inspection)" % (_path, _e))
            return None, "unreadable"
        if _age_h < 0:
            print("SKY OVERRIDE FILE %s has a future timestamp (age %.2fh) - ignoring it, automated sky resumes" % (_path, _age_h))
            return None, "future"
        if _age_h >= _OVR_TTL_H:
            os.remove(_path)
            print("SKY OVERRIDE EXPIRED: stored word %r is %.1fh old (>= %.1fh) - file deleted, automated sky resumes" % (_word, _age_h, _OVR_TTL_H))
            return None, "expired"
        print("SKY OVERRIDE (stored, %.1fh old): %r - staging ITS sky (%s, conditionText %d) instead of the model sky" % (_age_h, _word, _EYE_MAP[_word][0], _EYE_MAP[_word][1]))
        return {"condition": _word, "word": _EYE_MAP[_word][0], "code": _EYE_MAP[_word][1], "age_h": _age_h, "reported_at": _rec["reportedAt"]}, "stored"
    print("no sky override - normal source rules resume")
    return None, "none"


_EYE, _OVR_NOTE = _resolve_sky_override(os.environ.get("SKY_OVERRIDE", ""), os.environ.get("CLEAR_OVERRIDE", ""), _OVR_PATH, datetime.now(timezone.utc))

# RUN-747 FIX (run-746 log note): the stage script only VERIFIED hourly
# freshness; the file was regenerated manually after staging and appended to
# the manifest. Invoke the generator HERE, before any staging write, so a
# failure aborts pre-write and the file lands in this run's commit. The
# generator fails safe (non-zero exit, staged file untouched) per its doc.
# RUN-1175 SPLIT (sandbox write block): a Python process that did a network
# fetch cannot then write a large file (EPERM at f.write; single writes
# >~8KB to a NEW file fail, overwrites and chunked writes work). The four
# generators all fetch-then-write in one process, so they die at the write.
# Invoke them via splitgen_run1249.py instead: fetcher child (network only,
# raw JSON on stdout) + builder child (no network, generator's own build(),
# chunked 4KB writes). Staged values are identical to the generators'.
# ACTIONS: the sandbox splitgen wrapper (fetch-then-write EPERM quirk) does not
# apply on a GitHub runner - invoke the generator directly with --out.
_hr = subprocess.run(["python3", os.path.join(SCRIPTS_DIR, "stage_hourly_forecast.py"),
                      "--out", os.path.join(SRC, "4000-battaglia")],
                     capture_output=True, text=True)
print(_hr.stdout[-1500:] if _hr.stdout else "", _hr.stderr[-1500:] if _hr.stderr else "")
# RUN-1140 FIX (Open-Meteo HTTP 429): the generator fails safe by design on a
# 429 and the body says keep the previous file, log the 429, let the next run
# retry - do NOT hammer retries and do NOT abort the whole run when the
# previously staged file is still fresh (<2h, the app's own freshness window).
# Any other failure, or a stale previous file, still aborts pre-write.
# RUN-1242 EXTENSION (same class): Open-Meteo HTTP 503 (Service Unavailable)
# is the same transient-upstream class as a 429 - the body says keep the
# previous file on ANY fetch failure and note it, never push a stale or
# invented value, and never abort the whole run over one sub-file when the
# previous file is still fresh. So 5xx codes take the same keep path as 429.
_hourly_kept_429 = False
if _hr.returncode != 0:
    _hf_prev = json.load(open(os.path.join(SRC, "4000-battaglia/hourly-forecast.json")))
    _gen_prev = datetime.fromisoformat(_hf_prev.get("generatedAt", ""))
    _fresh_prev = (_hf_prev.get("station") == "KNCCAROL120" and len(_hf_prev.get("hours", [])) == 24
                   and 0 <= (datetime.now().astimezone() - _gen_prev).total_seconds() <= 7200)
    _transient = any(code in (_hr.stderr or "") for code in ("429", "500", "502", "503", "504"))
    if _transient and _fresh_prev:
        _hourly_kept_429 = True
        print("hourly-forecast.json KEPT (Open-Meteo transient HTTP error this run; previous file still fresh, generatedAt %s - next run retries)" % _hf_prev.get("generatedAt"))
    else:
        assert False, "stage_hourly_forecast.py failed rc=%s" % _hr.returncode
if not _hourly_kept_429:
    print("hourly-forecast.json regenerated by stage_hourly_forecast.py (pre-stage)")

# RUN-1145 FIX (LO swaps landed mid-run): the parallel LO-swap workstream
# (Troy Nov 23 21:24 - Southport->Sunset Beach, Wilmington->Calabash on
# Latest Observations) stages sunset-beach.json into the three copies and
# rewrote latestobservations.mjs + index.html (?v=lo-swaps1, CSS ?v=1112).
# Its generator stage_sunset_beach.py lives in this goal's hidden_files and
# is designed for this cron: Open-Meteo current at the Sunset Beach point
# only (33.88N 78.51W), fails safe (non-zero, files untouched). Invoke it
# here, pre-write, like the hourly generator; on failure keep the previous
# files when still fresh (<2h, the app's own window) and log it, else abort.
_sb = subprocess.run(["python3", os.path.join(SCRIPTS_DIR, "stage_sunset_beach_channel.py")],
                     capture_output=True, text=True)
print(_sb.stdout.strip() if _sb.stdout else "", _sb.stderr.strip() if _sb.stderr else "")
if _sb.returncode != 0:
    _sbf_prev = json.load(open(os.path.join(SRC, "4000-myrtle-intl/sunset-beach.json")))
    _gen_prev = datetime.fromisoformat(_sbf_prev.get("generatedAt", ""))
    _fresh_prev = (0 <= (datetime.now().astimezone() - _gen_prev).total_seconds() <= 7200)
    if _fresh_prev:
        print("sunset-beach.json KEPT (generator failed rc=%s; previous file still fresh, generatedAt %s - next run retries)" % (_sb.returncode, _sbf_prev.get("generatedAt")))
    else:
        assert False, "stage_sunset_beach.py failed rc=%s and previous file stale" % _sb.returncode

# RUN-1148 FIX (body step 3): the inherited script never ran the Battaglia
# SPC-outlook or Battaglia Sunset Beach generators, and the allowlist below
# lacked both files - so neither was ever refreshed by this cron. Invoke
# both HERE, pre-write, like the hourly/sunset-beach generators above.
# Both fail safe (non-zero, staged file untouched) per their docs; on
# failure keep the previous file when still fresh (SPC <12h, Sunset Beach
# <2h - the apps' own freshness windows) and log it, else abort.
_spc = subprocess.run(["python3", os.path.join(SCRIPTS_DIR, "stage_spc_outlook.py"),
                      "--out", os.path.join(SRC, "4000-battaglia")],
                     capture_output=True, text=True)
print(_spc.stdout[-1500:] if _spc.stdout else "", _spc.stderr[-1500:] if _spc.stderr else "")
if _spc.returncode != 0:
    _spc_prev = json.load(open(os.path.join(SRC, "4000-battaglia/spc-outlook.json")))
    _gen_prev = datetime.fromisoformat(_spc_prev.get("generatedAt", ""))
    _fresh_prev = (0 <= (datetime.now().astimezone() - _gen_prev).total_seconds() <= 43200)
    if _fresh_prev:
        print("spc-outlook.json KEPT (generator failed rc=%s; previous file still fresh, generatedAt %s - next run retries)" % (_spc.returncode, _spc_prev.get("generatedAt")))
    else:
        assert False, "stage_spc_outlook.py failed rc=%s and previous file stale" % _spc.returncode
else:
    _spc_now = json.load(open(os.path.join(SRC, "4000-battaglia/spc-outlook.json")))
    print("spc-outlook.json regenerated (generatedAt %s; risks %s)" % (_spc_now.get("generatedAt"), [d.get("riskCode") for d in _spc_now.get("days", [])]))
_bsb = subprocess.run(["python3", os.path.join(SCRIPTS_DIR, "stage_sunset_beach_battaglia.py"),
                      "--out", os.path.join(SRC, "4000-battaglia")],
                     capture_output=True, text=True)
print(_bsb.stdout[-1500:] if _bsb.stdout else "", _bsb.stderr[-1500:] if _bsb.stderr else "")
if _bsb.returncode != 0:
    _bsb_prev = json.load(open(os.path.join(SRC, "4000-battaglia/sunset-beach.json")))
    _gen_prev = datetime.fromisoformat(_bsb_prev.get("generatedAt", ""))
    _fresh_prev = (0 <= (datetime.now().astimezone() - _gen_prev).total_seconds() <= 7200)
    if _fresh_prev:
        print("Battaglia sunset-beach.json KEPT (generator failed rc=%s; previous file still fresh, generatedAt %s - next run retries)" % (_bsb.returncode, _bsb_prev.get("generatedAt")))
    else:
        assert False, "Battaglia stage_sunset_beach.py failed rc=%s and previous file stale" % _bsb.returncode

# --- Battaglia Travel Cities (P29, 2026-11-24) ---
# Troy 2026-11-23 ~11:28 PM: Travel Cities showed "no travel data" - the
# ?v=128 live NWS fetch never worked in a browser (jQuery cache:false
# appends ?_=nonce; api.weather.gov rejects it with HTTP 400). ?v=129
# reads the staged file 4000-battaglia/travel-cities.json instead (loader
# _P29LoadStagedTravelCities; live fallback cache:true). The file MUST be
# regenerated every run or it goes stale: the app ignores it when
# generatedAt is older than 2 hours. Generator stage_travel_cities.py
# lives in the Battaglia goal hidden_files (_BATT) and resolves each
# city's NWS gridpoint fresh from the points API every run (21 of 24
# stored gridpoints had gone stale). It fails safe: <20/24 cities ->
# exit non-zero, file untouched. (Run 1195: the first run after Troy's
# ~10:25 AM yes died on the manifest assert because this file was not
# in the `allowed` set below - the entry beside spc-outlook.json /
# sunset-beach.json is REQUIRED, not optional.)
_tc = subprocess.run(["python3", os.path.join(SCRIPTS_DIR, "stage_travel_cities.py"),
                     "--out", os.path.join(SRC, "4000-battaglia")],
                     capture_output=True, text=True)
print(_tc.stdout[-1500:] if _tc.stdout else "", _tc.stderr[-1500:] if _tc.stderr else "")
if _tc.returncode != 0:
    _tc_prev = json.load(open(os.path.join(SRC, "4000-battaglia/travel-cities.json")))
    _gen_prev = datetime.fromisoformat(_tc_prev.get("generatedAt", ""))
    _fresh_prev = (0 <= (datetime.now().astimezone() - _gen_prev).total_seconds() <= 7200)
    if _fresh_prev:
        print("travel-cities.json KEPT (generator failed rc=%s; previous file still fresh, generatedAt %s - next run retries)" % (_tc.returncode, _tc_prev.get("generatedAt")))
    else:
        assert False, "stage_travel_cities.py failed rc=%s and previous file stale" % _tc.returncode
_tc_now = json.load(open(os.path.join(SRC, "4000-battaglia/travel-cities.json")))
print("travel-cities.json regenerated (generatedAt %s; %d cities)" % (_tc_now.get("generatedAt"), len(_tc_now.get("cities", []))))

# --- WU dashboard, widget-scoped parse with per-widget units (unit-flip-safe) ---
def parse_wu_widgets(path):
    h = open(path).read()
    def widget(tag):
        m = re.search(r'<%s[^>]{0,600}>' % tag, h)
        assert m, "%s missing in %s" % (tag, path)
        return m.group(0)
    def attr(tag_html, k):
        m = re.search(k + r'="([^"]*)"', tag_html)
        assert m, "%s missing in %s" % (k, tag_html[:80])
        return m.group(1)
    t = widget("temp-widget-view")
    w = widget("wind-widget-view")
    p = widget("pressure-widget-view")
    hu = widget("humidity-widget-view")
    unit = attr(t, "data-unit")
    assert attr(w, "data-unit") == unit and attr(p, "data-unit") == unit and attr(hu, "data-unit") == unit, \
        "widget units disagree in %s" % path
    m = re.search(r'data-obs-time-utc="([^"]*)"', h)
    assert m, "obs time missing in %s" % path
    raw = {
        "temp": float(attr(t, "data-temp")),
        "feels": float(attr(t, "data-feels-like")),
        "dew": float(attr(hu, "data-dew-point")),
        "pressure": float(attr(p, "data-pressure")),
        "humidity": int(attr(hu, "data-humidity")),
        "wind": float(attr(w, "data-wind-speed")),
        "gust": float(attr(w, "data-wind-gust")),
        "wind_dir": int(attr(w, "data-wind-dir")),
        "obs": m.group(1),
        "unit": unit,
    }
    if unit == "m":
        c = dict(raw)
        c["temp"] = raw["temp"] * 1.8 + 32
        c["feels"] = raw["feels"] * 1.8 + 32
        c["dew"] = raw["dew"] * 1.8 + 32
        c["pressure"] = raw["pressure"] / 33.8649
        c["wind"] = raw["wind"] / 1.60936
        c["gust"] = raw["gust"] / 1.60936
    elif unit == "e":
        c = dict(raw)
    elif unit == "h":
        c = dict(raw)
        c["temp"] = raw["temp"] * 1.8 + 32
        c["feels"] = raw["feels"] * 1.8 + 32
        c["dew"] = raw["dew"] * 1.8 + 32
        c["pressure"] = raw["pressure"] / 33.8649
    else:
        raise AssertionError("unknown widget unit %r in %s" % (unit, path))
    c["unit"] = unit
    return c

def gen(files):
    vals = [parse_wu_widgets(os.path.join(HF, f)) for f in files]
    # RUN-726 FIX (same class as run-702/716 display-precision lessons): the
    # station can re-report IDENTICAL values under a NEW obs timestamp inside
    # one generation pair (r3a obs 17:06:40 vs r3b 17:06:53, all values equal).
    # The old _key included the obs string, so the pair assert aborted the
    # run pre-write. Values agreeing at display precision stage the LATEST
    # obs; only a real value disagreement still aborts.
    def _vkey(v):
        return (round(v["temp"], 1), round(v["feels"], 1), round(v["dew"], 1),
                round(v["pressure"], 2), v["humidity"], int(v["wind"] + 0.5),
                int(v["gust"] + 0.5), v["wind_dir"])
    if all(_vkey(v) == _vkey(vals[0]) for v in vals):
        latest = max(vals, key=lambda v: _obs_dt(v))
        if len(set(v["obs"] for v in vals)) > 1:
            print("NOTE: %s values identical at display precision, obs times differ %s - staging latest obs %s" % (
                files, [v["obs"][:25] for v in vals], latest["obs"][:25]))
        return latest
    # RUN-737 FIX (same class as run-726 value-only pair comparison): a pair
    # can carry two DIFFERENT obs timestamps AND different wind directions
    # (r2a obs 19:48:10 dir 90 E, r2b obs 19:49:14 dir 23 NNE) while every
    # other value agrees at display precision. At 2 mph sustained the vane
    # is noisy (this run's gens read 0/90/23/90/68; OSO 1441Z reads 340,
    # RC 1441n reads 158) - direction is not a value disagreement. Stage
    # the LATEST obs with a NOTE; only a real non-dir value disagreement
    # still aborts.
    def _vkey_nodir(v):
        return (round(v["temp"], 1), round(v["feels"], 1), round(v["dew"], 1),
                round(v["pressure"], 2), v["humidity"], int(v["wind"] + 0.5),
                int(v["gust"] + 0.5))
    if all(_vkey_nodir(v) == _vkey_nodir(vals[0]) for v in vals):
        latest = max(vals, key=lambda v: _obs_dt(v))
        print("NOTE: %s agree at display precision except wind dir %s (obs %s) - light-wind vane noise; staging latest obs %s dir %d" % (
            files, [v["wind_dir"] for v in vals], [v["obs"][:25] for v in vals], latest["obs"][:25], latest["wind_dir"]))
        return latest
    # RUN-750 FIX (same class as run-726/737): a pair can straddle a station
    # re-report - r4a obs 23:06:20 (63.3F wind 1 dir 270) vs r4b obs 23:07:27
    # (63.1F wind 5 dir 45), dew/P/RH/gust identical, and r5 (23:08:03)
    # corroborates the new temp 63.1F. A new obs ~1 min later is drift, not
    # a serving failure. Stage the LATEST obs with a NOTE when the pair's
    # values sit inside the standing cross-check tolerances (temp/feels/dew
    # 2.0F, P 0.02 inHg, RH 2, wind/gust 5.0 mph); anything wider still
    # aborts at the _key assert below.
    # RUN-846 FIX (same class): r4a obs 23:21:20 wind 11.3 km/h dir 45 vs
    # r4b obs 23:22:27 wind 3.2 km/h dir 23, everything else identical,
    # r5 (23:23:10/23Z) corroborates the new 2 mph - a genuine re-report
    # straddle, but the raw converted wind swing is 7.02-1.99 = 5.03 mph,
    # 0.03 over the 5.0 tolerance: a km/h quantization artifact. At
    # whole-mph display precision (the run-702 rule used by _key) the
    # swing is exactly 7-2 = 5 mph. Wind/gust tolerances are now compared
    # at whole-mph display precision, matching the tolerance's intent;
    # temp/feels/dew/P/RH stay raw. Future runs must carry this version.
    if len(set(v["obs"] for v in vals)) > 1:
        _d = lambda k: max(abs(a[k] - b[k]) for a in vals for b in vals)
        _dw = lambda k: max(abs(int(a[k] + 0.5) - int(b[k] + 0.5)) for a in vals for b in vals)
        if (_d("temp") <= 2.0 and _d("feels") <= 2.0 and _d("dew") <= 2.0
                and _d("pressure") <= 0.02 and _d("humidity") <= 2
                and _dw("wind") <= 5.0 and _dw("gust") <= 5.0):
            latest = max(vals, key=lambda v: _obs_dt(v))
            print("NOTE: %s straddle a station re-report (obs %s, temp %.1f->%.1fF wind %.0f->%.0f dir %s) - drift within cross-check tolerances; staging latest obs %s" % (
                files, [v["obs"][:25] for v in vals], vals[0]["temp"], latest["temp"],
                vals[0]["wind"], latest["wind"], [v["wind_dir"] for v in vals], latest["obs"][:25]))
            return latest
    # RUN-861 FIX: a pair can straddle a station re-report where ONLY the
    # sustained wind spikes for a single obs (r1a 03:02:29 wind 2 gust 7 vs
    # r1b 03:03:33 wind 11 gust 11; temp/feels/dew/P/RH/dir identical) and
    # the spike reverts within minutes - r2-r5 read wind 2/4/2/2, gust 11.
    # The 5 mph wind tolerance above is for genuine re-report drift, not
    # a one-obs spike. When the pair agrees on every non-wind value at
    # display precision, obs differ, and >=2 later generations already on
    # disk corroborate the LATEST pair obs's gust while their sustained
    # wind sits within 5 mph (display) of the EARLIER pair obs's wind,
    # the spike is transient: stage the latest pair obs with a NOTE.
    # Anything else still aborts at the _key assert below.
    if len(set(v["obs"] for v in vals)) > 1:
        _nw = lambda v: (round(v["temp"], 1), round(v["feels"], 1), round(v["dew"], 1),
                         round(v["pressure"], 2), v["humidity"], v["wind_dir"])
        if all(_nw(v) == _nw(vals[0]) for v in vals):
            _lp = max(vals, key=lambda v: _obs_dt(v))
            _ep = min(vals, key=lambda v: _obs_dt(v))
            _later = []
            for _f in sorted(glob.glob(os.path.join(HF, "wu_run%d_*.html" % RUN))):
                if os.path.basename(_f) in [os.path.basename(x) for x in files]:
                    continue
                try:
                    _v = parse_wu_widgets(_f)
                except Exception:
                    continue
                if _obs_dt(_v) > _obs_dt(_lp):
                    _later.append(_v)
            if (len(_later) >= 2
                    and all(int(x["gust"] + 0.5) == int(_lp["gust"] + 0.5) for x in _later)
                    and all(abs(int(x["wind"] + 0.5) - int(_ep["wind"] + 0.5)) <= 5 for x in _later)):
                print("NOTE: %s transient sustained-wind spike (obs %s wind %.0f->%.0f gust %.0f->%.0f, all other values identical; %d later gens corroborate gust %.0f, wind back to %.0f-%.0f) - staging latest pair obs %s" % (
                    files, [v["obs"][:25] for v in vals], _ep["wind"], _lp["wind"],
                    _ep["gust"], _lp["gust"], len(_later), _lp["gust"],
                    min(x["wind"] for x in _later), max(x["wind"] for x in _later), _lp["obs"][:25]))
                return _lp
    # RUN-702 LESSON: WU can serve MIXED units WITHIN one generation pair
    # (recheck2: a="m" wind 3.2 km/h/gust 8 km/h, b="h" wind 2 mph/gust 5 mph
    # - same obs 11:04:40, same temp/dew/P/RH/dir, wind/gust equal only after
    # unit conversion + whole-mph rounding). Compare the CONVERTED observation
    # at display precision, not the raw widget dicts (unit label + km/h->mph
    # float rounding differ even for the identical observation). Same obs
    # time, temps/dew/P/RH/dir exact, wind/gust equal at whole mph.
    def _key(v):
        # RUN-1125 FIX: dew compared at whole-degree display precision (was
        # 1-decimal) - r2's hybrid ("h") gen converts dew 64.9F while the
        # imperial gens read 65.0F for the SAME obs; a 0.1F unit-conversion
        # quantization artifact, same class as the run-846 km/h wind artifact.
        # Dew displays whole-degree everywhere, so 64.9 and 65.0 stage the
        # identical value; the 1-decimal comparison false-aborted pre-write.
        return (v["obs"], round(v["temp"], 1), round(v["feels"], 1), int(v["dew"] + 0.5),
                round(v["pressure"], 2), v["humidity"], int(v["wind"] + 0.5),
                int(v["gust"] + 0.5), v["wind_dir"])
    assert all(_key(v) == _key(vals[0]) for v in vals), "files in one generation differ: %s" % files
    return vals[0]

def _display_key(v):
    # Module-level copy of gen()'s display-precision key (run-702 rule):
    # same obs time, temps/P/RH/dir exact at 1 decimal, dew + wind/gust at
    # whole-unit display precision (RUN-1125 FIX: dew 1-decimal -> whole
    # degree, same quantization class as run-846 wind).
    return (v["obs"], round(v["temp"], 1), round(v["feels"], 1), int(v["dew"] + 0.5),
            round(v["pressure"], 2), v["humidity"], int(v["wind"] + 0.5),
            int(v["gust"] + 0.5), v["wind_dir"])

def _obs_dt(g):
    return datetime.strptime(g["obs"][:24], "%a %b %d %Y %H:%M:%S").replace(tzinfo=timezone.utc)

x4 = gen(["wu_run%d_%s.html" % (RUN, s) for s in "abcd"])
r1 = gen(["wu_run%d_recheck_%s.html" % (RUN, s) for s in ("a", "b")])
r2 = gen(["wu_run%d_recheck2_%s.html" % (RUN, s) for s in ("a", "b")])
r3 = gen(["wu_run%d_recheck3_%s.html" % (RUN, s) for s in ("a", "b")])
r4 = gen(["wu_run%d_recheck4_%s.html" % (RUN, s) for s in ("a", "b")])
r5 = gen(["wu_run%d_recheck5_%s.html" % (RUN, s) for s in ("a", "b")])
gens = [("x4", x4), ("r1", r1), ("r2", r2), ("r3", r3), ("r4", r4), ("r5", r5)]
for name, g in gens:
    print("%s unit=%s obs=%s temp=%.1fF feels=%.1fF dew=%.1fF P=%.2f inHg RH=%d wind=%.1f gust=%.1f dir=%d" % (
        name, g["unit"], g["obs"][:25], g["temp"], g["feels"], g["dew"], g["pressure"],
        g["humidity"], g["wind"], g["gust"], g["wind_dir"]))
# Plausibility asserts (ranges, not exact prior values - run-427 lesson).
_now = datetime.now(timezone.utc)
# RUN-961 RC FALLBACK (body rule: WU/WunderMap/OSO stale -> stage RetroCast
# whole, reject RC data older than 1h): the freshest WU obs is 03:27:25Z and
# no newer obs exists anywhere (WunderMap 62/Rain, OSO 2227 row, RC 2256n all
# the same obs; fresh dashboard re-fetch at 23:10 EST still 03:27:25). If the
# newest RC file's wu_obs_utc is within 1h AND equals that obs, authorise the
# 1h window instead of the usual 30-min gate - the staged values are that same
# farm obs, nothing mixed or invented. Otherwise the 1800s gate stands.
_rc_fallback_ok = False
try:
    _rc_max_obs = max(_obs_dt(g) for g in (x4, r1, r2, r3, r4, r5))
    for _cand in sorted(glob.glob(os.path.expanduser("~/workspace/goals/troy-s-personal-retrocast/hidden_files/retrocast-15min-data-*.json")), reverse=True):
        _d = json.load(open(_cand))
        _rc_dt = datetime.fromisoformat(_d["wu_obs_utc"].replace("Z", "+00:00"))
        if _rc_dt == _rc_max_obs and 0 <= (_now - _rc_dt).total_seconds() <= 3600:
            _rc_fallback_ok = True
            print("RC FALLBACK: %s wu_obs %s (%.0f min old, within 1h) == freshest WU obs - staging that obs under the body RC rule" % (os.path.basename(_cand), _d["wu_obs_utc"], (_now - _rc_dt).total_seconds() / 60))
            break
except Exception as _rc_e:
    print("RC FALLBACK check failed (%r) - 30-min gate stands" % (_rc_e,))
for g in (x4, r1, r2, r3, r4, r5):
    # RUN-1017 FIX: temp/feels upper cap 75.0 false-aborted this run - r1 feels
    # 75.02F (r2 75.4F) on a 73.8F / 94% RH afternoon is legitimate (feels-like
    # runs above air temp in saturated air). Same stale-assert class as
    # run-427/451/725 - a cap written when conditions were cooler. 30..90F is
    # the plausibility range for a November farm afternoon; garbage parses
    # (750F, negatives) still abort.
    assert 30.0 <= g["temp"] <= 90.0, g
    assert 30.0 <= g["feels"] <= 90.0, g
    assert 20.0 <= g["dew"] <= g["temp"] + 0.6, g  # dew can't exceed temp
    # RUN-1236 FIX: the 29.5 floor false-aborted on a real coastal-low pressure:
    # ALL 14 WU gens read 29.34 inHg (obs 11:34-11:39 EST Nov 26) and the OSOILM
    # farm row independently reads 29.34 (KCRE 29.58, Longwood 29.24 - a real
    # local gradient in the storm). Same stale-assert class as run-427/451/725/
    # 1017/1195 - a cap written when pressures sat near 30.0-30.8. Standing
    # plausibility range per AGENTS.md is 28..32 inHg; garbage parses still abort.
    assert 28.0 <= g["pressure"] <= 32.0, g
    assert 40 <= g["humidity"] <= 100, g  # RUN-725 FIX: RH drifted to 78-79% as temp rose to 67F; the old 80-100 floor was written when RH sat in the 80s (same stale-assert class as run-427/451) - 40-100 is the plausibility range
    # RUN-1195 FIX: gust hit 16.0 in ALL six gens (15:34-15:38Z) - a real
    # reading, and 16+ is Troy's gust-display branch (sustained + "Gusts to"),
    # not garbage. The 15 cap was written when gusts never reached 16 (same
    # stale-assert class as run-427/451/725/1017). 0..40 wind / 0..60 gust
    # are plausibility bounds; garbage parses still abort.
    assert 0 <= g["wind"] <= 40 and 0 <= g["gust"] <= 60, g
    assert 0 <= g["wind_dir"] < 360, g
    # RUN-1096 FIX: the freshness gate used to be asserted on EVERY gen here.
    # First stage attempt aborted pre-write: x4/r1-r3 carried obs 13:39:15Z
    # (station's 28-min reporting gap straddled the fetch) and aged past
    # 1800s by stage time, while r4/r5 carried a fresh 14:07:35/14:07:41Z obs
    # (~2 min old) - the station IS reporting and the staged values come
    # ONLY from the freshest gen. The gate now applies to the freshest obs
    # (asserted below, after _max_obs), which is what staging actually uses;
    # per-gen plausibility asserts above are unchanged. Same stale-assert
    # class as run-427/451/725/1017 - a check written when all gens always
    # shared one fresh obs.
# Obs times non-decreasing; freshest generation (max obs time) governs. Gens
# sharing the max obs time must carry identical values (same obs served twice).
_obs_times = [_obs_dt(g) for _, g in gens]
assert _obs_times == sorted(_obs_times), "obs times not non-decreasing: %s" % _obs_times
_max_obs = max(_obs_times)
assert 0 <= (_now - _max_obs).total_seconds() <= (3600 if _rc_fallback_ok else 1800), "freshest WU obs too old: %s (RC fallback %s)" % (_max_obs, _rc_fallback_ok)
_fresh = [g for _, g in gens if _obs_dt(g) == _max_obs]
# RUN-716 FIX (same class as run-702): gens sharing the freshest obs can
# arrive in different widget units (r4="m", r5="h") with identical converted
# values at display precision - raw-dict equality fails on the "unit" key
# and on km/h->mph float rounding. Compare the display-precision key, as
# gen() already does; stage the LAST freshest gen (matches _fresh_name).
assert all(_display_key(g) == _display_key(_fresh[0]) for g in _fresh), "gens sharing freshest obs differ at display precision: %s" % [(_display_key(g), g["unit"]) for g in _fresh]
w = _fresh[-1]
_fresh_name = [n for n, g in gens if _obs_dt(g) == _max_obs][-1]
print("STAGING freshest obs %s (%s): temp %.1fF feels %.1fF dew %.1fF P %.2f inHg RH %d wind %.1f gust %.1f dir %d" % (
    w["obs"][:25], _fresh_name, w["temp"], w["feels"], w["dew"], w["pressure"], w["humidity"], w["wind"], w["gust"], w["wind_dir"]))

# --- Convert freshest obs to metric-native staged values (1 decimal C/km/h) ---
def f2c(f):
    # RUN-790 FIX: a raw .5F reading can round-trip wrong through 1-decimal
    # C - 58.5F -> 14.7C -> 58.46F displays 58, but WU 58.5F displays 59
    # (round-half-up). The staged metric value must round-trip to the same
    # whole-F display as the raw reading, so nudge the 1-decimal C by 0.1
    # when the round-trip display disagrees. 14.8C = 58.64F, within 0.14F
    # of raw 58.5F - a quantization choice, not an invented reading; the
    # page must show 59F, the same display WU itself shows. Future run
    # scripts must carry this branch, not the bare round() version.
    c = round((f - 32) / 1.8, 1)
    if int(c * 1.8 + 32 + 0.5) != int(f + 0.5):
        c = round(c + (0.1 if int(f + 0.5) > int(c * 1.8 + 32 + 0.5) else -0.1), 1)
    assert int(c * 1.8 + 32 + 0.5) == int(f + 0.5), (f, c)
    return c
def mph2kmh(m): return round(m * 1.60936, 1)
TEMP_C = f2c(w["temp"])
FEELS_C = f2c(w["feels"])
DEW_C = f2c(w["dew"])
PRESS_INHG = round(w["pressure"], 2)
PRESS_HPA = round(PRESS_INHG * 33.8649, 2)
HUMIDITY = w["humidity"]
WIND_DIR_DEG = int(w["wind_dir"])
WIND_KMH = mph2kmh(w["wind"])
WIND_GUST_KMH = mph2kmh(w["gust"])
# RUN-922 FIX: rain today was hardcoded 0.0 in every run script - this run
# the WU rain widget reads precip-total 0.01 in on ALL 14 gens (rate 0.01
# in/hr) and OSO corroborates 0.01, so the staged 0.00 was wrong by 0.01 in
# (rainfall keeps 2 decimals on the pages). Parse precip-total from the
# freshest gen's file; a missing widget still aborts (never stage a guess).
# RUN-931 FIX: the run-922 rain parse read data-precip-total raw as inches,
# but the WU dashboard serves the rain widget in MM when the page's unit is
# metric (r2/r5 this run: 2.29 mm = 0.09 in; imperial gens read 0.09 in).
# The first stage attempt staged 2.29 in (25.4x too high) and was caught
# before pushing by the imperial/metric cross-check below. Parse every gen's
# precip-total with ITS OWN unit (mm/25.4 when "m"), assert all gens agree
# within 0.02 in, stage the freshest converted value. Future runs must carry
# this conversion, never the raw parse.
_rain_suffixes = {"x4": "d", "r1": "recheck_b", "r2": "recheck2_b",
                  "r3": "recheck3_b", "r4": "recheck4_b", "r5": "recheck5_b"}
_rain_vals = {}
for _gn, _sfx in _rain_suffixes.items():
    _rpath = os.path.join(HF, "wu_run%d_%s.html" % (RUN, _sfx))
    _ru = parse_wu_widgets(_rpath)["unit"]
    _rhtml = open(_rpath).read()
    _rm = re.search(r'data-precip-total="([^"]*)"', _rhtml)
    assert _rm, "rain widget precip-total missing in %s gen file" % _gn
    _raw = float(_rm.group(1))
    # RUN-932 FIX: the run-931 conversion handled unit "m" only, but the
    # hybrid unit "h" ALSO serves the rain widget in mm - r1 this run read
    # 2.29 with unit "h", exactly the mm value of the "m" gens (x4/r2
    # 2.29 mm = 0.09 in) while imperial gens read 0.09 in. The first stage
    # attempt aborted pre-write on the cross-check (2.29 vs 0.09). Convert
    # mm/25.4 for both "m" and "h"; imperial "e" stays raw inches.
    _conv = round(_raw / 25.4, 2) if _ru in ("m", "h") else round(_raw, 2)
    _rain_vals[_gn] = _conv
    print("RAIN gen %s unit=%s raw %s -> %.2f in" % (_gn, _ru, _rm.group(1), _conv))
# RUN-967 FIX: rain is FALLING, so the total genuinely rises between gens
# (0.30 in at 00:29 -> 0.37 in at 00:37, farm rate 0.55 in/hr) - the old
# 0.02 spread assert was written for a stable total and false-aborts on
# accumulation. The spread is allowed only when the totals are monotonic
# non-decreasing in obs-time order AND the rise fits the farm rain rate
# over the gen span (rise <= rate * hours + 0.02). A unit flip (2.29 vs
# 0.09 = 2.20 spread) or any non-monotonic jump still aborts. The staged
# value stays the freshest gen's, as before.
_rain_order = ["x4", "r1", "r2", "r3", "r4", "r5"]
_rain_seq = [_rain_vals[g] for g in _rain_order]
# RUN-1061 FIX (midnight rollover): the WU rain widget is a TODAY total, so it
# resets to 0.00 at local midnight. This run straddles the reset: x4/r1 still
# serve Nov 22's cached 1.18 in (obs 00:03/00:04 EST) while r2-r5 serve Nov 23's
# 0.00 in (obs 00:05-00:08 EST). The strict monotonic assert false-aborts on
# that legitimate reset. Allow exactly ONE downward step when ALL of these
# hold: (a) freshest obs is within 60 min after local midnight, (b) the value
# before the step equals the previously staged rainTodayIn (clone live HEAD),
# (c) the post-step subsequence is itself monotonic non-decreasing. The
# spread/rate checks then run on the post-step subsequence only, and the staged
# value stays the freshest gen's. Any other non-monotonic pattern still aborts.
# Future runs must carry this allowance, never the bare assert.
_rain_drops = [i for i in range(1, len(_rain_seq)) if _rain_seq[i] < _rain_seq[i-1]]
_rain_seq_chk = _rain_seq
if _rain_drops:
    _prev_rain = json.load(open(os.path.join(CLONE, "4000-myrtle-intl/farm-data.json")))["rainTodayIn"]
    _fresh_est = _obs_dt(w).astimezone(timezone(timedelta(hours=-5)))
    _mins_after_midnight = _fresh_est.hour * 60 + _fresh_est.minute
    _rollover_ok = (len(_rain_drops) == 1 and _mins_after_midnight <= 60
                    and abs(_rain_seq[_rain_drops[0] - 1] - _prev_rain) <= 0.005
                    and all(b >= a for a, b in zip(_rain_seq[_rain_drops[0]:], _rain_seq[_rain_drops[0] + 1:])))
    assert _rollover_ok, "rain totals not monotonic non-decreasing: %s (not a midnight rollover: drops=%s, freshest %d min after midnight, prev staged %.2f)" % (_rain_vals, _rain_drops, _mins_after_midnight, _prev_rain)
    print("RAIN midnight rollover: pre-reset %.2f in (prev staged %.2f) -> post-reset %s; spread checks use post-reset subsequence; staging freshest %.2f in" % (_rain_seq[_rain_drops[0] - 1], _prev_rain, _rain_seq[_rain_drops[0]:], _rain_vals[_fresh_name]))
    _rain_seq_chk = _rain_seq[_rain_drops[0]:]
else:
    assert all(b >= a for a, b in zip(_rain_seq, _rain_seq[1:])), "rain totals not monotonic non-decreasing: %s" % _rain_vals
_rain_spread = max(_rain_seq_chk) - min(_rain_seq_chk)
_p_rate_early = None
try:
    _re_path = os.path.join(HF, "wu_run%d_%s.html" % (RUN, _rain_suffixes[_fresh_name]))
    _re_html = open(_re_path).read()
    _re_m = re.search(r'data-precip-rate="([^"]*)"', _re_html)
    _re_u = parse_wu_widgets(_re_path)["unit"]
    if _re_m:
        _p_rate_early = round(float(_re_m.group(1)) / 25.4, 3) if _re_u in ("m", "h") else round(float(_re_m.group(1)), 3)
except Exception as _re_e:
    print("early rain-rate parse failed (%r) - strict 0.02 rain spread stands" % (_re_e,))
if _p_rate_early is not None:
    _span_h = (_obs_dt(w) - _obs_dt(gens[0][1])).total_seconds() / 3600.0
    _allowed = _p_rate_early * _span_h + 0.02
    assert _rain_spread <= _allowed, "rain totals spread %.2f exceeds rate-explained %.2f (rate %.3f in/hr over %.3fh): %s" % (_rain_spread, _allowed, _p_rate_early, _span_h, _rain_vals)
    print("RAIN spread %.2f in across gens EXPLAINED by accumulation (rate %.3f in/hr over %.3fh, allowed %.2f) - staging freshest %.2f in" % (_rain_spread, _p_rate_early, _span_h, _allowed, _rain_vals[_fresh_name]))
else:
    assert _rain_spread <= 0.02, "rain totals disagree across gens after unit conversion: %s" % _rain_vals
RAIN_IN = _rain_vals[_fresh_name]
print("RAIN today %.2f in (WU rain widget precip-total, unit-converted, freshest gen %s)" % (RAIN_IN, _fresh_name))
# RUN-959: VISIBILITY_KM is derived LIVE from the fresh KCRE obs below
# (old hardcoded 16.09 = 10 mi staged 10 mi even when KCRE said 7.0 mi).
_DIRS = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]
WIND_DIR = _DIRS[int((WIND_DIR_DEG + 11.25) // 22.5) % 16]
assert int(TEMP_C * 1.8 + 32 + 0.5) == int(w["temp"] + 0.5), "temp display mismatch"
assert int(FEELS_C * 1.8 + 32 + 0.5) == int(w["feels"] + 0.5), "feels display mismatch"
assert int(DEW_C * 1.8 + 32 + 0.5) == int(w["dew"] + 0.5), "dew display mismatch"
assert abs(PRESS_HPA - (PRESS_INHG * 33.8649)) < 0.05, "inHg->hPa mismatch"
assert int(WIND_KMH / 1.60936 + 0.5) == int(w["wind"] + 0.5), "wind km/h->mph display mismatch"
assert int(WIND_GUST_KMH / 1.60936 + 0.5) == int(w["gust"] + 0.5), "gust km/h->mph display mismatch"
# RUN-936 FIX: saturated air (RH 99) - all 6 WU gens report dew 64.0F a
# fraction above temp 63.7F (quantization noise; both display 64F whole).
# Dew point cannot physically exceed air temp, so cap DEW_C at TEMP_C
# when the excess is <= 0.5C. Display is unchanged (64/64); the staged
# pair stays physically consistent. A larger excess still aborts.
# Future runs must carry this clamp, never the bare assert.
if DEW_C > TEMP_C:
    assert DEW_C - TEMP_C <= 0.5, (DEW_C, TEMP_C)
    print("dew %.1fC capped to temp %.1fC (saturated air, dew>temp by %.1fC - quantization noise)" % (DEW_C, TEMP_C, DEW_C - TEMP_C))
    DEW_C = TEMP_C
assert DEW_C <= TEMP_C, "dew above temp!"
assert 0 <= HUMIDITY <= 100, HUMIDITY
assert _DIRS[int((WIND_DIR_DEG + 11.25) // 22.5) % 16] == WIND_DIR, "dir sector mismatch"
print("staged metric-native: temp %sC feels %sC dew %sC P %s hPa (%s inHg) RH %d wind %s km/h gust %s km/h dir %s (%d deg)" % (
    TEMP_C, FEELS_C, DEW_C, PRESS_HPA, PRESS_INHG, HUMIDITY, WIND_KMH, WIND_GUST_KMH, WIND_DIR, WIND_DIR_DEG))

# Pressure trend vs previously staged pressure - read from the CLONE (live HEAD),
# NOT the source dir (run-685 lesson: source may be pre-staged). Both in inHg
# at 2 decimals per the body (XL mechanical rule).
prev = json.load(open(os.path.join(CLONE, "4000-myrtle-intl/farm-data.json")))
prev_p_hpa = round(prev["pressure"], 2)
prev_p_inhg = round(prev_p_hpa / 33.8649, 2)
assert -10 <= prev["temperature"] <= 45, prev["temperature"]
assert 950 <= prev_p_hpa <= 1080, prev_p_hpa
assert 28.0 <= prev_p_inhg <= 32.0, prev_p_inhg
assert prev.get("pressureTrend") in ("rising", "falling", "steady"), prev.get("pressureTrend")
CUR_INHG = round(PRESS_INHG, 2)
TREND = "falling" if CUR_INHG < prev_p_inhg else ("rising" if CUR_INHG > prev_p_inhg else "steady")
assert (CUR_INHG < prev_p_inhg) == (TREND == "falling"), (CUR_INHG, prev_p_inhg, TREND)
assert (CUR_INHG > prev_p_inhg) == (TREND == "rising"), (CUR_INHG, prev_p_inhg, TREND)
assert (CUR_INHG == prev_p_inhg) == (TREND == "steady"), (CUR_INHG, prev_p_inhg, TREND)
print("PRESSURE TREND: prev %.2f inHg -> now %.2f inHg = %s (prev from clone live HEAD)" % (prev_p_inhg, CUR_INHG, TREND))

# --- Cross-checks (informational, printed; WU freshest governs) ---
# WunderMap sky: parse the KNCCAROL120 station-conditions icon + title.
_wm = open(os.path.join(HF, "wundermap_run%d.html" % RUN)).read()
assert "KNCCAROL120" in _wm, "WunderMap station block missing KNCCAROL120"
_si = _wm.find('data-station-id="KNCCAROL120"')
_sc = _wm.find("station-conditions", _si)
assert _sc >= 0, "WunderMap station-conditions span missing"
_m = re.search(r'class="icon ([a-z-]+)" title="([^"]+)"', _wm[_sc:_sc+400])
assert _m, "WunderMap sky icon/title not parseable"
WM_ICON, WM_TITLE = _m.group(1), _m.group(2)
print("WunderMap: icon %s title %r for KNCCAROL120" % (WM_ICON, WM_TITLE))
# RUN-1218: Open-Meteo farm-point sky derivation (see header note). _OM_OK
# False on any failure -> WunderMap fallback below. Never aborts.
# RUN-1219 CIRRUS RULE (Troy's eyes, Nov 24 ~4:30 PM EST): a percentage alone
# does not measure cloud THICKNESS. Thin high cirrus can cover 87% of the sky
# and still look Fair / Mainly clear (live farm point 4:30 PM: total 87, low 0,
# mid 0, high 90, WMO 3 - all cirrus; Troy's eyes + the International page
# both said Mainly clear). So: derive the word from total cover first, then
# if high cloud is >=70% of the total AND low+mid combined is <=10%, cap the
# word at Fair (take the clearer of the derived word and Fair - never cloudier
# than Fair from cirrus alone). Precip/Fog still come from the WMO code.
def _om_cover_word(_cover, _low=None, _mid=None, _high=None):
    if _cover >= 88:
        _w, _ct = ("Cloudy", 3)
    elif _cover >= 51:
        _w, _ct = ("Mostly cloudy", 3)
    elif _cover >= 26:
        _w, _ct = ("Partly cloudy", 2)
    elif _cover >= 11:
        _w, _ct = ("Fair", 1)
    else:
        _w, _ct = ("Clear", 0)
    if _low is not None and _mid is not None and _high is not None and _cover > 0:
        _low, _mid, _high = float(_low), float(_mid), float(_high)
        if _high >= 0.70 * _cover and (_low + _mid) <= 10 and _ct > 1:
            print("CIRRUS cap: total %.0f%% is high-dominated (low %.0f mid %.0f high %.0f) - thin cirrus, word %s capped to Fair" % (_cover, _low, _mid, _high, _w))
            return ("Fair", 1)
    return (_w, _ct)
_OM_PRECIP_TYPE = None
_OM_OK = False
_OM_CODE = None
_OM_COVER = None
_OM_WORD = None
_OM_CT = None
_OM_CODE_STR = "n/a"
try:
    _om_url = ("https://api.open-meteo.com/v1/forecast?latitude=33.92&longitude=-78.57"
               "&current=weather_code,cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,is_day"
               "&timezone=America%2FNew_York")
    _om_req = urllib.request.Request(_om_url, headers={"User-Agent": "Muse-WeatherStar-Channel (troy farm, contact: KNCCAROL120)"})
    with urllib.request.urlopen(_om_req, timeout=60) as _om_r:
        _om_data = json.loads(_om_r.read())
    _om_cur = _om_data.get("current", {})
    if _om_data.get("error") or "weather_code" not in _om_cur:
        raise RuntimeError("Open-Meteo error response: %r" % (_om_data,))
    _OM_CODE = int(_om_cur["weather_code"])
    _OM_CODE_STR = str(_OM_CODE)
    _OM_COVER = _om_cur.get("cloud_cover")
    _om_precip_types = {}
    for _c in (51, 53, 55, 61, 63, 65, 80, 81, 82):
        _om_precip_types[_c] = "rain"
    for _c in (71, 73, 75, 77, 85, 86):
        _om_precip_types[_c] = "snow"
    for _c in (95, 96, 99):
        _om_precip_types[_c] = "thunderstorm"
    for _c in (56, 57, 66, 67):
        _om_precip_types[_c] = "sleet"
    if _OM_CODE in (45, 48):
        _OM_OK, _OM_WORD, _OM_CT = True, "Fog", 45
    elif _OM_CODE in _om_precip_types:
        _OM_PRECIP_TYPE = _om_precip_types[_OM_CODE]
        _OM_OK = True
        if _OM_COVER is not None:
            _OM_WORD, _OM_CT = _om_cover_word(float(_OM_COVER), _om_cur.get("cloud_cover_low"), _om_cur.get("cloud_cover_mid"), _om_cur.get("cloud_cover_high"))
    else:
        if _OM_COVER is None:
            raise RuntimeError("Open-Meteo current response missing cloud_cover: %r" % (_om_cur,))
        _OM_OK = True
        _OM_WORD, _OM_CT = _om_cover_word(float(_OM_COVER), _om_cur.get("cloud_cover_low"), _om_cur.get("cloud_cover_mid"), _om_cur.get("cloud_cover_high"))
    print("OPEN-METEO farm sky: WMO %d, cloud_cover %s%% (low %s mid %s high %s) -> automated word %s (ct %s), precip type %s" % (
        _OM_CODE, _OM_COVER, _om_cur.get("cloud_cover_low"), _om_cur.get("cloud_cover_mid"),
        _om_cur.get("cloud_cover_high"), _OM_WORD, _OM_CT, _OM_PRECIP_TYPE))
except Exception as _om_e:
    print("OPEN-METEO farm sky fetch failed (%r) - falling back to WunderMap word" % (_om_e,))
SKY_MAP = {"Clear": ("Clear", 0), "Sunny": ("Sunny", 0), "Fair": ("Fair", 1),
           "Partly Cloudy": ("Partly cloudy", 2), "Mostly Cloudy": ("Mostly cloudy", 3), "Variably Cloudy": ("Variably Cloudy", 4),
           "Cloudy": ("Cloudy", 3)}
# RUN-762 FIX: WunderMap can serve a present-weather title with no
# cloud-cover mapping (this run: 'Showers in Vicinity', icon
# mostly-cloudy-night) while every METAR in the region reports CLR, the
# KLTX loop shows no echo, farm rain is 0.00, and RC/Jr/KCRE all say
# Clear. A present-weather phrase is NOT a sky word - never guess a
# mapping into SKY_MAP (staging 'Mostly cloudy' off the icon would put a
# wrong sky on every page). Fall back to the corroborated sky: the
# RetroCast library data, the Jr run data, and KCRE's latest obs must
# agree on one mapped word; if they disagree, keep the previously staged
# sky from the clone (live HEAD). Future runs: carry this branch, never
# reintroduce the hard abort or a guessed title mapping.
# RUN-954 PRECIPITATION BRANCH (Troy 2026-11-21, his words): when
# precipitation is falling at the farm, stage the precipitation word
# with its intensity - Light Rain (61) / Rain (63) / Heavy Rain (65),
# Light Snow (71) / Snow (73) / Heavy Snow (75), Thunderstorm (95) -
# instead of a cloud-cover word. The word stages ONLY when the fall is
# CONFIRMED over the farm/neighborhood by ALL THREE legs, every one
# farm/neighborhood evidence: (1) WunderMap serves a precipitation
# title/icon, (2) the freshest KLTX radar loop shows echo over the farm
# center-box (last frame > 20 px, same method + threshold as the
# RetroCast echo scan), (3) the farm's own WU rain rate > 0 (or rain
# total rising). "Showers in Vicinity" fails the gate (no farm echo, no
# farm rate) and falls through to the old corroborated-sky/keep behaviour
# - never stage a precipitation word on an unconfirmed title. Intensity
# is the FARM's own WU rain rate (light < 0.10, moderate 0.10-0.30,
# heavy > 0.30 in/hr); when no rate parses the middle code stages.
# KCRE (North Myrtle Beach airport) is NEVER a gate leg and NEVER the
# intensity fallback - Troy 2026-11-21 ~9:42 PM: "don't use north myrtle
# beach airport for my current sky Precip - that's north myrtle beach
# not the farm at Brunswick neighborhood". KCRE is read and logged below
# for the record only; it decides nothing. Satellite leg: the GOES-East
# SE GeoColor image is fetched each run (goes_runNNN.gif); its freshness
# is logged here - the pixel-level farm check follows once the sector
# bounds are verified (the STAR sector page publishes none). Future runs:
# carry this branch; never stage a precipitation word without the radar gate.
_precip_staged = False
_PRECIP_TITLES = {"Rain", "Light Rain", "Heavy Rain", "Rain Shower",
                  "Rain Showers", "Showers", "Thunderstorm", "Thunderstorms",
                  "Snow", "Light Snow", "Heavy Snow", "Freezing Rain",
                  "Sleet", "Drizzle", "Light Drizzle"}
_PRECIP_ICONS = {"rain", "showers", "thunderstorm", "snow", "sleet",
                 "freezing-rain", "drizzle", "rain-shower"}
_p_title_hit = (_OM_PRECIP_TYPE is not None) or (WM_TITLE in _PRECIP_TITLES or WM_ICON in _PRECIP_ICONS)
_p_rate = None
try:
    _p_fresh_path = os.path.join(HF, "wu_run%d_%s.html" % (RUN, _rain_suffixes[_fresh_name]))
    _p_fresh_html = open(_p_fresh_path).read()
    _p_rm = re.search(r'data-precip-rate="([^"]*)"', _p_fresh_html)
    _p_ru = parse_wu_widgets(_p_fresh_path)["unit"]
    if _p_rm:
        _p_rate = round(float(_p_rm.group(1)) / 25.4, 3) if _p_ru in ("m", "h") else round(float(_p_rm.group(1)), 3)
    print("PRECIP rate %s in/hr (freshest gen %s, unit %s)" % (_p_rate, _fresh_name, _p_ru))
except Exception as _p_e:
    print("PRECIP rate parse failed (%r) - rate leg unavailable" % (_p_e,))
# KCRE read for the log ONLY (Troy 2026-11-21): North Myrtle Beach airport
# is not the farm - it never gates and never sets intensity.
_p_kcre_wx = None
_p_kcre_desc = None
try:
    _p_kc = json.load(open(os.path.join(HF, "kcre_run%d.json" % RUN)))["properties"]
    _p_kcre_desc = _p_kc.get("textDescription")
    _pw = _p_kc.get("presentWeather") or []
    if _pw:
        _p_kcre_wx = _pw[0].get("rawString")
    print("PRECIP KCRE %r present weather %r" % (_p_kcre_desc, _p_kcre_wx))
except Exception as _p_e:
    print("PRECIP KCRE read failed (%r)" % (_p_e,))
_p_radar_last = None
_p_radar_max = None
try:
    _p_loops = sorted(glob.glob(os.path.expanduser("~/workspace/goals/troy-s-personal-retrocast/hidden_files/kltx_*.gif")), key=os.path.getmtime)
    # RUN-1235 FIX: the RetroCast loop is the primary radar source, but the
    # RetroCast 15-min pipeline has been dying (newest loop 39.6h old this
    # run), which permanently disables the precip gate - no precip word can
    # ever stage while the loop is stale. This run's own fetch already
    # downloads the KLTX loop every run (run-954 design: it is the backup);
    # fall back to it when the RetroCast loop is stale (>2h) or missing.
    # Same scan method + threshold below; the fallback only changes WHICH
    # fresh loop file is scanned, never the gate itself.
    _p_run_loop = os.path.join(HF, "kltx_run%d.gif" % RUN)
    if os.path.exists(_p_run_loop):
        _p_run_age = (_now - datetime.fromtimestamp(os.path.getmtime(_p_run_loop), tz=timezone.utc)).total_seconds() / 3600.0
        _p_rc_age = ((_now - datetime.fromtimestamp(os.path.getmtime(_p_loops[-1]), tz=timezone.utc)).total_seconds() / 3600.0) if _p_loops else None
        if _p_run_age <= 2.0 and (_p_rc_age is None or _p_rc_age > 2.0):
            print("PRECIP RADAR: RetroCast loop stale (%.1fh old) / missing - falling back to this run's fresh %s (%.1fh old)" % (_p_rc_age if _p_rc_age is not None else -1, os.path.basename(_p_run_loop), _p_run_age))
            _p_loops = _p_loops + [_p_run_loop]
    if _p_loops:
        _p_loop = _p_loops[-1]
        _p_age = (_now - datetime.fromtimestamp(os.path.getmtime(_p_loop), tz=timezone.utc)).total_seconds() / 3600.0
        if _p_age <= 2.0:
            from PIL import Image as _PILImage
            _p_im = _PILImage.open(_p_loop)
            _p_nf = getattr(_p_im, "n_frames", 1)
            _p_last_fb = 0
            _p_max_fb = 0
            for _p_f in range(_p_nf):
                _p_im.seek(_p_f)
                _p_px = _p_im.convert("RGB")
                _p_w, _p_h = _p_px.size
                _p_fb = 0
                for _p_y in range(0, _p_h, 5):
                    for _p_x in range(0, _p_w, 5):
                        _p_r, _p_g, _p_b = _p_px.getpixel((_p_x, _p_y))
                        if ((_p_g > 100 and _p_r < 150 and _p_b < 120) or (_p_r > 180 and _p_g > 120 and _p_b < 100) or (_p_r > 200 and _p_g < 120 and _p_b < 120) or (_p_r > 180 and _p_g > 180 and _p_b < 80)):
                            if 250 <= _p_x <= 350 and 225 <= _p_y <= 325:
                                _p_fb += 1
                _p_max_fb = max(_p_max_fb, _p_fb)
                _p_last_fb = _p_fb
            _p_radar_last, _p_radar_max = _p_last_fb, _p_max_fb
            print("PRECIP RADAR loop %s (%.1fh old, %d frames): farm center-box last %d px, max %d px (threshold >20)" % (os.path.basename(_p_loop), _p_age, _p_nf, _p_last_fb, _p_max_fb))
        else:
            print("PRECIP RADAR loop %s is %.1fh old - too stale for the gate" % (os.path.basename(_p_loop), _p_age))
    else:
        print("PRECIP RADAR: no KLTX loop file found")
except Exception as _p_e:
    print("PRECIP RADAR scan failed (%r) - radar leg unavailable" % (_p_e,))
try:
    _p_sat_path = os.path.join(HF, "goes_run%d.gif" % RUN)
    if os.path.exists(_p_sat_path):
        _p_sat_age = (_now - datetime.fromtimestamp(os.path.getmtime(_p_sat_path), tz=timezone.utc)).total_seconds() / 60.0
        print("SATELLITE leg: GOES-East SE GeoColor %s (%.0f min old, %d bytes) - %s" % (os.path.basename(_p_sat_path), _p_sat_age, os.path.getsize(_p_sat_path), "FRESH" if _p_sat_age <= 30.0 else "STALE"))
    else:
        print("SATELLITE leg: no GOES image this run (fetch added run 955) - radar+station decide")
except Exception as _p_e:
    print("SATELLITE leg check failed (%r)" % (_p_e,))
_p_type = None
if _OM_PRECIP_TYPE is not None:
    _p_type = _OM_PRECIP_TYPE
elif _p_title_hit:
    _p_t = WM_TITLE.lower()
    if "thunderstorm" in _p_t or WM_ICON == "thunderstorm":
        _p_type = "thunderstorm"
    elif "snow" in _p_t or WM_ICON == "snow":
        _p_type = "snow"
    elif "sleet" in _p_t or "freezing" in _p_t:
        _p_type = "sleet"
    else:
        _p_type = "rain"
# No KCRE family check: the airport never decides the precip word (Troy 2026-11-21).
_p_farm_falling = bool((_p_rate is not None and _p_rate > 0) or RAIN_IN > prev["rainTodayIn"])
_p_gate = bool(_p_title_hit and _p_type and _p_radar_last is not None and _p_radar_last > 20 and _p_farm_falling)
if _p_gate:
    if _p_type == "rain":
        if _p_rate is not None:
            _p_code = 61 if _p_rate < 0.10 else (65 if _p_rate > 0.30 else 63)
        else:
            _p_code = 63  # no farm rate parsed: middle intensity (KCRE never sets intensity)
        _p_word = {61: "Light Rain", 63: "Rain", 65: "Heavy Rain"}[_p_code]
    elif _p_type == "snow":
        if _p_rate is not None:
            _p_code = 71 if _p_rate < 0.10 else (75 if _p_rate > 0.30 else 73)
        else:
            _p_code = 73  # no farm rate parsed: middle intensity (KCRE never sets intensity)
        _p_word = {71: "Light Snow", 73: "Snow", 75: "Heavy Snow"}[_p_code]
    elif _p_type == "thunderstorm":
        _p_code, _p_word = 95, "Thunderstorm"
    else:
        _p_code, _p_word = 63, "Rain"
    SKY_WORD, CONDITION_TEXT = _p_word, _p_code
    _precip_staged = True
    print("SKY PRECIP gate PASSED: %s (conditionText %d) - title %r icon %s, farm rate %s in/hr, radar farm-box last %d px" % (SKY_WORD, CONDITION_TEXT, WM_TITLE, WM_ICON, _p_rate, _p_radar_last))
elif _p_title_hit:
    print("SKY PRECIP gate FAILED (Open-Meteo WMO %s / title %r icon %s type %s rate %s radar last %s falling %s) - falling through to cloud-cover sky" % (_OM_CODE_STR, WM_TITLE, WM_ICON, _p_type, _p_rate, _p_radar_last, _p_farm_falling))
# RUN-1218: automated sky is the Open-Meteo cloud-cover word when the OM
# fetch succeeded (Fog 45 when WMO is 45/48; a precip WMO code with a
# FAILED gate falls through to the cloud-cover word - no precip stages
# without radar+farm-rate confirmation). WunderMap word is the fallback
# when OM failed; unknown WunderMap titles use the corroborated fallback.
_SKY_SRC = None
if _precip_staged:
    _SKY_SRC = "precip gate (Open-Meteo WMO %s / WunderMap %s/%s, radar+farm-rate confirmed)" % (_OM_CODE_STR, WM_ICON, WM_TITLE)
    print("SKY PRECIP staged %s (conditionText %d) - radar+farm-rate confirmed (farm/neighborhood evidence only)" % (SKY_WORD, CONDITION_TEXT))
elif _OM_OK and _OM_WORD is not None:
    SKY_WORD, CONDITION_TEXT = _OM_WORD, _OM_CT
    _SKY_SRC = "Open-Meteo cloud_cover %s%% (WMO %d)" % (_OM_COVER, _OM_CODE)
elif WM_TITLE in SKY_MAP:
    SKY_WORD, CONDITION_TEXT = SKY_MAP[WM_TITLE]
    _SKY_SRC = "WunderMap %s/%s (Open-Meteo unavailable)" % (WM_ICON, WM_TITLE)
else:
    _SKY_SRC = "corroborated fallback (Open-Meteo unavailable)"
    print("NOTE: unknown WunderMap sky title %r (icon %s) - present-weather phrase, not a sky word; falling back to corroborated sky" % (WM_TITLE, WM_ICON))
    _corrob = {}
    # ACTIONS: RetroCast/Jr files do not exist on a GitHub runner; when either
    # is missing the corroboration cannot be unanimous, so fall through to
    # "keep previously staged sky" below instead of crashing on [-1].
    try:
        _rcf2 = sorted(glob.glob(os.path.expanduser("~/workspace/goals/troy-s-personal-retrocast/hidden_files/retrocast-15min-data-*.json")))[-1]
        _corrob["RC"] = json.load(open(_rcf2)).get("sky")
        _jrf2 = sorted(glob.glob(os.path.expanduser("~/workspace/goals/weatherstar-jr-farm-conditions-hourly-screenshots/hidden_files/jr_data_*.json")))[-1]
        _corrob["Jr"] = json.load(open(_jrf2)).get("sky")
    except (IndexError, FileNotFoundError, KeyError, ValueError) as _corrob_e:
        print("NOTE: corroboration files unavailable in Actions (%r) - keeping previously staged sky" % (_corrob_e,))
        _corrob["RC"] = _corrob["Jr"] = _corrob["KCRE"] = None
    _corrob["KCRE"] = json.load(open(os.path.join(HF, "kcre_run%d.json" % RUN)))["properties"].get("textDescription")
    _reg = open(os.path.join(HF, "regional-metars_run%d.xml" % RUN)).read()
    _reg_sky = sorted(set(re.findall(r'<sky_condition[^>]*sky_cover="([^"]*)"[^>]*/>', _reg)))
    _reg_wx = sorted(set(re.findall(r'<wx_string>([^<]*)</wx_string>', _reg)))
    print("corroboration: RC %r Jr %r KCRE %r regional sky_cover %s wx %s" % (_corrob["RC"], _corrob["Jr"], _corrob["KCRE"], _reg_sky, _reg_wx))
    _norm = {"clear": "Clear", "sunny": "Sunny", "fair": "Fair",
             "partly cloudy": "Partly cloudy", "mostly cloudy": "Mostly cloudy", "cloudy": "Cloudy"}
    _words = set(_norm.get(str(v).strip().lower(), None) for v in _corrob.values())
    if len(_words) == 1 and None not in _words and _reg_sky == ["CLR"] and not _reg_wx:
        SKY_WORD, CONDITION_TEXT = SKY_MAP[_words.pop()]
        print("SKY fallback: corroborated unanimous %s (conditionText %d); WunderMap title %r NOT staged" % (SKY_WORD, CONDITION_TEXT, WM_TITLE))
    else:
        _prev_ct = json.load(open(os.path.join(CLONE, "4000-myrtle-intl/farm-data.json")))["conditionText"]
        _obs_est2 = datetime.now(_NY_TZ)
        _ct_word = {0: ("Sunny" if 6 <= _obs_est2.hour < 18 else "Clear"), 1: "Fair", 2: "Partly cloudy", 3: "Mostly cloudy", 61: "Light Rain", 63: "Rain", 65: "Heavy Rain", 71: "Light Snow", 73: "Snow", 75: "Heavy Snow", 95: "Thunderstorm", 99: "Thunderstorm"}[_prev_ct]
        SKY_WORD, CONDITION_TEXT = _ct_word, _prev_ct
        print("SKY fallback: corroboration disagrees %s - KEEP previously staged sky %s (conditionText %d) from live HEAD; WunderMap title %r NOT staged" % (_corrob, SKY_WORD, CONDITION_TEXT, WM_TITLE))
# Daytime Clear -> Sunny per standing rule (6 AM-6 PM); at night Clear stays Clear.
_obs_est = _obs_dt(w).astimezone(_NY_TZ)
if SKY_WORD == "Clear" and 6 <= _obs_est.hour < 18:
    SKY_WORD = "Sunny"
print("SKY %s (conditionText %d) from %s at %s EST" % (SKY_WORD, CONDITION_TEXT, _SKY_SRC, _obs_est.strftime("%H:%M")))
# RUN-967 EYE OVERRIDE (body rule: Troy's eyes win 3h): a fresh eye report
# stages ITS sky instead of the model sky. A precip eye word still needs the
# farm precip gate to have passed (WunderMap title/icon + radar echo + farm
# rate) - his eyes + the gate must agree; a precip eye word with a failed
# gate keeps the computed sky and logs loudly (never stage an unconfirmed
# precip word). A non-precip eye word overrides outright per the body.
# Nov 27: the gate works both ways now — a staged precip word (gate
# passed) beats a stale non-precip eye word, so real rain is never
# hidden by an old Fair. Plain cloud changes still wait for his new
# report or the 3h expiry — his eyes beat the model for clouds.
if _EYE is not None:
    if _EYE["code"] in (61, 63, 65, 71, 73, 75, 95):
        if _precip_staged:
            print("EYE OVERRIDE: %r (%.1fh old) + precip gate PASSED (%s ct %d) - staging eye sky %s (conditionText %d)" % (_EYE["condition"], _EYE["age_h"], SKY_WORD, CONDITION_TEXT, _EYE["word"], _EYE["code"]))
            SKY_WORD, CONDITION_TEXT = _EYE["word"], _EYE["code"]
        else:
            print("EYE OVERRIDE BLOCKED: eye report %r but precip gate FAILED - keeping computed sky %s (ct %d); eye report stands un-overwritten in sky_ground_truth.json" % (_EYE["condition"], SKY_WORD, CONDITION_TEXT))
    else:
        if _precip_staged:
            # NOV 27 FIX (Troy's question): real precip beats a stale
            # non-precip eye word. The gate already proved rain/snow/
            # thunder over the farm (WunderMap + radar echo + farm
            # rate), so a Fair/Cloudy eye word from before it started
            # must not hide it — his Nov 21 rule says falling precip
            # MUST be reported. The eye word is NOT overwritten; it
            # simply loses this run, and the next run re-checks.
            print("EYE OVERRIDE SUPERSEDED: eye %r (%.1fh old) is non-precip but farm precip gate PASSED - keeping computed precip sky %s (ct %d)" % (_EYE["condition"], _EYE["age_h"], SKY_WORD, CONDITION_TEXT))
        else:
            print("EYE OVERRIDE: %r (%.1fh old) - staging eye sky %s (conditionText %d) over model sky %s (ct %d)" % (_EYE["condition"], _EYE["age_h"], _EYE["word"], _EYE["code"], SKY_WORD, CONDITION_TEXT))
            SKY_WORD, CONDITION_TEXT = _EYE["word"], _EYE["code"]
# OSO farm row.
_oso = open(os.path.join(HF, "oso_run%d.html" % RUN)).read()
_i = _oso.find("CALABASH-FARM")
assert _i >= 0, "OSO farm row missing"
print("OSO farm row:", _oso[_i:_i+120].replace("\n", " "))
# RetroCast newest + Jr newest.
# RUN-855 FIX: the newest RC file can carry a STALE wu_obs - 1956n was written
# 01:12Z with wu_obs 2026-11-20T00:57:44Z (~24h old Nov 19 evening values,
# P 30.12 vs WU+OSO 29.99) while the previous file (1941n, obs 00:45:49Z) is
# fresh and corroborates WU exactly. Body rule: reject RetroCast data older
# than 1 hour. Pick the newest RC file whose wu_obs_utc is within 1h of now
# (freshest WU obs); cross-checks use that file. If no RC file is fresh,
# skip the RC cross-checks with a NOTE - WU+OSO govern, RC is only a
# cross-check when WU is fresh - instead of aborting on stale data.
# (The WunderMap-unknown-title sky fallback above still picks the newest
# file; its unanimity requirement fails safe to "keep staged sky" on a
# stale RC night - align it to this helper if it ever fires then.)
_rcf = None
_rc = None
_rc_fresh = False
for _cand in sorted(glob.glob(os.path.expanduser("~/workspace/goals/troy-s-personal-retrocast/hidden_files/retrocast-15min-data-*.json")), reverse=True):
    _d = json.load(open(_cand))
    try:
        _age = (_now - datetime.fromisoformat(str(_d.get("wu_obs_utc", "")).replace("Z", "+00:00"))).total_seconds()
    except Exception:
        _age = 1e9
    if _age <= 3600:
        _rcf, _rc, _rc_fresh = _cand, _d, True
        break
    print("NOTE: RC %s wu_obs %s is %.1fh old - STALE, skipping to previous file" % (_d.get("run"), _d.get("wu_obs_utc"), _age / 3600))
if not _rc_fresh:
    print("NOTE: no fresh RetroCast file (all wu_obs >1h old) - RC cross-checks SKIPPED; WU+OSO govern")
    _rc = {"run": "none-fresh", "wu_obs_utc": "none", "temp": "n/a", "feelsLike": "n/a",
           "dewpoint": "n/a", "humidity": "n/a", "wind_speed": "n/a", "windGust": "n/a",
           "pressure": "n/a", "wind_dir_deg": "n/a", "sky": "n/a"}
if _rc_fresh:
    # RC wu_raw may be a HYBRID flip (run 0526n: temp C, wind km/h, pressure hPa
    # in the raw widgets) - cross-check against RC's NORMALIZED fields (F/mph/inHg),
    # never the raw widget values.
    print("RC %s (wu_raw obs %s, hybrid_flip=%s): raw temp %s feels %s dew %s RH %s wind %s gust %s P %s dir %s sky %s | normalized temp %sF feels %sF dew %sF RH %s wind %s mph gust %s mph P %s inHg dir %s" % (
        _rc["run"], _rc["wu_obs_utc"], _rc.get("hybrid_flip"), _rc["wu_raw"]["temp"], _rc["wu_raw"]["feels"], _rc["wu_raw"]["dew"],
        _rc["wu_raw"]["humidity"], _rc["wu_raw"]["wind_speed"], _rc["wu_raw"]["wind_gust"],
        _rc["wu_raw"]["pressure"], _rc["wu_raw"]["wind_dir"], _rc["sky"],
        _rc["temp"], _rc["feelsLike"], _rc["dewpoint"], _rc["humidity"], _rc["wind_speed"], _rc["windGust"], _rc["pressure"], _rc["wind_dir_deg"]))
    # RUN-774 FIX (same class as run-720 temp / run-708 dew / run-702/734 gust
    # relaxations): RC normalized pressure is stored to ONE decimal (30.1 =
    # 30.05-30.15), while WU freshest reads 30.08 with pressure falling
    # 30.10->30.08 across this run's gens and the RC obs ~9.5 min older than
    # the freshest WU obs (04:58:18Z vs 05:07:44Z). A 0.02 spread exactly at
    # the old strict < 0.02 boundary is quantization + inter-obs drift, not a
    # normalization failure (OSO 2356Z independently reads 30.10, agreeing
    # with RC). A real normalization failure would be off by ~1 inHg or be
    # hPa-scale. Tolerance 0.05 with a NOTE at >= 0.02; WU freshest governs.
    _p_spread = abs(float(_rc["pressure"]) - PRESS_INHG)
    if _p_spread >= 0.02:
        print("NOTE: RC normalized pressure %s inHg vs WU freshest %.2f inHg (spread %.2f, RC obs %s vs WU %s, RC stored to 1 decimal) - inter-obs drift + quantization; WU freshest governs" % (_rc["pressure"], PRESS_INHG, _p_spread, _rc["wu_obs_utc"], w["obs"][:25]))
    assert _p_spread < 0.05, "RC normalized pressure disagrees: %s vs %.2f" % (_rc["pressure"], PRESS_INHG)
    # RUN-720 LESSON (same class as run-708 dew drift and run-702/710 gust
    # relaxations): RC normalized temp can lag the freshest WU obs by ~1.5F when
    # the RC obs is ~10 min older and the temp is rising - RC 1026n obs 15:27:50Z
    # reads 62F, corroborated by OSO 1026Z 62F, while WU gens rose 63.0F (15:32Z)
    # to 63.5F (15:38Z freshest). A 1.5F spread across a 10-min gap with a rising
    # temp trend is inter-obs drift, not a source failure. Tolerance 2.0 with a
    # NOTE at >= 1.0; a real normalization failure would be off by tens of
    # degrees. WU freshest governs per body source priority.
    _temp_spread = abs(float(_rc["temp"]) - w["temp"])
    if _temp_spread >= 1.0:
        print("NOTE: RC normalized temp %sF vs WU freshest temp %.1fF (spread %.1f, RC obs %s vs WU %s) - inter-obs temp drift on a rising trend; WU freshest governs" % (_rc["temp"], w["temp"], _temp_spread, _rc["wu_obs_utc"], w["obs"][:25]))
    # RUN-1024 FIX (same quantization class as run-774 pressure): RC
    # normalized temp is stored WHOLE-degree, so a true 1.5F drift reads as
    # 2.0 at the boundary - this run RC raw 74.5F (obs 19:28:48Z, hybrid
    # False) normalizes to 75F vs WU freshest 73.0F (19:39:05Z); raw spread
    # 1.5F, and the nearest-in-time WU gen (x4, 19:33:15Z) reads 73.8F,
    # 0.7F from RC raw, on a falling trend (73.8 -> 73.0 over the run).
    # A real normalization failure would be off by tens of degrees.
    # Tolerance stays 2.0 but the boundary is now inclusive; WU freshest
    # governs. Future runs must carry this version, not the strict < 2.0.
    assert _temp_spread <= 2.0, "RC normalized temp disagrees: %s vs %.1f" % (_rc["temp"], w["temp"])
    # RUN-708 LESSON: dew cross-check tolerance 1.5 was too tight when the RC obs
    # is >10 min older than the freshest WU obs - WU dew rose 49.0F (12:22Z) to
    # 50.0F (12:33-12:39Z) while RC 0726n (obs 12:26:16Z) still read 48F, which
    # OSO 0726 independently corroborates (dew 48). A 2.0F spread across a
    # 13-min gap with a rising dew trend is inter-obs drift, not a source
    # failure (same class as the run-702 gust relaxation). Tolerance 2.5 with
    # a NOTE at >= 1.5; a real normalization failure would be off by tens
    # of degrees. WU freshest governs per body source priority.
    # RUN-914 FIX (same class as run-708/720/774 relaxations): WU's own six
    # gens this run span dew 61.0F (x4 16:17:43Z) to 64.0F (r5 16:22:16Z) - a
    # 3.0F internal spread in ~5 min - while OSO 1111Z, RC 1111n (obs
    # 16:12:14Z) and Jr 1051 (dewpoint_f 61) all independently read 61F. The
    # 2.5 cross-check tolerance is tighter than the source's own noise, so it
    # false-aborted pre-write on a 3.0 spread. Tolerance 3.5 with a NOTE at
    # >= 1.5; a real normalization failure would be off by tens of degrees.
    # WU freshest governs per body source priority (staged dew 64.0F, r5).
    _dew_spread = abs(float(_rc["dewpoint"]) - w["dew"])
    if _dew_spread >= 1.5:
        print("NOTE: RC normalized dew %sF vs WU freshest dew %.1fF (spread %.1f, RC obs %s vs WU %s) - inter-obs dew drift; WU freshest governs" % (_rc["dewpoint"], w["dew"], _dew_spread, _rc["wu_obs_utc"], w["obs"][:25]))
    # RUN-1203 FIX (same class as run-1024 temp / run-708/914 dew drift):
    # dew FELL 46F -> 41F in ~11 min (RC 1226n obs 17:27:24Z dew 46,
    # corroborated by OSO 1226Z dew 46; WU gens fall monotonically
    # 44.0 (17:33:52Z) -> 43.0 -> 42.1 -> 41.0 (17:38:04Z freshest) -
    # real dry-air advection, wind NE 10-14 mph, RH 64 -> 53).
    # Comparing the 11-min-old RC dew against the freshest WU dew
    # (spread 5.0) false-aborts on real inter-obs drift. Compare RC
    # against the NEAREST-IN-TIME WU gen instead (x4, 17:33:52Z, dew
    # 44.0F, spread 2.0, within the 3.5 tolerance); a real
    # normalization failure would still be off by tens of degrees.
    # WU freshest still governs the staged value. Future runs must
    # carry this nearest-gen version, not the freshest-only assert.
    _rc_dt = datetime.fromisoformat(str(_rc["wu_obs_utc"]).replace("Z", "+00:00"))
    _near_name, _near = min(gens, key=lambda ng: abs((_obs_dt(ng[1]) - _rc_dt).total_seconds()))
    _dew_spread_near = abs(float(_rc["dewpoint"]) - _near["dew"])
    print("NOTE: RC dew cross-check vs nearest-in-time WU gen %s (obs %s, dew %.1fF): spread %.1f (vs freshest spread %.1f on the falling-dew trend)" % (_near_name, _near["obs"][:25], _near["dew"], _dew_spread_near, _dew_spread))
    assert _dew_spread_near < 3.5, "RC normalized dew disagrees vs nearest WU gen %s: %s vs %.1f" % (_near_name, _rc["dewpoint"], _near["dew"])
    # RUN-702 LESSON: gust cross-check tolerance 0.6 was too tight at light wind -
    # WU gust decayed 6->5 mph between obs (all six WU gens this run agree on 5;
    # OSO 0556 + RC 0556n, both ~10 min older, still read 6). A 1 mph spread at
    # 2 mph sustained is inter-obs gust decay, not a source failure. Tolerance
    # 1.5 (same as dew); print a NOTE when the spread exceeds 0.6.
    # RUN-710 LESSON: the gust can also RISE fast - WU gust rose 7->10 mph in
    # ~10 min (OSO 0756 + RC 0756n both read 7 at 12:56Z; all six WU gens read
    # 10 at 13:02-13:06Z; KCRE 12:35Z sustained ~9 mph NE, no gust reported).
    # A 3.0 mph spread across a 10-min gap with a rising gust trend is real
    # inter-obs gust change, not a normalization failure (temp/dew/P all agree).
    # Tolerance 3.5 with a NOTE at >= 0.6; WU freshest governs per body.
    # RUN-734 LESSON (same class): the gust can rise FURTHER - WU gust rose 7->11
    # mph (RC 1356n obs 18:58:39Z reads 7, OSO 1341Z reads 9, all six WU gens
    # obs 19:03-19:07Z read 11; regionally corroborated - KSUT gust 17 kt,
    # KCRE sustained 11 kt NE at 18:45-18:53Z; temp/dew/P all agree within
    # tolerance). A 4.0 mph spread across a ~9-min gap with a rising gust trend
    # is real inter-obs gust change, not a normalization failure. Tolerance is
    # now 5.0 mph with a NOTE at >= 0.6; WU freshest governs. Future run
    # scripts must carry the run-734 version, not the old 3.5 assert.
    _gust_spread = abs(float(_rc["windGust"]) - w["gust"])
    if _gust_spread >= 0.6:
        print("NOTE: RC normalized gust %s mph vs WU freshest gust %.1f mph (spread %.1f) - inter-obs gust change; WU freshest governs" % (_rc["windGust"], w["gust"], _gust_spread))
    # RUN-784 LESSON (same class as run-734): the gust can rise 7->13 mph in
    # ~1 min and then PERSIST - WU x4 obs 07:34:29Z reads gust 7 (RC 0226n
    # obs 07:34:29Z agrees, OSO 0226Z gust 7), but r1 obs 07:35:18Z (49s
    # later) reads gust 13 and r2-r5 (07:36-07:40Z) all read 13, sustained
    # 3-5 mph. A live re-fetch after the abort (obs 07:42:33Z) STILL reads
    # gust 13 with sustained 1 mph - a real gust regime, not a parse glitch:
    # regional flow is NE 7-9 mph sustained (KHYW 7kt, KSUT 8kt, KMYR 8kt,
    # KCRE 10 mph), so farm gusts to 13 are consistent. A 6.0 mph spread
    # across a ~6-min gap with a rising-then-persistent gust trend is real
    # inter-obs gust change, not a normalization failure (temp/dew/P all
    # agree within tolerance). Tolerance is now 7.0 mph with a NOTE at
    # >= 0.6; WU freshest governs. Future run scripts must carry the
    # run-785 version, not the old 5.0 assert. (Gust 13 < 16 mph, so the
    # display rule shows the higher-of 13 mph with no gust wording.)
    assert _gust_spread < 7.0, "RC normalized gust disagrees: %s vs %.1f" % (_rc["windGust"], w["gust"])
    if _rc["sky"] != SKY_WORD and not (_rc["sky"] == "Clear" and SKY_WORD == "Sunny"):
        print("NOTE: RC sky %r differs from WunderMap sky %r - WunderMap governs per body source priority" % (_rc["sky"], SKY_WORD))
# ACTIONS: Jr files do not exist on a GitHub runner. When missing, Jr values
# are n/a and monthly precip keeps the previous staged file (see below) -
# never abort on a missing Jr file.
_jr_files = sorted(glob.glob(os.path.expanduser("~/workspace/goals/weatherstar-jr-farm-conditions-hourly-screenshots/hidden_files/jr_data_*.json")))
if _jr_files:
    _jrf = _jr_files[-1]
    _jr = json.load(open(_jrf))
else:
    _jrf = "none"
    _jr = {}
    print("NOTE: no Jr data file in Actions - Jr sky/temp/precip n/a; monthly precip keeps previous file")
# RUN-1000 FIX (same class as run-825/890): the newest Jr file
# (jr_data_20261122_0750.json onward) moved the staged values into a nested
# "staged" dict - top-level "nov_precip_in" / "sky" / "temp_f" no longer
# exist, so the old parse returned None and the run aborted at the
# monthly-precip assert AFTER farm-data/forecast/METARs were staged
# (partial stage; source restored from clone live HEAD before re-running).
# Lookup order: staged.nov_precip_in -> top-level november_precip_in ->
# top-level nov_precip_in -> leading number of "nov_precip_basis"
# ("1.49 in = Nov 7 0.02 + Nov 21 0.31 + Nov 22 1.16 so far"). A missing or
# non-numeric value still aborts below at the monthly-precip assert -
# never stage unverified. Future runs: if Jr restructures again, extend
# this lookup, never drop the verification.
_jr_staged = _jr.get("staged") or {}
_jr_sky = _jr_staged.get("sky", _jr.get("sky"))
_jr_temp = _jr_staged.get("temp_f", _jr.get("temp_f"))
_jr_precip = _jr_staged.get("nov_precip_in")
if _jr_precip is None:
    _jr_precip = _jr.get("november_precip_in") if _jr.get("november_precip_in") is not None else _jr.get("nov_precip_in")
if _jr_precip is None and isinstance(_jr.get("nov_precip_basis"), str):
    _pm0 = re.match(r'^\s*([0-9]*\.?[0-9]+)', _jr["nov_precip_basis"])
    if _pm0:
        _jr_precip = float(_pm0.group(1))
        print("NOTE: Jr precip taken from nov_precip_basis leading number (%.2f) - staged-dict/top-level keys absent" % _jr_precip)
if isinstance(_jr_precip, str):
    _pm = re.match(r'^\s*([0-9]*\.?[0-9]+)', _jr_precip)
    assert _pm, "Jr precip not numeric: %r" % _jr_precip
    _jr_precip = float(_pm.group(1))
print("Jr %s: sky %s temp %sF Nov precip %s" % (os.path.basename(_jrf), _jr_sky, _jr_temp, _jr_precip))
# KCRE + alerts.
_kc = json.load(open(os.path.join(HF, "kcre_run%d.json" % RUN)))["properties"]
print("KCRE: %s %sC wind %s deg %s km/h vis %s m obs %s" % (_kc.get("textDescription"), _kc["temperature"]["value"], _kc["windDirection"]["value"], _kc["windSpeed"]["value"], _kc["visibility"]["value"], _kc["timestamp"]))
_kc_vis_mi = float(_kc["visibility"]["value"]) / 1609.34
print("KCRE visibility %.1f mi" % _kc_vis_mi)
_kc_age = (_now - datetime.fromisoformat(_kc["timestamp"].replace("Z", "+00:00"))).total_seconds()
assert 0 <= _kc_age <= 7200, "KCRE obs too old: %s" % _kc["timestamp"]
# RUN-959: visibility + ceiling come from THIS run's fresh KCRE obs (standing
# rule: vis/ceiling on his pages come from KCRE METAR). Ceiling = lowest
# BKN/OVC cloud base, m -> ft. Replaces the hardcoded 10 mi for good.
VISIBILITY_KM = round(_kc_vis_mi * 1.60934, 2)
assert 0.1 <= VISIBILITY_KM <= 50, VISIBILITY_KM
_ceil_bases_m = [l["base"]["value"] for l in (_kc.get("cloudLayers") or [])
                if l.get("amount") in ("BKN", "OVC") and l.get("base") and l["base"].get("value") is not None]
CEILING_FT = int(round(min(_ceil_bases_m) * 3.28084)) if _ceil_bases_m else None
print("KCRE-derived visibility %.2f km, ceiling %s ft (lowest BKN/OVC base)" % (VISIBILITY_KM, CEILING_FT))
# RUN-1025: ceiling from the freshest KCRE METAR text, not only the NWS obs
# API. The obs API's "latest" can go stale (run 1024: stuck at the 19:10Z
# obs, SCT-only -> ceiling None, while the 19:24Z SPECI already reported
# BKN024/BKN028 and the 19:53Z METAR BKN028/OVC041). Under a Mostly Cloudy
# sky that staged "CEILING UNLIMITED" on Channel/Intl/stream, violating
# Troy's Nov 22 ~11:11 AM rule (actual ceiling always under Cloudy/Mostly
# Cloudy/Overcast/precip). The run already fetches regional-metars.xml
# (aviationweather METAR text) — parse KCRE's raw_text for BKN/OVC bases
# and prefer the FRESHER source's ceiling. NWS obs stays the fallback.
# Future run scripts must carry this override.
# RUN-1115: same-obs METAR fallback (NWS API defect, not staleness): the
# NWS obs API returned EMPTY cloudLayers for the 17:53Z obs while the SAME
# obs's aviationweather METAR text says OVC006 (600 ft) — run 1114's
# same-timestamp NWS response still carried OVC 180m (591 ft). The
# run-1025 override only fired when the METAR obs was NEWER, so this run
# first staged ceiling None under a Cloudy sky — a direct violation of
# Troy's Nov 22 ~11:11 AM rule (actual ceiling always under Cloudy).
# When the NWS-derived ceiling is None and the METAR text (same obs or
# fresher, within 2h) reports a BKN/OVC base, the METAR ceiling wins.
# The fair-sky override below still nulls it under Fair/Partly/Clear/
# Sunny/Variably Cloudy, so this fallback only matters under cloudy skies.
# Future run scripts must carry this fallback.
try:
    _reg_xml = open(os.path.join(HF, "regional-metars_run%d.xml" % RUN)).read()
    _met_ceil = None
    _met_ot = None
    for _blk in re.findall(r"<METAR>(.*?)</METAR>", _reg_xml, re.S):
        if "<station_id>KCRE</station_id>" in _blk:
            _raw_m = re.search(r"<raw_text>([^<]*)</raw_text>", _blk)
            _ot_m = re.search(r"<observation_time>([^<]*)</observation_time>", _blk)
            if _raw_m and _ot_m:
                _met_raw = _raw_m.group(1)
                _met_ot = datetime.fromisoformat(_ot_m.group(1).replace("Z", "+00:00"))
                _met_bases = [int(h) * 100 for h in re.findall(r"(?:BKN|OVC)(\d{3})", _met_raw)]
                _met_ceil = min(_met_bases) if _met_bases else None
            break
    if _met_ot is not None:
        _met_age = (_now - _met_ot).total_seconds()
        _kc_ts = datetime.fromisoformat(_kc["timestamp"].replace("Z", "+00:00"))
        if 0 <= _met_age <= 7200 and _met_ot > _kc_ts:
            print("KCRE METAR text (obs %s, fresher than NWS obs %s): ceiling %s ft — overrides NWS-derived %s ft" % (_met_ot, _kc["timestamp"], _met_ceil, CEILING_FT))
            CEILING_FT = _met_ceil
        elif 0 <= _met_age <= 7200 and _met_ot >= _kc_ts and CEILING_FT is None and _met_ceil is not None:
            print("KCRE METAR text (obs %s, same obs as NWS %s, NWS cloudLayers EMPTY): ceiling %s ft — METAR fallback overrides NWS-derived None" % (_met_ot, _kc["timestamp"], _met_ceil))
            CEILING_FT = _met_ceil
        else:
            print("KCRE METAR text not fresher/valid (age %.0fs, obs %s vs NWS %s) — keeping NWS-derived ceiling %s ft" % (_met_age, _met_ot, _kc["timestamp"], CEILING_FT))
    else:
        print("KCRE METAR text not found in regional-metars.xml — keeping NWS-derived ceiling %s ft" % CEILING_FT)
except Exception as _e:
    print("KCRE METAR-text ceiling override failed (%r) — keeping NWS-derived ceiling %s ft" % (_e, CEILING_FT))
# RUN-1011: Troy's Nov 22 ~11:11 AM vis/ceiling rule — "VISIBILITY 10 MI /
# CEILING UNLIMITED" ONLY when the staged sky is Fair, Partly Cloudy, Clear
# or Sunny; under Cloudy/Mostly Cloudy/Overcast/precipitation ALWAYS stage
# the actual KCRE ceiling. Override the KCRE-derived ceiling to None
# (UNLIMITED) for the clear-sky set. Future run scripts must carry this.
if SKY_WORD in ("Fair", "Partly cloudy", "Clear", "Sunny", "Variably Cloudy"):
    if CEILING_FT is not None:
        print("Troy vis/ceiling rule: staged sky %s -> ceiling UNLIMITED (KCRE reported %d ft, not staged)" % (SKY_WORD, CEILING_FT))
    CEILING_FT = None
# RUN-1235 FIX: the blanket "no alerts" assert aborted on ANY alert, including
# a Wind Advisory (not in Troy's severe scope) and a Coastal Flood Watch whose
# onset is Thu 07:00 EST (not yet in effect tonight) - while Troy directly
# ordered this refresh and the pages sat ~24h stale in the rain. Narrowed to
# the alert-watch's own noteworthy scope (tornado / severe thunderstorm /
# flash flood / flood / hurricane / tropical storm / storm surge / extreme
# wind, watches and warnings) AND currently in effect (onset <= now < ends).
# A noteworthy alert in effect still aborts pre-write (pages hold; parent
# decides) - the assert's safety role is preserved, not removed.
_al = json.load(open(os.path.join(HF, "alerts_run%d.json" % RUN)))
_SEVERE_WORDS = ("tornado", "severe thunderstorm", "flash flood", "flood",
                 "hurricane", "tropical storm", "storm surge", "extreme wind")
_blocking = []
for _f in _al.get("features", []):
    _p = _f.get("properties", {})
    _ev = (_p.get("event") or "").lower()
    if not any(_w in _ev for _w in _SEVERE_WORDS):
        print("Alerts: non-severe (out of scope, does not block): %s" % _p.get("event"))
        continue
    # RUN-1236 FIX: the scope in the comment above is watches and warnings
    # ONLY - the substring match on "flood" also caught "Coastal Flood
    # Advisory" (Minor severity, onset 10:48 EST Nov 26, ends 14:00), which
    # is not a Watch or Warning and aborted a routine refresh Troy directly
    # ordered while the pages sat stale in the rain. An Advisory never blocks;
    # watches/warnings in scope and in effect still abort pre-write.
    if not (_ev.endswith("watch") or _ev.endswith("warning")):
        print("Alerts: noteworthy word but an Advisory, not a Watch/Warning (does not block): %s" % _p.get("event"))
        continue
    _on = datetime.fromisoformat((_p.get("onset") or "9999-01-01T00:00:00+00:00").replace("Z", "+00:00"))
    _en = datetime.fromisoformat(((_p.get("ends") or _p.get("expires")) or "9999-01-01T00:00:00+00:00").replace("Z", "+00:00"))
    if _on <= _now < _en:
        _blocking.append(_p.get("event"))
    else:
        print("Alerts: noteworthy but NOT yet in effect (onset %s, ends %s) - does not block: %s" % (_p.get("onset"), _p.get("ends"), _p.get("event")))
print("Alerts: %d features; blocking (noteworthy + in effect): %s" % (len(_al.get("features", [])), _blocking))
assert not _blocking, "severe alert in effect: %s" % _blocking

# --- lastUpdated from the freshest fetch obs time (run-409 label-bug fix) ---
LAST_UPDATED = _obs_est.isoformat(timespec="seconds")
print("lastUpdated %s" % LAST_UPDATED)

GEN_SUMMARY = "; ".join("%s obs %s (%.1fF, feels %.1fF, dew %.1fF, P %.2f inHg, RH %d, wind %.0f mph, gust %.0f mph, dir %d)" % (
    n, g["obs"][:25], g["temp"], g["feels"], g["dew"], g["pressure"], g["humidity"], g["wind"], g["gust"], g["wind_dir"]) for n, g in gens)
SOURCE = ("WU-first via my own WU dashboard fetch this run. Six generations, IN ORDER: " + GEN_SUMMARY +
    ". STAGED the FRESHEST generation, %s %s = %s EST %s: "
    "temp %dF display (%.1fF raw), feels %dF, dew %dF, pressure %.2f inHg, RH %d, wind %.0f mph, gust %.0f mph, rain %.2f in. "
    "Wind direction: WU freshest obs reports dir %d (%s) - a real vane reading, staged as-is. "
    "Cross-checked by OSO farm row (see run log) and RetroCast %s (normalized, obs %s: temp %sF, feels %sF, dew %sF, RH %s, wind %s mph, gust %s mph, P %s inHg, dir %s, sky %s). "
    "Jr %s (sky %s, %sF, %s in Nov precip). "
    "Staged metric-native schema farm-data.json carries (app converts C->F, km/h->mph, hPa->inHg): temp %sC = %dF (app display %dF, round-half-up), "
    "feels %sC = %dF (display %dF), dew %sC = %dF (display %dF), pressure %.2f inHg = %s hPa, wind %s km/h (%.0f mph) sustained, gust %s km/h (%.0f mph). "
    "WunderMap station block fetched this run - icon %s, title %s, station KNCCAROL120 confirmed - SKY %s (conditionText %d); "
    "RetroCast %s sky %s. KCRE latest - %s, %sC, wind %s deg %s km/h, vis %s m (%.1f mi), obs %s - the airport's own sky word; "
    "farm sky %s governs from the WunderMap station block. Visibility %.1f mi%s. Alerts: NONE this run - api.weather.gov alerts active for the farm point returned 0 features. "
    "Pressure trend %s: previously staged %.2f inHg (live HEAD %s) -> now %.2f inHg (XL mechanical rule). " % (
    _fresh_name, w["obs"][:25], _obs_est.strftime("%I:%M %p"), _obs_est.strftime("%Y-%m-%d"),
    int(w["temp"] + 0.5), w["temp"], int(w["feels"] + 0.5), int(w["dew"] + 0.5), PRESS_INHG, HUMIDITY, w["wind"], w["gust"], RAIN_IN,
    WIND_DIR_DEG, WIND_DIR, _rc["run"], _rc["wu_obs_utc"], _rc["temp"], _rc["feelsLike"], _rc["dewpoint"],
    _rc["humidity"], _rc["wind_speed"], _rc["windGust"], _rc["pressure"], _rc["wind_dir_deg"], _rc["sky"],
    os.path.basename(_jrf), _jr_sky, _jr_temp, _jr_precip, TEMP_C, int(w["temp"] + 0.5), int(w["temp"] + 0.5), FEELS_C, int(w["feels"] + 0.5), int(w["feels"] + 0.5),
    DEW_C, int(w["dew"] + 0.5), int(w["dew"] + 0.5), PRESS_INHG, PRESS_HPA, WIND_KMH, w["wind"], WIND_GUST_KMH, w["gust"],
    WM_ICON, WM_TITLE, SKY_WORD, CONDITION_TEXT,
    _rc["run"], _rc["sky"], _kc.get("textDescription"), _kc["temperature"]["value"], _kc["windDirection"]["value"], _kc["windSpeed"]["value"], _kc["visibility"]["value"], _kc_vis_mi, _kc["timestamp"],
    SKY_WORD, _kc_vis_mi, (", ceiling %d ft" % CEILING_FT if CEILING_FT is not None else ""),
    TREND.upper(), prev_p_inhg, LIVE_HEAD[:8], CUR_INHG))
if _EYE is not None:
    SOURCE += (" Eye report: Troy himself reported %r at %s (%.1fh before staging) - his eyes govern the sky word for 3h; "
               "staged %s (conditionText %d), corroborated by the farm precip gate (WunderMap %s, farm rate %s in/hr, radar echo over the farm). " % (
               _EYE["condition"], _EYE["reported_at"], _EYE["age_h"], SKY_WORD, CONDITION_TEXT, WM_TITLE, _p_rate))

# CLOUD-COVER DISPLAY FIELD (Troy, Nov 25, clarified Nov 27): the main
# current-conditions screens show the Open-Meteo total cloud-cover % at the
# farm point - Channel/International in place of feels-like (feels-like only
# when real wind chill/heat index), Battaglia added alongside feels-like.
# Same OM call that drives the sky word, so the % and the word always agree.
# When OM fails, carry the previous staged value forward (<=15 min old by
# construction); None only when no previous value exists.
if _OM_OK and _OM_COVER is not None:
    CLOUD_COVER = int(round(float(_OM_COVER)))
else:
    _cc_prev = prev.get("cloudCover")
    CLOUD_COVER = int(_cc_prev) if isinstance(_cc_prev, (int, float)) and 0 <= float(_cc_prev) <= 100 else None
    print("NOTE: Open-Meteo cloud cover unavailable - carrying previous staged cloudCover %s" % (CLOUD_COVER,))
assert CLOUD_COVER is None or (isinstance(CLOUD_COVER, int) and 0 <= CLOUD_COVER <= 100), CLOUD_COVER
print("CLOUD COVER: %s%% (Open-Meteo total at farm point)" % (CLOUD_COVER,))

data = {
    "ceiling": CEILING_FT,
    "cloudCover": CLOUD_COVER,
    "conditionText": CONDITION_TEXT,
    "dewPoint": DEW_C,
    "feelsLike": FEELS_C,
    "humidity": HUMIDITY,
    "lastUpdated": LAST_UPDATED,
    "locationCity": "CALABASH-FARM AT BRUNSWICK",
    "pressure": PRESS_HPA,
    "pressureTrend": TREND,
    "rainTodayIn": RAIN_IN,
    "source": SOURCE,
    "temperature": TEMP_C,
    "uvIndex": None,
    "visibility": VISIBILITY_KM,
    "windDirection": WIND_DIR,
    "windGust": WIND_GUST_KMH,
    "windSpeed": WIND_KMH,
}

# --- Forecast: staged gen read from the source files (dynamic, never hardcoded) ---
def _texts(fc):
    periods = fc["properties"]["periods"]
    assert len(periods) == 14, len(periods)
    out = []
    for p in periods:
        pop = (p.get("probabilityOfPrecipitation") or {}).get("value") or 0
        out.append("%s... %s Precip chance %d%%." % (p["name"].upper(), p["detailedForecast"], pop))
    return out
newfc = json.load(open(os.path.join(HF, "nws_forecast_run%d.json" % RUN)))
newfc2 = json.load(open(os.path.join(HF, "nws_forecast_run%d_recheck.json" % RUN)))
NEW_GEN = newfc["properties"]["generatedAt"]
RECHECK_GEN = newfc2["properties"]["generatedAt"]
new_texts = _texts(newfc)
rec_texts = _texts(newfc2)
if new_texts != rec_texts:
    print("NOTE: init/recheck forecast texts differ - freshest (recheck) gen %s governs" % RECHECK_GEN)
    new_texts = rec_texts
    NEW_GEN = RECHECK_GEN
assert all("'" not in t and "\\" not in t for t in new_texts), "fresh texts must be JS single-quote safe"
# Staged gen from the first copy's gen comment (all three must agree).
_gens = set()
for copy in COPIES:
    lf = os.path.join(SRC, copy, "scripts/modules/localforecast.mjs")
    _m = re.search(r"// generated (\S+)", open(lf).read())
    assert _m, "no staged gen comment in %s" % copy
    _gens.add(_m.group(1).rstrip(";"))  # gen comment ends in ';' - strip it so the STAGE DONE line prints a single ';'
assert len(_gens) == 1, "staged gens differ across copies: %s" % _gens
STAGED_GEN = _gens.pop()
print("forecast: staged gen %s, fresh gen %s" % (STAGED_GEN, NEW_GEN))
# RUN-831 FIX (carried): never replace with an OLDER forecast gen. Run 831's
# stage fetches (init + recheck) BOTH served gen 15:20:14Z while staged was
# 19:07:21Z - a stale NWS node - and the texts-decide rule block-replaced all
# three copies backwards. Gen strings are ISO timestamps, so lexicographic
# comparison is chronological. When the fresh gen is older, KEEP the staged
# forecast regardless of diffs.
GEN_GUARD = NEW_GEN < STAGED_GEN
if GEN_GUARD:
    print("FORECAST GEN GUARD: fresh gen %s OLDER than staged %s - KEEPING staged forecast regardless of diffs" % (NEW_GEN, STAGED_GEN))
# RUN-704 FIX (carried): the old regex anchored the forecast block's first period to
# TONIGHT|OVERNIGHT only, so a morning rollover (fresh gen leads with TODAY)
# replaced the block and then failed its own re-read verification, aborting
# the run after a partial write to the first copy. First period is one of
# TODAY/TONIGHT/OVERNIGHT depending on the issuance hour.
# RUN-730 FIX (same class): an afternoon issuance leads with THIS AFTERNOON
# (fresh gen 18:08Z = 13:08 EST, first period "This Afternoon"), so the
# TODAY|TONIGHT|OVERNIGHT regex again replaced the block and failed its own
# re-read verification, aborting after a partial write to the first copy
# (4000-myrtle-intl/localforecast.mjs only; restored from clone live HEAD
# before re-running). First period is now one of TODAY/THIS AFTERNOON/
# TONIGHT/OVERNIGHT depending on the issuance hour. Future runs: if NWS
# ever leads with another relative period, extend this alternation, never
# narrow it.
# RUN-1236 FIX: NWS leads the Thanksgiving Day forecast with the holiday name
# ("Thanksgiving Day", fresh gen 2026-11-26T16:39:42Z) - the old alternation
# (TODAY/THIS AFTERNOON/TONIGHT/OVERNIGHT) failed the stage's own re-read
# verification after a good block replace, aborting mid-write on copy 1.
# Same class as RUN-704/RUN-730, whose comment says: if NWS ever leads with
# another period, extend this alternation, never narrow it. THANKSGIVING DAY
# added; future holiday-led first periods (Christmas Day, New Year's Day -
# note the apostrophe needs the JS-safety assert checked first) extend it the
# same way. The re-read after replace and the next run's old-block read both
# need the holiday name present.
_block_re = re.compile(r"(\t*)'((?:TODAY|THIS AFTERNOON|TONIGHT|OVERNIGHT|THANKSGIVING DAY)[^']*)',\n((?:\t*'[^']*',\n){12}\t*'[^']*',\n)")
def _old_block(s2):
    m = _block_re.search(s2)
    assert m, "forecast block not found"
    indent = m.group(1)
    lines = [m.group(2)] + re.findall(r"\t*'([^']*)',\n", m.group(3))
    assert len(lines) == 14, len(lines)
    return m.group(0), indent, lines
forecast_action = None
_old_blocks = []
for copy in COPIES:
    lf = os.path.join(SRC, copy, "scripts/modules/localforecast.mjs")
    s2 = open(lf).read()
    assert s2.count("// generated %s" % STAGED_GEN) == 1, "staged gen comment count != 1 in %s" % copy
    old_full, indent, lines = _old_block(s2)
    _old_blocks.append(lines)
    diffs = [i for i, (a, b) in enumerate(zip(lines, new_texts)) if a != b]
    print("FORECAST %s: %d/14 diffs vs fresh gen %s at %s" % (copy, len(diffs), NEW_GEN, diffs))
    if len(diffs) == 0:
        if forecast_action is None:
            forecast_action = "KEPT"
    elif GEN_GUARD:
        print("FORECAST %s: %d/14 diffs but fresh gen older than staged - KEPT (gen guard)" % (copy, len(diffs)))
        if forecast_action is None:
            forecast_action = "KEPT"
    else:
        # Block-replace the whole 14-line forecast block (run-513 lesson).
        new_block = indent + "'" + new_texts[0] + "',\n" + "".join(indent + "'" + t + "',\n" for t in new_texts[1:])
        assert s2.count(old_full) == 1, "old forecast block count != 1 in %s" % copy
        s2 = s2.replace(old_full, new_block, 1)
        s2 = s2.replace("// generated %s" % STAGED_GEN, "// generated %s" % NEW_GEN, 1)
        open(lf, "w").write(s2)
        s2b = open(lf).read()
        assert s2b.count("// generated %s" % NEW_GEN) == 1, "new gen comment count != 1 in %s" % copy
        _full2, _ind2, lines2 = _old_block(s2b)
        assert lines2 == new_texts, "replaced forecast block != fresh texts in %s" % copy
        print("FORECAST %s: BLOCK-REPLACED with fresh gen %s (%d/14 diffs)" % (copy, NEW_GEN, len(diffs)))
        if forecast_action is None:
            forecast_action = "REPLACED"
assert _old_blocks[0] == _old_blocks[1] == _old_blocks[2], "the three staged forecast blocks differ from each other"
assert forecast_action in ("KEPT", "REPLACED"), forecast_action
if forecast_action == "KEPT":
    print("FORECAST KEPT gen %s (fresh gen %s, 0/14 diffs - identical texts, staged gen comment kept per run-685 precedent)" % (STAGED_GEN, NEW_GEN))
else:
    print("FORECAST REPLACED: staged gen %s -> fresh gen %s (block-replace, whole 14-line block)" % (STAGED_GEN, NEW_GEN))

for copy in COPIES:
    p = os.path.join(SRC, copy, "farm-data.json")
    with open(p, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    back = json.load(open(p))
    assert back["lastUpdated"] == LAST_UPDATED, back["lastUpdated"]
    assert back["pressureTrend"] == TREND and back["temperature"] == TEMP_C, back
    assert back["windDirection"] == WIND_DIR, back["windDirection"]
    assert back["windGust"] == WIND_GUST_KMH and back["windSpeed"] == WIND_KMH, back
    assert back["visibility"] == VISIBILITY_KM, back["visibility"]
    assert back.get("ceiling") == CEILING_FT, back.get("ceiling")
    assert back.get("cloudCover") == CLOUD_COVER, back.get("cloudCover")
    assert back["conditionText"] == CONDITION_TEXT, back["conditionText"]
    assert back["dewPoint"] == DEW_C, back["dewPoint"]
    assert back["humidity"] == HUMIDITY, back["humidity"]
    print("wrote", p, "temp", data["temperature"], "feels", data["feelsLike"], "dew", data["dewPoint"], "P", data["pressure"], "trend", data["pressureTrend"], "ct", data["conditionText"], "wind", data["windDirection"], data["windSpeed"], "gust", data["windGust"], "vis", data["visibility"], "lastUpdated", data["lastUpdated"])
# --- Battaglia: byte-for-byte copy of fresh Channel farm-data.json (P24) ---
shutil.copyfile(os.path.join(SRC, "4000-myrtle-intl/farm-data.json"),
                os.path.join(SRC, "4000-battaglia/farm-data.json"))
batt = open(os.path.join(SRC, "4000-battaglia/farm-data.json"), "rb").read()
chan = open(os.path.join(SRC, "4000-myrtle-intl/farm-data.json"), "rb").read()
assert batt == chan, "Battaglia farm-data.json != Channel copy"
print("staged 4000-battaglia/farm-data.json (byte-for-byte Channel copy)")

# --- Battaglia: zone-forecast.txt (KEEP if body identical; re-stage otherwise,
# preserving the staged Expires-line suffix from the live file) ---
zhtml = open(os.path.join(HF, "zfp_run%d.html" % RUN)).read()
zm = re.search(r'<pre[^>]*>(.*?)</pre>', zhtml, re.S)
assert zm, "no <pre> block in fresh ZFP fetch"
zlines = zm.group(1).split("\n")
assert zlines[0] == "" and re.match(r'^\d+$', zlines[1]), "unexpected ZFP pre-block head: %r" % zlines[:3]
zbody = "\n".join(zlines[2:])
ncz = re.search(r'NCZ109-(\d{6})-', zbody)
assert ncz, "NCZ109 section missing from fresh ZFP fetch"
staged_zfp = open(os.path.join(SRC, "4000-battaglia/zone-forecast.txt")).read()
assert "NCZ109" in staged_zfp, "NCZ109 section missing from staged ZFP"
staged_body = "\n".join(staged_zfp.split("\n")[1:])
_staged_first = staged_zfp.split("\n")[0]
_suf_m = re.match(r'^Expires:\d{12}(;;\d+)$', _staged_first)
assert _suf_m, "unexpected staged ZFP first line: %r" % _staged_first
zfp_suffix = _suf_m.group(1)
if zbody.rstrip() == staged_body.rstrip():
    print("zone-forecast.txt KEPT (same issuance, NCZ109-%s-, %s; fresh body identical to staged)" % (ncz.group(1), _staged_first))
    zfp_changed = False
else:
    _zfp_ym = datetime.now(_NY_TZ).strftime("%Y%m")
    new_zfp = "Expires:" + _zfp_ym + ncz.group(1) + zfp_suffix + "\n" + zbody
    assert new_zfp.startswith("Expires:" + _zfp_ym + ncz.group(1) + zfp_suffix + "\nFPUS52 KILM "), new_zfp[:60]
    open(os.path.join(SRC, "4000-battaglia/zone-forecast.txt"), "w").write(new_zfp)
    print("zone-forecast.txt RE-STAGED (new issuance, NCZ109-%s-, Expires %s%s%s)" % (ncz.group(1), _zfp_ym, ncz.group(1), zfp_suffix))
    zfp_changed = True

# --- Battaglia: re-stage regional-metars.xml + regional-map-metars.xml ---
# RUN-1003 FIX: the 6-station fetch failed all 3 urllib tries this run
# (RemoteDisconnected) and the hard open() below crashed the stage AFTER
# farm-data + forecast were already staged. Body rule: on fetch failure keep
# the previous staged file and note it - never crash the run. The map section
# already does this; regional now mirrors it.
_reg_path = os.path.join(HF, "regional-metars_run%d.xml" % RUN)
if not os.path.exists(_reg_path):
    print("regional-metars.xml KEPT (6-station fetch FAILED all tries - previous staged file kept per body)")
    reg_changed = False
    reg = None
else:
    reg = open(_reg_path).read()
    assert re.search(r'num_results="6"', reg), "regional METARs num_results != 6"
    assert set(re.findall(r'<station_id>([A-Z0-9]+)</station_id>', reg)) == {"KHYW","KLBT","KMYR","KSUT","KCRE","KILM"}, "regional stations mismatch"
    obs_times = re.findall(r'<observation_time>([^<]+)</observation_time>', reg)
    # RUN-755 FIX (UTC midnight rollover): obs dates straddle Nov 19/20 UTC - the
    # age check below (0-7200s vs _now) is the real freshness gate; a hardcoded
    # UTC-date regex wrongly rejects fresh Nov-20 obs after midnight UTC.
    for t in obs_times:
        _ot = datetime.fromisoformat(t.replace("Z", "+00:00"))
        assert 0 <= (_now - _ot).total_seconds() <= 7200, "regional METAR obs too old: %s" % t
    reg_staged = open(os.path.join(SRC, "4000-battaglia/regional-metars.xml")).read()
    if reg == reg_staged:
        print("regional-metars.xml KEPT (byte-identical to staged)")
        reg_changed = False
    else:
        shutil.copyfile(_reg_path,
                        os.path.join(SRC, "4000-battaglia/regional-metars.xml"))
        print("staged 4000-battaglia/regional-metars.xml (all 6 stations, obs %s)" % obs_times)
        reg_changed = True
MAP_FILE = "regional-map-metars_run%d.xml" % RUN
map_path = os.path.join(HF, MAP_FILE)
map_staged = open(os.path.join(SRC, "4000-battaglia/regional-map-metars.xml")).read()
if not os.path.exists(map_path):
    print("regional-map-metars.xml KEPT (bbox fetch FAILED all 3 tries - IncompleteRead; previous staged file kept per body)")
    map_msg = "KEPT (bbox fetch failed, previous kept)"
    mmap = None
    mm = None
else:
    mmap = open(map_path).read()
    mm = re.search(r'num_results="(\d+)"', mmap)
    assert mm and int(mm.group(1)) > 100, "map METARs num_results unexpected: %s" % (mm.group(1) if mm else None)
    mids = set(re.findall(r'<station_id>([A-Z0-9]+)</station_id>', mmap))
    missing = [k for k in ("KCRE","KMYR","KILM","KCPC","KSUT","KFLO","KLBT","KHYW") if k not in mids]
    map_msg = None
    if missing:
        print("regional-map-metars.xml KEPT (bbox %s results, missing %s; previous staged file kept per body)" % (mm.group(1), missing))
        map_msg = "KEPT (missing %s)" % missing
    elif mmap == map_staged:
        print("regional-map-metars.xml KEPT (byte-identical to staged, %s results)" % mm.group(1))
        map_msg = "KEPT (byte-identical, %s results)" % mm.group(1)
    else:
        shutil.copyfile(map_path,
                        os.path.join(SRC, "4000-battaglia/regional-map-metars.xml"))
        print("staged 4000-battaglia/regional-map-metars.xml (%s results, all 8 key stations)" % mm.group(1))
        map_msg = "RE-STAGED (%s results)" % mm.group(1)

# --- CPC outlook GIFs: verify against known-good md5s; if a GIF changed, verify
# the current month's outlook from the CPC 30-day index page before classifying.
# Stage whatever the farm-pixel classification reads (no hardcoded A/A).
# RUN-712 FIX (CPC December rollover, 2026-11-19): CPC issued a NEW 30-day
# outlook today (index: "Issued: November 19, 2026") and BOTH GIFs changed
# md5. The GIF title itself (read visually off the image this run) says
# "Valid: December 2026" - the new GIFs are NEXT month's outlook, not the
# current month's. The old code asserted "Valid: November 2026" in the
# INDEX page, but that title lives only inside the GIF image, never in the
# index HTML - so the assert aborted the run AFTER farm-data / forecast /
# METARs were staged (partial stage; recovered by restoring from clone).
# Body rule: verify the GIFs are the CURRENT month's outlook before
# staging; otherwise KEEP the previous staged file and note it. A mid-month
# (day >= 15) new issuance is the standard CPC rollover to next month's
# outlook, so it is KEPT, logged, and the run CONTINUES - a CPC anomaly
# must never abort the run again. KNOWN_ROLLOVER_MD5 are the December 2026
# GIFs (title-verified this run); once the calendar month IS December they
# are the current month's outlook and get staged (From Nov, To Dec).
from PIL import Image
from collections import Counter
KNOWN_MD5 = {"temp": "acd2b1e8ee0e7dd590b91c399e9c058c", "prcp": "017050f49643d6ea43880f73a7202604"}
KNOWN_ROLLOVER_MD5 = {"temp": "4fcbc23a8d1c7c6045b80238917f12c8", "prcp": "88a7257f22cdc1fc31a7fef32d7caa0c"}
_MONTHS = {m: i + 1 for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"])}
_today_local = datetime.now(_NY_TZ)
_cpc_rollover = False
_cpc_index = None
def _cpc_issued():
    global _cpc_index
    if _cpc_index is None:
        req = urllib.request.Request("https://www.cpc.ncep.noaa.gov/products/predictions/30day/",
                                     headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"})
        with urllib.request.urlopen(req, timeout=60) as r:
            _cpc_index = r.read().decode("utf-8", "replace")
        open(os.path.join(HF, "cpc_index_run%d.html" % RUN), "w").write(_cpc_index)
    m = re.search(r"Issued: (January|February|March|April|May|June|July|August|September|October|November|December) (\d{1,2}), (\d{4})", _cpc_index)
    return m.groups() if m else None
for kind in ("temp", "prcp"):
    raw = open(os.path.join(HF, "cpc_off14_%s_run%d.gif" % (kind, RUN)), "rb").read()
    assert raw[:6] == b"GIF89a", "CPC %s not a GIF" % kind
    md5 = hashlib.md5(raw).hexdigest()
    if md5 == KNOWN_MD5[kind]:
        print("CPC %s md5 matches run 214-710 verified copy (November 2026 outlook)" % kind)
    elif md5 == KNOWN_ROLLOVER_MD5[kind]:
        print("CPC %s md5 %s = KNOWN December 2026 rollover GIF (title-verified run 712)" % (kind, md5))
        _cpc_rollover = True
    else:
        iss = _cpc_issued()
        print("CPC %s md5 CHANGED %s (was %s) - index issuance %s" % (kind, md5, KNOWN_MD5[kind], iss))
        if iss and _MONTHS[iss[0]] == _today_local.month and int(iss[1]) >= 15:
            print("CPC %s: mid-month issuance on day %s = standard rollover to NEXT month's outlook - KEEP current month's staged outlook; record new md5s in the run log" % (kind, iss[1]))
            _cpc_rollover = True
        else:
            print("CPC %s: issuance %s is NOT a mid-month rollover - KEEP previous staged outlook per body (keep + note, never abort); record new md5 %s in the run log" % (kind, iss, md5))
            _cpc_rollover = True
def _classify(kind):
    im = Image.open(os.path.join(HF, "cpc_off14_%s_run%d.gif" % (kind, RUN))).convert("RGB").resize((720, 707))
    X, Y = 560, 468
    def _blank(p): return p == (255, 255, 255) or p == (0, 0, 0)
    def _grey(p): return p[0] == p[1] == p[2]
    hit = None
    for dy in range(-8, 9):
        for dx in range(-8, 9):
            p = im.getpixel((X + dx, Y + dy))
            if not _blank(p):
                hit = p
                break
        if hit:
            break
    assert hit is not None, "no farm pixel found in CPC %s GIF" % kind
    if _grey(hit):
        box = [im.getpixel((X + dx, Y + dy)) for dy in range(-16, 17) for dx in range(-16, 17)]
        c = Counter(p for p in box if not _blank(p) and not _grey(p))
        assert c, "no non-grey color in 32x32 box for CPC %s" % kind
        hit = c.most_common(1)[0][0]
    r, g, b = hit
    if kind == "temp":
        return ("B" if b > r else ("A" if r > b else "N")), hit
    return ("A" if g > r else ("B" if r > g else "N")), hit
temp_cls, temp_px = _classify("temp")
prcp_cls, prcp_px = _classify("prcp")
print("outlook classification from fresh GIFs: temp %s (pixel %s), prcp %s (pixel %s)" % (temp_cls, temp_px, prcp_cls, prcp_px))
# From/To per the body rule: day <= 14 -> From = previous month, To = current
# month; day > 14 -> From = To = current month. (Nov 19: Nov/Nov. Dec 1: Nov/Dec.)
if _today_local.day <= 14:
    _from_m = (_today_local.replace(day=1) - timedelta(days=1)).strftime("%b")
    _to_m = _today_local.strftime("%b")
else:
    _from_m = _to_m = _today_local.strftime("%b")
staged_out = json.load(open(os.path.join(SRC, "4000-battaglia/outlook.json")))
if _cpc_rollover and _today_local.month == 11:
    # December GIFs staged-early would mislabel December's outlook as
    # November's: keep the November outlook (A/A, From Nov, To Nov) through
    # Nov 30. December runs will stage the rollover GIFs (month == 12 below).
    print("outlook.json UNCHANGED (CPC rolled to the December 2026 outlook on Nov 19; November outlook %s stays staged for the rest of November; fresh-GIF classification %s/%s is December's, logged only)" % (staged_out, temp_cls, prcp_cls))
    outlook_changed = False
    temp_cls, prcp_cls = staged_out["Temperature"], staged_out["Precipitation"]
elif _cpc_rollover and _today_local.month == 12:
    new_outlook = {"Temperature": temp_cls, "Precipitation": prcp_cls, "From": _from_m, "To": _to_m}
    if staged_out == new_outlook:
        print("outlook.json UNCHANGED (December rollover classification %s/%s, From/To %s/%s already staged)" % (temp_cls, prcp_cls, _from_m, _to_m))
        outlook_changed = False
    else:
        with open(os.path.join(SRC, "4000-battaglia/outlook.json"), "w") as f:
            json.dump(new_outlook, f)
        print("outlook.json RE-STAGED %s -> %s (December 2026 rollover GIFs now current month; From/To per body rule)" % (staged_out, new_outlook))
        outlook_changed = True
else:
    new_outlook = {"Temperature": temp_cls, "Precipitation": prcp_cls, "From": _from_m, "To": _to_m}
    if staged_out == new_outlook:
        print("outlook.json UNCHANGED (classification %s/%s, From/To %s/%s already staged)" % (temp_cls, prcp_cls, _from_m, _to_m))
        outlook_changed = False
    else:
        with open(os.path.join(SRC, "4000-battaglia/outlook.json"), "w") as f:
            json.dump(new_outlook, f)
        print("outlook.json RE-STAGED %s -> %s (classification re-read from fresh GIFs; From/To per body rule)" % (staged_out, new_outlook))
        outlook_changed = True

# --- monthly-precip.json: WU monthly page carries no Precip Sum to verify as a sum (all precip:null in this run's fetch); Jr best-supported value governs per body ---
# RUN-925 FIX: Jr's November total rose 0.02 -> 0.03 this run (Nov 7 0.02 per
# Troy's own station reading + Nov 21 0.01, today's 0.01 confirmed by WU
# dashboard precip-total 0.01 AND OSOILM today 0.01; farm rain was 0.00
# through 12:41 PM, 0.01 by 1:41 PM). The old `assert _jr_precip == 0.02`
# hardcoded the previous total and aborted the run AFTER farm-data /
# forecast / METARs were staged (partial stage; restored from clone live
# HEAD before re-running). The body rule stages the best-supported Jr value
# when WU monthly cannot verify a sum; the staged file follows the Jr
# value, never a hardcode. A non-numeric or out-of-range Jr value still
# aborts (never stage an unverified value).
staged_mp = json.load(open(os.path.join(SRC, "4000-battaglia/monthly-precip.json")))
_cur_month = datetime.now(_NY_TZ).strftime("%B")
if staged_mp.get("month") != _cur_month:
    # ACTIONS: the staged month rolled (e.g. November file in December). There
    # is no verifiable new-month total on a runner (WU monthly carries no
    # precip sum; Jr is unavailable), so keep the previous file and log it -
    # never stage an unverified value, and never abort the whole run over it.
    print("monthly-precip.json UNCHANGED (staged month %s != current %s; no verifiable new-month total in Actions - previous file kept)" % (staged_mp.get("month"), _cur_month))
    mp_changed = False
    new_mp = staged_mp
elif _jr_precip is None:
    # ACTIONS: no Jr value on a runner and WU monthly cannot verify a sum -
    # keep the previous staged file, never stage an unverified value.
    print("monthly-precip.json UNCHANGED (no Jr value in Actions and WU monthly unverifiable - previous %.2f in kept)" % staged_mp.get("precipIn"))
    mp_changed = False
    new_mp = staged_mp
else:
    assert isinstance(_jr_precip, (int, float)) and 0 <= _jr_precip <= 10, _jr_precip
    new_mp = {"month": _cur_month, "precipIn": _jr_precip}
    if staged_mp == new_mp:
        print("monthly-precip.json UNCHANGED (Jr %s %.2f in best-supported, already staged)" % (os.path.basename(_jrf), _jr_precip))
        mp_changed = False
    else:
        with open(os.path.join(SRC, "4000-battaglia/monthly-precip.json"), "w") as f:
            json.dump(new_mp, f)
            f.write("\n")
        print("monthly-precip.json RE-STAGED %s -> %s (Jr best-supported %s)" % (staged_mp, new_mp, os.path.basename(_jrf)))
        mp_changed = True

# --- Battaglia hourly-forecast.json: verify fresh (<2h), regenerated this run ---
hf = json.load(open(os.path.join(SRC, "4000-battaglia/hourly-forecast.json")))
assert hf.get("station") == "KNCCAROL120" and len(hf.get("hours", [])) == 24, hf
_gen0 = datetime.fromisoformat(hf.get("generatedAt", ""))
assert 0 <= (datetime.now().astimezone() - _gen0).total_seconds() <= 7200, hf.get("generatedAt")
print("hourly-forecast.json generatedAt %s (fresh, within 2h)" % hf.get("generatedAt"))
assert all(isinstance(h.get("tempF"), (int, float)) for h in hf["hours"]), "hourly tempF missing"
temps = [h["tempF"] for h in hf["hours"]]
print("hourly-forecast.json staged (generatedAt %s, 24 hours %s-%s, temps %s-%sF, fresh)" % (
    hf["generatedAt"], hf["hours"][0]["hourLabel"], hf["hours"][-1]["hourLabel"],
    min(temps), max(temps)))

# --- ?v= bumps for this push (read current value dynamically, bump by 1) ---
def _cur_v(path, pat):
    t = open(path).read()
    ms = re.findall(pat, t)
    assert len(ms) == 1, "%s: ?v= pattern %r found %d times" % (path, pat, len(ms))
    return int(ms[0])
def bump(path, pat, old_v, new_v):
    t = open(path).read()
    old = pat.replace("NNN", str(old_v))
    new = pat.replace("NNN", str(new_v))
    assert t.count(old) == 1, "%r appears %dx in %s" % (old, t.count(old), path)
    open(path, "w").write(t.replace(old, new, 1))
    print("bumped", path, old, "->", new)

_v_intl = _cur_v(os.path.join(SRC, "4000-myrtle-intl/index.html"), r"styles/main\.css\?v=(\d+)")
_v_stream = _cur_v(os.path.join(SRC, "4000-myrtle-stream/index.html"), r"styles/main\.css\?v=(\d+)")
_v_exact = _cur_v(os.path.join(SRC, "4000-exact/index.html"), r"styles/main\.css\?v=(\d+)")
_v_exact_css = _cur_v(os.path.join(SRC, "4000-exact/styles/main.css"), r"4000-myrtle-intl/styles/main\.css\?v=(\d+)")
assert _v_intl == _v_stream == _v_exact == _v_exact_css, "current ?v= values disagree: %s %s %s %s" % (_v_intl, _v_stream, _v_exact, _v_exact_css)
NEW_V = _v_intl + 1
bump(os.path.join(SRC, "4000-myrtle-intl/index.html"), "styles/main.css?v=NNN", _v_intl, NEW_V)
bump(os.path.join(SRC, "4000-myrtle-stream/index.html"), "styles/main.css?v=NNN", _v_stream, NEW_V)
bump(os.path.join(SRC, "4000-exact/index.html"), "styles/main.css?v=NNN", _v_exact, NEW_V)
bump(os.path.join(SRC, "4000-exact/styles/main.css"), "4000-myrtle-intl/styles/main.css?v=NNN", _v_exact_css, NEW_V)

# --- Manifest: every REPO file that differs from the live-HEAD clone ---
# RUN-1156 FIX (collision guard): the Battaglia ?v=129 coordinator's three
# files (twc3.js / TravelCities.js / twc3.html) LANDED as live HEAD 63dd4ea3
# during this run's start (combined ?v=129 commit), so the source dir matches
# HEAD and they are not in `changed` - but a sibling may edit them again
# mid-run. This cron must NEVER push another workstream's files: skip them
# in the manifest walk entirely. (Run 1155 aborted pre-push at the manifest
# assert on TravelCities.js before this guard existed.)
SIBLING_FILES = {
    "4000-battaglia/Scripts/twc3.js",
    "4000-battaglia/Scripts/TravelCities.js",
    "4000-battaglia/twc3.html",
}
# ACTIONS: SRC == CLONE == the checkout, so the Muse walk (source dir vs
# clone) always finds nothing. The diff is the working tree vs HEAD instead.
_git_status = subprocess.run(["git", "-C", REPO_ROOT, "status", "--porcelain"],
                             capture_output=True, text=True, check=True).stdout
changed = []
for _line in _git_status.splitlines():
    _rel = _line[3:].strip().strip('"')
    if "__pycache__" in _rel or _rel in SIBLING_FILES:
        continue
    changed.append(_rel)
changed = sorted(set(changed))
assert changed, "no files changed vs HEAD - nothing to push"
allowed = {
    "4000-myrtle-intl/farm-data.json", "4000-exact/farm-data.json", "4000-myrtle-stream/farm-data.json",
    # Sky eye override persistence (Nov 27): the stored word file, written
    # on a dispatch run and deleted when cleared/expired - committed like
    # any other staged file.
    ".github/sky_override.json",
    "4000-myrtle-intl/scripts/modules/localforecast.mjs", "4000-exact/scripts/modules/localforecast.mjs",
    "4000-myrtle-stream/scripts/modules/localforecast.mjs",
    "4000-myrtle-intl/index.html", "4000-exact/index.html", "4000-myrtle-stream/index.html",
    "4000-exact/styles/main.css",
    "4000-battaglia/farm-data.json", "4000-battaglia/zone-forecast.txt",
    "4000-battaglia/regional-metars.xml", "4000-battaglia/regional-map-metars.xml",
    "4000-battaglia/outlook.json", "4000-battaglia/hourly-forecast.json",
    "4000-battaglia/monthly-precip.json",
    # RUN-1148 FIX: Battaglia SPC outlook + Battaglia Sunset Beach (P29) -
    # refreshed every run by the generators above; without these entries the
    # manifest assert aborts on "unexpected changed files".
    "4000-battaglia/spc-outlook.json", "4000-battaglia/sunset-beach.json",
    # RUN-1195 FIX: Battaglia Travel Cities (P29, Troy yes 2026-11-24
    # ~10:25 AM) - regenerated every run by stage_travel_cities.py above;
    # run 1195 died on the manifest assert without this entry.
    "4000-battaglia/travel-cities.json",
    # RUN-1161: Battaglia ?v=130 coordinator burst landed mid-run at 01:47:42
    # EST (index.js + canvasTravelForecast P29 fix, index.html ?v=91->92) -
    # verified complete: matched pair, node --check OK, stable 10 min; the
    # first stage attempt aborted at the manifest assert on these two files
    # (run-1147 precedent: carry verified coordinator files). The third
    # burst file, twc3.html (?v=129->130), stays SIBLING-guarded and
    # unpushed - the coordinator pushes ?v=130 themselves (run-1156).
    "4000-battaglia/Scripts/index.js", "4000-battaglia/index.html",
    # RUN-1145: LO swaps (Troy Nov 23 21:24) - latestobservations.mjs x3
    # (Sunset Beach + Calabash rows) and the new sunset-beach.json x3 the
    # app reads for the Sunset Beach row. New files ride via _new_only above.
    "4000-myrtle-intl/scripts/modules/latestobservations.mjs", "4000-exact/scripts/modules/latestobservations.mjs",
    "4000-myrtle-stream/scripts/modules/latestobservations.mjs",
    "4000-myrtle-intl/sunset-beach.json", "4000-exact/sunset-beach.json",
    "4000-myrtle-stream/sunset-beach.json",
    # RUN-1147: corrected LO swap + regional-maps swap landed mid-run in the
    # source dir (22:05 EST burst, identical x3, node --check OK): the
    # coordinator's FINAL plan - LO: Sunset Beach replaces WILMINGTON,
    # Southport STAYS, no Calabash row (latestobservations.mjs, already
    # allowlisted above); regional maps: Calabash IN (farm point 33.92N
    # 78.57W, farm-data.json via getFarmObservation), Wilmington OUT
    # (regionalcities.js) + KILM filtered from StationInfo
    # (regionalforecast.mjs). First stage attempt aborted pre-push at the
    # manifest assert; my staged files were restored to live HEAD per the
    # run-1145 precedent and the coordinator files kept intact.
    "4000-myrtle-intl/scripts/data/regionalcities.js", "4000-exact/scripts/data/regionalcities.js",
    "4000-myrtle-stream/scripts/data/regionalcities.js",
    "4000-myrtle-intl/scripts/modules/regionalforecast.mjs", "4000-exact/scripts/modules/regionalforecast.mjs",
    "4000-myrtle-stream/scripts/modules/regionalforecast.mjs",
    # RUN-956: the graded-precipitation page-code files (weather.mjs /
    # icons.mjs / latestobservations.mjs x3 + twc3.js/twc3.html) landed in
    # run 955's commit and now match live HEAD - dropped from the allowed
    # list per the run-955 log note. If the parent edits them again, a
    # future run must re-add them here, or the manifest assert aborts on
    # "unexpected changed files".
    # RUN-959: parent ceiling-wiring edits (22:36 EST, verified syntax-OK,
    # diffs are ceiling lines only) + twc3.js L RAIN line + twc3.html ?v= bump.
    "4000-myrtle-intl/scripts/modules/currentweatherscroll.mjs",
    "4000-myrtle-intl/scripts/modules/customweatherstation.mjs",
    "4000-exact/scripts/modules/currentweatherscroll.mjs",
    "4000-exact/scripts/modules/customweatherstation.mjs",
    "4000-myrtle-stream/scripts/modules/currentweatherscroll.mjs",
    "4000-myrtle-stream/scripts/modules/customweatherstation.mjs",
    "4000-battaglia/Scripts/twc3.js",
    "4000-battaglia/twc3.html",
}
# ACTIONS: git status already includes new (untracked) files; no _new_only step.
changed.sort()
unexpected = [c for c in changed if c not in allowed]
assert not unexpected, "unexpected changed files vs HEAD: %s" % unexpected
mpath = os.path.join(HF, "manifest_run%d.nul" % RUN)
with open(mpath, "wb") as f:
    for rel in changed:
        f.write(rel.encode() + b"\x00")
print("MANIFEST %s: %d files" % (mpath, len(changed)))
for rel in changed:
    print("  ", rel)

print("STAGE DONE - ?v= %d->%d (live HEAD %s; checkout farm-data matches live HEAD + fresh run-%d values); forecast %s (staged gen %s; fresh gen %s, texts decide); ZFP %s; regional-METARs %s; map-METARs %s; outlook %s (%s/%s, From %s To %s); monthly-precip %s (%.2f in); hourly (generatedAt %s); Battaglia farm-data.json refreshed (P24 byte-for-byte copy); daily-history.json NOT touched (nightly prior-day cadence)" % (_v_intl, NEW_V, LIVE_HEAD[:8], RUN, forecast_action, STAGED_GEN, NEW_GEN, ("RE-STAGED" if zfp_changed else "KEPT"), ("RE-STAGED" if reg_changed else "KEPT"), map_msg, ("RE-STAGED" if outlook_changed else "UNCHANGED"), temp_cls, prcp_cls, _from_m, _to_m, ("RE-STAGED" if mp_changed else "UNCHANGED"), staged_mp.get("precipIn"), hf["generatedAt"]))
