// navigation handles progress, next/previous and initial load messages from the parent frame
import noSleep from './utils/nosleep.mjs';
import STATUS from './status.mjs';
import { wrap } from './utils/calc.mjs';
import {
	getPoint, getMarinePoint, getGeocoding, aggregateWeatherForecastData, getAirQualityPoint,
} from './utils/weather.mjs';
// eslint-disable-next-line import/no-cycle
import settings from './settings.mjs';
import NearbyCities from './utils/nearby-cities.mjs';
import ExperimentalFeatures from './utils/experimental.mjs';

import { parseQueryString } from './share.mjs';

document.addEventListener('DOMContentLoaded', () => {
	init();
});

// @todo - absolutely gnarly, but displays must be SEQUENTIALLY LOADED & REGISTERED.
// you CANNOT set an arbitrary display navId to "21" and expect it to work.
// doing this will cause the logic to insert a number of nulls into the array between the
// last known display and the "next one" (ex.[1,2,3, ...NULLx17, 21])
const displays = [];
let playing = false;
let progress;
const weatherParameters = {};

// auto refresh
const AUTO_REFRESH_INTERVAL_MS = 500;
const AUTO_REFRESH_TIME_MS = 600_000; // 10 min.
const CHK_AUTO_REFRESH_SELECTOR = '#chkAutoRefresh';
let AutoRefreshIntervalId = null;
let AutoRefreshCountMs = 0;

const init = async () => {
	// set up resize handler
	window.addEventListener('resize', resize);
	window.addEventListener('orientationchange', resize);
	document.addEventListener('fullscreenchange', resize);
	resize();

	// set up custom event listener for custom messages from displays
	window.addEventListener('custom-weather:update', (event) => {
		console.debug('Received custom-weather:update event with data:', event);
		if (event.detail) {
			// store on shared weatherParameters so displays can read it
			weatherParameters.customWeather = event.detail;

			// optionally notify displays that implement a handler
			displays.forEach((display) => {
				if (typeof display.onCustomWeather === 'function') {
					display.onCustomWeather(event.detail);
				}
			});
		}
	});

	// Replay a PWS payload that arrived via SSE before this listener
	// registered (see index.ejs applyPayload): otherwise a freshly
	// loaded copy shows locality numbers in the ticker until the next
	// 5-minute bridge push, even though the server already holds farm data.
	if (window.__latestPwsPayload) {
		// Only seed the shared object: displays pick it up in getData
		// (and the ticker reads it from display 13), and late pushes
		// still redraw via onCustomWeather as before. Do not force a
		// redraw here — displays may not have their elements yet.
		weatherParameters.customWeather = window.__latestPwsPayload;
	}

	// auto refresh
	const autoRefresh = localStorage.getItem('autoRefresh');
	if (!autoRefresh || autoRefresh === 'true') {
		document.querySelector(CHK_AUTO_REFRESH_SELECTOR).checked = true;
	} else {
		document.querySelector(CHK_AUTO_REFRESH_SELECTOR).checked = false;
	}
	document.querySelector(CHK_AUTO_REFRESH_SELECTOR).addEventListener('change', autoRefreshChange);
	generateCheckboxes();
};

const message = (data) => {
	// dispatch event
	if (!data.type) return false;
	if (data.type === 'navButton') return handleNavButton(data.message);
	return console.error(`Unknown event ${data.type}`);
};

const getWeather = async (latLon, haveDataCallback) => {
	// get initial weather data
	const point = await getPoint(latLon.lat, latLon.lon);

	const aggregatedForecastData = aggregateWeatherForecastData(point);

	if (typeof haveDataCallback === 'function') haveDataCallback(point);

	// Get locality data from open-meteo and local storage
	const localityName = localStorage.getItem('latLonQuery');
	const storedLatLon = localStorage.getItem('latLon');
	let locality;

	// We need to check if localityName is set in localStorage
	// if it is not set, it's likely that the page was loaded from a permalink
	// and we need to derive the locality name from the latLon.

	// We can assume this is safe because the latLon would've been set by the user
	// during a previous search
	if (!localityName) {
		console.warn('getWeather:'
			+ '\nlocalityName is not set in localStorage. Origin could be a permalink.'
			+ '\nAttempting to derive localityName from latLonQuery.');

		const parsedParameters = parseQueryString();
		if (parsedParameters && parsedParameters.latLonQuery != null) {
			console.warn(`getWeather: parsed localityName as: ${parsedParameters.latLonQuery}`);
			// This is only useful if the page is refreshed
			localStorage.setItem('latLonQuery', parsedParameters.latLonQuery);
			// Pass the value from our query params
			locality = await getGeocoding(parsedParameters.latLonQuery.split(',')[0]);
		}
	} else {
		// 'latLonQuery' is set in server>scripts>index.mjs in the format of "Amsterdam, NLD"
		// therefore we need to split on the "," to get the locality name for open-meteo
		locality = await getGeocoding(localityName.split(',')[0]);
	}

	// If the geocoding lookup failed (e.g. Open-Meteo rate-limited), fall back
	// to the farm locality so one failed lookup cannot wedge the whole app.
	if (!locality || !locality.results || !locality.results.length) {
		locality = {
			results: [{
				name: 'Carolina Shores', country: 'United States', admin1: 'North Carolina', timezone: 'America/New_York', latitude: latLon.lat, longitude: latLon.lon,
			}],
		};
	}

	// we need to confirm that the stored latLon matches the latLon of the weather data we
	// just retrieved. This ensures that we don't have a mismatch between the locality and the
	// weather data
	if (storedLatLon) {
		const epsilon = 0.01; // ~1.1 km
		// eslint-disable-next-line no-plusplus
		for (let i = 0; i < locality.results.length; i++) {
			const result = locality.results[i];
			if (
				Math.abs(result.latitude - latLon.lat) < epsilon
				&& Math.abs(result.longitude - latLon.lon) < epsilon
			) {
				console.debug('getWeather: found a locality that matches the current latLon (rounded to 0.1)');
				locality = {
					results: [result],
				};
				break;
			}
		}
	}

	// set the city and state
	const city = locality.results[0].name;
	const { country } = locality.results[0];
	const state = locality.results[0].admin1;	// admin1 is usually the state / province
	const { timezone } = locality.results[0];

	// populate the weather parameters
	weatherParameters.latitude = latLon.lat;
	weatherParameters.longitude = latLon.lon;
	weatherParameters.city = city;
	weatherParameters.state = state;
	weatherParameters.country = country;
	weatherParameters.timeZone = timezone;

	// WeatherParameters to modify...
	weatherParameters.forecast = aggregatedForecastData;
	// weatherParameters.forecastGridData = point.properties.forecastGridData;
	// weatherParameters.stations = stations.features;

	// WeatherParameters that might be optional to modify
	// or aren't obviously used anywhere for data retrieval...
	weatherParameters.stationId = 'stationId-dont-matter-anymore';
	weatherParameters.zoneId = 'zoneId-dont-matter';
	weatherParameters.radarId = 'radarId-dont-matter';
	weatherParameters.weatherOffice = 'weatherOffice-dont-matter';

	// update the main process for display purposes
	populateWeatherParameters(weatherParameters);

	// draw the progress canvas and hide others
	hideAllCanvases();
	document.querySelector('#loading').style.display = 'none';
	if (progress) {
		await progress.drawCanvas();
		progress.showCanvas();
	}

	// call for new data on each display
	displays.forEach((display) => display.getData(weatherParameters));

	// We check for nearbyCities after calling the displays to load because it's essentially a blocking request.
	// Generally it takes 2-3 seconds to get this data, and it looks like the application hangs while waiting.
	const nearybyCities = JSON.parse(localStorage.getItem('nearbyCitiesFromLocality'));
	let newNearbyCities;

	// @todo - not stoked with how experimentatlFeatures is handled
	if (ExperimentalFeatures.getExperimentalFlag()) {
		console.warn('Experimental features enabled - you may encounter unintended behavior');
		if (!nearybyCities) {
			console.warn('getWeather:'
				+ '\nnearybyCities is not set in localStorage. Origin could be a permalink.'
				+ '\nAttempting to retrieve new cities.');

			newNearbyCities = await NearbyCities.getNearbyCities(localityName.split(',')[0]).catch((error) => {
				console.error('Error fetching nearby cities:', error);
				return [];
			});
			localStorage.setItem('nearbyCitiesFromLocality', JSON.stringify(newNearbyCities));

			weatherParameters.nearbyCities = newNearbyCities;
		} else {
			weatherParameters.nearbyCities = nearybyCities;
		}
	}
};

const getMarineForecast = async (latLon, haveDataCallback) => {
	const marinePoint = await getMarinePoint(latLon.lat, latLon.lon, 'marine');
	const point = await getPoint(latLon.lat, latLon.lon);

	if (typeof haveDataCallback === 'function') haveDataCallback(marinePoint);

	displays.forEach((display) => {
		if (display.name === 'Marine Forecast') {
			display.getMarineData(point, marinePoint);
		}
	});
};

const getAirQualityForecast = async (latLon, haveDataCallback) => {
	const airQualityPoint = await getAirQualityPoint(latLon.lat, latLon.lon);
	const point = await getPoint(latLon.lat, latLon.lon);

	if (typeof haveDataCallback === 'function') haveDataCallback(airQualityPoint);

	displays.forEach((display) => {
		if (display.name === 'Air Quality') {
			display.getAirQualityData(point, airQualityPoint);
		}
	});
};

// receive a status update from a module {id, value}
const updateStatus = (value) => {
	if (value.id < 0) return;
	if (!progress) return;
	progress.drawCanvas(displays, countLoadedDisplays());

	// first display is hazards and it must load before evaluating the first display
	if (displays[0].status === STATUS.loading) return;

	// calculate first enabled display
	const firstDisplayIndex = displays.findIndex((display) => display.enabled && display.timing.totalScreens > 0);

	// value.id = 0 is hazards, if they fail to load hot-wire a new value.id to the current display to see if it needs to be loaded
	// typically this plays out as current conditions loads, then hazards fails.
	if (value.id === 0 && (value.status === STATUS.failed || value.status === STATUS.retrying)) {
		value.id = firstDisplayIndex;
		value.status = displays[firstDisplayIndex].status;
	}

	// if hazards data arrives after the firstDisplayIndex loads, then we need to hot wire this to the first display
	if (value.id === 0 && value.status === STATUS.loaded && displays[0].timing.totalScreens === 0) {
		value.id = firstDisplayIndex;
		value.status = displays[firstDisplayIndex].status;
	}

	// if this is the first display and we're playing, load it up so it starts playing
	if (isPlaying() && value.id === firstDisplayIndex && value.status === STATUS.loaded) {
		navTo(msg.command.firstFrame);
	}

	// send loaded messaged to parent
	if (countLoadedDisplays() < displays.length) return;

	// everything loaded, set timestamps
	AssignLastUpdate(new Date());
};

// note: a display that is "still waiting"/"retrying" is considered loaded intentionally
// the weather.gov api has long load times for some products when you are the first
// requester for the product after the cache expires
const countLoadedDisplays = () => displays.reduce((acc, display) => {
	if (display.status !== STATUS.loading) return acc + 1;
	return acc;
}, 0);

const hideAllCanvases = () => {
	displays.forEach((display) => display.hideCanvas());
};

// is playing interface
const isPlaying = () => playing;

// navigation message constants
const msg = {
	response: {	// display to navigation
		previous: Symbol('previous'),		// already at first frame, calling function should switch to previous canvas
		inProgress: Symbol('inProgress'),	// have data to display, calling function should do nothing
		next: Symbol('next'),				// end of frames reached, calling function should switch to next canvas
	},
	command: {	// navigation to display
		firstFrame: Symbol('firstFrame'),
		previousFrame: Symbol('previousFrame'),
		nextFrame: Symbol('nextFrame'),
		lastFrame: Symbol('lastFrame'),	// used when navigating backwards from the begining of the next canvas
	},
};

// receive navigation messages from displays
const displayNavMessage = (myMessage) => {
	if (myMessage.type === msg.response.previous) loadDisplay(-1);
	if (myMessage.type === msg.response.next) loadDisplay(1);
};

// navigate to next or previous
const navTo = (direction) => {
	// test for a current display
	const current = currentDisplay();
	progress.hideCanvas();
	if (!current) {
		// special case for no active displays (typically on progress screen)
		// find the first ready display
		// FARM-FIRST (Troy, Oct 31): start on the farm PWS Current Conditions
		// screen (navId 13, CALABASH-FARM AT BRUNSWICK) when it is loaded,
		// not on hazards/generic Current Conditions/Carolina Shores.

		// FARM-FIRST WAIT GATE (Troy, 2026-11-07): same wait as loadDisplay —
		// do not fall back to the first loaded screen while the farm PWS
		// screen (13) is still loading.
		const farm = displays[13];
		const farmReady = farm && farm.status === STATUS.loaded && farm.timing.totalScreens > 0;
		if (!farmReady && farm && typeof window !== 'undefined') {
			const since = window.__farmFirstSince || (window.__farmFirstSince = Date.now());
			if (Date.now() - since < 15000) {
				if (!window.__farmFirstTimer) {
					window.__farmFirstTimer = setTimeout(() => { window.__farmFirstTimer = undefined; navTo(direction); }, 500);
				}
				return;
			}
		}
		let firstDisplay;
		if (displays[13] && displays[13].status === STATUS.loaded && displays[13].timing.totalScreens > 0) {
			firstDisplay = displays[13];
		} else {
			let displayCount = 0;
			do {
				if (displays[displayCount].status === STATUS.loaded && displays[displayCount].timing.totalScreens > 0) firstDisplay = displays[displayCount];
				displayCount += 1;
			} while (!firstDisplay && displayCount < displays.length);
		}

		if (!firstDisplay) return;

		firstDisplay.navNext(msg.command.firstFrame);
		firstDisplay.showCanvas();
		if (typeof window !== 'undefined') window.__myrtleShownAt = Date.now();
		return;
	}
	if (direction === msg.command.nextFrame) currentDisplay().navNext();
	if (direction === msg.command.previousFrame) currentDisplay().navPrev();
};

// find the next or previous available display
const loadDisplay = (direction) => {
	const totalDisplays = displays.length;
	const curIdx = currentDisplayIndex();
	let idx;
	// FARM-FIRST WAIT GATE (Troy, 2026-11-07, STREAM-MATCH): the farm PWS
	// screen (13) loads slowest, so the candidate loop used to skip it and
	// open Hourly first. When nothing is showing yet, wait for 13 (up to
	// 15 s) instead of falling through to the first loaded screen.
	if (curIdx === -1 && direction > 0 && typeof window !== 'undefined' && displays[13] && !(displays[13].status === STATUS.loaded && displays[13].timing.totalScreens > 0)) {
		const since = window.__farmFirstSince || (window.__farmFirstSince = Date.now());
		if (Date.now() - since < 15000) {
			if (!window.__farmFirstTimer) {
				window.__farmFirstTimer = setTimeout(() => { window.__farmFirstTimer = undefined; loadDisplay(direction); }, 500);
			}
			return;
		}
	}

	// FARM-FIRST (Troy, Oct 31): after the farm PWS screen, go straight to
	// Latest Observations (navId 2), not back to hazards/generic screens.
	if (curIdx === 13 && direction > 0 && displays[2] && displays[2].status === STATUS.loaded && displays[2].timing.totalScreens > 0) {
		idx = 2;
		hideAllCanvases();
		displays[idx].showCanvas(msg.command.firstFrame);
		if (typeof window !== 'undefined') window.__myrtleShownAt = Date.now();
		return;
	}
	// MYRTLE-INTL ORDER (Troy Oct 31, corrected): 13 farm Current Conditions,
	// 2 Latest Observations, 3 Hourly, 6 Regional Forecast (maps), 7 Local Forecast (written out), 9 Almanac,
	// 8 Extended Forecast, 5 Travel Forecast, 10 Local Radar, then loop.
	// Native navId order would put Travel (5) before Local (7) and Almanac
	// (9) after Extended (8), so the cycle is stepped through this list.
	const MYRTLE_ORDER = [13, 2, 3, 4, 6, 7, 9, 8, 5, 11, 12, 10, 0];
	const curPos = MYRTLE_ORDER.indexOf(curIdx);
	let newPos = -1;
	for (let i = 0; i < MYRTLE_ORDER.length; i += 1) {
		const candPos = (((curPos + (i + 1) * direction) % MYRTLE_ORDER.length) + MYRTLE_ORDER.length) % MYRTLE_ORDER.length;
		const cand = MYRTLE_ORDER[candPos];
		if (displays[cand] && displays[cand].status === STATUS.loaded && displays[cand].timing.totalScreens > 0) { idx = cand; newPos = candPos; break; }
	}
	if (idx === undefined) return;
	// MYRTLE DWELL (v=22 PAGE-SPEED, Troy 2026-11-08: "And make all the
	// pages change quicker also"). Gate only the automatic advance
	// (loadDisplay) so a screen that exhausted its internal frames early
	// still stays up for at least 10 s total (was 45 s — every page sat
	// for 45 s and a full 13-page cycle took ~10 min, that's the "taking
	// its time"). Now each page stays up at least 10 s (readable), then
	// advances; pages with longer internal content (Hourly ~36 s, Travel
	// ~30 s, Regional 27 s, Extended 18 s, Local ~15 s) still play out
	// their full content. Full cycle now ~3 min. Manual nav buttons go
	// through navNext/navPrev on the display itself, not this gate, except
	// at end-of-display where the same path is used (accepted tradeoff).
	if (typeof window !== 'undefined' && window.__myrtleManualStep) { window.__myrtleManualStep = false; /* manual tap: bypass dwell gate */ }
	else if (typeof window !== 'undefined' && window.__myrtleShownAt) {
		const elapsed = Date.now() - window.__myrtleShownAt;
		if (elapsed < 10000) {
			if (window.__myrtleTimeout) clearTimeout(window.__myrtleTimeout);
			window.__myrtleTimeout = setTimeout(() => { window.__myrtleTimeout = undefined; loadDisplay(direction); }, 10000 - elapsed);
			return;
		}
	}
	const wrapped = (direction > 0 && newPos < curPos) || (direction < 0 && newPos > curPos);
	// if the order list wrapped, test for reload timeout
	if (wrapped && refreshCheck()) return;
	const newDisplay = displays[idx];
	// hide all displays
	hideAllCanvases();
	// show the new display and navigate to an appropriate display
	if (direction < 0) newDisplay.showCanvas(msg.command.lastFrame);
	if (direction > 0) newDisplay.showCanvas(msg.command.firstFrame);
	if (typeof window !== 'undefined') window.__myrtleShownAt = Date.now();
};

// get the current display index or value
const currentDisplayIndex = () => displays.findIndex((display) => display.active);
const currentDisplay = () => displays[currentDisplayIndex()];

const setPlaying = (newValue) => {
	playing = newValue;
	const playButton = document.querySelector('#NavigatePlay');
	localStorage.setItem('play', playing);

	if (playing) {
		noSleep(true);
		playButton.title = 'Pause';
		playButton.src = 'images/nav/ic_pause_white_24dp_2x.png';
	} else {
		noSleep(false);
		playButton.title = 'Play';
		playButton.src = 'images/nav/ic_play_arrow_white_24dp_2x.png';
	}
	// if we're playing and on the progress screen jump to the next screen
	if (!progress) return;
	if (playing && !currentDisplay()) navTo(msg.command.firstFrame);
};

// handle all navigation buttons
const handleNavButton = (button) => {
	switch (button) {
		case 'play':
			setPlaying(true);
			break;
		case 'playToggle':
			setPlaying(!playing);
			break;
		case 'stop':
			setPlaying(false);
			break;
		case 'next':
			// Troy Oct 31 18:58: manual click-through MUST step display-to-display,
			// immediately, every tap, while auto-cycle stays ON. Pause is the
			// ONLY way to stop auto-cycle. Old navTo(nextFrame) only stepped
			// internal frames, which looked unreliable / did nothing.
			if (typeof window !== 'undefined') { window.__myrtleManualStep = true; if (window.__myrtleTimeout) { clearTimeout(window.__myrtleTimeout); window.__myrtleTimeout = undefined; } }
			loadDisplay(1);
			break;
		case 'previous':
			if (typeof window !== 'undefined') { window.__myrtleManualStep = true; if (window.__myrtleTimeout) { clearTimeout(window.__myrtleTimeout); window.__myrtleTimeout = undefined; } }
			loadDisplay(-1);
			break;
		case 'menu':
			setPlaying(false);
			progress.showCanvas();
			hideAllCanvases();
			break;
		default:
			console.error(`Unknown navButton ${button}`);
	}
};

// return the specificed display
const getDisplay = (index) => displays[index];

// resize the container on a page resize
// LAYOUT-FIX 2026-11-07 (Troy: colours OK, layout broken on phone):
// scale from top-left, not the centre, measure width from the viewport
// (not #divTwcBottom, whose width changes with the kiosk stage), and pull
// the following content up/down with a negative/positive bottom margin so
// the layout height matches the scaled 4:3 panel - no black gap, no
// clipped left edge, CALABASH-FARM AT BRUNSWICK stays inside the panel.
// Colours untouched. NOTE: container height stays 480px - the transform
// scales it visually; setting height to 480*scale would double-scale.
const resize = () => {
	const container = document.querySelector('#container');
	if (!container) return;
	// LAYOUT 2026-11-09 (single scaler): navigation.mjs resize() is the ONLY
	// scaler. The inline FARM-LAYOUT script in index.html no longer touches
	// #container geometry — two scalers (0.591 vs 0.609 on a 390px phone,
	// worse sideways) made the panel shift/clip every second.
	// Design box is 640x480; the 10px border-image frame sits OUTSIDE it
	// (content-box) except in wide TV mode, where #container is
	// box-sizing:border-box and the frame sits INSIDE 854x480. Frame counted
	// once, here, nowhere else.
	const FRAME_PX = 10;
	const availWidth = document.documentElement.clientWidth || window.innerWidth;
	const availHeight = window.innerHeight;
	const isTvWide = (availWidth / availHeight) > 1.34;
	// v=18 TV-ZOOM (Troy 2026-11-08: "zoomed more in on the TV"): the 854px
	// widescreen container applies ONLY in TV mode (?tv=1) on a wide screen.
	// Phone links keep the 640px panel.
	const tvParams = new URLSearchParams(window.location.search);
	const arrowsParam = tvParams.get('arrows');
	const tvParam = tvParams.get('tv');
	const tvMode = arrowsParam === 'on' ? false : (arrowsParam === 'off' || tvParam === '1');
	// v=20 ARROWS STAY BIG (Troy 2026-11-08/09: arrows must show on the
	// phone so he can click through the pages — going big took them away).
	// bigMode no longer forces the bar off: fullscreen now targets the whole
	// document (see farmToggleFullscreen), so the bar stays inside it and
	// tappable. ?tv=1 still hides every control by design.
	const showArrows = arrowsParam === 'on' ? true : (arrowsParam === 'off' || tvParam === '1' ? false : (availWidth <= 1200 || navigator.maxTouchPoints > 0));
	const barReserve = showArrows ? 84 : 0;
	const targetWidth = (tvMode && isTvWide) ? 854 : 640;
	const designW = (tvMode && isTvWide) ? targetWidth : (targetWidth + 2 * FRAME_PX);
	const designH = (tvMode && isTvWide) ? 480 : (480 + 2 * FRAME_PX);
	const divTwcEl = document.querySelector('#divTwc');
	if (divTwcEl) { if (tvMode && isTvWide) divTwcEl.classList.add('wide'); else divTwcEl.classList.remove('wide'); }
	// v=6 PANEL-FIT (Troy's phone): in kiosk #divTwc is display:flex, so
	// #container is a flex item that SHRINKS to the viewport and its
	// overflow:hidden clips the 640px screens. Pin it to the design width.
	container.style.width = `${targetWidth}px`;
	container.style.minWidth = `${targetWidth}px`;
	container.style.flexShrink = '0';
	container.style.flexGrow = '0';
	container.style.flexBasis = `${targetWidth}px`;
	// v=18 TV-ZOOM (scale alignment): same 32px width reserve as before, so
	// the orange side bars still show on a real TV. The nav-bar reserve
	// keeps the PREV/PAUSE/NEXT bar on screen in wide/landscape mode.
	let scale;
	if (isTvWide) {
		scale = Math.max(0.2, Math.min((availHeight - barReserve) / designH, (availWidth - ((tvMode && isTvWide) ? 32 : 0)) / designW));
	} else {
		scale = Math.min(availWidth / targetWidth, availHeight / designH, 1.6);
	}
	let totalW = designW * scale;
	if (totalW > availWidth) { scale = availWidth / designW; totalW = availWidth; }
	const scaledWidth = targetWidth * scale;
	const frameScreen = FRAME_PX * scale;
	if (scale < 1.0 || isTvWide || document.fullscreenElement || settings.kiosk) {
		container.style.transform = `scale(${scale})`;
		container.style.transformOrigin = 'top left';
		if (divTwcEl) { divTwcEl.style.justifyContent = 'flex-start'; divTwcEl.style.alignItems = 'flex-start'; }
		container.style.marginBottom = `${designH * (scale - 1)}px`;
		container.style.marginLeft = availWidth > totalW ? `${(availWidth - totalW) / 2}px` : '0px';
		// v=7 FARM-NAV: keep the PREV/PAUSE/NEXT bar exactly under the scaled panel.
		const farmBar = document.getElementById('farm-nav-bar');
		if (farmBar) { farmBar.style.width = `${scaledWidth}px`; farmBar.style.marginLeft = `${(parseFloat(container.style.marginLeft) || 0) + frameScreen}px`; farmBar.style.marginRight = '0px'; farmBar.style.display = showArrows ? 'flex' : 'none'; }
	} else {
		container.style.transform = 'unset';
		container.style.transformOrigin = '';
		container.style.marginBottom = '';
		container.style.marginLeft = '';
		const farmBar2 = document.getElementById('farm-nav-bar');
		if (farmBar2) { farmBar2.style.width = ''; farmBar2.style.marginLeft = ''; farmBar2.style.marginRight = ''; farmBar2.style.display = showArrows ? 'flex' : 'none'; }
	}
	// v=8 TV-FILL: on a wide screen the scaled panel's positive bottom
	// margin makes the document taller than the viewport, so a scrollbar
	// appears and shrinks the viewport. Hide page scroll on TV (the panel +
	// bar are all there is to see in kiosk); phones are unaffected.
	document.body.style.overflow = (isTvWide && !showArrows) ? 'hidden' : '';
};

// reset all statuses to loading on all displays, used to keep the progress bar accurate during refresh
const resetStatuses = () => {
	displays.forEach((display) => { display.status = STATUS.loading; });
};

// allow displays to register themselves
const registerDisplay = (display) => {
	displays[display.navId] = display;

	// generate checkboxes
	generateCheckboxes();
};

const generateCheckboxes = () => {
	const availableDisplays = document.querySelector('#enabledDisplays');

	if (!availableDisplays) return;
	// generate checkboxes
	const checkboxes = displays.map((d) => d.generateCheckbox(d.defaultEnabled)).filter((d) => d);

	// write to page
	availableDisplays.innerHTML = '';
	availableDisplays.append(...checkboxes);
};

// special registration method for progress display
const registerProgress = (_progress) => {
	progress = _progress;
};

const populateWeatherParameters = (params) => {
	document.querySelector('#spanCity').innerHTML = `${params.city}, `;
	document.querySelector('#spanState').innerHTML = params.state;
	// document.querySelector('#spanStationId').innerHTML = params.stationId;
	// document.querySelector('#spanRadarId').innerHTML = params.radarId;
	// document.querySelector('#spanZoneId').innerHTML = params.zoneId;
};

const autoRefreshChange = (e) => {
	const { checked } = e.target;

	if (checked) {
		startAutoRefreshTimer();
	} else {
		stopAutoRefreshTimer();
	}

	localStorage.setItem('autoRefresh', checked);
};

const AssignLastUpdate = (date) => {
	if (date) {
		document.querySelector('#spanLastRefresh').innerHTML = date.toLocaleString('en-US', {
			weekday: 'short', month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: 'numeric', second: 'numeric', timeZoneName: 'short',
		});
		if (document.querySelector(CHK_AUTO_REFRESH_SELECTOR).checked) startAutoRefreshTimer();
	} else {
		document.querySelector('#spanLastRefresh').innerHTML = '(none)';
	}
};

const latLonReceived = async (data, haveDataCallback) => {
	await getWeather(data, haveDataCallback);
	await getMarineForecast(data, haveDataCallback);
	await getAirQualityForecast(data, haveDataCallback);
	AssignLastUpdate(null);

	// We can immediately start playing (auto play),
	// as all data has been retrieved
	setPlaying(true);
};

const startAutoRefreshTimer = () => {
	// Ensure that any previous timer has already stopped.
	// check if timer is running
	if (AutoRefreshIntervalId) return;

	// Reset the time elapsed.
	AutoRefreshCountMs = 0;

	const AutoRefreshTimer = () => {
		// Increment the total time elapsed.
		AutoRefreshCountMs += AUTO_REFRESH_INTERVAL_MS;

		// Display the count down.
		let RemainingMs = (AUTO_REFRESH_TIME_MS - AutoRefreshCountMs);
		if (RemainingMs < 0) {
			RemainingMs = 0;
		}
		const dt = new Date(RemainingMs);
		document.querySelector('#spanRefreshCountDown').innerHTML = `${dt.getMinutes().toString().padStart(2, '0')}:${dt.getSeconds().toString().padStart(2, '0')}`;

		// Time has elapsed.
		if (AutoRefreshCountMs >= AUTO_REFRESH_TIME_MS && !isPlaying()) loadTwcData();
	};
	AutoRefreshIntervalId = window.setInterval(AutoRefreshTimer, AUTO_REFRESH_INTERVAL_MS);
	AutoRefreshTimer();
};
const stopAutoRefreshTimer = () => {
	if (AutoRefreshIntervalId) {
		window.clearInterval(AutoRefreshIntervalId);
		document.querySelector('#spanRefreshCountDown').innerHTML = '--:--';
		AutoRefreshIntervalId = null;
	}
};

const refreshCheck = () => {
	// Time has elapsed.
	if (AutoRefreshCountMs >= AUTO_REFRESH_TIME_MS && isPlaying()) {
		loadTwcData();
		return true;
	}
	return false;
};

const loadTwcData = () => {
	if (loadTwcData.callback) loadTwcData.callback();
};

const registerRefreshData = (callback) => {
	loadTwcData.callback = callback;
};

// Fallback to the farm location's zone (Carolina Shores, NC) until latLonReceived
// sets weatherParameters.timeZone from a successful location load; without it the
// header clock falls back to the VM system zone (UTC) and shows the wrong time.
const timeZone = () => weatherParameters.timeZone || 'America/New_York';

export {
	hideAllCanvases,
	updateStatus,
	displayNavMessage,
	resetStatuses,
	isPlaying,
	resize,
	registerDisplay,
	registerProgress,
	currentDisplay,
	getDisplay,
	msg,
	message,
	latLonReceived,
	stopAutoRefreshTimer,
	registerRefreshData,
	timeZone,
};
