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

		this.calcNavTiming();
		this.setStatus(STATUS.loaded);
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

		let condition = getConditionText(customWeatherParameters.conditionText);
		if (condition.length > 15) {
			condition = `${condition.slice(0, 15)}...`;
		}

		const iconImage = getWeatherIconFromIconLink(customWeatherParameters.conditionText, this.weatherParameters.timeZone);

		// Troy 2026-10-26: wind spaced out, e.g. "NE 5 MPH", not "NE5"
		// Troy 2026-10-26 evening: 0 mph is CALM, never "N 0 MPH" — the
		// gust row below still carries any gust, e.g. CALM + Gusts to 10.
		const windSpeed = Math.round(ConversionHelpers.convertWindUnits(customWeatherParameters.windSpeed));
		const windUnit = ConversionHelpers.getWindUnitText().toUpperCase();
		const windText = windSpeed === 0 ? 'CALM' : `${customWeatherParameters.windDirection} ${windSpeed} ${windUnit}`;
		// Pressure trend vs the last PWS pressure drawn (0.02 inHg threshold,
		// same as his standing rule): rising / falling arrow, steady = no arrow.
		// Stored for the bottom ticker's R/S/F letter too.
		const pressureInHg = parseFloat(ConversionHelpers.convertPressureUnits(customWeatherParameters.pressure).toFixed(2));
		let pressureArrow = '';
		let pressureTrend = 'steady';
		try {
			const prev = parseFloat(window.localStorage.getItem('pwsPressureInHg'));
			if (!Number.isNaN(prev)) {
				if (pressureInHg - prev >= 0.02) pressureTrend = 'rising';
				else if (prev - pressureInHg >= 0.02) pressureTrend = 'falling';
			}
			window.localStorage.setItem('pwsPressureInHg', String(pressureInHg));
			window.localStorage.setItem('pwsPressureTrend', pressureTrend);
		} catch (e) { /* localStorage unavailable — no arrow, no crash */ }
		if (pressureTrend === 'rising') pressureArrow = ' <img class="pressure-arrow" src=\'images/pressure-arrow.png\'></img>';
		if (pressureTrend === 'falling') pressureArrow = ' <img class="pressure-arrow invert-pressure-arrow" src=\'images/pressure-arrow.png\'></img>';

		const fill = {
			temp: ConversionHelpers.convertTemperatureUnits(customWeatherParameters.temperature) + String.fromCharCode(176),
			condition,
			wind: windText,
			location: 'CALABASH-FARM AT BRUNSWICK',
			humidity: `${Math.round(customWeatherParameters.humidity)}%`,
			dewpoint: ConversionHelpers.convertTemperatureUnits(customWeatherParameters.dewPoint) + String.fromCharCode(176),
			visibility: `${Math.min(10, ConversionHelpers.convertDistanceUnits(customWeatherParameters.visibility))} ${ConversionHelpers.getDistanceUnitText()}`,
			ceiling: 'Unlimited',
			pressure: `${pressureInHg.toFixed(2)} in${pressureArrow}`,
			'feels-like': (customWeatherParameters.feelsLike !== undefined && customWeatherParameters.feelsLike !== null
				? ConversionHelpers.convertTemperatureUnits(customWeatherParameters.feelsLike)
				: ConversionHelpers.convertTemperatureUnits(customWeatherParameters.temperature)) + String.fromCharCode(176),
			icon: { type: 'img', src: iconImage },
		};

		if (customWeatherParameters.windGust) fill['wind-gusts'] = `Gusts to ${Math.round(ConversionHelpers.convertWindUnits(customWeatherParameters.windGust))}`;

		const area = this.elem.querySelector('.main');

		area.innerHTML = '';
		area.append(this.fillTemplate('weather', fill));

		this.finishDraw();
	}
}

// register display
registerDisplay(new CustomWeatherStation(13, 'custom-weather-station', false));
