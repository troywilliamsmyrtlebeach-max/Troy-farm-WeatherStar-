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
