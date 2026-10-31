// Troy fixed Local Forecast wording (2026-10-29, from his screenshot
// ~/workspace/user/files/987_2_ryoh.png). ONE fixed sentence structure for
// every period — no random phrase variations, no random templates, no
// 'FORECAST:' / 'OUTLOOK:' / 'WEATHER:' variants, no 'PRECIPITATION NOT
// EXPECTED', no 'CHANCE OF PRECIPITATION ... AFTER ...' variants.
// Fixed template:
//   <PERIOD>... <Sky sentence>. <High/Low sentence>. <Wind sentence>. Precip chance N%.
// Examples (numbers from the screenshot only; real numbers come from data):
//   TONIGHT... A few passing clouds. Low around 60. WNW winds 5 to 10 mph. Precip chance 14%.
//   TUESDAY... Sunny. High 83. East winds 5 to 10 mph. Precip chance 13%.
//   TUESDAY NIGHT... Clear skies. Low 62. Winds light and variable. Precip chance 15%.
// Units are fixed to Troy's standing rule: whole numbers, degrees F, mph.
// Open-Meteo hourly input is degrees C and km/h, so this file converts
// directly with celsiusToFahrenheit / kphToMph (both whole-number) instead
// of reading the page's unit settings via document, which also makes the
// generator testable in plain Node.

import { directionToNSEW } from './calc.mjs';
import { kphToMph, celsiusToFahrenheit } from './units.mjs';

function generateLocalForecast(dateStamp, hourlyData, options = {}) {
	const MORNING_HOURS = [...Array(12).keys()].map((h) => h + 6); // 6 AM - 6 PM
	const NIGHT_HOURS = [...Array(6).keys()].map((h) => h + 18).concat([...Array(6).keys()]); // 6 PM - 6 AM
	// NOTE: hour windows are unchanged from the previous version. Because
	// localforecast.mjs passes only one calendar date's hours, a NIGHT
	// period covers that date's 0-5 AM hours plus its 18-23 PM hours.

	// Deterministic most-frequent value: first value wins on a tie, so the
	// same data always produces the same sentence (no Math.random anywhere).
	function mostFrequent(arr) {
		const counts = new Map();
		let best = null;
		let bestCount = 0;
		arr.forEach((value) => {
			const count = (counts.get(value) || 0) + 1;
			counts.set(value, count);
			if (count > bestCount) {
				best = value;
				bestCount = count;
			}
		});
		return { value: best, count: bestCount };
	}

	// Screenshot wording: cardinal directions are spelled out (East, North,
	// South, West); compound directions keep their 16-point code (WNW, NNE).
	// That reproduces both screenshot examples: 'WNW winds ...' and
	// 'East winds ...'.
	function directionLabel(code) {
		const full = {
			N: 'North', E: 'East', S: 'South', W: 'West',
		};
		return full[code] || code;
	}

	// Short plain sky sentence, no trailing period (the template adds it).
	// If a WMO weather_code is present, the dominant code decides; otherwise
	// the period's mean cloud cover decides. Mean (not max) is used so one
	// cloudy hour does not turn a mostly clear period into 'Cloudy'.
	function skyDescription(periodData, periodKind) {
		const codes = periodData
			.map((entry) => entry.weather_code)
			.filter((code) => code !== null && code !== undefined);
		if (codes.length) {
			const code = mostFrequent(codes).value;
			if (code === 0 || code === 1) return periodKind === 'MORNING' ? 'Sunny' : 'Clear skies';
			if (code === 2) return 'A few passing clouds';
			if (code === 3) return 'Cloudy';
			if (code === 45 || code === 48) return 'Foggy';
			if ([51, 53, 55, 56, 57].includes(code)) return 'Drizzle';
			if ([61, 63, 65, 66, 67].includes(code)) return 'Rain';
			if ([71, 73, 75, 77].includes(code)) return 'Snow';
			if ([80, 81, 82].includes(code)) return 'Rain showers';
			if ([85, 86].includes(code)) return 'Snow showers';
			if ([95, 96, 99].includes(code)) return 'Thunderstorms';
		}
		const cloudValues = periodData.map((entry) => entry.cloud_cover ?? 0);
		const meanCloud = cloudValues.reduce((sum, value) => sum + value, 0) / cloudValues.length;
		if (meanCloud < 20) return periodKind === 'MORNING' ? 'Sunny' : 'Clear skies';
		if (meanCloud < 50) return 'A few passing clouds';
		if (meanCloud < 80) return 'Partly cloudy';
		return 'Cloudy';
	}

	// Wind sentence, no trailing period (the template adds it).
	// Light/variable threshold (deterministic, plain): the period's fastest
	// wind is at most 5 mph, OR at most 10 mph with no single direction in
	// at least half the hours (no prevailing direction). Otherwise the
	// prevailing 16-point direction plus the whole-number mph range; a
	// single speed is written without 'to'.
	function windSentence(periodData) {
		const speeds = periodData.map((entry) => kphToMph(entry.wind_speed_10m ?? 0));
		const maxSpeed = Math.max(...speeds);
		const minSpeed = Math.min(...speeds);
		const dirs = periodData.map((entry) => directionToNSEW(entry.wind_direction_10m ?? 0));
		const prevailing = mostFrequent(dirs);
		const prevailingShare = prevailing.count / dirs.length;
		if (maxSpeed <= 5 || (maxSpeed <= 10 && prevailingShare < 0.5)) {
			return 'Winds light and variable';
		}
		const label = directionLabel(prevailing.value);
		if (minSpeed === maxSpeed) return `${label} winds ${maxSpeed} mph`;
		return `${label} winds ${minSpeed} to ${maxSpeed} mph`;
	}

	// eslint-disable-next-line no-shadow
	function processForecast(hourlyData, periodKind, periodName) {
		const periodData = hourlyData.filter((entry) => (periodKind === 'MORNING' ? MORNING_HOURS : NIGHT_HOURS).includes(new Date(entry.time).getHours()));

		if (!periodData.length) return null;

		const temps = periodData.map((entry) => celsiusToFahrenheit(entry.temperature_2m));
		const temp = periodKind === 'MORNING' ? Math.max(...temps) : Math.min(...temps);
		const tempLabel = periodKind === 'MORNING' ? 'HIGH' : 'LOW';
		// Screenshot rule: only the TONIGHT period says 'Low around N.';
		// any other night period says 'Low N.' (e.g. TUESDAY NIGHT... Low 62.).
		const tempSentence = periodKind === 'MORNING'
			? `High ${temp}`
			: (periodName === 'TONIGHT' ? `Low around ${temp}` : `Low ${temp}`);

		const sky = skyDescription(periodData, periodKind);
		const wind = windSentence(periodData);

		// Precip chance is ALWAYS shown, as a whole-number percent: the
		// period's maximum hourly precipitation probability (0 when absent).
		const precipProbs = periodData.map((entry) => entry.precipitation_probability ?? 0);
		const precip = Math.round(Math.max(...precipProbs));
		const precipSentence = `Precip chance ${precip}%`;

		const forecastText = `${periodName}... ${sky}. ${tempSentence}. ${wind}. ${precipSentence}.`;

		return {
			period: periodKind,
			periodName,
			temperature: { label: tempLabel, value: temp },
			wind,
			precipitation: precipSentence,
			skyCondition: sky,
			text: forecastText,
		};
	}

	// Period names. generateLocalForecast is called once per calendar date,
	// in date order, by localforecast.mjs, which passes isFirstDay for the
	// first date. Troy 2026-10-30: the first date's day period is TODAY
	// (never its weekday name); its night period is TONIGHT; any later
	// day period is its weekday name and any later night period is
	// WEEKDAY NIGHT.
	// (e.g. first date Friday, next date Saturday ->
	//  TODAY, TONIGHT, SATURDAY, SATURDAY NIGHT, ...)
	const dayDate = new Date(dateStamp);
	const weekday = dayDate.toLocaleDateString('en-US', { weekday: 'long' }).toUpperCase();
	const isFirstDay = options.isFirstDay === true;

	const dailyData = hourlyData.filter((entry) => new Date(entry.time).toDateString() === dayDate.toDateString());

	const morningForecast = processForecast(dailyData, 'MORNING', isFirstDay ? 'TODAY' : weekday);
	const nightForecast = processForecast(dailyData, 'NIGHT', isFirstDay ? 'TONIGHT' : `${weekday} NIGHT`);

	const forecast = {
		date: weekday,
		periods: {
			morning: morningForecast,
			night: nightForecast,
		},
	};

	return JSON.stringify(forecast, null, 2);
}

export {
	// eslint-disable-next-line import/prefer-default-export
	generateLocalForecast,
};
