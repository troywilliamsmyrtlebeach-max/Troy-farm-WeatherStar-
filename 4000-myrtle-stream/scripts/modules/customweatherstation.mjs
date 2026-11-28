// custom weather station display, similar to current weather but based on a user-defined station
import STATUS from './status.mjs';
import { getWeatherIconFromIconLink } from './icons.mjs';
import WeatherDisplay from './weatherdisplay.mjs';
import { registerDisplay } from './navigation.mjs';
import { getConditionText } from './utils/weather.mjs';

import ConversionHelpers from './utils/conversionHelpers.mjs';

class CustomWeatherStation extends WeatherDisplay {
	constructor(navId, elemId, defaultActive) {
		super(navId, elemId, 'Personal Weather Station', false, defaultActive);

		// set timings
		this.timing.baseDelay = 5000;
	}

	async getData(_weatherParameters) {
		if (!super.getData(_weatherParameters)) return;
		// FARM PAGES FIX (Oct 31): on Pages the farm payload can arrive
		// before this display registers, so the shared weatherParameters
		// object alone does not carry it. Pull the latest farm payload
		// directly when this screen loads, so clicking Personal Weather
		// Station never shows NO DATA when farm-data.json is present.
		if ((!this.weatherParameters || !this.weatherParameters.customWeather) && window.__latestPwsPayload) {
			if (!this.weatherParameters) this.weatherParameters = {};
			this.weatherParameters.customWeather = window.__latestPwsPayload;
		}
		this.calcNavTiming();
		this.setStatus(STATUS.loaded);
	}

	// Clicking Personal Weather Station must show the farm screen NOW,
	// not just enable it for a later cycle pass. After the checkbox
	// enables it, load the farm payload, draw it, and show it at once.
	checkboxChange(e) {
		super.checkboxChange(e);
		if (!this.isEnabled) return;
		// Ensure the farm payload is in hand, then draw and show immediately.
		if ((!this.weatherParameters || !this.weatherParameters.customWeather) && window.__latestPwsPayload) {
			if (!this.weatherParameters) this.weatherParameters = {};
			this.weatherParameters.customWeather = window.__latestPwsPayload;
		}
		this.setStatus(STATUS.loaded);
		// Hide any currently shown display, then show the farm screen.
		document.querySelectorAll('#divTwc .show').forEach((el) => { if (el !== this.elem) el.classList.remove('show'); });
		this.drawCanvas();
		this.showCanvas();
	}

	// Live PWS updates arrive via SSE after this screen has already drawn
	// once (with NO DATA, if the first draw ran before any push). The base
	// class only redraws on a screen-index change, so a late-arriving push
	// would otherwise never replace NO DATA. Redraw on every live update.
	onCustomWeather(detail) {
		// Use the payload passed by navigation directly: the shared
		// weatherParameters object is not reliably the same object this
		// display stored at getData time, so relying on it alone leaves
		// late pushes drawing NO DATA even though the payload arrived.
		if (detail) {
			if (!this.weatherParameters) this.weatherParameters = {};
			this.weatherParameters.customWeather = detail;
		}
		this.drawCanvas();
	}

	async drawCanvas() {
		super.drawCanvas();
		const customWeatherParameters = this.weatherParameters.customWeather;

		if (!customWeatherParameters) {
			console.warn('CustomWeatherStation: No custom weather data available, unable to render custom forecast.');
			this.finishDraw();
			return;
		}

		let condition = getConditionText(customWeatherParameters.conditionText, this.weatherParameters.timeZone);
		if (condition.length > 15) {
			condition = `${condition.slice(0, 15)}...`;
		}

		const iconImage = getWeatherIconFromIconLink(customWeatherParameters.conditionText, this.weatherParameters.timeZone);

		// Troy 2026-10-26: wind spaced out, e.g. "NE 5 MPH", not "NE5"
		// Troy 2026-10-26 evening: 0 mph is CALM, never "N 0 MPH".
		// Troy 2026-11-16 wind rule (supersedes the Oct 31 gust-row rule):
		// gust below 16 mph -> show the HIGHER of sustained/gust, ONE
		// number, NO gust wording anywhere. Gust 16+ -> sustained (lower)
		// first, then "Gusts to <gust>". Both 0 -> CALM, no direction.
		const sustMph = Math.round(ConversionHelpers.convertWindUnits(customWeatherParameters.windSpeed));
		const gustMph = Math.round(ConversionHelpers.convertWindUnits(customWeatherParameters.windGust || 0));
		const windSpeed = gustMph >= 16 ? sustMph : Math.max(sustMph, gustMph);
		const windUnit = ConversionHelpers.getWindUnitText().toUpperCase();
		// Troy Oct 31 19:10 (screenshot): farm main page shows wind as direction + speed ONLY, e.g. 'SSW 2' — NO 'MPH' unit anywhere on this screen.
		const windText = windSpeed === 0 ? 'CALM' : `${customWeatherParameters.windDirection} ${windSpeed}`;
		// Troy 2026-11-10: the arrow comes from the STAGED station trend
		// (farm-data.json pressureTrend — same mechanical rule as XL: any
		// increase = rising, any decrease = falling, equal = steady), so
		// the arrow is right on first load, on any device. The localStorage
		// comparison below runs ONLY when no staged trend exists.
		// Stored for the bottom ticker's R/S/F letter too.
		const pressureInHg = parseFloat(ConversionHelpers.convertPressureUnits(customWeatherParameters.pressure).toFixed(2));
		let pressureArrow = '';
		let pressureTrend = customWeatherParameters.pressureTrend;
		if (pressureTrend !== 'rising' && pressureTrend !== 'falling' && pressureTrend !== 'steady') {
			pressureTrend = 'steady';
			try {
				const prev = parseFloat(window.localStorage.getItem('pwsPressureInHg'));
				if (!Number.isNaN(prev)) {
					if (pressureInHg - prev >= 0.02) pressureTrend = 'rising';
					else if (prev - pressureInHg >= 0.02) pressureTrend = 'falling';
				}
			} catch (e) { /* localStorage unavailable — keep steady */ }
		}
		try {
			window.localStorage.setItem('pwsPressureInHg', String(pressureInHg));
			window.localStorage.setItem('pwsPressureTrend', pressureTrend);
		} catch (e) { /* localStorage unavailable — no arrow, no crash */ }
		if (pressureTrend === 'rising') pressureArrow = ' <img class="pressure-arrow" src=\'images/pressure-arrow.png\'></img>';
		if (pressureTrend === 'falling') pressureArrow = ' <img class="pressure-arrow invert-pressure-arrow" src=\'images/pressure-arrow.png\'></img>';

		// Troy 2026-11-25, clarified Nov 27: the main screen shows the
		// cloud-cover % (Open-Meteo total at the farm point, staged as
		// cloudCover in farm-data.json) IN PLACE OF feels-like, unless
		// there is real wind chill or heat index (displayed feels-like
		// differs from displayed air temp — convertTemperatureUnits
		// already returns whole degrees). The swap keys off the data
		// field, so until the Actions stage writes cloudCover the screen
		// behaves exactly as today (feels-like shown); the new display
		// activates automatically at cutover. The template already has
		// a "Cloud Cover:" row (left blank on this screen until now).
		const tempF = ConversionHelpers.convertTemperatureUnits(customWeatherParameters.temperature);
		const feelsF = (customWeatherParameters.feelsLike !== undefined && customWeatherParameters.feelsLike !== null
			? ConversionHelpers.convertTemperatureUnits(customWeatherParameters.feelsLike)
			: tempF);
		const cloudCover = customWeatherParameters.cloudCover;
		const hasCloudCover = (typeof cloudCover === 'number' && Number.isFinite(cloudCover));
		const hasWindChillOrHeatIndex = (feelsF !== tempF);

		const fill = {
			temp: tempF + String.fromCharCode(176),
			condition,
			wind: windText,
			location: 'CALABASH-FARM AT BRUNSWICK',
			humidity: `${Math.round(customWeatherParameters.humidity)}%`,
			dewpoint: ConversionHelpers.convertTemperatureUnits(customWeatherParameters.dewPoint) + String.fromCharCode(176),
			visibility: `${Math.min(10, ConversionHelpers.convertDistanceUnits(customWeatherParameters.visibility))} ${ConversionHelpers.getDistanceUnitText()}`,
			ceiling: (customWeatherParameters.ceiling != null ? `${Number(customWeatherParameters.ceiling).toLocaleString('en-US')} ft.` : 'Unlimited'),
			pressure: `${pressureInHg.toFixed(2)}${pressureArrow}`,
			'feels-like': feelsF + String.fromCharCode(176),
			icon: { type: 'img', src: iconImage },
		};
		// Cloud-cover % fills the template's "Cloud Cover:" row when the
		// staged field is present; absent (pre-cutover Muse pipeline) the
		// key is omitted and the row stays blank, as today.
		if (hasCloudCover) fill.cloud = `${Math.round(cloudCover)}%`;

		// Troy 2026-11-16 wind rule: the GUSTS row shows ONLY at gust 16+
		// ("Gusts <gust>"); below 16 the gust is already folded into the
		// main WIND number above, so the row stays empty. This supersedes
		// the Oct 31 "gusts MUST show, always" rule.
		// Screenshot style: 'Gusts 9' — no 'to', no 'MPH', just the speed.
		if (gustMph >= 16) fill['wind-gusts'] = `Gusts ${gustMph}`;

		const area = this.elem.querySelector('.main');

		area.innerHTML = '';
		const node = this.fillTemplate('weather', fill);
		area.append(node);
		// Hide the Feels Like row when cloud cover replaces it (no real
		// wind chill/heat index); with real wind chill/heat index both
		// rows show.
		if (hasCloudCover && !hasWindChillOrHeatIndex && node) {
			const feelsRow = node.querySelector('.feels-like');
			const row = feelsRow ? feelsRow.closest('.row') : null;
			if (row) row.style.display = 'none';
		}

		this.finishDraw();
	}
}

// register display
registerDisplay(new CustomWeatherStation(13, 'custom-weather-station', false));
