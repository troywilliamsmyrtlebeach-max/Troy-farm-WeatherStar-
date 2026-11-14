/* spell-checker: disable */

// TROY 2026-11-14: moon icons at night, sun icons in the day, ALWAYS.
// Night is REAL night at the farm (33.92N 78.57W) from the sun's actual
// position — NOAA rule: night = solar zenith > 90.833° (sun more than
// 0.833° below the horizon) — NOT the old fixed 18:00–06:00 window. In
// mid-November the sun sets ~5:11 PM and rises ~6:45 AM, so the fixed
// window showed day icons for ~50 min after sunset and night icons for
// ~45 min after sunrise. SunCalc is loaded as a classic script by
// index.html (almanac.mjs already uses the global); if it is ever
// unavailable, fall back to the 18:00–06:00 farm-local window. Never
// throws: an unparseable date renders as day, never crashes a screen.
const FARM_LATITUDE = 33.92;
const FARM_LONGITUDE = -78.57;
const NIGHT_ALTITUDE_RAD = -0.01454; // -0.833°

const farmIsNight = (atDate) => {
	const date = atDate instanceof Date ? atDate : new Date();
	try {
		if (Number.isNaN(date.getTime())) return false;
		if (typeof SunCalc !== 'undefined' && SunCalc.getPosition) {
			return SunCalc.getPosition(date, FARM_LATITUDE, FARM_LONGITUDE).altitude < NIGHT_ALTITUDE_RAD;
		}
		const hour = Number(new Intl.DateTimeFormat('en-US', {
			hour: 'numeric',
			hour12: false,
			timeZone: 'America/New_York',
		}).format(date));
		return hour >= 18 || hour < 6;
	} catch (e) { return false; }
};

function isNightTime() {
	return farmIsNight(new Date());
}

const getWaveIconFromCondition = (condition) => {
	const addPath = (icon) => `images/r/${icon}`;

	let tidyText = condition.toLowerCase();
	if (tidyText.includes(' ')) tidyText = tidyText.replaceAll(' ', '-');

	switch (tidyText) {
		case 'calm':
		case 'smooth':
			return addPath('smooth.svg');
		case 'slight':
		case 'mdt-chop':
			return addPath('slight.svg');
		case 'choppy':
			return addPath('choppy.svg');
		case 'rough':
		case 'v-rough':
		case 'high':
		case 'v-high':
		case 'phenomenal':
			return addPath('rough.svg');
		default:
			console.log(`Unable to locate wave icon for: ${condition}`);
			return addPath('Logo3.gif');
	}
};

const getWeatherRegionalIconFromIconLink = (text, isDay) => {
	// internal function to add path to returned icon
	const addPath = (icon) => `images/r/${icon}`;

	// const nightTime = isNightTime(timeZone);
	let tidyText = String(text ?? '').toLowerCase();
	// NWS icon URLs: https://api.weather.gov/icons/land/day/clear, .../night/bkn, .../skc, .../ovc, .../rain, etc.
	// Map those to the switch words below BEFORE the switch, so map cities get sky icons, never Logo3.
	if (tidyText.includes('api.weather.gov/icons')) {
		const m = tidyText.match(/\/(day|night)\/([a-z0-9_\-]+)/);
		if (m) {
			const dayNight = m[1], code = m[2].split('?')[0].split('/')[0];
			const nightSuffix = dayNight === 'night' ? '-night' : '';
			const codeMap = { skc: 'clear', few: 'mostly-clear', sct: 'partly-cloudy', bkn: 'mostly-cloudy', ovc: 'overcast', fog: 'fog', rain: 'moderate-rain', rain_showers: 'moderate-rain-showers', tsra: 'thunderstorm', snow: 'moderate-snow-fall', sleet: 'snow-grains', fzra: 'light-freezing-rain', mix: 'light-freezing-rain' };
			if (codeMap[code]) tidyText = codeMap[code] + nightSuffix;
		}
	}
	// Plain words that were missing from the switch (Overcast variants, etc.)
	if (tidyText.includes('overcast')) tidyText = tidyText.includes('night') ? 'overcast-night' : 'overcast';
	if (tidyText.includes('partly') && tidyText.includes('cloud')) tidyText = tidyText.includes('night') ? 'partly-cloudy-night' : 'partly-cloudy';
	if (tidyText.includes('mostly') && tidyText.includes('cloud')) tidyText = tidyText.includes('night') ? 'mostly-cloudy-night' : 'mostly-cloudy';
	if (tidyText.includes('mostly') && tidyText.includes('clear')) tidyText = tidyText.includes('night') ? 'mostly-clear-night' : 'mostly-clear';
	if (tidyText === 'clear' || tidyText === 'sunny') tidyText = isDay === 0 ? 'clear-night' : 'clear';
	if (tidyText.includes(' ')) tidyText = tidyText.replaceAll(' ', '-');

	// TROY 2026-11-14: only append once — the clear/sunny normalisation
	// above (and the NWS-URL parse) may already have set '-night';
	// appending again made 'clear-night-night', which matched no case and
	// fell back to the DAY Partly-Cloudy icon at night.
	if (isDay === 0 && !tidyText.endsWith('-night')) tidyText += '-night';

	// find the icon
	switch (tidyText) {
		case 0:
		case 'clear-sky':
		case 'clear':
		case 'sunny':
			return addPath('Sunny.gif');

		case 'fair':
			return addPath('Partly-Cloudy.gif');
		case 'fair-night':
			return addPath('Mostly-Clear.gif');
		case 'clear-sky-night':
		case 'clear-night':
		case 'sunny-night':
			return addPath('Clear-1992.gif');

		case 'mostly-clear':
			return addPath('Sunny.gif');
		case 'mostly-clear-night':
			return addPath('Mostly-Clear.gif');

		case 'mostly-cloudy':
			return addPath('Mostly-Cloudy.gif');
		case 'mostly-cloudy-night':
			return addPath('Mostly-Clear.gif');

		case 'cloudy':
		case 'cloudy-night':
			return addPath('Cloudy.gif');

		case 'partly-clear':
			return addPath('Partly-Clear.gif');
		case 'partly-clear-night':
			return addPath('Mostly-Clear.gif');

		case 1:
		case 'mainly-clear':
			return addPath('Sunny.gif');
		case 'mainly-clear-night':
			return addPath('Mostly-Clear.gif');

		case 2:
		case 'partly-cloudy':
			return addPath('Partly-Cloudy.gif');
		case 'partly-cloudy-night':
			return addPath('Mostly-Clear.gif');

		case 3:
		case 'overcast':
			return addPath('Partly-Cloudy.gif');
		case 'overcast-night':
			return addPath('Mostly-Clear.gif');

		case 45:
		case 48:
		case 'fog':
		case 'fog-night':
		case 'depositing-rime-fog':
		case 'depositing-rime-fog-night':
			return addPath('Fog.gif');

		case 51:
		case 'light-drizzle':
			return addPath('Scattered-Showers-1994-2.gif');
		case 'light-drizzle-night':
			return addPath('Scattered-Showers-Night.gif');

		case 53:
		case 55:
		case 'moderate-drizzle':
		case 'dense-drizzle':
		case 'moderate-drizzle-night':
		case 'dense-drizzle-night':
			return addPath('Shower.gif');

		case 56:
		case 57:
		case 'light-freezing-drizzle':
		case 'dense-freezing-drizzle':
		case 'light-freezing-drizzle-night':
		case 'dense-freezing-drizzle-night':
			return addPath('Freezing-Rain-1992.gif');

		case 61:
		case 'slight-rain':
		case 'slight-rain-night':
			return addPath('Shower.gif');

		case 63:
		case 65:
		case 'moderate-rain':
		case 'heavy-rain':
		case 'moderate-rain-night':
		case 'heavy-rain-night':
			return addPath('Shower.gif');

		case 66:
		case 67:
		case 'light-freezing-rain':
		case 'heavy-freezing-rain':
		case 'light-freezing-rain-night':
		case 'heavy-freezing-rain-night':
			return addPath('Freezing-Rain-1992.gif');

		case 71:
		case 'slight-snow-fall':
		case 'slight-snow-fall-night':
			return addPath('Light-Snow.gif');

		case 73:
		case 'moderate-snow-fall':
		case 'moderate-snow-fall-night':
			return addPath('Heavy-Snow.gif');

		case 75:
		case 'heavy-snow-fall':
		case 'heavy-snow-fall-night':
			return addPath('Heavy-Snow.gif');

		case 77:
		case 'snow-grains':
		case 'snow-grains-night':
			return addPath('Sleet.gif');

		case 80:
		case 'slight-rain-showers':
		case 'slight-rain-showers-night':
			return addPath('Shower.gif');

		case 81:
		case 82:
		case 'moderate-rain-showers':
		case 'voilent-rain-showers':
		case 'moderate-rain-showers-night':
		case 'voilent-rain-showers-night':
			return addPath('Rain-1992.gif');

		case 85:
		case 86:
		case 'slight-snow-showers':
		case 'heavy-snow-showers':
			return addPath('Scattered-Snow-Showers-1994-2.gif');
		// TROY 2026-11-14: the snow-showers file shows a SUN — at night use
		// the plain snow icons instead (both verified sun-free).
		case 'slight-snow-showers-night':
			return addPath('Light-Snow.gif');
		case 'heavy-snow-showers-night':
			return addPath('Heavy-Snow.gif');

		case 95:
		case 'thunderstorm':
		case 'thunderstorm-night':
			return addPath('Thunderstorm.gif');

		case 99:
		case 'thunderstorm-with-slight-hail':
		case 'thunderstorm-with-heavy-hail':
		case 'thunderstorm-with-slight-hail-night':
		case 'thunderstorm-with-heavy-hail-night':
			return addPath('ThunderSnow.gif');

		default:
			console.log(`Unable to locate icon for: ${text}`);
			// Troy Oct 31 19:28: NEVER Logo3 (WeatherStar 4000+ logo) on regional maps — fall back to a sky icon instead.
			// TROY 2026-11-14: the fallback is night-aware too — an unknown
			// condition at night gets the moon icon, never the day sun.
			return addPath(isDay === 0 ? 'Mostly-Clear.gif' : 'Partly-Cloudy.gif');
	}
};

/**
 * This function will return the icon for the current weather condition.
 * This is based on the text description (which is provided by the API), the current timezone (used for CurrentWeather view),
 * and the extended forecast (which is used to determine overrules the current time and isNight() function to return daytime images only).
 * @param {*} text string - the text description of the weather condition
 * @param {*} timeZone string - the timezone of the current location
 * @param {*} extendedForecast boolean value to determine if the icon should be daytime only - this is required for the extended forecast view
 * @returns string - the path to the icon
 */
const getWeatherIconFromIconLink = (text, timeZone, extendedForecast) => {
	// Code 0 (clear) is falsy, so a plain !text check drops the sky icon
	// for the PWS screen, which uses numeric weather codes.
	if (text === undefined || text === null || text === '') return false;

	const addPath = (icon) => `images/${icon}`;

	const nightTime = isNightTime(timeZone);
	// TROY 2026-11-14: extended-forecast day columns always show DAY
	// icons, even at night — only the current-conditions screens flip.
	const nightIcon = !extendedForecast && nightTime;
	let tidyText;
	if (text.length > 3) {
		tidyText = text.toLowerCase().replaceAll(' ', '-');
	} else {
		tidyText = text;
	}

	// Numeric clear codes get the night icon after dark, like the text codes.
	if (!extendedForecast && nightTime && tidyText === 0) {
		return addPath('CC_Clear0.gif');
	}

	if (!extendedForecast && tidyText.length > 3) {
		// 'clear', 'mostly-clear', 'mainly-clear', 'partly-clear' all carry
		// 'clear'; 'sunny' is the daytime word for code 0 and must also flip
		// to the moon icon if it ever arrives at night.
		if (nightTime && (tidyText.includes('clear') || tidyText === 'sunny')) tidyText += '-night';
	}

	// find the icon
	switch (tidyText) {
		case 0:
		case 'clear-sky':
		case 'clear':
		case 'sunny':
			return addPath('CC_Clear1.gif');

		case 'fair':
			return addPath(nightIcon ? 'CC_PartlyCloudy0.gif' : 'CC_PartlyCloudy1.gif');
		case 'fair-night':
			return addPath('CC_PartlyCloudy0.gif');
		case 'clear-sky-night':
		case 'clear-night':
		case 'sunny-night':
			return addPath('CC_Clear0.gif');

		case 'mostly-clear':
			return addPath('CC_Clear1.gif');
		case 'mostly-clear-night':
			return addPath('CC_Clear0.gif');

		case 'mostly-cloudy':
			return addPath(nightIcon ? 'CC_MostlyCloudy0.gif' : 'CC_MostlyCloudy1.gif');
		case 'mostly-cloudy-night':
			return addPath('CC_MostlyCloudy0.gif');

		case 'cloudy':
			return addPath(nightIcon ? 'CC_MostlyCloudy0.gif' : 'Cloudy.gif');
		case 'cloudy-night':
			return addPath('CC_MostlyCloudy0.gif');

		case 'partly-clear':
			return addPath('CC_PartlyCloudy1.gif');
		case 'partly-clear-night':
			return addPath('CC_PartlyCloudy0.gif');

		case 1:
			return addPath(nightIcon ? 'CC_PartlyCloudy0.gif' : 'CC_PartlyCloudy1.gif');
		case 'mainly-clear':
			return addPath('CC_Clear1.gif');

		case 'mainly-clear-night':
			return addPath('CC_Clear0.gif');

		case 2:
		case 'partly-cloudy':
			return addPath(nightIcon ? 'CC_PartlyCloudy0.gif' : 'CC_PartlyCloudy1.gif');

		case 'partly-cloudy-night':
			return addPath('CC_PartlyCloudy0.gif');

		case 3:
		case 'overcast':
			return addPath(nightIcon ? 'CC_MostlyCloudy0.gif' : 'Cloudy.gif');

		case 45:
		case 48:
		case 'fog':
		case 'depositing-rime-fog':
			return addPath('CC_Fog.gif');

		case 51:
		case 'light-drizzle':
			return addPath('CC_Showers.gif');

		case 53:
		case 55:
		case 'moderate-drizzle':
		case 'dense-drizzle':
			return addPath('CC_Rain.gif');

		case 56:
		case 57:
		case 'light-freezing-drizzle':
		case 'dense-freezing-drizzle':
			return addPath('Freezing-Rain.gif');

		case 61:
		case 'slight-rain':
			return addPath('CC_Showers.gif');

		case 63:
		case 65:
		case 'moderate-rain':
		case 'heavy-rain':
			return addPath('CC_Rain.gif');

		case 66:
		case 67:
		case 'light-freezing-rain':
		case 'heavy-freezing-rain':
			return addPath('CC_FreezingRain.gif');

		case 71:
		case 'slight-snow-fall':
			return addPath('CC_SnowShowers.gif');

		case 73:
		case 'moderate-snow-fall':
			return addPath('CC_Snow.gif');

		case 75:
		case 'heavy-snow-fall':
			return addPath('Heavy-Snow.gif');

		case 77:
		case 'snow-grains':
			return addPath('Sleet.gif');

		case 80:
		case 'slight-rain-showers':
			return addPath('CC_Showers.gif');

		case 81:
		case 82:
		case 'moderate-rain-showers':
		case 'voilent-rain-showers':
			return addPath('Rain.gif');

		case 85:
		case 86:
		case 'slight-snow-showers':
		case 'heavy-snow-showers':
			return addPath('CC_Mix.gif');

		case 95:
		case 'thunderstorm':
			return addPath('CC_TStorm.gif');

		case 99:
		case 'thunderstorm-with-slight-hail':
		case 'thunderstorm-with-heavy-hail':
			return addPath('ThunderSnow.gif');

		default:
			console.log(`Unable to locate icon for: ${text}`);
			// Troy Oct 31 19:28: NEVER Logo3 (WeatherStar 4000+ logo) on regional maps — fall back to a sky icon instead.
			// TROY 2026-11-14: the fallback is night-aware too — an unknown
			// condition at night gets the moon icon, never the day sun.
			return addPath(nightIcon ? 'CC_PartlyCloudy0.gif' : 'Partly-Cloudy.gif');
	}
};

// const getHourlyIcon = (skyCover, weather, iceAccumulation, probabilityOfPrecipitation, snowfallAmount, windSpeed, isNight = false) => {
// 	// internal function to add path to returned icon
// 	const addPath = (icon) => `images/r/${icon}`;

// 	// possible phenomenon
// 	let thunder = false;
// 	let snow = false;
// 	let ice = false;
// 	let fog = false;
// 	let wind = false;

// 	// test the phenomenon for various value if it is provided.
// 	weather.forEach((phenomenon) => {
// 		if (!phenomenon.weather) return;
// 		if (phenomenon.weather.toLowerCase().includes('thunder')) thunder = true;
// 		if (phenomenon.weather.toLowerCase().includes('snow')) snow = true;
// 		if (phenomenon.weather.toLowerCase().includes('ice')) ice = true;
// 		if (phenomenon.weather.toLowerCase().includes('fog')) fog = true;
// 		if (phenomenon.weather.toLowerCase().includes('wind')) wind = true;
// 	});

// 	// first item in list is highest priority, units are metric where applicable
// 	if (iceAccumulation > 0 || ice) return addPath('Freezing-Rain-1992.gif');
// 	if (snowfallAmount > 10) {
// 		if (windSpeed > 30 || wind) return addPath('Blowing Snow.gif');
// 		return addPath('Heavy-Snow-1994.gif');
// 	}
// 	if ((snowfallAmount > 0 || snow) && thunder) return addPath('ThunderSnow.gif');
// 	if (snowfallAmount > 0 || snow) return addPath('Light-Snow.gif');
// 	if (thunder) return (addPath('Thunderstorm.gif'));
// 	if (probabilityOfPrecipitation > 70) return addPath('Rain-1992.gif');
// 	if (probabilityOfPrecipitation > 50) return addPath('Shower.gif');
// 	if (probabilityOfPrecipitation > 30) {
// 		if (!isNight) return addPath('Scattered-Showers-1994.gif');
// 		return addPath('Scattered-Showers-Night.gif');
// 	}
// 	if (fog) return addPath('Fog.gif');
// 	if (skyCover > 70) return addPath('Cloudy.gif');
// 	if (skyCover > 50) {
// 		if (!isNight) return addPath('Mostly-Cloudy-1994.gif');
// 		return addPath('Partly-Clear-1994.gif');
// 	}
// 	if (skyCover > 30) {
// 		if (!isNight) return addPath('Partly-Cloudy.gif');
// 		return addPath('Mostly-Clear.gif');
// 	}
// 	if (isNight) return addPath('Clear-1992.gif');
// 	return addPath('Sunny.gif');
// };

export {
	getWeatherIconFromIconLink,
	getWeatherRegionalIconFromIconLink,
	getWaveIconFromCondition,
	farmIsNight,
	// getHourlyIcon,
};
