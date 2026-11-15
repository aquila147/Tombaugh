"""Why plain differences leave residuals on stars: wavelength or pixel sampling?

For bright isolated Gaia stars in one field and detector, this compares how
much the star's total brightness (a 39 arcsec box) and a single pixel at its
centre change from exposure to exposure, before and after removing a smooth
trend with wavelength.

Run from backend/:  python -m scripts.measure_sampling
Writes docs/data/validation/sampling.json
"""

import json
import logging

import numpy as np

from app import config, frames
from scripts.build_showcase import CENTRE_MJD, FOV_DEG, MAX_PER_DETECTOR, TARGETS

OUT = config.BACKEND_DIR.parent / "docs" / "data" / "validation" / "sampling.json"
FIELD = "eps_indi_b"
DETECTOR = "D2"
STARS = 3
MIN_EXPOSURES = 20
HALF_BOX = 6


def percent_rms(values: np.ndarray, wavelength: np.ndarray) -> tuple[float, float]:
    """Scatter about the mean and about a quadratic in wavelength, in percent."""
    trend = np.polyval(np.polyfit(wavelength, values, 2), wavelength)
    mean = values.mean()
    return float(values.std() / mean * 100), float((values - trend).std() / mean * 100)


def main() -> None:
    logging.basicConfig(level=logging.ERROR)
    target = TARGETS[FIELD]
    ra, dec = frames.position_at(target, CENTRE_MJD)
    field = frames.build_frames(
        round(float(ra), 4),
        round(float(dec), 4),
        FOV_DEG,
        [DETECTOR],
        MAX_PER_DETECTOR,
        collection=config.ENGINE_COLLECTION,
    )
    stars = field["stars"]
    isolated = frames.isolated_stars(stars)
    size = field["size"]
    rows = []
    for star, ok in zip(stars, isolated):
        if not ok or len(rows) >= STARS:
            continue
        x, y = (
            float(v) for v in field["grid"].all_world2pix(star["ra"], star["dec"], 0)
        )
        if not (30 < x < size - 30 and 30 < y < size - 30):
            continue
        xi, yi = int(round(x)), int(round(y))
        series = []
        for frame in field["frames"]:
            box = frame["image"][
                yi - HALF_BOX : yi + HALF_BOX + 1, xi - HALF_BOX : xi + HALF_BOX + 1
            ]
            if np.isfinite(box).all():
                wave = np.nanmedian(
                    frame["wavelength"][yi - 1 : yi + 2, xi - 1 : xi + 2]
                )
                series.append((wave, box.sum(), frame["image"][yi, xi]))
        if len(series) < MIN_EXPOSURES:
            continue
        wave, total, centre = (np.array(v) for v in zip(*series))
        total_mean, total_fit = percent_rms(total, wave)
        pixel_mean, pixel_fit = percent_rms(centre, wave)
        rows.append(
            {
                "gaia_g": round(star["g"], 1),
                "exposures": len(series),
                "total_brightness_rms_percent": round(total_mean, 1),
                "total_brightness_rms_after_wavelength_trend_percent": round(
                    total_fit, 1
                ),
                "centre_pixel_rms_percent": round(pixel_mean, 1),
                "centre_pixel_rms_after_wavelength_trend_percent": round(pixel_fit, 1),
            }
        )
    result = {
        "field": target["name"],
        "detector": DETECTOR,
        "collection": config.ENGINE_COLLECTION,
        "exposures_in_field": len(field["frames"]),
        "stars": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
