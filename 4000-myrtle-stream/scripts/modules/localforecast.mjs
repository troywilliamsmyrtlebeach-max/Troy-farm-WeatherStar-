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
				// FRESH FORECAST 2026-11-18 ~4:19 AM EST (NWS ILM gridpoint 68,59 for the farm,
				// generated 2026-11-20T00:23:04+00:00 forecast through Wednesday, verified this run). Written in the screenshot format (generator
				// style) with precip chance on every period, like the live path.
				'TONIGHT... Mostly cloudy, with a low around 52. Northeast wind around 5 mph. Precip chance 2%.',
				'FRIDAY... Partly sunny, with a high near 74. Northeast wind 6 to 10 mph. Precip chance 1%.',
				'FRIDAY NIGHT... Mostly cloudy, with a low around 54. Northeast wind 6 to 10 mph. Precip chance 0%.',
				'SATURDAY... A chance of rain showers after 1pm. Mostly cloudy, with a high near 72. Northeast wind 10 to 14 mph, with gusts as high as 22 mph. Chance of precipitation is 40%. New rainfall amounts less than a tenth of an inch possible. Precip chance 39%.',
				'SATURDAY NIGHT... Rain showers. Mostly cloudy, with a low around 58. Northeast wind 9 to 14 mph, with gusts as high as 21 mph. Chance of precipitation is 80%. New rainfall amounts between a quarter and half of an inch possible. Precip chance 75%.',
				'SUNDAY... Rain showers. Partly sunny, with a high near 72. Chance of precipitation is 80%. New rainfall amounts between a half and three quarters of an inch possible. Precip chance 75%.',
				'SUNDAY NIGHT... A slight chance of rain showers before 1am. Partly cloudy, with a low around 52. Precip chance 22%.',
				'MONDAY... Sunny, with a high near 75. Precip chance 4%.',
				'MONDAY NIGHT... Partly cloudy, with a low around 49. Precip chance 5%.',
				'TUESDAY... A slight chance of rain showers after 1pm. Partly sunny, with a high near 64. Precip chance 16%.',
				'TUESDAY NIGHT... A chance of rain showers. Mostly cloudy, with a low around 43. Chance of precipitation is 40%. Precip chance 38%.',
				'WEDNESDAY... A chance of rain showers. Mostly cloudy, with a high near 63. Chance of precipitation is 50%. Precip chance 49%.',
				'WEDNESDAY NIGHT... A chance of rain showers. Mostly cloudy, with a low around 45. Chance of precipitation is 50%. Precip chance 49%.',
				'THANKSGIVING DAY... A chance of rain showers. Partly sunny, with a high near 61. Precip chance 29%.',
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
