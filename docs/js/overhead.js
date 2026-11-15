// Zenith position for a place and time, computed in the browser so the exact
// location never leaves the device. Same result as backend/app/overhead.py.

const RAD = Math.PI / 180;
const ARCSEC = RAD / 3600;
export const FIELD_STEP_DEG = 0.2;

// --- Zenith ---

// Greenwich mean sidereal time in degrees (Meeus, Astronomical Algorithms 12.4).
function gmstDegrees(jd) {
  const t = (jd - 2451545.0) / 36525;
  const gmst = 280.46061837 + 360.98564736629 * (jd - 2451545.0) + 0.000387933 * t * t - (t * t * t) / 38710000;
  return ((gmst % 360) + 360) % 360;
}

// Rotate a position of date back to J2000 (IAU 1976 precession angles).
function toJ2000(ra, dec, jd) {
  const t = (jd - 2451545.0) / 36525;
  const zeta = (2306.2181 * t + 0.30188 * t * t + 0.017998 * t * t * t) * ARCSEC;
  const z = (2306.2181 * t + 1.09468 * t * t + 0.018203 * t * t * t) * ARCSEC;
  const theta = (2004.3109 * t - 0.42665 * t * t - 0.041833 * t * t * t) * ARCSEC;
  const [cz, sz] = [Math.cos(zeta), Math.sin(zeta)];
  const [cZ, sZ] = [Math.cos(z), Math.sin(z)];
  const [ct, st] = [Math.cos(theta), Math.sin(theta)];
  // Matrix that takes J2000 to date; its transpose takes date to J2000
  const p = [
    [cz * ct * cZ - sz * sZ, -sz * ct * cZ - cz * sZ, -st * cZ],
    [cz * ct * sZ + sz * cZ, -sz * ct * sZ + cz * cZ, -st * sZ],
    [cz * st, -sz * st, ct],
  ];
  const v = [
    Math.cos(dec * RAD) * Math.cos(ra * RAD),
    Math.cos(dec * RAD) * Math.sin(ra * RAD),
    Math.sin(dec * RAD),
  ];
  const x = p[0][0] * v[0] + p[1][0] * v[1] + p[2][0] * v[2];
  const y = p[0][1] * v[0] + p[1][1] * v[1] + p[2][1] * v[2];
  const w = p[0][2] * v[0] + p[1][2] * v[1] + p[2][2] * v[2];
  return [((Math.atan2(y, x) / RAD) % 360 + 360) % 360, Math.asin(w) / RAD];
}

// RA and Dec (J2000) straight overhead. Of date, RA is the local sidereal
// time and Dec is the latitude; precession then moves it by about 0.4 degrees.
export function zenith(latDeg, lonDeg, date) {
  const jd = date.getTime() / 86400000 + 2440587.5;
  const lst = (((gmstDegrees(jd) + lonDeg) % 360) + 360) % 360;
  return toJ2000(lst, latDeg, jd);
}

// Snap to the field grid so only a coarse sky patch is ever used or sent.
export function fieldCentre(ra, dec) {
  const decC = Math.round(dec / FIELD_STEP_DEG) * FIELD_STEP_DEG;
  const raStep = FIELD_STEP_DEG / Math.max(Math.cos(decC * RAD), 0.05);
  const raC = (((Math.round(ra / raStep) * raStep) % 360) + 360) % 360;
  return [Number(raC.toFixed(4)), Number(decC.toFixed(4))];
}

// --- Places ---

// Latitude and longitude in degrees, east positive.
const CITIES = {
  singapore: [1.3521, 103.8198],
  "kuala lumpur": [3.139, 101.6869],
  jakarta: [-6.2088, 106.8456],
  bangkok: [13.7563, 100.5018],
  manila: [14.5995, 120.9842],
  hanoi: [21.0278, 105.8342],
  "hong kong": [22.3193, 114.1694],
  taipei: [25.033, 121.5654],
  tokyo: [35.6762, 139.6503],
  seoul: [37.5665, 126.978],
  beijing: [39.9042, 116.4074],
  shanghai: [31.2304, 121.4737],
  delhi: [28.6139, 77.209],
  mumbai: [19.076, 72.8777],
  dubai: [25.2048, 55.2708],
  istanbul: [41.0082, 28.9784],
  cairo: [30.0444, 31.2357],
  nairobi: [-1.2921, 36.8219],
  lagos: [6.5244, 3.3792],
  johannesburg: [-26.2041, 28.0473],
  london: [51.5074, -0.1278],
  paris: [48.8566, 2.3522],
  berlin: [52.52, 13.405],
  madrid: [40.4168, -3.7038],
  rome: [41.9028, 12.4964],
  "new york": [40.7128, -74.006],
  "los angeles": [34.0522, -118.2437],
  chicago: [41.8781, -87.6298],
  flagstaff: [35.1983, -111.6513],
  "mexico city": [19.4326, -99.1332],
  "sao paulo": [-23.5505, -46.6333],
  "buenos aires": [-34.6037, -58.3816],
  sydney: [-33.8688, 151.2093],
  auckland: [-36.8485, 174.7633],
};

// Accepts "lat, lon" or a city from the list. Returns null if not understood.
export function parsePlace(text) {
  const clean = text.trim().toLowerCase();
  const numbers = clean.match(/^(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)$/);
  if (numbers) {
    const lat = parseFloat(numbers[1]);
    const lon = parseFloat(numbers[2]);
    if (Math.abs(lat) <= 90 && Math.abs(lon) <= 360) return { lat, lon, label: "that place" };
    return null;
  }
  const name = Object.keys(CITIES).find((city) => city === clean) || Object.keys(CITIES).find((city) => clean && city.startsWith(clean));
  if (!name) return null;
  const label = name.replace(/\b\w/g, (c) => c.toUpperCase());
  return { lat: CITIES[name][0], lon: CITIES[name][1], label };
}
