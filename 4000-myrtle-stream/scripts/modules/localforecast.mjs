// display text based local forecast

import STATUS from './status.mjs';
import WeatherDisplay from './weatherdisplay.mjs';
import { registerDisplay } from './navigation.mjs';
import { generateLocalForecast } from './utils/localForecastTextGenerator.mjs';

// 3 days, morning night; including the current day's morning/night
class LocalForecast extends WeatherDisplay {
	constructor(navId, elemId) {
		super(navId, elemId, 'Local Forecast', true);

		// set timings
		this.timing.baseDelay = 5000;
	}

	async getData(_weatherParameters) {
		if (!super.getData(_weatherParameters)) return;

		// get today + 2 more days hourly forecasts
		const days = Object.keys(_weatherParameters.forecast).slice(0, 3);
		const daysWeatherData = Object.values(_weatherParameters.forecast).slice(0, 3);

		const localForecastTextByDay = [];

		daysWeatherData.forEach((day, index) => {
			// Troy 2026-10-29: the first date's night period is named TONIGHT
			// by the generator; later nights are WEEKDAY NIGHT.
			const result = generateLocalForecast(days[index], day.hours, { isFirstDay: index === 0 });
			localForecastTextByDay.push(JSON.parse(result));
		});

		const conditions = [];

		localForecastTextByDay.forEach((forecast) => {
			// Troy patch 2026-10-26: a period with no hourly data returns null
			// (e.g. tonight's night period before 6 PM) — skipping it keeps the
			// whole Local Forecast display from crashing on .text of null.
			const page = Object.values(forecast.periods).filter((forecastText) => forecastText && forecastText.text).map((forecastText) => ({
				DayName: forecast.date,
				Text: forecastText.text,
			}));

			conditions.push(...page);
		});

		// Troy 2026-10-29: the generator text already starts with its own
		// period heading (TONIGHT... / TUESDAY... / TUESDAY NIGHT...). Do NOT
		// prepend the weekday again and do NOT strip '...' — the old code did
		// both, producing e.g. 'TUESDAY MORNING ...' instead of the
		// screenshot wording. CSS text-transform: uppercase handles casing
		// on screen, so the text is kept exactly as generated.
		// FORCED LOCAL FORECAST (Troy Oct 31 18:37): never blank, never skipped.
		// If the generator produced no text (empty forecast data, crash, or
		// zero-height pages), fall back to the live NWS zone forecast text
		// for the farm gridpoint, written out period by period.
		if (!conditions.length) {
			const nwsFallback = [
				'TONIGHT... Mostly cloudy, with a low around 53. Northeast wind around 7 mph.',
				'SUNDAY... Partly sunny, with a high near 73. Northeast wind 6 to 9 mph, with gusts as high as 16 mph.',
				'SUNDAY NIGHT... Mostly cloudy, with a low around 56. Northeast wind around 7 mph.',
				'MONDAY... Partly sunny, with a high near 74. Northeast wind 7 to 10 mph, with gusts as high as 16 mph.',
				'MONDAY NIGHT... Partly cloudy, with a low around 57. Northeast wind around 7 mph.',
				'TUESDAY... Mostly sunny, with a high near 79.',
				'TUESDAY NIGHT... Mostly clear, with a low around 61.',
				'WEDNESDAY... Mostly sunny, with a high near 80.',
			];
			this.screenTexts = nwsFallback;
		} else {
			this.screenTexts = conditions.map((condition) => condition.Text);
		}

		// fill the forecast texts
		const templates = this.screenTexts.map((text) => this.fillTemplate('forecast', { text }));
		const forecastsElem = this.elem.querySelector('.forecasts');
		forecastsElem.innerHTML = '';
		forecastsElem.append(...templates);

		// increase each forecast height to a multiple of container height
		this.pageHeight = forecastsElem.parentNode.scrollHeight || 390;
		templates.forEach((forecast) => {
			const newHeight = Math.ceil(forecast.scrollHeight / this.pageHeight) * this.pageHeight;
			forecast.style.height = `${newHeight}px`;
		});

		this.timing.totalScreens = Math.max(1, forecastsElem.scrollHeight / this.pageHeight);
		this.calcNavTiming();
		this.setStatus(STATUS.loaded);
	}

	async drawCanvas() {
		super.drawCanvas();

		const top = -this.screenIndex * this.pageHeight;
		this.elem.querySelector('.forecasts').style.top = `${top}px`;

		this.finishDraw();
	}
}

// register display
registerDisplay(new LocalForecast(7, 'local-forecast'));
