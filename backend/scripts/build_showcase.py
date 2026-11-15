"""Precompute the showcase targets into docs/data/showcase/.

Run from backend/:  python -m scripts.build_showcase [target ...]
Writes frames as PNG, meta.json per target, and summary.json with the
alignment and motion numbers quoted in the README.
"""

import json
import logging
import sys

import numpy as np
from astropy.time import Time

from app import config, frames, png

log = logging.getLogger("tombaugh.showcase")

OUT_DIR = config.BACKEND_DIR.parent / "docs" / "data" / "showcase"
FOV_DEG = 0.2
MAX_PER_DETECTOR = 80
CENTRE_MJD = 61000.0

# Positions and proper motions (arcsec/yr, RA term includes cos Dec) from the literature.
# They place the field and the search window only.
TARGETS = {
    "barnard": {
        "name": "Barnard's Star",
        "ra": 269.45208,
        "dec": 4.69336,
        "epoch_mjd": 51544.5,
        "pm_ra": -0.8028,
        "pm_dec": 10.3625,
        "published_rate": 10.39,
        "detectors": ["D3", "D4"],
    },
    "eps_indi_b": {
        "name": "Epsilon Indi B",
        "ra": 331.04383,
        "dec": -56.78269,
        "epoch_mjd": 51544.5,
        "pm_ra": 3.9609,
        "pm_dec": -2.5390,
        "published_rate": 4.70,
        "search_arcsec": 15.0,
        "detectors": ["D2", "D3"],
    },
    "wise0855": {
        "name": "WISE 0855-0714",
        "ra": 133.7951,
        "dec": -7.2451,
        "epoch_mjd": 55340.0,
        "pm_ra": -8.118,
        "pm_dec": 0.680,
        "published_rate": 8.15,
        "search_arcsec": 20.0,
        "centre": [133.7951, -7.2451],
        "detectors": ["D5", "D6"],
    },
    "rw_aur": {
        "name": "RW Aurigae",
        "ra": 76.9565,
        "dec": 30.4013,
        "epoch_mjd": 51544.5,
        "pm_ra": 0.0,
        "pm_dec": 0.0,
        "published_rate": None,
        "detectors": ["D2", "D4"],
    },
    "r_dra": {
        "name": "R Draconis",
        "ra": 248.1975,
        "dec": 66.7519,
        "epoch_mjd": 51544.5,
        "pm_ra": 0.0,
        "pm_dec": 0.0,
        "published_rate": None,
        "detectors": ["D2", "D4"],
    },
}


def median_or_none(values: list) -> float | None:
    values = [v for v in values if v is not None]
    return float(np.median(values)) if values else None


def alignment_summary(field_frames: list[dict]) -> dict:
    """Per-frame Gaia offsets, summarised over the field."""
    fitted = [
        f["align"] for f in field_frames if f["align"]["offset_arcsec"] is not None
    ]
    shifts = np.array([a["params"][:2] for a in fitted]) * config.NATIVE_PIXEL_ARCSEC
    return {
        "frames": len(field_frames),
        "frames_aligned": len(fitted),
        "finast_solved": sum(f["finast"] for f in field_frames),
        "median_stars_per_frame": median_or_none([a["n_stars"] for a in fitted]),
        "median_offset_arcsec": median_or_none([a["offset_arcsec"] for a in fitted]),
        "median_scatter_arcsec": median_or_none([a["scatter_arcsec"] for a in fitted]),
        "frame_shift_std_arcsec": (
            float(np.mean(np.std(shifts, axis=0))) if len(fitted) > 1 else None
        ),
    }


def build_target(key: str) -> dict:
    target = TARGETS[key]
    ra, dec = target.get("centre") or frames.position_at(target, CENTRE_MJD)
    ra, dec = round(float(ra), 4), round(float(dec), 4)
    log.info("%s: field centre %.4f %+.4f", target["name"], ra, dec)

    field = frames.build_frames(ra, dec, FOV_DEG, target["detectors"], MAX_PER_DETECTOR)
    stacks = frames.stack_visits(field["frames"])
    # The two variable stars are shown for brightness change, not motion
    motion = {"points": [], "n_stacks": len(stacks), "fit": None}
    if target["published_rate"] is not None:
        motion = frames.measure_motion(stacks, field["grid"], target)
    align = alignment_summary(field["frames"])

    # --- Frames as PNG, one stretch per detector ---
    out_dir = OUT_DIR / key
    for old in out_dir.glob("*.png"):
        old.unlink()
    stretch = {}
    for detector in target["detectors"]:
        images = [s["image"] for s in stacks if s["detector"] == detector]
        if images:
            pairs = np.array([png.limits(im, 25.0, 99.8) for im in images])
            stretch[detector] = [float(v) for v in np.median(pairs, axis=0)]
    frame_meta = []
    for i, stack in enumerate(stacks):
        name = f"{i:03d}_{stack['detector']}.png"
        lo, hi = stretch[stack["detector"]]
        png.save_png(
            out_dir / name, png.stretch(stack["image"], lo, hi), negative=False
        )
        frame_meta.append(
            {
                "file": name,
                "detector": stack["detector"],
                "mjd": round(stack["mjd"], 5),
                "date": Time(stack["mjd"], format="mjd").utc.isot[:16],
                "wavelength_um": round(stack["wavelength_um"], 4),
                "n_exposures": stack["n_exposures"],
                "collections": stack["collections"],
                "noise": stack["noise"],
            }
        )

    meta = {
        "id": key,
        "name": target["name"],
        "ra": ra,
        "dec": dec,
        "fov_deg": FOV_DEG,
        "size": field["size"],
        "pixel_arcsec": config.GRID_PIXEL_ARCSEC,
        "stretch": stretch,
        "catalogue": {
            k: target[k]
            for k in ["ra", "dec", "epoch_mjd", "pm_ra", "pm_dec", "published_rate"]
        },
        "frames": frame_meta,
        "gaia": [s for s in field["stars"] if s["g"] < 16.0],
        "alignment": align,
        "motion": motion,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta))

    fit = motion["fit"]
    summary = {
        "name": target["name"],
        "centre": [ra, dec, FOV_DEG],
        "detectors": target["detectors"],
        "stacks": len(stacks),
        "alignment": align,
        "motion_points": len(motion["points"]),
        "motion_fit": fit,
        "motion_fit_with_parallax": motion.get("fit_with_parallax"),
        "published_rate_arcsec_yr": target["published_rate"],
    }
    print(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    keys = sys.argv[1:] or list(TARGETS)
    path = OUT_DIR / "summary.json"
    summary = json.loads(path.read_text()) if path.is_file() else {}
    for key in keys:
        summary[key] = build_target(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
