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
				// FRESH FORECAST 2026-11-09 ~7:31 PM EST (NWS ILM gridpoint 68,59 for the farm,
				// generated 2026-11-10T00:31:46Z; forecast through Monday, verified this run). Written in the screenshot format (generator
				// style) with precip chance on every period, like the live path.
				'TONIGHT... Mostly clear. Low around 44. Precip chance 0%.',
				'TUESDAY... Sunny. High 76. Southwest wind 0 to 6 mph. Precip chance 0%.',
				'TUESDAY NIGHT... Partly cloudy. Low around 50. West wind 0 to 5 mph. Precip chance 0%.',
				'VETERANS DAY... Mostly sunny. High 75. West wind 0 to 5 mph. Precip chance 0%.',
				'WEDNESDAY NIGHT... Partly cloudy. Low around 53. Southwest wind 5 mph. Precip chance 1%.',
				'THURSDAY... A slight chance of rain showers between 7am and 1pm. Mostly sunny. High 76. Southwest wind 5 to 13 mph. Precip chance 17%.',
				'THURSDAY NIGHT... Mostly clear. Low around 46. West wind 9 mph. Precip chance 14%.',
				'FRIDAY... Sunny. High 64. West wind 9 to 16 mph. Precip chance 3%.',
				'FRIDAY NIGHT... Mostly clear. Low around 38. Northwest wind 7 to 12 mph. Precip chance 3%.',
				'SATURDAY... Sunny. High 59. Northwest wind 9 to 13 mph. Precip chance 0%.',
				'SATURDAY NIGHT... Clear. Low around 35. Northwest wind 3 to 7 mph. Precip chance 0%.',
				'SUNDAY... Sunny. High 61. Northwest wind 6 mph. Precip chance 0%.',
				'SUNDAY NIGHT... Mostly clear. Low around 37. North wind 2 mph. Precip chance 1%.',
				'MONDAY... A slight chance of rain showers after 1pm. Sunny. High 65. North wind 5 mph. Precip chance 15%.',
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
