// Sky geometry for the north-up tangent-plane grid the frames are built on.

const RAD = Math.PI / 180;
const ARCSEC = 3600 / RAD;
const GAIA_EPOCH_MJD = 57388.5;

// --- Projection ---

// East and north offsets in arcsec from the field centre.
export function project(ra, dec, ra0, dec0) {
  const d = dec * RAD;
  const d0 = dec0 * RAD;
  const da = (ra - ra0) * RAD;
  const c = Math.sin(d0) * Math.sin(d) + Math.cos(d0) * Math.cos(d) * Math.cos(da);
  return [
    ((Math.cos(d) * Math.sin(da)) / c) * ARCSEC,
    ((Math.cos(d0) * Math.sin(d) - Math.sin(d0) * Math.cos(d) * Math.cos(da)) / c) * ARCSEC,
  ];
}

export function deproject(east, north, ra0, dec0) {
  const x = east / ARCSEC;
  const y = north / ARCSEC;
  const rho = Math.hypot(x, y);
  if (rho === 0) return [ra0, dec0];
  const c = Math.atan(rho);
  const d0 = dec0 * RAD;
  const dec = Math.asin(Math.cos(c) * Math.sin(d0) + (y * Math.sin(c) * Math.cos(d0)) / rho);
  const ra =
    ra0 * RAD +
    Math.atan2(x * Math.sin(c), rho * Math.cos(d0) * Math.cos(c) - y * Math.sin(d0) * Math.sin(c));
  return [(((ra / RAD) % 360) + 360) % 360, dec / RAD];
}

// Image column and row (row 0 at the top, north) for a sky position.
export function skyToImage(meta, ra, dec) {
  const [east, north] = project(ra, dec, meta.ra, meta.dec);
  const mid = (meta.size - 1) / 2;
  return [mid - east / meta.pixel_arcsec, mid - north / meta.pixel_arcsec];
}

export function imageToSky(meta, col, row) {
  const mid = (meta.size - 1) / 2;
  return deproject((mid - col) * meta.pixel_arcsec, (mid - row) * meta.pixel_arcsec, meta.ra, meta.dec);
}

// --- Proper motion ---

// Catalogue entry with pm in arcsec per year (RA term includes cos Dec).
export function positionAt(cat, mjd) {
  const years = (mjd - cat.epoch_mjd) / 365.25;
  const dec = cat.dec + (cat.pm_dec * years) / 3600;
  return [cat.ra + (cat.pm_ra * years) / 3600 / Math.cos(dec * RAD), dec];
}

// Gaia DR3 star with pm in mas per year at epoch 2016.0.
export function gaiaAt(star, mjd) {
  const years = (mjd - GAIA_EPOCH_MJD) / 365.25;
  return [
    star.ra + (star.pmra * years) / 3.6e6 / Math.cos(star.dec * RAD),
    star.dec + (star.pmdec * years) / 3.6e6,
  ];
}

// --- Formatting ---

export function formatCoord(ra, dec) {
  return `RA ${ra.toFixed(4)}  Dec ${dec >= 0 ? "+" : ""}${dec.toFixed(4)}`;
}
