"""Curl-based fetch - GitHub Actions port (mirrors the Muse run-1249 fetch
(URLs, output filenames, recheck cadence) but uses curl, because the
egress tunnel returns 403 for Python urllib CONNECTs to *.wunderground.com
while curl succeeds (verified 2026-11-25 ~19:35 EST). Stage script reads
only the files, so the fetch tool does not matter. Log goes to
fetch_run1249.log (same file the urllib run wrote to)."""
import os, time, subprocess
from datetime import datetime, timezone

RUN = int(os.environ.get("REFRESH_RUN_ID", datetime.now(timezone.utc).strftime("%Y%m%d%H%M")))
HF = os.environ["WORK_DIR"]
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

def fetch(url, path, tries=3):
    last = ""
    for i in range(tries):
        r = subprocess.run(["curl", "-sS", "--max-time", "120", "-A", UA,
                            "-o", path, url], capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(path) and os.path.getsize(path) > 1000:
            print("OK %s -> %s %d bytes" % (url[:80], os.path.basename(path), os.path.getsize(path)), flush=True)
            return True
        last = (r.stderr or "")[:200]
        print("TRY %d FAIL %s: rc=%s %r" % (i + 1, url[:80], r.returncode, last), flush=True)
        if os.path.exists(path):
            os.remove(path)
        time.sleep(5)
    print("FAILED %s %r" % (url, last), flush=True)
    return False

# WU dashboard x4 (separate fetches)
for suffix in ("a", "b", "c", "d"):
    fetch("https://www.wunderground.com/dashboard/pws/KNCCAROL120",
          os.path.join(HF, "wu_run%d_%s.html" % (RUN, suffix)))
# Recheck generations (a,b each), ~60s apart
for gen in ("recheck", "recheck2", "recheck3", "recheck4", "recheck5"):
    time.sleep(60)
    for suffix in ("a", "b"):
        fetch("https://www.wunderground.com/dashboard/pws/KNCCAROL120",
              os.path.join(HF, "wu_run%d_%s_%s.html" % (RUN, gen, suffix)))
fetch("https://www.wunderground.com/weather/us/nc/carolina-shores/KNCCAROL120",
      os.path.join(HF, "wundermap_run%d.html" % RUN))
fetch("https://forecast.weather.gov/product.php?site=NWS&issuedby=ILM&product=OSO&format=CI&version=1&glossary=0",
      os.path.join(HF, "oso_run%d.html" % RUN))
fetch("https://api.weather.gov/gridpoints/ILM/68,59/forecast",
      os.path.join(HF, "nws_forecast_run%d.json" % RUN))
# RUN-1239 FIX: the generic fetch() above requires >1000 bytes, but a
# 0-feature alerts response is only 229 bytes - fetch() "failed" it 3x and
# deleted the file, aborting the stage at the alerts assert (run 1239 first
# attempt). Fetch alerts separately with a >100-byte threshold.
_alerts_path = os.path.join(HF, "alerts_run%d.json" % RUN)
_r = subprocess.run(["curl", "-sS", "--max-time", "120", "-A", UA,
                     "-o", _alerts_path,
                     "https://api.weather.gov/alerts/active?point=33.92,-78.57"],
                    capture_output=True, text=True)
if _r.returncode == 0 and os.path.exists(_alerts_path) and os.path.getsize(_alerts_path) > 100:
    print("OK alerts -> %s %d bytes" % (os.path.basename(_alerts_path), os.path.getsize(_alerts_path)), flush=True)
else:
    print("ALERTS FAIL rc=%s stderr=%r - removing partial file" % (_r.returncode, _r.stderr[:300]), flush=True)
    if os.path.exists(_alerts_path):
        os.remove(_alerts_path)
fetch("https://api.weather.gov/stations/KCRE/observations/latest",
      os.path.join(HF, "kcre_run%d.json" % RUN))
fetch("https://forecast.weather.gov/product.php?site=ILM&issuedby=ILM&product=ZFP&format=CI&version=1&glossary=0",
      os.path.join(HF, "zfp_run%d.html" % RUN))
fetch("https://aviationweather.gov/api/data/metar?ids=KHYW,KLBT,KMYR,KSUT,KCRE,KILM&format=xml",
      os.path.join(HF, "regional-metars_run%d.xml" % RUN))
_map_url = "https://aviationweather.gov/api/data/metar?format=xml&hours=1&bbox=31.8004,-84.3151,36.0396,-73.8249"
_map_path = os.path.join(HF, "regional-map-metars_run%d.xml" % RUN)
_r = subprocess.run(["curl", "-sS", "--max-time", "120", "--retry", "3", "--retry-all-errors",
                     "-A", UA, "-o", _map_path, _map_url], capture_output=True, text=True)
if _r.returncode == 0 and os.path.getsize(_map_path) > 100000:
    print("OK curl bbox -> %s %d bytes" % (os.path.basename(_map_path), os.path.getsize(_map_path)), flush=True)
else:
    print("CURL BBOX FAIL rc=%s stderr=%r - removing partial file" % (_r.returncode, _r.stderr[:300]), flush=True)
    if os.path.exists(_map_path):
        os.remove(_map_path)
for kind in ("temp", "prcp"):
    fetch("https://www.cpc.ncep.noaa.gov/products/predictions/30day/off14_%s.gif" % kind,
          os.path.join(HF, "cpc_off14_%s_run%d.gif" % (kind, RUN)))
fetch("https://www.wunderground.com/history/monthly/us/nc/carolina-shores/KNCCAROL120/date/2026-11",
      os.path.join(HF, "wu_monthly_run%d.html" % RUN))
fetch("https://api.weather.gov/gridpoints/ILM/68,59/forecast",
      os.path.join(HF, "nws_forecast_run%d_recheck.json" % RUN))
fetch("https://cdn.star.nesdis.noaa.gov/GOES19/ABI/SECTOR/se/GEOCOLOR/GOES19-SE-GEOCOLOR-600x600.gif",
      os.path.join(HF, "goes_run%d.gif" % RUN))
fetch("https://radar.weather.gov/ridge/standard/KLTX_loop.gif",
      os.path.join(HF, "kltx_run%d.gif" % RUN))
print("FETCH DONE", flush=True)
