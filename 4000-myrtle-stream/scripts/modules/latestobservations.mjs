// current weather conditions display
import { distance as calcDistance, directionToNSEW } from './utils/calc.mjs';
import { json } from './utils/fetch.mjs';
import STATUS from './status.mjs';
import { locationCleanup } from './utils/string.mjs';
import { celsiusToFahrenheit, kphToMph } from './utils/units.mjs';
import WeatherDisplay from './weatherdisplay.mjs';
import { registerDisplay } from './navigation.mjs';
import { getConditionText } from './utils/weather.mjs';


// STREAM-MATCH 2026-11-07 (v=6): TOWN names, never airport codes and never
// cut mid-word. Known airport/county names map to their town; anything else
// loses its "Airport" suffix, then truncates at a word boundary (max 18
// chars, so "North Myrtle Beach" fits whole in the 225px location column).
const TOWN_NAMES = {
	'Conway Horry County Airport': 'Conway',
	'Conway-Horry County Airport': 'Conway',
	'North Myrtle Beach Grand Strand Airport': 'North Myrtle Beach',
	'Grand Strand Airport': 'North Myrtle Beach',
	'Myrtle Beach International Airport': 'Myrtle Beach',
	'Wilmington International Airport': 'Wilmington',
	'Columbus County Municipal Airport': 'Whiteville',
	'Curtis L Brown Jr Field': 'Elizabethtown',
	'Lumberton Regional Airport': 'Lumberton',
	'Florence Regional Airport': 'Florence',
	'Brunswick County': 'Southport',
};
const cleanStationName = (city) => {
	const cleaned = locationCleanup(city || '');
	const mapped = TOWN_NAMES[cleaned] || cleaned;
	const stripped = mapped
		.replace(/ International Airport$/i, '')
		.replace(/ Regional Airport$/i, '')
		.replace(/ Airport$/i, '')
		.trim();
	if (stripped.length <= 18) return stripped;
	// Never cut mid-word: back up to the last space inside 18 chars.
	const cut = stripped.slice(0, 18);
	const lastSpace = cut.lastIndexOf(' ');
	return (lastSpace > 0 ? cut.slice(0, lastSpace) : cut).trim();
};

class LatestObservations extends WeatherDisplay {
	constructor(navId, elemId) {
		super(navId, elemId, 'Latest Observations', false);

		// constants
		this.MaximumRegionalStations = 7; // Troy Oct 31 20:47: farm + 6 towns, Whiteville REMOVED
		this.showOnProgress = false;
	}

	async getData(_weatherParameters) {
		if (!super.getData(_weatherParameters)) return;
		const weatherParameters = _weatherParameters ?? this.weatherParameters;
		const farmTimeZone = weatherParameters?.timeZone ?? 'America/New_York';

		// TROY SCREENSHOT (Oct 31 19:16): Latest Observations is EXACTLY these 7 towns,
		// in this order, with live NWS readings — not the nearest-30 by distance.
		//  Conway = KHYW, Lumberton = KLBT, Myrtle Beach = KMYR,
		//  North Myrtle Beach = KCRE, Southport = KSUT (Brunswick County),
		//  Wilmington = KILM. Wind is speed only, no MPH (screenshot style, already in drawCanvas).
		// Troy Oct 31 19:32: farm FIRST, Elizabethtown DROPPED. Oct 31 20:06: N. Myrtle Beach ADDED — 7 towns + farm = 8 rows.
		const SCREENSHOT_TOWNS = [
			{ id: 'KHYW', city: 'Conway Horry County Airport' },
			{ id: 'KLBT', city: 'Lumberton' },
			{ id: 'KMYR', city: 'Myrtle Beach International Airport' },
			{ id: 'KCRE', city: 'North Myrtle Beach Grand Strand Airport' },
			{ id: 'KSUT', city: 'Southport' },
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

		// Farm row FIRST, from the live farm payload (same data as Current Conditions).
		// Direction string -> degrees for the shared wind code; sky word from WMO code via getConditionText if available.
		try {
			const farm = (typeof window !== 'undefined' && window.__latestPwsPayload) ? window.__latestPwsPayload : null;
			if (farm && farm.temperature !== undefined && farm.temperature !== null) {
				const dirDeg = { N: 0, NNE: 22.5, NE: 45, ENE: 67.5, E: 90, ESE: 112.5, SE: 135, SSE: 157.5, S: 180, SSW: 202.5, SW: 225, WSW: 247.5, W: 270, WNW: 292.5, NW: 315, NNW: 337.5 }[farm.windDirection] ?? 0;
				const farmSky = (farm.conditionText === 3) ? 'Overcast' : (farm.conditionText === 0) ? getConditionText(0, farmTimeZone) : (farm.conditionText === 1) ? 'Fair' : (farm.conditionText === 2) ? 'Partly Cloudy' : (farm.conditionText === 45 || farm.conditionText === 48) ? 'Fog' : 'Fair';
				actualConditions.unshift({
					temperature: { value: farm.temperature },
					// Troy Oct 31 19:36: farm Latest Observations wind = HIGHEST wind speed (sustained vs gust) — e.g. sustained 2, gust 8 -> show 8, not 2.
					windSpeed: { value: Math.max(farm.windSpeed || 0, farm.windGust || 0) },
					windDirection: { value: dirDeg },
					textDescription: farmSky,
					StationId: 'FARM',
					city: 'CALABASH-FARM AT BRUNSWICK',
				});
			}
		} catch (e) { /* farm row optional — towns still show */ }
		// cut down to the maximum of 7 (farm + 6 towns)
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

		// Farm FIRST, then towns in screenshot order (do not alphabetical-sort the farm away)

		this.elem.querySelector('.column-headers .temp.english').classList.add('show');
		this.elem.querySelector('.column-headers .temp.metric').classList.remove('show');

		const lines = conditions.map((condition) => {
			const windDirection = directionToNSEW(condition.windDirection.value);

			if (condition.temperature.value === null || condition.temperature.value === undefined) return null;
			const	Temperature = Math.round(celsiusToFahrenheit(condition.temperature.value));
			const WindSpeed = Math.round(kphToMph(condition.windSpeed.value));

			// v=6: full TOWN names, never airport codes, never truncated
			// mid-word — "Conway", "North Myrtle Beach" (not "Conway-Horry C" / "N. Myrtle Beach").
			const SCREENSHOT_NAMES = { KHYW: 'Conway', KEYF: 'Elizabethtown', KLBT: 'Lumberton', KMYR: 'Myrtle Beach', KSUT: 'Southport', KCPC: 'Whiteville', KILM: 'Wilmington', FARM: 'CALABASH-FARM', KCRE: 'North Myrtle Beach' };
			const fill = {
				location: SCREENSHOT_NAMES[condition.StationId] || cleanStationName(condition.city),
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
