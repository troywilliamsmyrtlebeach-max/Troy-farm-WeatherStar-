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

		const days = Object.keys(_weatherParameters.forecast).slice(0, 3);
		const daysWeatherData = Object.values(_weatherParameters.forecast).slice(0, 3);
		const localForecastTextByDay = [];

		daysWeatherData.forEach((day, index) => {
			const result = generateLocalForecast(days[index], day.hours, { isFirstDay: index === 0 });
			localForecastTextByDay.push(JSON.parse(result));
		});

		const conditions = [];
		localForecastTextByDay.forEach((forecast) => {
			const page = Object.values(forecast.periods).filter((forecastText) => forecastText && forecastText.text).map((forecastText) => ({
				DayName: forecast.date,
				Text: forecastText.text,
			}));
			conditions.push(...page);
		});

		if (!conditions.length) {
			this.screenTexts = [
				// FRESH FORECAST 2026-11-07 ~11:52 PM EST (NWS ILM gridpoint 68,59 for the farm,
				// generated 2026-11-08T03:52Z). Written in the screenshot format (generator
				// style) with precip chance on every period, like the live path.
				'TONIGHT... Mostly clear. Low around 41. North wind around 3 mph. Precip chance 0%.',
				'SUNDAY... Sunny. High 68. North wind around 3 mph. Precip chance 0%.',
				'SUNDAY NIGHT... Mostly clear. Low 44. West wind around 2 mph. Precip chance 0%.',
				'MONDAY... Sunny. High 74. West wind 1 to 6 mph. Precip chance 0%.',
				'MONDAY NIGHT... Clear. Low 44. Southeast wind around 1 mph. Precip chance 0%.',
				'TUESDAY... Sunny. High 74. Winds light and variable. Precip chance 0%.',
				'TUESDAY NIGHT... Partly cloudy. Low 48. Winds light and variable. Precip chance 0%.',
				'VETERANS DAY... Mostly sunny. High 75. Winds light and variable. Precip chance 0%.',
			];
		} else {
			this.screenTexts = conditions.map((condition) => condition.Text);
		}

		// Troy 2026-11-07 (screenshot 987_1_5ss8.png): the Local Forecast screen writes
		// the forecast out in paragraph form, THREE periods on one screen — period label
		// in yellow caps on its own line, then the text in white. Group the period texts
		// into pages of 3; each page is one .forecast template (fillTemplate sets
		// innerHTML, so the label span renders as HTML).
		const pages = [];
		for (let i = 0; i < this.screenTexts.length; i += 3) pages.push(this.screenTexts.slice(i, i + 3));
		const templates = pages.map((pageTexts) => {
			const html = pageTexts.map((text) => {
				const m = text.match(/^([^.]*\.\.\.)\s*([\s\S]*)$/);
				if (!m) return `<div class="fc-period"><div class="fc-body">${text}</div></div>`;
				return `<div class="fc-period"><div class="fc-label">${m[1]}</div><div class="fc-body">${m[2]}</div></div>`;
			}).join('');
			return this.fillTemplate('forecast', { text: html });
		});
		const forecastsElem = this.elem.querySelector('.forecasts');
		forecastsElem.innerHTML = '';
		forecastsElem.append(...templates);

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
