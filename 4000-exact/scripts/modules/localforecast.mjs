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
				'TONIGHT... Mostly cloudy, with a low around 53. Northeast wind around 7 mph.',
				'SUNDAY... Partly sunny, with a high near 73. Northeast wind 6 to 9 mph, with gusts as high as 16 mph.',
				'SUNDAY NIGHT... Mostly cloudy, with a low around 56. Northeast wind around 7 mph.',
				'MONDAY... Partly sunny, with a high near 74. Northeast wind 7 to 10 mph, with gusts as high as 16 mph.',
				'MONDAY NIGHT... Partly cloudy, with a low around 57. Northeast wind around 7 mph.',
				'TUESDAY... Mostly sunny, with a high near 79.',
				'TUESDAY NIGHT... Mostly clear, with a low around 61.',
				'WEDNESDAY... Mostly sunny, with a high near 80.',
			];
		} else {
			this.screenTexts = conditions.map((condition) => condition.Text);
		}

		const templates = this.screenTexts.map((text) => this.fillTemplate('forecast', { text }));
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
