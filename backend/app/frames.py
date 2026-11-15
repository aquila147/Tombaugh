"""Cleaning, Gaia alignment, reprojection, visit stacking and target motion."""

import logging
import warnings

import numpy as np
from astropy.coordinates import get_body_barycentric
from astropy.time import Time
from astropy.wcs import WCS
from scipy.ndimage import map_coordinates

from app import archive, catalogs, config, flags

log = logging.getLogger("tombaugh.frames")

# --- Cleaning ---


def measure_noise(image: np.ndarray) -> float:
    """Robust scatter measured from the image itself, not the VARIANCE plane."""
    good = image[np.isfinite(image)]
    if good.size == 0:
        return float("nan")
    return float(1.4826 * np.median(np.abs(good - np.median(good))))


def clean_image(cutout: dict) -> np.ndarray:
    """Subtract ZODI and the leftover median background; bad pixels become NaN."""
    image = cutout["image"] - cutout["zodi"]
    bad = flags.bad_pixel_mask(cutout["flags"], cutout["flags_header"])
    image[bad | ~np.isfinite(image)] = np.nan
    if np.isfinite(image).any():
        image -= np.nanmedian(image)
    return image


# --- Visits ---


def group_visits(products: list[dict]) -> list[list[dict]]:
    """Split time-sorted products into visits wherever the gap is long."""
    gap_days = config.VISIT_GAP_HOURS / 24.0
    visits: list[list[dict]] = []
    for p in sorted(products, key=lambda p: p["mjd"]):
        if visits and p["mjd"] - visits[-1][-1]["mjd"] <= gap_days:
            visits[-1].append(p)
        else:
            visits.append([p])
    return visits


# --- Centroids ---


def centroid(
    image: np.ndarray, x: float, y: float, sigma: float, gain: float = 2.0
) -> tuple[float, float] | None:
    """Gaussian-weighted centre, iterated until it stops moving. NaN pixels are ignored."""
    ny, nx = image.shape
    half = int(np.ceil(3 * sigma))
    for _ in range(60):
        xi, yi = int(round(x)), int(round(y))
        if xi - half < 0 or yi - half < 0 or xi + half >= nx or yi + half >= ny:
            return None
        box = image[yi - half : yi + half + 1, xi - half : xi + half + 1]
        yy, xx = np.mgrid[yi - half : yi + half + 1, xi - half : xi + half + 1]
        weight = np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma**2))
        # Drop the mirror image of every masked pixel so a masked core cannot pull the centre
        good = np.isfinite(box)
        good &= good[::-1, ::-1]
        flux = np.where(good, np.clip(box, 0, None), 0.0) * weight
        total = flux.sum()
        if total <= 0:
            return None
        # A Gaussian weight halves the apparent offset of a Gaussian star, so the
        # default gain is 2. Masked cores need a gain of 1 to stay stable.
        new_x = x + gain * ((flux * xx).sum() / total - x)
        new_y = y + gain * ((flux * yy).sum() / total - y)
        moved = np.hypot(new_x - x, new_y - y)
        x, y = float(new_x), float(new_y)
        if moved < 0.002:
            break
    return x, y


# --- Gaia alignment ---


def isolated_stars(stars: list[dict]) -> np.ndarray:
    """True for stars with no similar or brighter Gaia neighbour close by."""
    ra = np.array([s["ra"] for s in stars])
    dec = np.array([s["dec"] for s in stars])
    g = np.array([s["g"] for s in stars])
    keep = np.ones(len(stars), dtype=bool)
    for i in range(len(stars)):
        sep = 3600 * np.hypot((ra - ra[i]) * np.cos(np.radians(dec[i])), dec - dec[i])
        near = (sep < config.ALIGN_ISOLATION_ARCSEC) & (g < g[i] + 2.5)
        keep[i] = near.sum() == 1
    return keep


def robust_std(values: np.ndarray) -> float:
    return float(1.4826 * np.median(np.abs(values - np.median(values))))


def align_frame(
    image: np.ndarray, cutout: dict, stars: list[dict], usable: np.ndarray
) -> dict:
    """Fit a small correction from header-WCS pixel positions to measured ones.

    The correction is measured = predicted + shift + [[a, -b], [b, a]] (predicted - centre).
    With few stars only the shift is fitted. With none the header WCS is kept.
    """
    ny, nx = image.shape
    noise = measure_noise(image)
    ra, dec = catalogs.gaia_at_epoch(stars, cutout["mjd"])
    px, py = cutout["wcs"].all_world2pix(ra, dec, 0, quiet=True)

    pred, meas = [], []
    for i in np.flatnonzero(usable):
        x, y = px[i], py[i]
        if not (4 <= x < nx - 4 and 4 <= y < ny - 4):
            continue
        xi, yi = int(round(x)), int(round(y))
        core = image[yi - 1 : yi + 2, xi - 1 : xi + 2]
        if not np.isfinite(core).all() or core.max() < config.ALIGN_MIN_SNR * noise:
            continue
        found = centroid(image, x, y, config.CENTROID_SIGMA_PIX)
        if found is None:
            continue
        if np.hypot(found[0] - x, found[1] - y) > config.ALIGN_MAX_SHIFT_PIX:
            continue
        pred.append((x, y))
        meas.append(found)

    scale = config.NATIVE_PIXEL_ARCSEC
    centre = np.array([(nx - 1) / 2, (ny - 1) / 2])
    result = {
        "n_stars": len(pred),
        "params": [0.0, 0.0, 0.0, 0.0],
        "centre": centre.tolist(),
        "offset_arcsec": None,
        "scatter_arcsec": None,
    }
    if len(pred) < 3:
        return result

    pred_arr, meas_arr = np.array(pred), np.array(meas)
    delta = meas_arr - pred_arr
    uv = pred_arr - centre
    keep = np.ones(len(pred_arr), dtype=bool)
    params = np.zeros(4)
    resid = delta.copy()
    for _ in range(3):
        if keep.sum() >= config.ALIGN_MIN_STARS_FULL_FIT:
            u, v = uv[keep, 0], uv[keep, 1]
            one, zero = np.ones_like(u), np.zeros_like(u)
            design = np.vstack(
                [
                    np.column_stack([one, zero, u, -v]),
                    np.column_stack([zero, one, v, u]),
                ]
            )
            target = np.concatenate([delta[keep, 0], delta[keep, 1]])
            params = np.linalg.lstsq(design, target, rcond=None)[0]
        else:
            params = np.array([*np.median(delta[keep], axis=0), 0.0, 0.0])
        sx, sy, a, b = params
        model = np.column_stack(
            [sx + a * uv[:, 0] - b * uv[:, 1], sy + b * uv[:, 0] + a * uv[:, 1]]
        )
        resid = delta - model
        dist = np.hypot(resid[:, 0], resid[:, 1])
        limit = 3 * max(1.4826 * np.median(dist[keep]), 0.02)
        new_keep = dist < limit
        if new_keep.sum() < 3 or (new_keep == keep).all():
            break
        keep = new_keep

    result["n_stars"] = int(keep.sum())
    result["params"] = [float(p) for p in params]
    # Header WCS error: median distance between Gaia and the measured stars
    result["offset_arcsec"] = float(scale * np.median(np.hypot(*delta[keep].T)))
    # Scatter per axis of single stars about the fitted correction
    result["scatter_arcsec"] = float(
        scale * 0.5 * (robust_std(resid[keep, 0]) + robust_std(resid[keep, 1]))
    )
    return result


def apply_alignment(
    px: np.ndarray, py: np.ndarray, align: dict
) -> tuple[np.ndarray, np.ndarray]:
    sx, sy, a, b = align["params"]
    u, v = px - align["centre"][0], py - align["centre"][1]
    return px + sx + a * u - b * v, py + sy + b * u + a * v


# --- Common grid ---


def make_grid(ra: float, dec: float, fov_deg: float) -> tuple[WCS, int]:
    """North-up tangent-plane grid centred on the field."""
    size = int(round(fov_deg * 3600 / config.GRID_PIXEL_ARCSEC))
    grid = WCS(naxis=2)
    grid.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    grid.wcs.crval = [ra, dec]
    grid.wcs.crpix = [(size + 1) / 2, (size + 1) / 2]
    grid.wcs.cdelt = [
        -config.GRID_PIXEL_ARCSEC / 3600,
        config.GRID_PIXEL_ARCSEC / 3600,
    ]
    return grid, size


def reproject_frame(
    image: np.ndarray,
    wavelength: np.ndarray,
    cutout_wcs: WCS,
    align: dict,
    grid_ra: np.ndarray,
    grid_dec: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Bilinear resample of a frame and its wavelength map onto the common grid."""
    px, py = cutout_wcs.all_world2pix(grid_ra, grid_dec, 0, quiet=True)
    px, py = apply_alignment(px, py, align)
    out = map_coordinates(image, [py, px], order=1, cval=np.nan, prefilter=False)
    wave = map_coordinates(wavelength, [py, px], order=1, mode="nearest")
    wave[~np.isfinite(out)] = np.nan
    return out.astype(np.float32), wave.astype(np.float32)


# --- Field pipeline ---


def pick_evenly(items: list, limit: int) -> list:
    if len(items) <= limit:
        return items
    index = np.unique(np.linspace(0, len(items) - 1, limit).round().astype(int))
    return [items[i] for i in index]


def build_frames(
    ra: float,
    dec: float,
    fov_deg: float,
    detectors: list[str],
    max_per_detector: int | None = None,
    collection: str | None = None,
    select=None,
    progress=None,
    products: list[dict] | None = None,
) -> dict:
    """Search, download, clean, align and reproject every frame of a field.

    Pass a collection to keep to one data release. select, if given, takes the
    products of one detector and returns the ones to use. progress, if given,
    is called with a short text as each step starts. products, if given, is an
    exposure list to use in place of a new archive search.
    """
    if products is None:
        products = archive.search(
            ra, dec, collections=[collection] if collection else None
        )
    elif collection:
        products = [p for p in products if p["collection"] == collection]
    try:
        stars = catalogs.gaia_stars(ra, dec, fov_deg * 0.75)
    except RuntimeError as err:
        # Fallback from the brief: keep the header WCS and say so
        log.warning("No Gaia stars, frames keep their header WCS: %s", err)
        stars = []
    usable = isolated_stars(stars) if stars else np.zeros(0, dtype=bool)
    grid, size = make_grid(ra, dec, fov_deg)
    yy, xx = np.mgrid[0:size, 0:size]
    grid_ra, grid_dec = grid.all_pix2world(xx, yy, 0)

    frames = []
    for detector in detectors:
        chosen = [p for p in products if p["detector"] == detector]
        if select:
            chosen = select(chosen)
        if max_per_detector:
            chosen = pick_evenly(chosen, max_per_detector)
        if progress:
            progress(
                f"Downloading {len(chosen)} {detector} cutouts from the SPHEREx archive."
            )
        paths = archive.fetch_cutouts(chosen, ra, dec, fov_deg)
        if progress:
            progress(f"Aligning {detector} frames to Gaia stars.")
        for product, path in zip(chosen, paths):
            if path is None:
                continue
            try:
                cutout = archive.read_cutout(path)
            except (OSError, KeyError, ValueError) as err:
                log.warning("Unreadable cutout %s: %s", path.name, err)
                continue
            image = clean_image(cutout)
            if np.isfinite(image).mean() < 0.5:
                continue
            align = align_frame(image, cutout, stars, usable)
            out, wave = reproject_frame(
                image, cutout["wavelength"], cutout["wcs"], align, grid_ra, grid_dec
            )
            if np.isfinite(out).mean() < 0.5:
                continue
            frames.append(
                {
                    "obs_id": product["obs_id"],
                    "detector": detector,
                    "collection": product["collection"],
                    "mjd": cutout["mjd"],
                    "finast": cutout["finast"],
                    "image": out,
                    "wavelength": wave,
                    "noise": measure_noise(out),
                    "align": align,
                }
            )
        log.info(
            "%s: %d frames", detector, sum(f["detector"] == detector for f in frames)
        )
    frames.sort(key=lambda f: f["mjd"])
    return {"grid": grid, "size": size, "stars": stars, "frames": frames}


# --- Stacking ---


def stack_frames(frames: list[dict]) -> dict:
    """Weighted mean of frames with outlier rejection, which removes cosmic rays."""
    cube = np.array([f["image"] for f in frames])
    noise = np.array([f["noise"] for f in frames])[:, None, None]
    if len(frames) >= 3:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            median = np.nanmedian(cube, axis=0)
        # Allow for real brightness change with wavelength in bright stars
        limit = np.maximum(config.STACK_CLIP_SIGMA * noise, 0.3 * np.abs(median))
        cube = np.where(np.abs(cube - median) > limit, np.nan, cube)
    weight = np.where(np.isfinite(cube), 1 / noise**2, 0.0)
    total = weight.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        image = np.nansum(cube * weight, axis=0) / total
    image[total == 0] = np.nan
    image = image.astype(np.float32)
    return {
        "image": image,
        "noise": measure_noise(image),
        "mjd": float(np.mean([f["mjd"] for f in frames])),
        "detector": frames[0]["detector"],
        "collections": sorted({f["collection"] for f in frames}),
        "n_exposures": len(frames),
        "wavelength_um": float(
            np.nanmedian([np.nanmedian(f["wavelength"]) for f in frames])
        ),
    }


def stack_visits(frames: list[dict]) -> list[dict]:
    """One stack per visit and detector, in time order."""
    stacks = []
    for detector in sorted({f["detector"] for f in frames}):
        for visit in group_visits([f for f in frames if f["detector"] == detector]):
            stacks.append(stack_frames(visit))
    return sorted(stacks, key=lambda s: s["mjd"])


# --- Target motion ---


def position_at(target: dict, mjd: float) -> tuple[float, float]:
    """Catalogue position moved to a date with the catalogue proper motion."""
    years = (mjd - target["epoch_mjd"]) / 365.25
    dec = target["dec"] + target["pm_dec"] * years / 3600
    ra = target["ra"] + target["pm_ra"] * years / 3600 / np.cos(np.radians(dec))
    return ra, dec


def measure_motion(stacks: list[dict], grid: WCS, target: dict) -> dict:
    """Centroid the target in each stack and fit a straight line over time.

    The catalogue motion is used only to place a search window; the measured
    positions come from the images.
    """
    scale = config.GRID_PIXEL_ARCSEC
    sigma = config.CENTROID_SIGMA_PIX * config.NATIVE_PIXEL_ARCSEC / scale
    sigma_wide = config.SATURATED_SIGMA_PIX * config.NATIVE_PIXEL_ARCSEC / scale
    radius = target.get("search_arcsec", 12.0) / scale
    ra0, dec0 = grid.wcs.crval
    points = []
    for stack in stacks:
        image = stack["image"]
        ra, dec = position_at(target, stack["mjd"])
        x, y = (float(v) for v in grid.all_world2pix(ra, dec, 0))
        yy, xx = np.indices(image.shape)
        inside = np.hypot(xx - x, yy - y) <= radius
        window = inside & np.isfinite(image)
        saturated = window.sum() < 0.7 * inside.sum()
        if saturated:
            # Core is masked: centre on the wings with a wide weight
            wide = np.hypot(xx - x, yy - y) <= 3 * sigma_wide
            wings = wide & np.isfinite(image)
            if wings.sum() < 0.3 * wide.sum():
                continue
            snr = float(image[wings].max() / stack["noise"])
            start, width, gain = (x, y), sigma_wide, 1.0
        else:
            peak = np.argmax(np.where(window, image, -np.inf))
            py, px = np.unravel_index(peak, image.shape)
            snr = float(image[py, px] / stack["noise"])
            start, width, gain = (float(px), float(py)), sigma, 2.0
        if snr < config.MOTION_MIN_SNR:
            continue
        found = centroid(image, start[0], start[1], width, gain)
        if found is None:
            continue
        ra_m, dec_m = (float(v) for v in grid.all_pix2world(found[0], found[1], 0))
        points.append(
            {
                "mjd": stack["mjd"],
                "detector": stack["detector"],
                "ra": ra_m,
                "dec": dec_m,
                "x_arcsec": (ra_m - ra0) * np.cos(np.radians(dec0)) * 3600,
                "y_arcsec": (dec_m - dec0) * 3600,
                "snr": snr,
                "saturated": bool(saturated),
            }
        )

    result = {"points": points, "n_stacks": len(stacks), "fit": None}
    if len(points) < 3:
        return result
    t = np.array([(p["mjd"] - points[0]["mjd"]) / 365.25 for p in points])
    if np.ptp(t) < target.get("min_baseline_yr", 0.2):
        return result
    xy = np.array([[p["x_arcsec"], p["y_arcsec"]] for p in points])
    snr = np.array([p["snr"] for p in points])
    # Centroid error falls with signal to noise; the floor covers alignment error
    sigma = np.hypot(config.MOTION_ERR_FLOOR_ARCSEC, config.MOTION_ERR_ARCSEC / snr)
    pa, pd = parallax_factors(ra0, dec0, np.array([p["mjd"] for p in points]))

    straight, keep = fit_track(t, xy, sigma, None)
    for p, used in zip(points, keep):
        p["used"] = bool(used)
    result["fit"] = straight
    # Needs both seasons to separate parallax from proper motion
    if np.ptp(pa) > 0.5 or np.ptp(pd) > 0.5:
        result["fit_with_parallax"], _ = fit_track(t, xy, sigma, (pa, pd))
    return result


def parallax_factors(
    ra: float, dec: float, mjd: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Shift in RA cos Dec and Dec per arcsec of parallax, from the Earth's position."""
    x, y, z = get_body_barycentric("earth", Time(mjd, format="mjd")).xyz.to_value("au")
    a, d = np.radians(ra), np.radians(dec)
    pa = x * np.sin(a) - y * np.cos(a)
    pd = x * np.cos(a) * np.sin(d) + y * np.sin(a) * np.sin(d) - z * np.cos(d)
    return pa, pd


def fit_track(
    t: np.ndarray,
    xy: np.ndarray,
    sigma: np.ndarray,
    parallax: tuple[np.ndarray, np.ndarray] | None,
) -> tuple[dict, np.ndarray]:
    """Weighted straight-line fit of position against time, with optional parallax."""
    n = len(t)
    one, zero = np.ones(n), np.zeros(n)
    cols_x = [one, zero, t, zero]
    cols_y = [zero, one, zero, t]
    if parallax is not None:
        cols_x.append(parallax[0])
        cols_y.append(parallax[1])
    design = np.vstack([np.column_stack(cols_x), np.column_stack(cols_y)])
    values = np.concatenate([xy[:, 0], xy[:, 1]])
    weight = np.concatenate([1 / sigma, 1 / sigma])

    keep = np.ones(n, dtype=bool)
    for _ in range(4):
        rows = np.concatenate([keep, keep])
        a = design[rows] * weight[rows, None]
        coef = np.linalg.lstsq(a, values[rows] * weight[rows], rcond=None)[0]
        resid = (values - design @ coef).reshape(2, n)
        chi = np.hypot(resid[0], resid[1]) / sigma
        new_keep = chi < 3 * max(1.4826 * np.median(chi[keep]), 1.0)
        if new_keep.sum() < 3 or (new_keep == keep).all():
            break
        keep = new_keep

    used = int(keep.sum())
    dof = max(2 * used - design.shape[1], 1)
    chi2 = float(((resid[:, keep] / sigma[keep]) ** 2).sum() / dof)
    cov = np.linalg.inv(a.T @ a) * max(chi2, 1.0)
    rate = float(np.hypot(coef[2], coef[3]))
    rate_err = float(
        np.sqrt(coef[2] ** 2 * cov[2, 2] + coef[3] ** 2 * cov[3, 3]) / max(rate, 1e-9)
    )
    fit = {
        "pm_ra_arcsec_yr": float(coef[2]),
        "pm_dec_arcsec_yr": float(coef[3]),
        "rate_arcsec_yr": rate,
        "rate_err_arcsec_yr": rate_err,
        "residual_rms_arcsec": float(np.sqrt((resid[:, keep] ** 2).mean())),
        "n_points": used,
        "baseline_yr": float(np.ptp(t[keep])),
    }
    if parallax is not None:
        fit["parallax_arcsec"] = float(coef[4])
        fit["parallax_err_arcsec"] = float(np.sqrt(cov[4, 4]))
    return fit, keep
