"""Clean difference images.

Each sky pixel is seen at a different wavelength in every frame. We fit that
pixel's brightness as a smooth function of wavelength, plus a steady change
with time, over all frames, predict every frame from its own wavelengths and
date, and subtract the prediction.
"""

import warnings

import numpy as np
from scipy.ndimage import uniform_filter

from app import config, frames

# --- Per-pixel fit ---


def fit_pixel_spectra(
    cube: np.ndarray, wave: np.ndarray, noise: np.ndarray, years: np.ndarray
) -> dict:
    """Robust fit of brightness against wavelength and time at every pixel.

    cube and wave are (frames, y, x); noise and years are one value per frame.
    The model is a polynomial in wavelength plus a straight line in time.
    Points far from the fit are dropped and the fit repeated, so movers and
    cosmic rays do not pull it. The time slope and its error come back as
    maps: a slowly moving source fades behind itself and brightens ahead.
    """
    degree = config.ENGINE_POLY_DEGREE
    n, h, w = cube.shape
    lo, hi = np.nanmin(wave), np.nanmax(wave)
    valid = np.isfinite(cube) & np.isfinite(wave)
    x = np.where(valid, (2 * wave - lo - hi) / (hi - lo), 0.0).astype(np.float64)
    flux = np.where(valid, cube, 0.0).astype(np.float64)
    frame_weight = (1 / noise**2)[:, None, None]
    columns = [x**k for k in range(degree + 1)]
    with_time = np.ptp(years) >= config.ENGINE_MIN_TREND_YEARS
    if with_time:
        columns.append(
            np.broadcast_to(years[:, None, None], cube.shape).astype(np.float64)
        )
    k = len(columns)

    keep = valid.copy()
    for _ in range(config.ENGINE_FIT_ROUNDS):
        weight = keep * frame_weight
        matrix = np.empty((h, w, k, k))
        vector = np.empty((h, w, k))
        for i in range(k):
            vector[..., i] = (weight * flux * columns[i]).sum(axis=0)
            for j in range(i, k):
                matrix[..., i, j] = matrix[..., j, i] = (
                    weight * columns[i] * columns[j]
                ).sum(axis=0)
        total = matrix[..., 0, 0].copy()
        for i in range(k):
            # A small pull towards a flat, steady pixel keeps thin coverage stable
            matrix[..., i, i] += (config.ENGINE_RIDGE if i else 0.0) * total + 1e-12
        coef = np.linalg.solve(matrix, vector[..., None])[..., 0]
        model = sum(coef[..., i] * columns[i] for i in range(k))
        resid = np.where(valid, flux - model, np.nan)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            centre = np.nanmedian(np.where(keep, resid, np.nan), axis=0)
            scatter = 1.4826 * np.nanmedian(np.abs(resid - centre), axis=0)
        sigma = np.maximum(noise[:, None, None], scatter[None])
        new_keep = valid & (np.abs(resid) <= config.ENGINE_CLIP_SIGMA * sigma)
        if (new_keep == keep).all():
            break
        keep = new_keep

    used = keep.sum(axis=0)
    thin = used < k + 2
    resid[:, thin] = np.nan
    mean_image = np.where(thin, np.nan, coef[..., 0])

    trend = np.full((h, w), np.nan)
    trend_err = np.full((h, w), np.nan)
    if with_time:
        weight = keep * frame_weight
        chi2 = (weight * np.nan_to_num(resid) ** 2).sum(axis=0) / np.maximum(
            used - k, 1
        )
        cov = np.linalg.inv(matrix)[..., k - 1, k - 1] * np.maximum(chi2, 1e-30)
        trend = np.where(thin, np.nan, coef[..., k - 1])
        trend_err = np.where(thin, np.nan, np.sqrt(cov))
    return {
        "residual": resid.astype(np.float32),
        "model": np.where(valid, model, np.nan).astype(np.float32),
        "mean_image": mean_image.astype(np.float32),
        "trend": trend.astype(np.float32),
        "trend_err": trend_err.astype(np.float32),
    }


# --- Local sampling match ---


def match_sampling(frame: np.ndarray, predicted: np.ndarray) -> np.ndarray:
    """Subtract the prediction after matching it to the frame's local sampling.

    SPHEREx pixels are larger than a star image, so the same star lands on the
    pixel grid differently in every frame. Around each pixel we fit the frame
    with the prediction, its first and second derivatives and a constant,
    which allows a small shift, a change of sharpness and a change of scale.
    A source that is absent from the prediction cannot be fitted away.
    """
    grad_y, grad_x = np.gradient(np.nan_to_num(predicted))
    grad_yy, _ = np.gradient(grad_y)
    grad_xy, grad_xx = np.gradient(grad_x)
    basis = [
        predicted,
        grad_x,
        grad_y,
        grad_xx,
        grad_yy,
        grad_xy,
        np.ones_like(predicted),
    ]
    prior = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    valid = np.isfinite(frame) & np.isfinite(predicted)
    flux = np.where(valid, frame, 0.0).astype(np.float64)
    basis = [np.where(valid, b, 0.0).astype(np.float64) for b in basis]
    k = len(basis)
    size = 2 * config.ENGINE_MATCH_HALF_PIX + 1
    matrix = np.empty(frame.shape + (k, k))
    vector = np.empty(frame.shape + (k,))
    for i in range(k):
        vector[..., i] = uniform_filter(basis[i] * flux, size)
        for j in range(i, k):
            matrix[..., i, j] = matrix[..., j, i] = uniform_filter(
                basis[i] * basis[j], size
            )
    for i in range(k):
        # Where the prediction is empty the fit falls back to plain subtraction
        pull = config.ENGINE_RIDGE * matrix[..., i, i] + 1e-9
        matrix[..., i, i] += pull
        vector[..., i] += pull * prior[i]
    coef = np.linalg.solve(matrix, vector[..., None])[..., 0]
    fitted = sum(coef[..., i] * basis[i] for i in range(k))
    return np.where(valid, flux - fitted, np.nan).astype(np.float32)


# --- Residual significance ---


def pixel_excess(residuals: np.ndarray) -> np.ndarray:
    """How much noisier than a background pixel each pixel is across all frames."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        centre = np.nanmedian(residuals, axis=0)
        scatter = 1.4826 * np.nanmedian(np.abs(residuals - centre), axis=0)
        excess = scatter / np.nanmedian(scatter)
    return np.where(np.isfinite(excess), np.clip(excess, 1.0, None), np.nan)


def significance(mjds: list[float], residuals: np.ndarray) -> list[dict]:
    """Per-frame maps: z uses the image noise, z_local also the per-pixel excess."""
    excess = pixel_excess(residuals)
    out = []
    for mjd, resid in zip(mjds, residuals):
        sigma = frames.measure_noise(resid)
        out.append(
            {
                "mjd": mjd,
                "residual": resid,
                "noise": sigma,
                "z": resid / sigma,
                "z_local": resid / (sigma * excess),
            }
        )
    return out


def clean_differences(field_frames: list[dict], match: bool = False) -> dict:
    """Run the engine on every frame of one detector.

    maps holds a residual and its significance per frame, for fast movers.
    trend and trend_err are the per-pixel change per year, for slow movers.
    """
    cube = np.array([f["image"] for f in field_frames])
    wave = np.array([f["wavelength"] for f in field_frames])
    noise = np.array([f["noise"] for f in field_frames])
    mjds = np.array([f["mjd"] for f in field_frames])
    fit = fit_pixel_spectra(cube, wave, noise, (mjds - mjds.mean()) / 365.25)
    residuals = fit["residual"]
    if match:
        residuals = np.array(
            [match_sampling(image, model) for image, model in zip(cube, fit["model"])]
        )
    return {
        "maps": significance(list(mjds), residuals),
        "mean_image": fit["mean_image"],
        "trend": fit["trend"],
        "trend_err": fit["trend_err"],
    }


# --- Plain differences, for comparison ---


def plain_differences(field_frames: list[dict], reference: np.ndarray) -> list[dict]:
    """Frame minus a fixed reference image, with the same significance maps."""
    residuals = np.array([f["image"] - reference for f in field_frames])
    return significance([f["mjd"] for f in field_frames], residuals)


def median_image(field_frames: list[dict]) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmedian(np.array([f["image"] for f in field_frames]), axis=0)
