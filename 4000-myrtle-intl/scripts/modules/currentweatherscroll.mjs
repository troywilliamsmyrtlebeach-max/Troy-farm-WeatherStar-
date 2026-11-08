import { elemForEach } from './utils/elem.mjs';
import getCurrentWeather from './currentweather.mjs';
import { currentDisplay, getDisplay } from './navigation.mjs';
import { getConditionText } from './utils/weather.mjs';
import ConversionHelpers from './utils/conversionHelpers.mjs';

// constants
const degree = String.fromCharCode(176);

// local variables
let interval;
let screenIndex = 0;

// start drawing conditions
// reset starts from the first item in the text scroll list
const start = () => {
	// store see if the context is new

	// set up the interval if needed
	if (!interval) {
		interval = setInterval(incrementInterval, 12000);
	}

	// draw the data
	drawScreen();
};

const stop = (reset) => {
	if (reset) screenIndex = 0;
};

// increment interval, roll over
const incrementInterval = () => {
	// test current screen
	const display = currentDisplay();
	if (!display?.okToDrawCurrentConditions) {
		stop(display?.elemId === 'progress');
		return;
	}
	screenIndex = (screenIndex + 1) % (screens.length);
	// draw new text
	drawScreen();
};

// When the farm's own station data is available, the ticker cycles through
// THAT, not the Carolina Shores locality model — so the bottom ticker on
// every screen, including the PWS screen, reads from KNCCAROL120.
const pwsTickerData = () => {
	const cw = getDisplay(13)?.weatherParameters?.customWeather;
	if (!cw) return null;
	return {
		city: 'CALABASH-FARM AT BRUNSWICK',
		TextConditions: cw.conditionText,
		Temperature: ConversionHelpers.convertTemperatureUnits(cw.temperature),
		TemperatureUnit: ConversionHelpers.getTemperatureUnitText(),
		Humidity: Math.round(cw.humidity),
		DewPoint: ConversionHelpers.convertTemperatureUnits(cw.dewPoint),
		Pressure: ConversionHelpers.convertPressureUnits(cw.pressure).toFixed(2),
		PressureUnit: ConversionHelpers.getPressureUnitText(),
		WindDirection: cw.windDirection,
		WindSpeed: Math.round(ConversionHelpers.convertWindUnits(cw.windSpeed)),
		WindGust: cw.windGust ? Math.round(ConversionHelpers.convertWindUnits(cw.windGust)) : 0,
		WindUnit: ConversionHelpers.getWindUnitText(),
		Visibility: Math.min(10, ConversionHelpers.convertDistanceUnits(cw.visibility)),
		VisibilityUnit: ConversionHelpers.getDistanceUnitText(),
		Ceiling: 0,
		CeilingUnit: ConversionHelpers.getDistanceUnitText(),
	};
};

const drawScreen = async () => {
	// get the conditions
	const data = pwsTickerData() ?? await getCurrentWeather();

	// nothing to do if there's no data yet
	if (!data) return;

	drawCondition(screens[screenIndex](data));
};

// the "screens" are stored in an array for easy addition and removal
const screens = [
	// station name
	(data) => {
		let sanitizedText = 'CONDITIONS AT ';
		// Troy's farm name is long on purpose — never truncate it.
		// Troy 2026-10-27: label is all caps, at the left bottom edge.
		if (data.city === 'CALABASH-FARM AT BRUNSWICK') {
			return 'CONDITIONS AT CALABASH-FARM AT BRUNSWICK';
		}
		// Typically an airport with "International" at the second position
		if (data.city.split(' ').length > 2 && data.city.split(' ')[1].toLowerCase() === 'international') {
			sanitizedText += `${data.city.split(' ')[0]} Intl. ${data.city.split(' ')[2]} `;
		// or a very long city name...this will
		// truncate very long airports too, like
		// "John F. Kennedy International Airport"
		} else if (data.city.length > 20) {
			sanitizedText += `${data.city.slice(0, 18)}...`;
		} else {
			sanitizedText += `${data.city} `;
		}
		return sanitizedText;
	},

	// condition — Troy 2026-10-31: sky condition as its own ticker frame,
	// labelled SKY so it cannot be mistaken for another reading. All caps
	// is applied by drawCondition. Farm data: FOG on Oct 31 01:56 AM.
	// Troy 2026-10-31: ticker reads just the sky condition itself, no SKY label — same as the main page.
	(data) => `${getConditionText(data.TextConditions)}`,

	// temperature
	(data) => {
		const text = `Temp: ${data.Temperature}${degree}${data.TemperatureUnit}`;
		return text;
	},

	// humidity
	(data) => `Humidity: ${data.Humidity}%   Dewpoint: ${data.DewPoint}${degree}${data.TemperatureUnit}`,

	// barometric pressure — Troy 2026-10-26 evening: say "Barometric Pressure", not just "Pressure", with just the letter R / S / F beside the number
	(data) => {
		let letter = 'S';
		if (data.PressureDirection === 'rising') letter = 'R';
		else if (data.PressureDirection === 'falling') letter = 'F';
		else {
			try {
				const t = window.localStorage.getItem('pwsPressureTrend');
				if (t === 'rising') letter = 'R';
				else if (t === 'falling') letter = 'F';
			} catch (e) { /* keep S */ }
		}
		return `Barometric Pressure ${data.Pressure} ${letter}`;
	},

	// wind
	(data) => {
		let text = data.WindSpeed > 0
			? `Wind: ${data.WindDirection} ${data.WindSpeed} ${data.WindUnit}`
			: 'Wind: Calm';

		if (data.WindGust > 0) {
			text += `   Gusts to ${data.WindGust}`;
		}
		return text;
	},

	// visibility
	(data) => {
		const distance = `${data.Ceiling} ${data.CeilingUnit}`;
		return `Visib: ${data.Visibility} ${data.VisibilityUnit}   Ceiling: ${data.Ceiling === 0 ? 'Unlimited' : distance}`;
	},
];

// internal draw function with preset parameters
const drawCondition = (text) => {
	elemForEach('.weather-display .scroll .fixed', (elem) => {
		// Remove old text-layers with exit
		const layers = elem.querySelectorAll('.text-layer');
		layers.forEach((layer) => {
			layer.classList.remove('active');
			layer.classList.add('exit');
			layer.addEventListener('transitionend', () => {
				layer.remove();
			}, { once: true });
		});

		// Create new layer with wrapped content
		const newLayer = document.createElement('div');
		newLayer.className = 'text-layer';
		const content = document.createElement('div');
		content.className = 'text-content';
		// Long farm label (CONDITIONS AT CALABASH-FARM AT BRUNSWICK, 38 chars)
		// is clipped by the 640px ticker at 24pt. Shrink only long frames
		// so BRUNSWICK stays fully visible; short frames keep 24pt.
		if (text.length > 32) content.style.fontSize = '18pt';
		// Troy 2026-10-27: every ticker reading in capital letters.
		content.textContent = text.toUpperCase();
		newLayer.appendChild(content);
		elem.appendChild(newLayer);

		// Force reflow
		// eslint-disable-next-line no-void
		void newLayer.offsetWidth;

		// Trigger wipe
		newLayer.classList.add('active');
	});
};
document.addEventListener('DOMContentLoaded', () => {
	start();
});
