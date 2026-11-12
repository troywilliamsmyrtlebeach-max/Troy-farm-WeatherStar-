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
				// FRESH FORECAST 2026-11-11 ~11:04 PM EST (NWS ILM gridpoint 68,59 for the farm,
				// generated 2026-11-12T04:04:25Z; forecast through Wednesday, verified this run). Written in the screenshot format (generator
				// style) with precip chance on every period, like the live path.
				'TONIGHT... Mostly clear, with a low around 55. Southwest wind around 7 mph. Precip chance 2%.',
				'THURSDAY... Sunny, with a high near 75. West wind 8 to 14 mph, with gusts as high as 23 mph. Precip chance 7%.',
				'THURSDAY NIGHT... Mostly clear, with a low around 46. West wind 6 to 10 mph, with gusts as high as 18 mph. Precip chance 0%.',
				'FRIDAY... Sunny, with a high near 64. Northwest wind around 9 mph. Precip chance 0%.',
				'FRIDAY NIGHT... Mostly clear, with a low around 39. Northwest wind 3 to 7 mph. Precip chance 0%.',
				'SATURDAY... Sunny, with a high near 58. Precip chance 0%.',
				'SATURDAY NIGHT... Clear, with a low around 34. Precip chance 0%.',
				'SUNDAY... Sunny, with a high near 59. Precip chance 0%.',
				'SUNDAY NIGHT... Mostly clear, with a low around 35. Precip chance 0%.',
				'MONDAY... Mostly sunny, with a high near 60. Precip chance 2%.',
				'MONDAY NIGHT... Mostly cloudy, with a low around 39. Precip chance 12%.',
				'TUESDAY... A slight chance of rain showers between 7am and 1pm. Mostly sunny, with a high near 60. Precip chance 16%.',
				'TUESDAY NIGHT... Partly cloudy, with a low around 39. Precip chance 14%.',
				'WEDNESDAY... Sunny, with a high near 63. Precip chance 13%.',
			];
		} else {
			this.screenTexts = conditions.map((condition) => condition.Text);
		}

		// Troy 2026-11-07 (screenshot 987_1_5ss8.png): the Local Forecast screen writes
		// the forecast out in paragraph form — period label in yellow caps on its own
		// line, then the text in white. Troy 2026-11-08 (v=23): ONE period per screen,
		// in bigger letters the size of the Almanac page (24pt) — TODAY on one page,
		// TONIGHT on the next, MONDAY on the next, and so on. Each page is one
		// .forecast template (fillTemplate sets innerHTML, so the label span renders
		// as HTML).
		const pages = [];
		for (let i = 0; i < this.screenTexts.length; i += 1) pages.push(this.screenTexts.slice(i, i + 1));
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
