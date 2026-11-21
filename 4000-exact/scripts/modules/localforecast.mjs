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
				// generated 2026-11-21T16:43:12+00:00 forecast through Wednesday, verified this run). Written in the screenshot format (generator
				// style) with precip chance on every period, like the live path.
				'TODAY... Rain showers likely. Cloudy, with a high near 71. Northeast wind around 12 mph, with gusts as high as 21 mph. Chance of precipitation is 70%. New rainfall amounts between a tenth and quarter of an inch possible. Precip chance 72%.',
				'TONIGHT... Rain showers before 7pm, then showers and thunderstorms. Cloudy, with a low around 60. Northeast wind 6 to 9 mph, with gusts as high as 17 mph. Chance of precipitation is 90%. New rainfall amounts between three quarters and one inch possible. Precip chance 93%.',
				'SUNDAY... A chance of showers and thunderstorms before 11am, then a slight chance of showers and thunderstorms between 1pm and 5pm, then a chance of showers and thunderstorms. Mostly cloudy, with a high near 73. West wind 2 to 7 mph. Chance of precipitation is 40%. New rainfall amounts between a quarter and half of an inch possible. Precip chance 43%.',
				'SUNDAY NIGHT... A slight chance of showers and thunderstorms before 7pm. Partly cloudy, with a low around 56. West wind around 2 mph. Chance of precipitation is 20%. Precip chance 20%.',
				'MONDAY... Mostly sunny, with a high near 75. Northwest wind 1 to 5 mph. Precip chance 3%.',
				'MONDAY NIGHT... Mostly cloudy, with a low around 52. Precip chance 2%.',
				'TUESDAY... Mostly cloudy, with a high near 66. Precip chance 6%.',
				'TUESDAY NIGHT... A chance of rain showers after 1am. Mostly cloudy, with a low around 41. Chance of precipitation is 40%. Precip chance 35%.',
				'WEDNESDAY... Rain showers likely. Mostly cloudy, with a high near 63. Chance of precipitation is 70%. Precip chance 71%.',
				'WEDNESDAY NIGHT... Rain showers likely. Mostly cloudy, with a low around 46. Chance of precipitation is 70%. Precip chance 71%.',
				'THANKSGIVING DAY... A chance of rain showers before 1pm. Partly sunny, with a high near 65. Chance of precipitation is 50%. Precip chance 45%.',
				'THURSDAY NIGHT... Partly cloudy, with a low around 38. Precip chance 10%.',
				'FRIDAY... Mostly sunny, with a high near 64. Precip chance 2%.',
				'FRIDAY NIGHT... Partly cloudy, with a low around 38. Precip chance 5%.',
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
