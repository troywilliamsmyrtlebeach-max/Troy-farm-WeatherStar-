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
				// FRESH FORECAST 2026-11-18 ~4:19 AM EST (NWS ILM gridpoint 68,59 for the farm,
				// generated 2026-11-24T10:53:50+00:00 forecast through Wednesday, verified this run). Written in the screenshot format (generator
				// style) with precip chance on every period, like the live path.
				'OVERNIGHT... Mostly cloudy, with a low around 55. North wind around 9 mph. Precip chance 2%.',
				'TUESDAY... Mostly cloudy, with a high near 60. Northeast wind 9 to 14 mph, with gusts as high as 22 mph. Precip chance 4%.',
				'TUESDAY NIGHT... A chance of rain showers after 1am. Mostly cloudy, with a low around 42. Northeast wind 7 to 13 mph, with gusts as high as 20 mph. Chance of precipitation is 30%. New rainfall amounts less than a tenth of an inch possible. Precip chance 28%.',
				'WEDNESDAY... Rain showers before 4pm, then showers and thunderstorms. Cloudy, with a high near 67. Northeast wind 13 to 16 mph, with gusts as high as 28 mph. Chance of precipitation is 100%. New rainfall amounts between 1 and 2 inches possible. Precip chance 95%.',
				'WEDNESDAY NIGHT... Showers and thunderstorms. Cloudy, with a low around 57. East wind 8 to 16 mph, with gusts as high as 26 mph. Chance of precipitation is 100%. New rainfall amounts between 2 and 3 inches possible. Precip chance 100%.',
				'THANKSGIVING DAY... Showers and thunderstorms. Mostly cloudy, with a high near 72. Chance of precipitation is 100%. New rainfall amounts between a half and three quarters of an inch possible. Precip chance 100%.',
				'THURSDAY NIGHT... A slight chance of rain showers before 7pm. Partly cloudy, with a low around 44. Precip chance 18%.',
				'FRIDAY... Sunny, with a high near 60. Precip chance 0%.',
				'FRIDAY NIGHT... Partly cloudy, with a low around 41. Precip chance 0%.',
				'SATURDAY... Mostly sunny, with a high near 64. Precip chance 0%.',
				'SATURDAY NIGHT... Partly cloudy, with a low around 43. Precip chance 0%.',
				'SUNDAY... Mostly sunny, with a high near 67. Precip chance 2%.',
				'SUNDAY NIGHT... A slight chance of rain showers after 7pm. Partly cloudy, with a low around 49. Precip chance 16%.',
				'MONDAY... A slight chance of rain showers before 7am. Mostly sunny, with a high near 68. Precip chance 16%.',
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
