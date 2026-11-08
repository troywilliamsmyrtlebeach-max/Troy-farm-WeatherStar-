import STATUS from './status.mjs';
import WeatherDisplay from './weatherdisplay.mjs';
import { registerDisplay } from './navigation.mjs';
import { DateTime } from '../vendor/auto/luxon.mjs';

// KLTX LOOP RADAR (Troy 2026-11-07, v=6): the radar screen mirrors his
// library RetroCast "Current Radar" — the NWS KLTX loop GIF itself
// (grey land, blue ocean, green/yellow echoes, county lines + city names
// baked in), shown up close with the warning-legend bar and dBZ scale
// re-added as overlays so they stay visible at this crop. The GIF
// animates itself, so there are no Leaflet/RainViewer frames any more.
const KLTX_LOOP_URL = 'https://radar.weather.gov/ridge/standard/KLTX_loop.gif';

class Radar extends WeatherDisplay {
	constructor(navId, elemId) {
		super(navId, elemId, 'Local Radar', true);

		// Troy 2026-11-07: the ticker NEVER pauses — it keeps cycling the farm
		// conditions even while the radar screen shows (the radar screen has no
		// ticker band of its own, so this flag only ever froze the cycle).
		this.okToDrawCurrentDateTime = false;

		// Single screen — the GIF loops on its own for the whole dwell.
		this.timing.baseDelay = 500;
		this.timing.delay = 1;
		this.timing.totalScreens = 1;

		this.kltxRetries = 0;
	}

	buildKltxView() {
		const mapEl = this.elem.querySelector('#map');
		if (!mapEl) return false;
		if (mapEl.querySelector('.kltx-wrap')) return true;
		mapEl.innerHTML = `
			<div class="kltx-wrap">
				<img class="kltx-loop" src="${KLTX_LOOP_URL}" alt="KLTX radar loop">
				<div class="kltx-warnbar">
					<span class="w-tornado">TORNADO</span><span class="w-svr">SEVERE THUNDERSTORM</span><span class="w-flood">FLASH FLOOD</span><span class="w-marine">SPECIAL MARINE</span>
				</div>
				<div class="kltx-tag">KLTX &bull; SHALLOTTE, NC</div>
				<div class="kltx-scale"><span>LIGHT</span><i></i><span>HEAVY</span></div>
				<div class="kltx-dbz"><span>-30</span><span>-20</span><span>-10</span><span>0</span><span>10</span><span>20</span><span>30</span><span>40</span><span>50</span><span>60</span><span>70</span><span>80&nbsp;dBZ</span></div>
			</div>`;
		const img = mapEl.querySelector('.kltx-loop');
		img.addEventListener('error', () => {
			if (this.kltxRetries < 3) {
				this.kltxRetries += 1;
				setTimeout(() => { img.src = `${KLTX_LOOP_URL}?t=${Date.now()}`; }, 10000);
			} else {
				const wrap = mapEl.querySelector('.kltx-wrap');
				if (wrap && !wrap.querySelector('.kltx-off')) {
					wrap.insertAdjacentHTML('beforeend', '<div class="kltx-off">RADAR LOOP UNAVAILABLE &mdash; WILL RETRY</div>');
				}
			}
		});
		return true;
	}

	async getData(_weatherParameters) {
		if (!super.getData(_weatherParameters)) return;
		const weatherParameters = _weatherParameters ?? this.weatherParameters;

		this.buildKltxView();

		// Header clock: the frame time the old Leaflet view showed.
		try {
			const timeElem = this.elem.querySelector('.time');
			if (timeElem) {
				timeElem.textContent = DateTime.now().setZone(weatherParameters.timeZone).toLocaleString(DateTime.TIME_SIMPLE);
			}
		} catch (e) { /* clock is cosmetic */ }

		this.setStatus(STATUS.loaded);
	}

	// No frames to step — the GIF loops itself.
	screenIndexChange() {}

	async drawCanvas() {
		super.drawCanvas();
		this.finishDraw();
	}
}

registerDisplay(new Radar(10, 'radar'));
