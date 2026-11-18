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
				// FRESH FORECAST 2026-11-18 ~10:48 AM EST (NWS ILM gridpoint 68,59 for the farm,
				// generated 2026-11-18T15:48:09+00:00; forecast through Tuesday Night, verified this run). Written in the screenshot format (generator
				// style) with precip chance on every period, like the live path.
				'TODAY... Sunny, with a high near 70. Northeast wind around 8 mph. Precip chance 0%.',
				'TONIGHT... Mostly clear, with a low around 48. Northeast wind around 7 mph. Precip chance 0%.',
				'THURSDAY... Mostly cloudy, with a high near 73. Northeast wind 7 to 10 mph. Precip chance 0%.',
				'THURSDAY NIGHT... Mostly cloudy, with a low around 52. Northeast wind around 7 mph. Precip chance 1%.',
				'FRIDAY... Partly sunny, with a high near 74. Northeast wind 7 to 10 mph, with gusts as high as 16 mph. Precip chance 3%.',
				'FRIDAY NIGHT... Mostly cloudy, with a low around 54. Precip chance 13%.',
				'SATURDAY... A chance of rain showers after 7am. Partly sunny, with a high near 73. Chance of precipitation is 40%. Precip chance 41%.',
				'SATURDAY NIGHT... A chance of rain showers. Mostly cloudy, with a low around 56. Chance of precipitation is 50%. Precip chance 52%.',
				'SUNDAY... A chance of rain showers. Partly sunny, with a high near 74. Chance of precipitation is 50%. Precip chance 46%.',
				'SUNDAY NIGHT... A slight chance of rain showers before 7pm. Partly cloudy, with a low around 51. Precip chance 17%.',
				'MONDAY... Sunny, with a high near 73. Precip chance 5%.',
				'MONDAY NIGHT... Partly cloudy, with a low around 45. Precip chance 4%.',
				'TUESDAY... Mostly sunny, with a high near 64. Precip chance 7%.',
				'TUESDAY NIGHT... A slight chance of rain showers between 7pm and 1am. Partly cloudy, with a low around 42. Precip chance 15%.',
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
