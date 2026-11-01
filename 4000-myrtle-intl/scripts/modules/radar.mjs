/* eslint-disable no-param-reassign */
/* eslint-disable no-plusplus */
/* eslint-disable no-underscore-dangle */
import STATUS from './status.mjs';
import WeatherDisplay from './weatherdisplay.mjs';
import { registerDisplay } from './navigation.mjs';
import { DateTime } from '../vendor/auto/luxon.mjs';

import { getConditionText } from './utils/weather.mjs';
import { getWeatherIconFromIconLink } from './icons.mjs';
import { haversineDistance } from './utils/calc.mjs';

import ConversionHelpers from './utils/conversionHelpers.mjs';
import ExperimentalFeatures from './utils/experimental.mjs';
import RadarBoundsCities from './utils/radar-bounds-cities.mjs';
import RadarUtils from './utils/radar-utils.mjs';

class Radar extends WeatherDisplay {
	static radarSource = 'https://api.rainviewer.com/public/weather-maps.json';

	static tileSource = 'https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}';

	static defaultCityDistance = 40; 				// 40 km

	static additionalLocationBufferDistance = 10; 	// 10 km

	static radarIterationCount = 3;

	// RetroCast-style Current Radar (Troy's Oct 31 23:37 screenshot):
	// tight NC+SC coast crop — Charleston to just above Wilmington, farm
	// coast centred, ILM / MYR / CHS prominent, as in that screenshot.
	// [[south, west], [north, east]]. The view is also forced with
	// setView (zoom 7) in getData, because fitBounds alone settled on
	// zoom 6 at init time and rendered the old wide view.
	static screenshotBounds = [[32.8, -80.7], [34.9, -77.2]];

	// City codes exactly as labelled in the screenshot. Coordinates are
	// airport positions taken from this repo's own server/scripts/data/stations.js
	// (HAT = Hatteras, Mitchell Field, KHSE in that file — there is no KHAT).
	static screenshotCities = [
		{ code: 'GSP', lat: 34.88389, lon: -82.22083 },
		{ code: 'CLT', lat: 35.21333, lon: -80.94861 },
		{ code: 'FAY', lat: 34.98944, lon: -78.88 },
		{ code: 'EWN', lat: 35.0675, lon: -77.04722 },
		{ code: 'HAT', lat: 35.23222, lon: -75.6225 },
		{ code: 'FLO', lat: 34.18778, lon: -79.73083 },
		{ code: 'ILM', lat: 34.26681, lon: -77.89987 },
		{ code: 'CAE', lat: 33.94194, lon: -81.11806 },
		{ code: 'OGB', lat: 33.46389, lon: -80.85361 },
		{ code: 'MYR', lat: 33.67975, lon: -78.92833 },
		{ code: 'CHS', lat: 32.89889, lon: -80.04056 },
		{ code: 'AGS', lat: 33.36444, lon: -81.96333 },
		{ code: 'SAV', lat: 32.13137, lon: -81.20226 },
	];

	// Stylised interstate corridors, drawn as thin lines with one shield each,
	// in the positions the screenshot shows them — corridor approximations for
	// a broadcast map, NOT survey-grade highway geometry.
	static screenshotInterstates = [
		{ num: '95', shield: [34.9, -78.9], points: [[30.9, -81.7], [32.1, -81.2], [32.9, -79.9], [34.2, -79.7], [35.0, -78.9], [35.4, -78.5], [36.45, -77.65]] },
		{ num: '85', shield: [35.0, -81.3], points: [[33.5, -84.0], [34.9, -82.2], [35.2, -80.9], [36.1, -79.8], [36.0, -78.9], [36.5, -78.5]] },
		{ num: '77', shield: [35.0, -80.9], points: [[33.0, -81.0], [34.0, -81.0], [35.2, -80.85], [35.8, -80.9], [36.5, -81.0]] },
		{ num: '40', shield: [35.9, -79.9], points: [[35.6, -82.6], [35.7, -81.7], [36.1, -79.8], [35.8, -78.6], [35.4, -78.5], [34.2, -77.9]] },
		{ num: '26', shield: [34.3, -81.3], points: [[33.0, -81.9], [33.9, -81.1], [34.9, -82.0], [35.6, -82.5]] },
		{ num: '20', shield: [33.9, -80.8], points: [[33.4, -82.0], [34.0, -81.0], [34.2, -79.8]] },
	];

	constructor(navId, elemId) {
		super(navId, elemId, 'Local Radar', true);

		this.okToDrawCurrentConditions = false;
		this.okToDrawCurrentDateTime = false;

		this.radarLayers = [];
		this.mapFrames = [];
		this.animationPosition = 0;
		this.lastPastFramePosition = -1;
		this.loadingTilesCount = 0;
		this.loadedTilesCount = 0;
		this.radarData = {};
		this.locationMarker = null;

		this.radarOptions = {
			kind: 'radar',
			tileSize: 256,
			colorScheme: 4,
			smoothData: 1,
			snowColors: 1,
			extension: 'webp',
		};

		// Set max images - this will be updated when we get actual data
		this.dopplerRadarImageMax = 6;

		// Update timing for animation
		this.timing.baseDelay = 500; // 500ms per frame
		this.timing.delay = 1; // Each frame shows for 1 * baseDelay
		this.timing.totalScreens = 1; // Will be updated when data loads
	}

	// this is for the nearby cities _only_
	static getWeatherForCityFromNearestHour(cityOpenMeteoData) {
		if (!cityOpenMeteoData || !cityOpenMeteoData.time) return null;

		const now = new Date();
		const currentHour = new Date(now.getFullYear(), now.getMonth(), now.getDate(), now.getHours());

		let nearestIndex = 0;
		let smallestDiff = Infinity;

		for (let i = 0; i < cityOpenMeteoData.time.length; i++) {
			const dataTime = new Date(cityOpenMeteoData.time[i]);
			const diff = Math.abs(dataTime - currentHour);
			if (diff < smallestDiff) {
				smallestDiff = diff;
				nearestIndex = i;
			}
		}

		return {
			time: cityOpenMeteoData.time[nearestIndex],
			temperature: cityOpenMeteoData.temperature_2m[nearestIndex],
			weatherCode: cityOpenMeteoData.weather_code[nearestIndex],
		};
	}

	static createWeatherIconHTML(weatherCode, temperature, cityName, timeZone) {
		const text = getConditionText(parseInt(weatherCode, 10));
		const weatherIcon = getWeatherIconFromIconLink(text, timeZone, true);

		return `
		<div style="margin:0; padding: 0; display: flex; flex-direction: column;">
			<div class="row-1" style="display: flex; width: 100%;">
				<div style="
					text-shadow: 3px 3px 0 #000, -1.5px -1.5px 0 #000, 0 -1.5px 0 #000, 1.5px -1.5px 0 #000, 1.5px 0 0 #000, 1.5px 1.5px 0 #000, 0 1.5px 0 #000, -1.5px 1.5px 0 #000, -1.5px 0 0 #000;
					font-family: 'Star4000';
					font-size: 18pt;"
				>${cityName}</div>
			</div>
			<div class="temperature-icon" style="display: flex; align-items: center; margin-top: -14px;">
				<div style="
					padding-right: 6px;
					font-family: 'Star4000';
					text-shadow: 3px 3px 0 #000, -1.5px -1.5px 0 #000, 0 -1.5px 0 #000, 1.5px -1.5px 0 #000, 1.5px 0 0 #000, 1.5px 1.5px 0 #000, 0 1.5px 0 #000, -1.5px 1.5px 0 #000, -1.5px 0 0 #000;
					font-size: 36px;
					color: #ff0;">${Math.round(temperature)}</div>
				<img src="${weatherIcon}" alt="Weather" style="width: auto; height: 40px;" />
			</div>
		</div>
	`;
	}

	addLocationMarker(latitude, longitude, cityName, weatherData = null) {
	// Remove existing marker if it exists
		if (this.locationMarker && window._leafletMap) {
			window._leafletMap.removeLayer(this.locationMarker);
		}

		if (!window._leafletMap) {
			console.warn('Map not initialized');
			return;
		}

		let markerContent;

		if (weatherData && weatherData.icon && weatherData.temperature !== undefined) {
			markerContent = Radar.createWeatherIconHTML(
				weatherData.icon,
				weatherData.temperature,
				cityName,
				this.weatherParameters.timeZone,
			);
		} else {
			// Simple city name marker
			markerContent = `
				<div class="city-marker" style="
					background: rgba(0, 0, 0, 0.8);
					color: white;
					border-radius: 6px;
					padding: 6px 10px;
					font-family: Arial, sans-serif;
					font-size: 14px;
					font-weight: bold;
					text-align: center;
					box-shadow: 0 2px 8px rgba(0,0,0,0.3);
					border: 2px solid white;
					white-space: nowrap;
				">
					${cityName}
				</div>
			`;
		}

		const customIcon = window.L.divIcon({
			html: markerContent,
			className: 'custom-weather-marker',
			iconSize: [140, 120],
			iconAnchor: [60, 60], // Center the marker
			popupAnchor: [0, -60],
		});

		this.locationMarker = window.L.marker([latitude, longitude], {
			icon: customIcon,
			zIndexOffset: 1000, // Ensure it appears above other layers
		}).addTo(window._leafletMap);

		return this.locationMarker;
	}

	updateLocationMarker(weatherData) {
		if (!this.locationMarker || !weatherData) return;

		const markerContent = Radar.createWeatherIconHTML(
			weatherData.icon,
			ConversionHelpers.convertTemperatureUnits(weatherData.temperature),
			weatherData.cityName || 'Current Location',
			this.weatherParameters.timeZone,
		);

		const customIcon = window.L.divIcon({
			html: markerContent,
			className: 'custom-weather-marker',
			iconSize: [140, 120],
			iconAnchor: [60, 60], // Center the marker
			popupAnchor: [0, -60],
		});

		this.locationMarker.setIcon(customIcon);
	}

	isTilesLoading() {
		return this.loadingTilesCount > this.loadedTilesCount;
	}

	static removeLayer(layer) {
		if (!layer) {
			console.warn('Tried to remove a layer, but layer is undefined or null');
			return;
		}

		if (!window._leafletMap) {
			console.warn('Leaflet map is not initialized');
			return;
		}

		if (!window._leafletMap.hasLayer(layer)) {
			console.warn('Layer not found on the map:', layer);
			return;
		}

		console.log('Removing layer:', layer);
		window._leafletMap.removeLayer(layer);
	}

	// Screenshot-style overlay layers: gray county land, interstate corridors
	// with shields, and the screenshot's city codes. Stacking (Leaflet panes):
	// base Ocean tiles (200) < county fill (250) < RainViewer radar tiles (300)
	// < interstate lines / county-line overlay (400) < city + shield markers (600).
	// County fill must sit BELOW the radar tiles, or it would hide the echoes.
	// If the county file fails to load, the radar still works — no fake map.
	async addScreenshotRadarLayers() {
		if (!window._leafletMap) return;

		// Remove a previous screenshot layer group (getData can run more than once).
		if (this.screenshotLayerGroup) {
			window._leafletMap.removeLayer(this.screenshotLayerGroup);
			this.screenshotLayerGroup = null;
		}

		if (!window._leafletMap.getPane('countyPane')) {
			const countyPane = window._leafletMap.createPane('countyPane');
			countyPane.style.zIndex = 250;
		}
		if (!window._leafletMap.getPane('radarPane')) {
			const radarPane = window._leafletMap.createPane('radarPane');
			radarPane.style.zIndex = 300;
		}

		const layers = [];

		try {
			const response = await fetch('/scripts/data/nc-sc-counties.json');
			if (!response.ok) throw new Error(`county GeoJSON HTTP ${response.status}`);
			const countyData = await response.json();
			layers.push(window.L.geoJSON(countyData, {
				pane: 'countyPane',
				style: {
					fillColor: '#8a8a8a',
					fillOpacity: 1,
					color: '#c9c9c9',
					weight: 1,
					opacity: 1,
				},
				interactive: false,
			}));
		} catch (error) {
			console.warn('Screenshot radar: county layer unavailable, continuing without it:', error);
		}

		Radar.screenshotInterstates.forEach((route) => {
			layers.push(window.L.polyline(route.points, {
				color: '#e6e6e6',
				weight: 2,
				opacity: 0.9,
				interactive: false,
			}));
			layers.push(window.L.marker(route.shield, {
				icon: window.L.divIcon({
					className: 'radar-interstate-shield',
					html: `<div>${route.num}</div>`,
					iconSize: [24, 24],
					iconAnchor: [12, 12],
				}),
				interactive: false,
			}));
		});

		Radar.screenshotCities.forEach((city) => {
			layers.push(window.L.marker([city.lat, city.lon], {
				icon: window.L.divIcon({
					className: 'radar-city-code',
					html: city.code,
					iconSize: [46, 18],
					iconAnchor: [23, 9],
				}),
				interactive: false,
			}));
		});

		this.screenshotLayerGroup = window.L.layerGroup(layers);
		this.screenshotLayerGroup.addTo(window._leafletMap);
	}

	addLayer(frame) {
		if (!frame) return null;

		const tileUrl = `${this.radarData.host}${frame.path}/${this.radarOptions.tileSize}/{z}/{x}/{y}/${this.radarOptions.colorScheme}/${this.radarOptions.smoothData}_${this.radarOptions.snowColors}.${this.radarOptions.extension}`;

		// Check if layer already exists
		const existingLayer = this.radarLayers.find((layer) => layer._url && layer._url.includes(frame.path));

		if (existingLayer) {
			return existingLayer;
		}

		const source = new window.L.TileLayer(tileUrl, {
			tileSize: this.radarOptions.tileSize,
			opacity: 0, // Start invisible
			zIndex: frame.time,
			// Above the gray county fill, below city/shield markers.
			// Falls back to the default tile pane if the pane was not created.
			...(window._leafletMap.getPane('radarPane') ? { pane: 'radarPane' } : {}),
		});

		// Add event handlers for tile loading
		source.on('loading', () => {
			this.loadingTilesCount++;
		});

		source.on('load', () => {
			this.loadedTilesCount++;
		});

		source.on('tileerror', (e) => {
			console.warn('Tile failed to load:', e);
			this.loadedTilesCount++; // Count failed tiles as "loaded" to prevent infinite waiting
		});

		this.radarLayers.push(source);
		source.addTo(window._leafletMap);

		return source;
	}

	changeRadarPosition(position, preloadOnly = false, force = false) {
	// Wrap position to valid range
		while (position >= this.mapFrames.length) {
			position -= this.mapFrames.length;
		}
		while (position < 0) {
			position += this.mapFrames.length;
		}

		if (this.mapFrames.length === 0) return;

		const nextFrame = this.mapFrames[position];

		// Find or create the layer for the next frame
		let nextLayer = this.radarLayers.find((layer) => layer._url && layer._url.includes(nextFrame.path));

		if (!nextLayer) {
			nextLayer = this.addLayer(nextFrame);
		}

		// Quit if this call is for preloading only
		if (preloadOnly) {
			return;
		}

		// Don't wait for tiles if forced, or if we're not currently loading
		if (!force && this.isTilesLoading()) {
		// Set a timeout to try again
			setTimeout(() => {
				this.changeRadarPosition(position, false, true);
			}, 100);
			return;
		}

		// Hide all layers first
		this.radarLayers.forEach((layer) => {
			if (layer && layer.setOpacity) {
				layer.setOpacity(0);
			}
		});

		// Update position
		this.animationPosition = position;

		// Show the current frame
		if (nextLayer && nextLayer.setOpacity) {
			nextLayer.setOpacity(0.8);
		}

		// Update timestamp display
		this.updateTimestamp(nextFrame);
	}

	updateTimestamp(frame) {
		const timeElem = this.elem.querySelector('.time');
		if (timeElem && frame.time) {
			const frameTime = DateTime.fromSeconds(frame.time).setZone(this.weatherParameters.timeZone);
			// Screenshot shows the frame time alone ("10:30 PM"), no PAST:/FORECAST: prefix.
			const timeString = frameTime.toLocaleString(DateTime.TIME_SIMPLE);
			timeElem.innerHTML = timeString;
		}
	}

	showFrame(nextPosition, force = false) {
		if (this.mapFrames.length === 0) return;

		const preloadingDirection = nextPosition - this.animationPosition > 0 ? 1 : -1;

		this.changeRadarPosition(nextPosition, false, force);

		// Preload next frame
		const preloadPosition = (nextPosition + preloadingDirection + this.mapFrames.length) % this.mapFrames.length;
		this.changeRadarPosition(preloadPosition, true);
	}

	static async getRadarData() {
		try {
			const response = await fetch(Radar.radarSource);
			return await response.json();
		} catch (error) {
			console.error('Failed to fetch radar data:', error);
			throw error;
		}
	}

	async initializeRadar(api, kind = 'radar') {
		// Clear existing layers
		if (window._leafletMap && Array.isArray(this.radarLayers)) {
			this.radarLayers.forEach((layer) => {
				if (window._leafletMap.hasLayer(layer)) {
					window._leafletMap.removeLayer(layer);
				}
			});
		}

		// Reset state
		this.mapFrames = [];
		this.radarLayers = [];
		this.animationPosition = 0;
		this.loadingTilesCount = 0;
		this.loadedTilesCount = 0;

		if (!api) return;

		if (kind === 'satellite' && api.satellite && api.satellite.infrared) {
			this.mapFrames = api.satellite.infrared;
			this.lastPastFramePosition = api.satellite.infrared.length - 1;
		} else if (api.radar && api.radar.past) {
			this.mapFrames = Array(Radar.radarIterationCount).fill(api.radar.past).flat();
			if (api.radar.nowcast) {
				this.mapFrames = this.mapFrames.concat(api.radar.nowcast);
			}
			this.lastPastFramePosition = api.radar.past.length - 1;
		}

		// Update timing based on actual frame count
		this.timing.totalScreens = this.mapFrames.length;
		this.calcNavTiming();

		// RetroCast: LOOP the radar frames for the whole visit (Troy:
		// radar IN MOTION), instead of the engine default of playing the
		// sequence once and then holding the last frame until the
		// display dwell ends. Repeat the frame sequence 6x (~39 s at
		// 500 ms/frame, inside the 45 s display dwell); the base class
		// supports [{time, si}] delay entries, and showFrame() takes a
		// frame index, so repeated indexes loop cleanly.
		if (this.mapFrames.length > 0) {
			const seq = this.mapFrames.map((_, i) => ({ time: 1, si: i }));
			this.timing.delay = [];
			for (let r = 0; r < 6; r += 1) this.timing.delay.push(...seq);
			this.calcNavTiming();
		}

		// Show initial frame
		if (this.mapFrames.length > 0) {
			this.showFrame(this.lastPastFramePosition, true);
		}

		if (ExperimentalFeatures.getExperimentalFlag()) {
			const bounds = window._leafletMap.getBounds();
			const sw = bounds.getSouthWest();
			const ne = bounds.getNorthEast();

			const cities = await RadarBoundsCities.getBoundingBoxCities(sw.lng, sw.lat, ne.lng, ne.lat).catch((error) => {
				console.error('Error fetching bounding box cities:', error);
				return [];
			});

			// Do this so the map isn't cluttered around origin location
			const filteredCities = cities.filter((city) => {
				const distance = haversineDistance(this.weatherParameters.latitude, this.weatherParameters.longitude, parseFloat(city.lat), parseFloat(city.lon));
				return distance >= Radar.defaultCityDistance + Radar.additionalLocationBufferDistance;	// distance away from the main city
			});

			filteredCities.forEach(async (cityData) => {
				// Check if this city is not the main city and not within 30km of any other city in filteredCities
				if (
					cityData.city !== this.weatherParameters.city
					// this is a distance check to again avoid cluttering the map with too many markers
					&& !filteredCities.some(
						(other) => other !== cityData
							&& haversineDistance(
								parseFloat(cityData.lat),
								parseFloat(cityData.lon),
								parseFloat(other.lat),
								parseFloat(other.lon),
							) < Radar.defaultCityDistance,	// distance away from any other city in the filtered list
					)
				) {
					const lat = parseFloat(cityData.lat);
					const lon = parseFloat(cityData.lon);
					const name = cityData.city;

					const weatherData = await RadarBoundsCities.getWeatherForCity(lat, lon);
					const cityWeather = Radar.getWeatherForCityFromNearestHour(weatherData);

					const location = Radar.createWeatherIconHTML(
						cityWeather.weatherCode,
						cityWeather.temperature,
						name,
						this.weatherParameters.timeZone,
					);

					let latlng = window.L.latLng(lat, lon);
					const overlapArea = RadarUtils.getMaxOverlapWithMarkers(latlng);

					if (overlapArea > 0.3) {	// 30%
						latlng = RadarUtils.jitterAwayFromOverlaps(latlng);
					}

					const label = window.L.marker(latlng, {
						icon: window.L.divIcon({
							className: 'custom-weather-marker',
							html: location,
							iconSize: [140, 120],
							iconAnchor: [50, 10],
						}),
						interactive: false, // Makes sure the label doesn't block clicks
					});

					label.addTo(window._leafletMap);
				}
			});
		}
	}

	refreshCurrentFrame() {
		if (this.mapFrames.length > 0) {
			this.showFrame(this.animationPosition, true);
		}
	}

	async getData(_weatherParameters) {
		const superResult = super.getData(_weatherParameters);
		if (!superResult) return;

		const weatherParameters = _weatherParameters ?? this.weatherParameters;

		const leafletInitializationOptions = {
			zoomControl: false,
			// RetroCast framing must apply instantly: Leaflet's default
			// zoom animation left a stale zoom-7 read after setView(8).
			zoomAnimation: false,
			fadeAnimation: false,
			dragging: false,
			touchZoom: false,
			scrollWheelZoom: false,
			doubleClickZoom: false,
			boxZoom: false,
			keyboard: false,
			tap: false,
			attributionControl: false,
		};

		try {
			const mapContainer = document.getElementById('map');

			// Initialize Leaflet map if not already done — screenshot-style wide
			// NC+SC window, not a zoom-7 view centred on the farm.
			if (!mapContainer._leaflet_id) {
				window._leafletMap = window.L.map(mapContainer, leafletInitializationOptions)
					.fitBounds(Radar.screenshotBounds);

				window.L.tileLayer(Radar.tileSource, {
					attribution: 'Tiles &copy; Esri &mdash; Sources: GEBCO, NOAA, CHS, OSU, UNH, CSUMB, National Geographic, DeLorme, NAVTEQ, and Esri',
				}).addTo(window._leafletMap);
			} else {
				window._leafletMap.fitBounds(Radar.screenshotBounds);
			}
			// RetroCast framing: force the tight coast view (farm coast
			// centred, zoom 8) — fitBounds alone rendered zoom 6 wide.
			window._leafletMap.invalidateSize();
			window._leafletMap.setView([33.58, -78.95], 7);

			// County fill, interstate corridors/shields, and city codes.
			// Runs before the RainViewer tiles load so the radar pane exists.
			await this.addScreenshotRadarLayers();

			// Get radar data
			this.radarData = await Radar.getRadarData();
			await this.initializeRadar(this.radarData, 'radar');

			const todayKey = DateTime.now().setZone(weatherParameters.timeZone).toFormat('yyyy-MM-dd');

			const currentWeatherData = {
				icon: weatherParameters.forecast[todayKey].weather_code,
				temperature: weatherParameters.Temperature,
				city: weatherParameters.city,
			};

			// RetroCast screenshot has city codes only — no farm weather
			// marker over the map — so do not draw one here (Troy Oct 31).
			// (currentWeatherData kept for a future non-radar use.)
			void currentWeatherData;

			this.setStatus(STATUS.loaded);
		} catch (error) {
			console.error('Failed to initialize radar:', error);
			this.setStatus(STATUS.failed);
		}
	}

	// Handle screen index changes from base class navigation
	screenIndexChange(screenIndex) {
		if (this.mapFrames.length > 0) {
			this.showFrame(screenIndex);
		}
	}

	async drawCanvas() {
		super.drawCanvas();

		// Update the display if we have frames
		if (this.mapFrames.length > 0) {
			this.showFrame(this.screenIndex);
		}

		this.finishDraw();
	}
}

registerDisplay(new Radar(10, 'radar'));
