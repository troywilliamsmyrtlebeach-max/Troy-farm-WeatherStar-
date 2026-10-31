// current weather conditions display
import { distance as calcDistance, directionToNSEW } from './utils/calc.mjs';
import { json } from './utils/fetch.mjs';
import STATUS from './status.mjs';
import { locationCleanup } from './utils/string.mjs';
import { celsiusToFahrenheit, kphToMph } from './utils/units.mjs';
import WeatherDisplay from './weatherdisplay.mjs';
import { registerDisplay } from './navigation.mjs';

class LatestObservations extends WeatherDisplay {
	constructor(navId, elemId) {
		super(navId, elemId, 'Latest Observations', false);

		// constants
		this.MaximumRegionalStations = 7;
		this.showOnProgress = false;
	}

	async getData(_weatherParameters) {
		if (!super.getData(_weatherParameters)) return;
		const weatherParameters = _weatherParameters ?? this.weatherParameters;

		// TROY SCREENSHOT (Oct 31 19:16): Latest Observations is EXACTLY these 7 towns,
		// in this order, with live NWS readings — not the nearest-30 by distance.
		//  Conway-Horry C = KHYW, Elizabethtown = KEYF (Curtis L Brown Jr Field, Elizabethtown NC),
		//  Lumberton = KLBT, Myrtle Beach = KMYR, Southport = KSUT (Brunswick County, nearest to Southport),
		//  Whiteville = KCPC, Wilmington = KILM. Wind is speed only, no MPH (screenshot style, already in drawCanvas).
		const SCREENSHOT_TOWNS = [
			{ id: 'KHYW', city: 'Conway Horry County Airport' },
			{ id: 'KEYF', city: 'Elizabethtown' },
			{ id: 'KLBT', city: 'Lumberton' },
			{ id: 'KMYR', city: 'Myrtle Beach International Airport' },
			{ id: 'KSUT', city: 'Southport' },
			{ id: 'KCPC', city: 'Whiteville, Columbus County Municipal Airport' },
			{ id: 'KILM', city: 'Wilmington International Airport' },
		];
		const regionalStations = SCREENSHOT_TOWNS;

		// get data for regional stations
		// get first 7 stations
		const actualConditions = [];
		let lastStation = Math.min(regionalStations.length, 7);
		let firstStation = 0;
		while (actualConditions.length < 7 && (lastStation) <= regionalStations.length && firstStation < regionalStations.length) {
			// eslint-disable-next-line no-await-in-loop
			const someStations = await getStations(regionalStations.slice(firstStation, lastStation));

			actualConditions.push(...someStations);
			// update counters
			firstStation += lastStation;
			lastStation = Math.min(regionalStations.length + 1, firstStation + 7 - actualConditions.length);
		}

		// cut down to the maximum of 7
		this.data = actualConditions.slice(0, this.MaximumRegionalStations);

		// test for at least one station
		if (this.data.length === 0) {
			this.setStatus(STATUS.noData);
			return;
		}
		this.setStatus(STATUS.loaded);
	}

	async drawCanvas() {
		super.drawCanvas();
		const conditions = this.data;

		// sort array by station name
		const sortedConditions = conditions.sort((a, b) => ((a.Name < b.Name) ? -1 : 1));

		this.elem.querySelector('.column-headers .temp.english').classList.add('show');
		this.elem.querySelector('.column-headers .temp.metric').classList.remove('show');

		const lines = sortedConditions.map((condition) => {
			const windDirection = directionToNSEW(condition.windDirection.value);

			if (condition.temperature.value === null || condition.temperature.value === undefined) return null;
			const	Temperature = Math.round(celsiusToFahrenheit(condition.temperature.value));
			const WindSpeed = Math.round(kphToMph(condition.windSpeed.value));

			const SCREENSHOT_NAMES = { KHYW: 'Conway-Horry C', KEYF: 'Elizabethtown', KLBT: 'Lumberton', KMYR: 'Myrtle Beach', KSUT: 'Southport', KCPC: 'Whiteville', KILM: 'Wilmington' };
			const fill = {
				location: SCREENSHOT_NAMES[condition.StationId] || locationCleanup(condition.city).substr(0, 14),
				temp: Temperature,
				weather: shortenCurrentConditions(condition.textDescription).substr(0, 9),
			};

			if (WindSpeed > 0) {
				fill.wind = windDirection + (Array(6 - windDirection.length - WindSpeed.toString().length).join(' ')) + WindSpeed.toString();
			} else if (WindSpeed === 'NA') {
				fill.wind = 'NA';
			} else {
				fill.wind = 'Calm';
			}

			return this.fillTemplate('observation-row', fill);
		});

		const linesFiltered = lines.filter(Boolean);
		const linesContainer = this.elem.querySelector('.observation-lines');
		linesContainer.innerHTML = '';
		linesContainer.append(...linesFiltered);

		this.finishDraw();
	}
}
const shortenCurrentConditions = (_condition) => {
	let condition = _condition;
	condition = condition.replace(/Light/, 'L');
	condition = condition.replace(/Heavy/, 'H');
	condition = condition.replace(/Partly/, 'P');
	condition = condition.replace(/Mostly/, 'M');
	condition = condition.replace(/Few/, 'F');
	condition = condition.replace(/Thunderstorm/, 'T\'storm');
	condition = condition.replace(/ in /, '');
	condition = condition.replace(/Vicinity/, '');
	condition = condition.replace(/ and /, ' ');
	condition = condition.replace(/Freezing Rain/, 'Frz Rn');
	condition = condition.replace(/Freezing/, 'Frz');
	condition = condition.replace(/Unknown Precip/, '');
	condition = condition.replace(/L Snow Fog/, 'L Snw/Fog');
	condition = condition.replace(/ with /, '/');
	return condition;
};

const getStations = async (stations) => {
	const stationData = await Promise.all(stations.map(async (station) => {
		try {
			const data = await json(`https://api.weather.gov/stations/${station.id}/observations/latest`, { retryCount: 1, stillWaiting: () => this.stillWaiting() });
			// test for temperature, weather and wind values present
			if (data.properties.temperature.value === null
			|| data.properties.textDescription === ''
			|| data.properties.windSpeed.value === null) return false;
			// format the return values
			return {
				...data.properties,
				StationId: station.id,
				city: station.city,
			};
		} catch (error) {
			console.log(`Unable to get latest observations for ${station.id}`);
			return false;
		}
	}));
	// filter false (no data or other error)
	return stationData.filter((d) => d);
};
// register display
registerDisplay(new LatestObservations(2, 'latest-observations'));
