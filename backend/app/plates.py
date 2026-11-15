"""Write a field to disk in the form the viewer reads: PNG frames and JSON."""

import json
from pathlib import Path

import numpy as np
from astropy.time import Time

from app import config, detect, engine, png

ENGINE_SIGMA_RANGE = 10.0
ENGINE_STEPS = 40

# --- Visit plates ---


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
        "median_stars_per_frame": median_or_none([a["n_stars"] for a in fitted]),
        "median_offset_arcsec": median_or_none([a["offset_arcsec"] for a in fitted]),
        "median_scatter_arcsec": median_or_none([a["scatter_arcsec"] for a in fitted]),
        "frame_shift_std_arcsec": (
            float(np.mean(np.std(shifts, axis=0))) if len(fitted) > 1 else None
        ),
    }


def write_plate(
    out_dir: Path,
    key: str,
    name: str,
    field: dict,
    stacks: list[dict],
    centre: tuple[float, float, float],
    catalogue: dict | None = None,
    motion: dict | None = None,
    extra: dict | None = None,
) -> dict:
    """Save per-visit stacks as PNG with one stretch per detector, plus meta.json."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.png"):
        old.unlink()
    stretch = {}
    for detector in sorted({s["detector"] for s in stacks}):
        images = [s["image"] for s in stacks if s["detector"] == detector]
        pairs = np.array([png.limits(im, 25.0, 99.8) for im in images])
        stretch[detector] = [float(v) for v in np.median(pairs, axis=0)]
    rows = []
    for i, stack in enumerate(stacks):
        file = f"{i:03d}_{stack['detector']}.png"
        lo, hi = stretch[stack["detector"]]
        png.save_png(
            out_dir / file, png.stretch(stack["image"], lo, hi), negative=False
        )
        rows.append(
            {
                "file": file,
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
        "name": name,
        "ra": centre[0],
        "dec": centre[1],
        "fov_deg": centre[2],
        "size": field["size"],
        "pixel_arcsec": config.GRID_PIXEL_ARCSEC,
        "stretch": stretch,
        "catalogue": catalogue,
        "frames": rows,
        "gaia": [s for s in field["stars"] if s["g"] < 16.0],
        "alignment": alignment_summary(field["frames"]),
        "motion": motion or {"points": [], "n_stacks": len(stacks), "fit": None},
        **(extra or {}),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta))
    return meta


# --- Engine before and after ---


def sigma_to_unit(z: np.ndarray) -> np.ndarray:
    """Significance to 0..1 in half-sigma steps. Masked pixels sit at zero sigma."""
    scaled = np.nan_to_num(z, nan=0.0) + ENGINE_SIGMA_RANGE
    scaled = np.clip(scaled / (2 * ENGINE_SIGMA_RANGE), 0, 1)
    return (np.round(scaled * ENGINE_STEPS) / ENGINE_STEPS).astype(np.float32)


def write_engine_view(
    out_dir: Path,
    field_frames: list[dict],
    after: list[dict],
    show: list[int],
) -> dict:
    """Save before (plain difference) and after (engine) maps for the chosen frames."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.png"):
        old.unlink()
    before = engine.plain_differences(field_frames, engine.median_image(field_frames))
    counts_before = [len(detect.find_peaks(m["z"])) for m in before]
    counts_after = [len(detect.find_peaks(m["z_local"])) for m in after]
    rows = []
    for i in show:
        frame = field_frames[i]
        names = {"before": f"{i:03d}_before.png", "after": f"{i:03d}_after.png"}
        png.save_png(out_dir / names["before"], sigma_to_unit(before[i]["z"]), False)
        png.save_png(
            out_dir / names["after"], sigma_to_unit(after[i]["z_local"]), False
        )
        rows.append(
            {
                **names,
                "detector": frame["detector"],
                "mjd": round(frame["mjd"], 5),
                "date": Time(frame["mjd"], format="mjd").utc.isot[:16],
                "wavelength_um": round(float(np.nanmedian(frame["wavelength"])), 4),
                "n_exposures": 1,
                "collections": [frame["collection"]],
                "peaks_before": counts_before[i],
                "peaks_after": counts_after[i],
            }
        )
    meta = {
        "detector": field_frames[0]["detector"],
        "collection": field_frames[0]["collection"],
        "sigma_range": ENGINE_SIGMA_RANGE,
        "detect_sigma": config.DETECT_SIGMA,
        "frames_in_run": len(field_frames),
        "mean_peaks_before": round(float(np.mean(counts_before)), 2),
        "mean_peaks_after": round(float(np.mean(counts_after)), 2),
        "frames": rows,
    }
    (out_dir / "engine.json").write_text(json.dumps(meta))
    return meta
