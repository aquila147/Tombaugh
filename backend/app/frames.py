"""Frame cleaning and visit grouping. Reprojection and alignment come in Phase 2."""

import numpy as np

from app import config, flags

# --- Cleaning ---


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
