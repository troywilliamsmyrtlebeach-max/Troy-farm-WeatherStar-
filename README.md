# 24/7 Retro Weather Channel Live Stream Configuration
This repository runs a customized instance of the [mwood77/ws4kp-international](https://github.com/mwood77/ws4kp-international) framework, hardcoded to bypass online host caching issues.

## Active Stream Configuration
* **Target Display:** WeatherStar 4000+ Graphic Layout
* **Primary Station ID:** `KNCCAROL120` (The Farm Station — Carolina Shores, NC)
* **Ingest Status:** Real-time mesonet feed active

## Manual Cache Clear & Hard Reset Protocol
If the scrolling layout text freezes or GitHub server degradation breaks the asset pipeline, execute this hard refresh override command directly inside the browser script console:

```javascript
localStorage.clear(); sessionStorage.clear(); indexedDB.databases().then(dbs => dbs.forEach(db => indexedDB.deleteDatabase(db.name))); window.location.href = window.location.origin + window.location.pathname + "?pws=KNCCAROL120&refresh=" + Date.now();
```
<script>
  // Automatically lock in Troy's Farm Weather Station defaults
  (function enforceFarmDefaults() {
    const params = new URLSearchParams(window.location.search);
    let changed = false;

    if (!params.has('pwsId')) {
      params.set('pwsId', 'KNCCAROL120');
      changed = true;
    }
    if (!params.has('units')) {
      params.set('units', 'english');
      changed = true;
    }
    if (!params.has('kiosk')) {
      params.set('kiosk', 'true');
      changed = true;
    }

    // Populate browser local storage state used by the emulator engine
    localStorage.setItem('ws4kp_pws_id', 'KNCCAROL120');
    localStorage.setItem('ws4kp_units_temp', 'F');
    localStorage.setItem('ws4kp_units_speed', 'mph');
    localStorage.setItem('ws4kp_units_pressure', 'inHg');

    if (changed && window.history.replaceState) {
      const newRelativePathQuery = `${window.location.pathname}?${params.toString()}${window.location.hash}`;
      window.history.replaceState(null, '', newRelativePathQuery);
    }
  })();
</script>
