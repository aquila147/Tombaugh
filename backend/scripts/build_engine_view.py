"""Before and after images for the viewer, for the three mover fields.

Before: frame minus the median of all frames, over the image noise.
After: the engine residual over the per-pixel measured noise.
Both are significance maps from Data Release 1 only, saved between
-10 and +10 sigma in half-sigma steps.

Run from backend/:  python -m scripts.build_engine_view
Writes docs/data/showcase/<target>/engine/
"""

import json
import logging

import numpy as np
from astropy.time import Time

from app import config, detect, engine, frames, png
from scripts.build_showcase import (
    CENTRE_MJD,
    FOV_DEG,
    MAX_PER_DETECTOR,
    OUT_DIR,
    TARGETS,
)
from scripts.run_engine import MOVERS

SIGMA_RANGE = 10.0
STEPS = 40
MAX_FRAMES = 40


def to_unit(z: np.ndarray) -> np.ndarray:
    """Significance to 0..1 in half-sigma steps. Masked pixels sit at zero sigma."""
    scaled = np.clip(
        (np.nan_to_num(z, nan=0.0) + SIGMA_RANGE) / (2 * SIGMA_RANGE), 0, 1
    )
    return (np.round(scaled * STEPS) / STEPS).astype(np.float32)


def build(key: str) -> None:
    target = TARGETS[key]
    detector = target["detectors"][0]
    ra, dec = target.get("centre") or frames.position_at(target, CENTRE_MJD)
    field = frames.build_frames(
        round(float(ra), 4),
        round(float(dec), 4),
        FOV_DEG,
        [detector],
        MAX_PER_DETECTOR,
        collection=config.ENGINE_COLLECTION,
    )
    field_frames = field["frames"]
    before = engine.plain_differences(field_frames, engine.median_image(field_frames))
    after = engine.clean_differences(field_frames)["maps"]

    out_dir = OUT_DIR / key / "engine"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.png"):
        old.unlink()
    rows = []
    for i in frames.pick_evenly(list(range(len(field_frames))), MAX_FRAMES):
        frame = field_frames[i]
        names = {"before": f"{i:03d}_before.png", "after": f"{i:03d}_after.png"}
        png.save_png(out_dir / names["before"], to_unit(before[i]["z"]), negative=False)
        png.save_png(
            out_dir / names["after"], to_unit(after[i]["z_local"]), negative=False
        )
        rows.append(
            {
                **names,
                "detector": detector,
                "mjd": round(frame["mjd"], 5),
                "date": Time(frame["mjd"], format="mjd").utc.isot[:16],
                "wavelength_um": round(float(np.nanmedian(frame["wavelength"])), 4),
                "n_exposures": 1,
                "collections": [frame["collection"]],
                "peaks_before": len(detect.find_peaks(before[i]["z"])),
                "peaks_after": len(detect.find_peaks(after[i]["z_local"])),
            }
        )
    meta = {
        "detector": detector,
        "collection": config.ENGINE_COLLECTION,
        "sigma_range": SIGMA_RANGE,
        "detect_sigma": config.DETECT_SIGMA,
        "frames_in_run": len(field_frames),
        "mean_peaks_before": round(
            float(np.mean([len(detect.find_peaks(m["z"])) for m in before])), 2
        ),
        "mean_peaks_after": round(
            float(np.mean([len(detect.find_peaks(m["z_local"])) for m in after])), 2
        ),
        "frames": rows,
    }
    (out_dir / "engine.json").write_text(json.dumps(meta))
    print(
        key,
        detector,
        len(rows),
        "frames shown of",
        len(field_frames),
        "mean peaks before",
        meta["mean_peaks_before"],
        "after",
        meta["mean_peaks_after"],
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    for key in MOVERS:
        build(key)
