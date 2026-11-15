"""Brown dwarf score from proper motion, colour and a methane index.

This is a score, not an identification. It counts how many of three features
look like a cold brown dwarf when compared with ordinary stars measured in
the same images. Settings live here so no other module changes.
"""

import numpy as np
from astropy.wcs import WCS

# --- Settings ---

LABEL = "Brown dwarf score (a score, not an identification)"

# Wavelength bands in microns
METHANE_BAND = (3.15, 3.45)
CONTINUUM_BAND = (3.9, 4.2)
SHORT_BAND = (2.45, 2.95)

# Photometry on the 3 arcsec grid: a 21 arcsec box, sky from a ring around it
BOX_HALF = 3
RING_INNER = 8
RING_OUTER = 12
MIN_FINITE = 0.8
MIN_POINTS = 3

# A feature counts when it sits this many sigma from the field stars
FEATURE_SIGMA = 3.0
MOTION_SIGMA = 5.0
# Faster than this is a solar-system object, not a star or brown dwarf
MAX_STELLAR_RATE_ARCSEC_YR = 15.0


# --- Photometry ---


def box_flux(frame: dict, x: float, y: float) -> tuple[float, float] | None:
    """Sky-subtracted box sum and the wavelength at a grid position."""
    image = frame["image"]
    xi, yi = int(round(x)), int(round(y))
    size = image.shape[0]
    if not (
        RING_OUTER <= xi < size - RING_OUTER and RING_OUTER <= yi < size - RING_OUTER
    ):
        return None
    box = image[yi - BOX_HALF : yi + BOX_HALF + 1, xi - BOX_HALF : xi + BOX_HALF + 1]
    if np.isfinite(box).mean() < MIN_FINITE:
        return None
    patch = image[
        yi - RING_OUTER : yi + RING_OUTER + 1, xi - RING_OUTER : xi + RING_OUTER + 1
    ]
    yy, xx = np.mgrid[-RING_OUTER : RING_OUTER + 1, -RING_OUTER : RING_OUTER + 1]
    ring = patch[np.maximum(np.abs(xx), np.abs(yy)) >= RING_INNER]
    if np.isfinite(ring).sum() < 20:
        return None
    sky = np.nanmedian(ring)
    wave = np.nanmedian(frame["wavelength"][yi - 1 : yi + 2, xi - 1 : xi + 2])
    if not np.isfinite(wave):
        return None
    return float(np.nansum(box - sky)), float(wave)


def measure_points(field_frames: list[dict], grid: WCS, position) -> np.ndarray:
    """(wavelength, flux) per exposure. position(mjd) returns RA and Dec."""
    points = []
    for frame in field_frames:
        ra, dec = position(frame["mjd"])
        x, y = (float(v) for v in grid.all_world2pix(ra, dec, 0))
        got = box_flux(frame, x, y)
        if got:
            points.append((got[1], got[0]))
    return np.array(points).reshape(-1, 2)


def band_flux(points: np.ndarray, band: tuple[float, float]) -> dict | None:
    """Median flux in a band with its error from the scatter between exposures."""
    inside = points[(points[:, 0] >= band[0]) & (points[:, 0] <= band[1]), 1]
    if len(inside) < MIN_POINTS:
        return None
    median = float(np.median(inside))
    spread = 1.4826 * float(np.median(np.abs(inside - median)))
    return {
        "flux": median,
        "err": 1.25 * spread / np.sqrt(len(inside)),
        "n": len(inside),
    }


def flux_ratio(top: dict | None, bottom: dict | None) -> dict | None:
    """top / bottom with its error. None unless the bottom band is detected."""
    if top is None or bottom is None or bottom["flux"] <= 3 * bottom["err"]:
        return None
    value = top["flux"] / bottom["flux"]
    err = np.hypot(top["err"], value * bottom["err"]) / bottom["flux"]
    return {"value": float(value), "err": float(err)}


def band_fluxes(points: np.ndarray, sky: dict | None = None) -> dict:
    """Median flux in the three bands. sky, if given, holds the blank-sky
    offset and scatter per band; the offset is removed and the scatter added."""
    bands = {
        "methane": band_flux(points, METHANE_BAND),
        "continuum": band_flux(points, CONTINUUM_BAND),
        "short": band_flux(points, SHORT_BAND),
    }
    for name, band in bands.items():
        blank = (sky or {}).get(name)
        if band and blank:
            band["flux"] -= blank["median"]
            band["err"] = float(np.hypot(band["err"], blank["sigma"]))
    return bands


def spectral_features(points: np.ndarray, sky: dict | None = None) -> dict:
    """Methane index (lower means more methane) and short-to-long colour."""
    bands = band_fluxes(points, sky)
    return {
        "bands": bands,
        "methane_index": flux_ratio(bands["methane"], bands["continuum"]),
        # Inverted so a source too faint to see at the short end still gets a value
        "short_over_long": flux_ratio(bands["short"], bands["continuum"]),
    }


# --- Comparison with field stars ---


def star_reference(values: list[float]) -> dict | None:
    """Median and robust scatter of a feature over the field stars."""
    if len(values) < 5:
        return None
    values = np.array(values)
    median = float(np.median(values))
    return {
        "median": median,
        "sigma": 1.4826 * float(np.median(np.abs(values - median))),
        "n": len(values),
    }


def sigma_below(feature: dict | None, reference: dict | None) -> float | None:
    """How many sigma a feature sits below the field-star median."""
    if feature is None or reference is None:
        return None
    spread = np.hypot(feature["err"], reference["sigma"])
    return float((reference["median"] - feature["value"]) / spread) if spread else None


# --- Score ---


def score(
    rate_arcsec_yr: float | None,
    rate_err_arcsec_yr: float | None,
    methane_sigma: float | None,
    colour_sigma: float | None,
) -> dict:
    """Count the features that look like a cold brown dwarf, 0 to 3."""
    motion = bool(
        rate_arcsec_yr is not None
        and rate_err_arcsec_yr
        and rate_arcsec_yr / rate_err_arcsec_yr >= MOTION_SIGMA
    )
    too_fast = bool(
        rate_arcsec_yr is not None and rate_arcsec_yr > MAX_STELLAR_RATE_ARCSEC_YR
    )
    features = {
        "moves_like_a_nearby_star": motion and not too_fast,
        "methane_absorption": methane_sigma is not None
        and methane_sigma >= FEATURE_SIGMA,
        "red_colour": colour_sigma is not None and colour_sigma >= FEATURE_SIGMA,
    }
    total = 0 if too_fast else sum(features.values())
    note = ""
    if too_fast:
        note = "Moves far too fast for a star or brown dwarf: a solar-system object."
    return {
        "label": LABEL,
        "score": int(total),
        "out_of": 3,
        "features": {k: bool(v) for k, v in features.items()},
        "features_measured": 1
        + (methane_sigma is not None)
        + (colour_sigma is not None),
        "note": note,
    }
