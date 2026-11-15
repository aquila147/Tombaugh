"""Residual source detection and motion linking."""

import numpy as np
from scipy import ndimage

from app import config

# --- Detection ---


def find_peaks(z: np.ndarray) -> list[dict]:
    """Connected patches of a significance map above the threshold.

    Positions are in grid pixels (x along columns, y along rows).
    """
    filled = np.nan_to_num(z, nan=0.0)
    labels, count = ndimage.label(filled > config.DETECT_SIGMA)
    if count == 0:
        return []
    index = np.arange(1, count + 1)
    area = ndimage.sum_labels(np.ones_like(filled), labels, index)
    peak = ndimage.maximum(filled, labels, index)
    centre = ndimage.center_of_mass(filled, labels, index)
    return [
        {"x": float(c[1]), "y": float(c[0]), "snr": float(p), "area": int(a)}
        for a, p, c in zip(area, peak, centre)
        if a >= config.DETECT_MIN_AREA
    ]


def detections_table(maps: list[dict], key: str) -> dict:
    """All detections of a run as flat arrays, positions in arcsec on the grid."""
    rows = []
    for frame_index, entry in enumerate(maps):
        for peak in find_peaks(entry[key]):
            rows.append(
                (
                    entry["mjd"],
                    peak["x"] * config.GRID_PIXEL_ARCSEC,
                    peak["y"] * config.GRID_PIXEL_ARCSEC,
                    frame_index,
                    peak["snr"],
                    peak["area"],
                )
            )
    table = np.array(rows, dtype=float).reshape(-1, 6)
    return {
        "t": table[:, 0],
        "x": table[:, 1],
        "y": table[:, 2],
        "frame": table[:, 3].astype(int),
        "snr": table[:, 4],
        "area": table[:, 5],
    }


# --- Motion linking ---


def link_tracks(dets: dict, rule: dict) -> list[dict]:
    """Find detections that lie on a straight line at a steady rate.

    rule holds max_rate (arcsec/day), min_gap and max_gap (days) between the
    two detections that define a trial line, min_shift (arcsec) so that fixed
    residuals are not called movers, and tol (arcsec) around the line.
    A track needs detections in at least LINK_MIN_FRAMES different frames.
    """
    t, x, y, frame = dets["t"], dets["x"], dets["y"], dets["frame"]
    tol = rule["tol"]
    trials = []
    for i in range(len(t)):
        dt = t - t[i]
        dist = np.hypot(x - x[i], y - y[i])
        seeds = np.flatnonzero(
            (dt >= rule["min_gap"])
            & (dt <= rule["max_gap"])
            & (dist >= rule["min_shift"])
            & (dist <= rule["max_rate"] * dt + tol)
        )
        near = np.abs(dt) <= rule["max_gap"]
        for j in seeds:
            vx, vy = (x[j] - x[i]) / dt[j], (y[j] - y[i]) / dt[j]
            off = np.hypot(x - (x[i] + vx * dt), y - (y[i] + vy * dt))
            members = np.flatnonzero((off <= tol) & near)
            n_frames = len(np.unique(frame[members]))
            if n_frames >= config.LINK_MIN_FRAMES:
                trials.append((n_frames, members))

    # Best lines first; a detection belongs to one track only
    trials.sort(key=lambda trial: -trial[0])
    taken = np.zeros(len(t), dtype=bool)
    tracks = []
    for _, members in trials:
        members = members[~taken[members]]
        if len(np.unique(frame[members])) < config.LINK_MIN_FRAMES:
            continue
        tm = t[members] - t[members].mean()
        if np.ptp(tm) == 0:
            continue
        vx, vy = np.polyfit(tm, x[members], 1)[0], np.polyfit(tm, y[members], 1)[0]
        fit_x = x[members].mean() + vx * tm
        fit_y = y[members].mean() + vy * tm
        rms = float(
            np.sqrt(np.mean((x[members] - fit_x) ** 2 + (y[members] - fit_y) ** 2))
        )
        shift = float(np.hypot(vx, vy) * np.ptp(tm))
        if rms > tol or shift < rule["min_shift"]:
            continue
        taken[members] = True
        tracks.append(
            {
                "members": members.tolist(),
                "n_frames": int(len(np.unique(frame[members]))),
                "t0": float(t[members].mean()),
                "x0": float(x[members].mean()),
                "y0": float(y[members].mean()),
                "vx": float(vx),
                "vy": float(vy),
                "rate_arcsec_day": float(np.hypot(vx, vy)),
                "shift_arcsec": shift,
                "rms_arcsec": rms,
                "span_days": float(np.ptp(tm)),
            }
        )
    return tracks


# --- Slow movers ---


def velocity_map(
    trend: np.ndarray, trend_err: np.ndarray, mean_image: np.ndarray
) -> dict:
    """Velocity that best explains the per-pixel time slope around every pixel.

    A source moving by less than its own width fades behind itself and
    brightens ahead. For a small step the time slope equals minus the velocity
    times the image gradient. Around each pixel we fit the slope map with the
    two gradients of the mean image, giving a velocity and its error. The mean
    image, its curvature and a constant are fitted too, so a source that only
    brightens, fades or changes sharpness is not mistaken for motion.
    """
    grad_y, grad_x = np.gradient(mean_image)
    grad_yy, _ = np.gradient(grad_y)
    _, grad_xx = np.gradient(grad_x)
    basis = [-grad_x, -grad_y, mean_image, grad_xx + grad_yy, np.ones_like(mean_image)]
    valid = np.isfinite(trend) & np.isfinite(trend_err) & (trend_err > 0)
    for b in basis:
        valid &= np.isfinite(b)
    weight = np.where(valid, 1 / np.where(valid, trend_err, 1.0) ** 2, 0.0).astype(
        np.float64
    )
    target = np.where(valid, trend, 0.0).astype(np.float64)
    basis = [np.where(valid, b, 0.0).astype(np.float64) for b in basis]

    k = len(basis)
    size = 2 * config.SLOW_FIT_HALF_PIX + 1
    count = ndimage.uniform_filter(valid.astype(np.float64), size) * size**2
    matrix = np.empty(trend.shape + (k, k))
    vector = np.empty(trend.shape + (k,))
    for i in range(k):
        vector[..., i] = (
            ndimage.uniform_filter(weight * basis[i] * target, size) * size**2
        )
        for j in range(i, k):
            matrix[..., i, j] = matrix[..., j, i] = (
                ndimage.uniform_filter(weight * basis[i] * basis[j], size) * size**2
            )
    for i in range(k):
        matrix[..., i, i] += 1e-9 * matrix[..., i, i] + 1e-30
    coef = np.linalg.solve(matrix, vector[..., None])[..., 0]
    total = ndimage.uniform_filter(weight * target**2, size) * size**2
    misfit = np.clip(total - (coef * vector).sum(axis=-1), 0, None) / np.maximum(
        count - k, 1
    )
    cov = np.linalg.inv(matrix) * np.maximum(misfit, 1.0)[..., None, None]

    scale = config.GRID_PIXEL_ARCSEC
    enough = count >= 0.9 * size**2
    with np.errstate(invalid="ignore"):
        err_x = np.where(enough, scale * np.sqrt(cov[..., 0, 0]), np.nan)
        err_y = np.where(enough, scale * np.sqrt(cov[..., 1, 1]), np.nan)
    # Grid x runs west, so flip the sign to get motion towards east
    return {
        "pm_east": -coef[..., 0] * scale,
        "pm_north": coef[..., 1] * scale,
        "err_east": err_x,
        "err_north": err_y,
    }


def star_positions(mean_image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Row and column of bright local maxima of the mean image."""
    filled = np.nan_to_num(mean_image, nan=0.0)
    good = mean_image[np.isfinite(mean_image)]
    noise = 1.4826 * np.median(np.abs(good - np.median(good)))
    peaks = (filled == ndimage.maximum_filter(filled, 9)) & (
        filled > config.SLOW_STAR_SNR * noise
    )
    return np.nonzero(peaks)


def find_slow_movers(
    trend: np.ndarray, trend_err: np.ndarray, mean_image: np.ndarray
) -> list[dict]:
    """Places where the fitted velocity stands out from the rest of the field.

    The formal errors are too small because resampled pixels share noise, and
    stars show small false velocities from changes in the star image between
    passes. Both are measured on the field itself: the error scale from all
    pixels, and the common drift and its spread from the bright stars, nearly
    all of which move far less than the rate floor.
    """
    velocity = velocity_map(trend, trend_err, mean_image)
    east, north = velocity["pm_east"], velocity["pm_north"]
    err_e, err_n = velocity["err_east"], velocity["err_north"]

    with np.errstate(invalid="ignore", divide="ignore"):
        ratios = np.concatenate([(east / err_e).ravel(), (north / err_n).ravel()])
    ratios = ratios[np.isfinite(ratios)]
    if ratios.size == 0:
        return []
    error_scale = max(
        1.0, float(1.4826 * np.median(np.abs(ratios - np.median(ratios))))
    )

    rows, cols = star_positions(mean_image)
    star_e, star_n = east[rows, cols], north[rows, cols]
    ok = np.isfinite(star_e) & np.isfinite(star_n)
    drift_e = drift_n = spread = 0.0
    if ok.sum() >= config.SLOW_MIN_STARS:
        drift_e, drift_n = float(np.median(star_e[ok])), float(np.median(star_n[ok]))
        spread = float(
            1.4826
            * 0.5
            * (
                np.median(np.abs(star_e[ok] - drift_e))
                + np.median(np.abs(star_n[ok] - drift_n))
            )
        )

    east, north = east - drift_e, north - drift_n
    rate = np.hypot(east, north)
    with np.errstate(invalid="ignore", divide="ignore"):
        formal = np.sqrt((east * err_e) ** 2 + (north * err_n) ** 2) / rate
        rate_err = np.hypot(error_scale * formal, spread)
        z = rate / rate_err
    z = np.where(rate >= config.SLOW_MIN_RATE_ARCSEC_YR, z, 0.0)
    filled = np.nan_to_num(z, nan=0.0)
    labels, n = ndimage.label(filled > config.DETECT_SIGMA)
    movers = []
    half = config.SLOW_FIT_HALF_PIX
    for index in range(1, n + 1):
        patch = labels == index
        if patch.sum() < config.DETECT_MIN_AREA:
            continue
        y, x = np.unravel_index(np.argmax(np.where(patch, filled, 0.0)), filled.shape)
        # The window reaches past the plate border there, so the fit is not trusted
        if min(x, y, filled.shape[1] - 1 - x, filled.shape[0] - 1 - y) < 2 * half:
            continue
        # The fit window is wide; place the candidate on the brightest pixel inside it
        box = np.nan_to_num(
            mean_image[y - half : y + half + 1, x - half : x + half + 1]
        )
        by, bx = np.unravel_index(np.argmax(box), box.shape)
        movers.append(
            {
                "x": float(x - half + bx),
                "y": float(y - half + by),
                "snr": float(filled[y, x]),
                "rate_arcsec_yr": float(rate[y, x]),
                "rate_err_arcsec_yr": float(rate_err[y, x]),
                "pm_east_arcsec_yr": float(east[y, x]),
                "pm_north_arcsec_yr": float(north[y, x]),
                "error_scale": round(error_scale, 2),
                "star_drift_arcsec_yr": [round(drift_e, 2), round(drift_n, 2)],
                "star_spread_arcsec_yr": round(spread, 2),
                "stars_used": int(ok.sum()),
            }
        )
    return movers
