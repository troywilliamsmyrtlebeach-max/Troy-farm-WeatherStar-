import { elemForEach } from './utils/elem.mjs';
import getCurrentWeather from './currentweather.mjs';
import { currentDisplay, getDisplay } from './navigation.mjs';
import { getConditionText } from './utils/weather.mjs';
import ConversionHelpers from './utils/conversionHelpers.mjs';

// constants
const degree = String.fromCharCode(176);

// local variables
let interval;
let screenIndex = 0;

// start drawing conditions
// reset starts from the first item in the text scroll list
const start = () => {
	// store see if the context is new

	// set up the interval if needed
	if (!interval) {
		// v=21 TICKER-SPEED (Troy 2026-11-08: "Can you make my conditions
		// change quicker... its like it was taking its time awhile ago" — on the
		// bottom ticker). Was 12000ms per frame (12s each, 96s for a full
		// 8-frame cycle — that's the "taking its time"). Now 2000ms per
		// frame (2s each, 16s for the full cycle), so the conditions change
		// quicker. Still readable: the wipe is only 0.2s, so each frame sits
		// fully visible for ~1.8s. Still cycles, never scrolls; every frame
		// still shows; red-alert crawl untouched.
		interval = setInterval(incrementInterval, 2000);
	}

	// draw the data
	drawScreen();
};

const stop = (reset) => {
	if (reset) screenIndex = 0;
};

// increment interval, roll over
const incrementInterval = () => {
	// test current screen
	const display = currentDisplay();
	if (!display?.okToDrawCurrentConditions) {
		stop(display?.elemId === 'progress');
		return;
	}
	screenIndex = (screenIndex + 1) % (screens.length);
	// draw new text
	drawScreen();
};

// When the farm's own station data is available, the ticker cycles through
// THAT, not the Carolina Shores locality model — so the bottom ticker on
// every screen, including the PWS screen, reads from KNCCAROL120.
const pwsTickerData = () => {
	const cw = getDisplay(13)?.weatherParameters?.customWeather;
	if (!cw) return null;
	return {
		city: 'CALABASH-FARM AT BRUNSWICK',
		TextConditions: cw.conditionText,
		Temperature: ConversionHelpers.convertTemperatureUnits(cw.temperature),
		TemperatureUnit: ConversionHelpers.getTemperatureUnitText(),
		// Troy 2026-11-07: the ticker cycles Temp + Feels Like (one frame) and Rainfall Today.
		FeelsLike: ConversionHelpers.convertTemperatureUnits(cw.feelsLike ?? cw.temperature),
		RainToday: (cw.rainTodayIn ?? null),
		Humidity: Math.round(cw.humidity),
		DewPoint: ConversionHelpers.convertTemperatureUnits(cw.dewPoint),
		Pressure: ConversionHelpers.convertPressureUnits(cw.pressure).toFixed(2),
		PressureUnit: ConversionHelpers.getPressureUnitText(),
		WindDirection: cw.windDirection,
		WindSpeed: Math.round(ConversionHelpers.convertWindUnits(cw.windSpeed)),
		WindGust: cw.windGust ? Math.round(ConversionHelpers.convertWindUnits(cw.windGust)) : 0,
		WindUnit: ConversionHelpers.getWindUnitText(),
		Visibility: Math.min(10, ConversionHelpers.convertDistanceUnits(cw.visibility)),
		VisibilityUnit: ConversionHelpers.getDistanceUnitText(),
		Ceiling: 0,
		CeilingUnit: ConversionHelpers.getDistanceUnitText(),
	};
};

const drawScreen = async () => {
	// Severe alert mode: the ticker carries the watch/warning instead of conditions.
	if (alertActive) {
		drawAlertTicker();
		return;
	}

	// get the conditions
	const data = pwsTickerData() ?? await getCurrentWeather();

	// nothing to do if there's no data yet
	if (!data) return;

	// Skip frames that return null (e.g. rainfall when the data has no rain figure).
	for (let tries = 0; tries < screens.length; tries++) {
		const text = screens[screenIndex](data);
		if (text) {
			drawCondition(text);
			return;
		}
		screenIndex = (screenIndex + 1) % screens.length;
	}
};

// the "screens" are stored in an array for easy addition and removal
const screens = [
	// station name
	(data) => {
		let sanitizedText = 'CONDITIONS AT ';
		// Troy's farm name is long on purpose — never truncate it.
		// Troy 2026-10-27: label is all caps, at the left bottom edge.
		if (data.city === 'CALABASH-FARM AT BRUNSWICK') {
			return 'CONDITIONS AT CALABASH-FARM AT BRUNSWICK';
		}
		// Typically an airport with "International" at the second position
		if (data.city.split(' ').length > 2 && data.city.split(' ')[1].toLowerCase() === 'international') {
			sanitizedText += `${data.city.split(' ')[0]} Intl. ${data.city.split(' ')[2]} `;
		// or a very long city name...this will
		// truncate very long airports too, like
		// "John F. Kennedy International Airport"
		} else if (data.city.length > 20) {
			sanitizedText += `${data.city.slice(0, 18)}...`;
		} else {
			sanitizedText += `${data.city} `;
		}
		return sanitizedText;
	},

	// condition — Troy 2026-10-31: sky condition as its own ticker frame,
	// labelled SKY so it cannot be mistaken for another reading. All caps
	// is applied by drawCondition. Farm data: FOG on Oct 31 01:56 AM.
	// Troy 2026-10-31: ticker reads just the sky condition itself, no SKY label — same as the main page.
	(data) => `${getConditionText(data.TextConditions)}`,

	// temperature + feels-like (Troy 2026-11-07: one frame, both numbers)
	(data) => {
		const feels = data.FeelsLike ?? data.Temperature;
		return `Temp: ${data.Temperature}${degree}${data.TemperatureUnit}   Feels Like: ${feels}${degree}${data.TemperatureUnit}`;
	},

	// humidity
	(data) => `Humidity: ${data.Humidity}%   Dewpoint: ${data.DewPoint}${degree}${data.TemperatureUnit}`,

	// barometric pressure — Troy 2026-10-26 evening: say "Barometric Pressure", not just "Pressure", with just the letter R / S / F beside the number
	(data) => {
		let letter = 'S';
		if (data.PressureDirection === 'rising') letter = 'R';
		else if (data.PressureDirection === 'falling') letter = 'F';
		else {
			try {
				const t = window.localStorage.getItem('pwsPressureTrend');
				if (t === 'rising') letter = 'R';
				else if (t === 'falling') letter = 'F';
			} catch (e) { /* keep S */ }
		}
		return `Barometric Pressure ${data.Pressure} ${letter}`;
	},

	// wind
	(data) => {
		let text = data.WindSpeed > 0
			? `Wind: ${data.WindDirection} ${data.WindSpeed} ${data.WindUnit}`
			: 'Wind: Calm';

		if (data.WindGust > 0) {
			text += `   Gusts to ${data.WindGust}`;
		}
		return text;
	},

	// visibility
	(data) => {
		const distance = `${data.Ceiling} ${data.CeilingUnit}`;
		return `Visib: ${data.Visibility} ${data.VisibilityUnit}   Ceiling: ${data.Ceiling === 0 ? 'Unlimited' : distance}`;
	},

	// rainfall today (farm rain gauge) — Troy 2026-11-07. Only when the data
	// has a rain figure (farm PWS path); skipped otherwise (returns null).
	(data) => {
		if (data.RainToday === undefined || data.RainToday === null) return null;
		return `Rainfall Today: ${Number(data.RainToday).toFixed(2)} in`;
	},
];

// internal draw function with preset parameters
const drawCondition = (text) => {
	elemForEach('.weather-display .scroll .fixed', (elem) => {
		// Remove old text-layers with exit
		const layers = elem.querySelectorAll('.text-layer');
		layers.forEach((layer) => {
			layer.classList.remove('active');
			layer.classList.add('exit');
			layer.addEventListener('transitionend', () => {
				layer.remove();
			}, { once: true });
		});

		// Create new layer with wrapped content
		const newLayer = document.createElement('div');
		newLayer.className = 'text-layer';
		const content = document.createElement('div');
		content.className = 'text-content';
		// v=20 TICKER-SIZE (Troy 2026-11-08: "Where it says rain fall today
		// on the bottom ticker make all the words on the current conditions
		// match that size on the ticker" — and "even conditions at
		// CALABASH-FARM AT BRUNSWICK and visib 10 mi ceiling unlimited").
		// The RAINFALL TODAY frame is the reference size (24pt, the CSS base
		// for .text-content). Every frame now renders at that same 24pt —
		// CONDITIONS AT CALABASH-FARM AT BRUNSWICK, VISIB 10 MI CEILING
		// UNLIMITED, and all the rest — no length-based shrink, so the ticker
		// text never changes size as it cycles. The old shrink (18pt for
		// text > 32 chars) is gone. Measured live 2026-11-08: the longest
		// frame (CONDITIONS, 40 chars) is ~608px at 24pt in the Star4000
		// font vs the 640px ticker bar, so it fits fully visible; VISIB is
		// ~472px. The red alert crawl already uses 24pt and is untouched.
		// Troy 2026-10-27: every ticker reading in capital letters.
		content.textContent = text.toUpperCase();
		newLayer.appendChild(content);
		elem.appendChild(newLayer);

		// Force reflow
		// eslint-disable-next-line no-void
		void newLayer.offsetWidth;

		// Trigger wipe
		newLayer.classList.add('active');
	});
};

// ---------------------------------------------------------------------------
// SEVERE WEATHER ALERT MODE (Troy 2026-11-07)
// Two DIFFERENT red screens, kept separate:
//   (1) the MAIN screen (top of the panel) goes red and scrolls the warning
//       text UP (vertically), like the classic WeatherStar alert screen;
//   (2) the BOTTOM ticker goes red and scrolls the watch/warning SIDEWAYS
//       (left-to-right crawl), like the classic severe weather crawl.
// Normal mode: the navy ticker cycles his current farm conditions and NEVER
// scrolls. When the alert ends, both red screens go away and the navy
// cycling ticker comes back. Only a severe watch/warning for the farm
// triggers this (tornado, severe thunderstorm, flood, flash flood,
// hurricane, tropical storm, storm surge, extreme wind).
// ---------------------------------------------------------------------------
const ALERT_KEYWORDS = ['Tornado', 'Severe Thunderstorm', 'Flash Flood', 'Flood', 'Hurricane', 'Tropical Storm', 'Storm Surge', 'Extreme Wind'];
const ALERT_CHECK_MS = 5 * 60 * 1000; // re-check NWS every 5 minutes
const ALERT_CRAWL_PX_PER_SEC = 120; // sideways ticker crawl speed
const ALERT_SCROLL_PX_PER_SEC = 40; // upward main-screen scroll speed
let alertActive = false;
let activeAlerts = [];
let alertMainEl = null;
let alertScrollAnim = null;

const isSevereAlert = (event) => {
	if (!event) return false;
	// watches and warnings only — advisories and statements do not trigger it
	if (!/(Watch|Warning)$/.test(event)) return false;
	return ALERT_KEYWORDS.some((k) => event.includes(k));
};

const alertScore = (f) => {
	const p = f.properties || {};
	const sev = { Extreme: 4, Severe: 3, Moderate: 2, Minor: 1 }[p.severity] || 0;
	const pri = {
		Tornado: 100, 'Severe Thunderstorm': 90, 'Flash Flood': 80, Hurricane: 70, 'Tropical Storm': 60, 'Storm Surge': 50, 'Extreme Wind': 40, Flood: 30,
	};
	let best = 0;
	Object.keys(pri).forEach((k) => { if ((p.event || '').includes(k)) best = Math.max(best, pri[k]); });
	return sev * 1000 + best + (/Warning$/.test(p.event || '') ? 10 : 0);
};

const alertHeadline = (f) => {
	const p = f.properties || {};
	const text = p.headline || `${p.event || 'Severe weather'} — ${p.areaDesc || ''}`;
	return text.replace(/\s+/g, ' ').trim();
};

// Red-screen CSS (injected once): the red ticker band (html.farm-alert turns
// every .scroll band red) and the main red screen overlay.
const injectAlertStyles = () => {
	if (document.getElementById('farm-alert-styles')) return;
	const style = document.createElement('style');
	style.id = 'farm-alert-styles';
	style.textContent = `
/* ALERT MODE (Troy 2026-11-07): two separate red screens. */
html.farm-alert .weather-display .scroll,
html.farm-alert .weather-display .scroll .fixed,
html.farm-alert .weather-display .scroll .fixed .text-layer,
html.farm-alert .weather-display .scroll .fixed .text-content { background: #e60000 !important; }
#farm-alert-main { position: absolute; left: 0; top: 0; width: 100%; background: #e60000; color: #fff; z-index: 9999; display: none; overflow: hidden; font-family: "Star4000", monospace; text-shadow: 2px 2px 0 #000; }
#farm-alert-main.on { display: block; }
#farm-alert-main .fam-header { position: absolute; top: 0; left: 0; right: 0; height: 64px; display: flex; align-items: center; justify-content: center; background: #b30000; border-bottom: 3px solid #fff; font-size: 34px; font-weight: 900; letter-spacing: 1px; text-align: center; }
#farm-alert-main .fam-viewport { position: absolute; top: 64px; left: 0; right: 0; bottom: 0; overflow: hidden; padding: 0 18px; }
#farm-alert-main .fam-scroll { font-size: 22px; line-height: 30px; }
#farm-alert-main .fam-event { font-size: 26px; font-weight: 900; color: #ffe600; margin: 16px 0 6px; }
#farm-alert-main .fam-headline { font-weight: 700; margin-bottom: 10px; }
#farm-alert-main .fam-body p { margin: 0 0 10px; }
`;
	document.head.appendChild(style);
};

// Main red screen (top of the panel): event header + warning text scrolling UP.
const ensureAlertMain = () => {
	if (alertMainEl) return alertMainEl;
	const container = document.querySelector('#divTwc #container') || document.getElementById('container');
	if (!container) return null;
	const el = document.createElement('div');
	el.id = 'farm-alert-main';
	el.innerHTML = '<div class="fam-header"></div><div class="fam-viewport"><div class="fam-scroll"></div></div>';
	container.appendChild(el);
	alertMainEl = el;
	return el;
};

const showAlertMain = () => {
	const el = ensureAlertMain();
	if (!el) return;
	const container = document.querySelector('#divTwc #container') || document.getElementById('container');
	const tickerEl = document.querySelector('.weather-display .scroll');
	// Cover the panel down to the ticker band (ticker stays its own red screen below).
	const tickerH = tickerEl ? tickerEl.offsetHeight + 10 : 80;
	el.style.height = `${Math.max(0, (container ? container.clientHeight : 480) - tickerH)}px`;
	const top = activeAlerts[0];
	el.querySelector('.fam-header').textContent = ((top && top.properties && top.properties.event) || 'SEVERE WEATHER').toUpperCase();
	const scroll = el.querySelector('.fam-scroll');
	scroll.innerHTML = activeAlerts.map((f) => {
		const p = f.properties || {};
		const desc = (p.description || '').replace(/\n\n+/g, '</p><p>').replace(/\n/g, ' ');
		const inst = p.instruction
			? `<p><strong>WHAT TO DO:</strong> ${p.instruction.replace(/\n\n+/g, '</p><p>').replace(/\n/g, ' ')}</p>`
			: '';
		return `<div class="fam-event">${(p.event || '').toUpperCase()}</div><div class="fam-headline">${alertHeadline(f)}</div><div class="fam-body"><p>${desc}</p>${inst}</div>`;
	}).join('');
	el.classList.add('on');
	// Scroll the warning text UP: from just below the viewport to fully above it.
	const viewport = el.querySelector('.fam-viewport');
	const vpH = viewport.clientHeight;
	const contentH = scroll.scrollHeight;
	if (alertScrollAnim) alertScrollAnim.cancel();
	alertScrollAnim = scroll.animate(
		[{ transform: `translateY(${vpH}px)` }, { transform: `translateY(${-contentH}px)` }],
		{ duration: Math.max(20000, ((vpH + contentH) / ALERT_SCROLL_PX_PER_SEC) * 1000), iterations: Infinity },
	);
};

const hideAlertMain = () => {
	if (alertScrollAnim) {
		alertScrollAnim.cancel();
		alertScrollAnim = null;
	}
	if (alertMainEl) alertMainEl.classList.remove('on');
};

// Bottom ticker red screen: the watch/warning crawls SIDEWAYS across the red ticker band.
const restartCrawl = (content) => {
	if (content._farmAnim) content._farmAnim.cancel();
	const oneCopyW = Math.max(640, Math.ceil(content.scrollWidth / 2));
	content._farmAnim = content.animate(
		[{ transform: 'translateX(0)' }, { transform: `translateX(${-oneCopyW}px)` }],
		{ duration: (oneCopyW / ALERT_CRAWL_PX_PER_SEC) * 1000, iterations: Infinity },
	);
};

const drawAlertTicker = () => {
	document.documentElement.classList.add('farm-alert');
	const crawlText = activeAlerts.map(alertHeadline).join('   \u2022\u2022\u2022   ').toUpperCase();
	elemForEach('.weather-display .scroll .fixed', (elem) => {
		let layer = elem.querySelector('.farm-alert-crawl-layer');
		if (!layer) {
			elem.querySelectorAll('.text-layer').forEach((l) => l.remove());
			layer = document.createElement('div');
			layer.className = 'text-layer farm-alert-crawl-layer';
			layer.style.textAlign = 'left';
			const content = document.createElement('div');
			content.className = 'text-content farm-alert-crawl';
			content.style.whiteSpace = 'nowrap';
			content.style.textAlign = 'left';
			content.style.fontSize = '24pt';
			// .text-content is clip-path hidden until its layer is .active
			content.style.clipPath = 'inset(0 0% 0 0)';
			layer.appendChild(content);
			elem.appendChild(layer);
			layer.classList.add('active');
		}
		const content = layer.querySelector('.farm-alert-crawl');
		const doubled = `${crawlText}   \u2022\u2022\u2022   ${crawlText}`;
		if (content.textContent !== doubled) {
			content.textContent = doubled;
			restartCrawl(content);
		}
	});
};

const clearAlertTicker = () => {
	document.documentElement.classList.remove('farm-alert');
	document.querySelectorAll('.farm-alert-crawl').forEach((c) => {
		if (c._farmAnim) c._farmAnim.cancel();
	});
	document.querySelectorAll('.farm-alert-crawl-layer').forEach((l) => l.remove());
};

// NWS alerts for the farm point, filtered to Troy's severe watch/warning list.
const checkAlerts = async () => {
	let feats = null;
	try {
		const p = getDisplay(13)?.weatherParameters;
		const lat = p?.latitude ?? 33.92;
		const lon = p?.longitude ?? -78.57;
		const res = await fetch(`https://api.weather.gov/alerts/active?point=${lat},${lon}&limit=10`, { headers: { Accept: 'application/geo+json' } });
		if (!res.ok) throw new Error(`alerts HTTP ${res.status}`);
		const data = await res.json();
		feats = (data.features || []).filter((f) => isSevereAlert(f.properties?.event));
	} catch (e) {
		// Transient failure: keep the last known state (never flash the alert off/on).
		console.warn('farm alert check failed (keeping last state):', e);
		return;
	}
	feats.sort((a, b) => alertScore(b) - alertScore(a));
	const key = feats.map((f) => f.id).join('|');
	const prevKey = activeAlerts.map((f) => f.id).join('|');
	if (key === prevKey) return; // no change
	activeAlerts = feats;
	alertActive = feats.length > 0;
	if (alertActive) {
		showAlertMain();
		drawAlertTicker();
	} else {
		hideAlertMain();
		clearAlertTicker();
		screenIndex = 0;
		drawScreen();
	}
};

document.addEventListener('DOMContentLoaded', () => {
	start();
	injectAlertStyles();
	// Test hooks (console only): render the red screens with fake alerts, or clear them.
	// e.g. window.__farmAlertShow([{id:'t1',properties:{event:'Tornado Warning',severity:'Extreme',headline:'Tornado Warning issued...',description:'...',instruction:'...',areaDesc:'Brunswick County'}}])
	window.__farmAlertShow = (fake) => {
		activeAlerts = fake || [];
		alertActive = activeAlerts.length > 0;
		if (alertActive) {
			showAlertMain();
			drawAlertTicker();
		}
	};
	window.__farmAlertHide = () => {
		activeAlerts = [];
		alertActive = false;
		hideAlertMain();
		clearAlertTicker();
		screenIndex = 0;
		drawScreen();
	};
	setTimeout(checkAlerts, 8000);
	setInterval(checkAlerts, ALERT_CHECK_MS);
});
