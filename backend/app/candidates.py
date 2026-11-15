"""Turn engine output into candidates and into rows for the candidates table."""

import numpy as np
from astropy.time import Time

from app import config

# A run is one field and detector after the engine:
#   plate, detector, centre (ra, dec, fov), field, dets, mjds, tracks, movers


def plain(value):
    """Numpy values to plain Python so they can be stored as JSON."""
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def sky(run: dict, x_arcsec: float, y_arcsec: float) -> tuple[float, float]:
    scale = config.GRID_PIXEL_ARCSEC
    ra, dec = run["field"]["grid"].all_pix2world(x_arcsec / scale, y_arcsec / scale, 0)
    return float(ra), float(dec)


# --- Candidates from a run ---


def fast_candidates(run: dict) -> list[dict]:
    """One candidate per linked fast track, with its member detections."""
    out = []
    dets = run["dets"]
    for track in run["tracks"]:
        ra, dec = sky(run, track["x0"], track["y0"])
        detections = []
        for m in track["members"]:
            d_ra, d_dec = sky(run, dets["x"][m], dets["y"][m])
            detections.append(
                {
                    "frame": int(dets["frame"][m]),
                    "mjd": float(dets["t"][m]),
                    "x_arcsec": float(dets["x"][m]),
                    "y_arcsec": float(dets["y"][m]),
                    "ra": d_ra,
                    "dec": d_dec,
                    "snr": float(dets["snr"][m]),
                    "area": float(dets["area"][m]),
                }
            )
        out.append(
            {
                "kind": "fast",
                "run": run,
                "ra": ra,
                "dec": dec,
                "mjd": track["t0"],
                "x0": track["x0"],
                "y0": track["y0"],
                "vx": track["vx"],
                "vy": track["vy"],
                "span_days": track["span_days"],
                "n_frames": track["n_frames"],
                "rate_arcsec_hr": track["rate_arcsec_day"] / 24,
                "detections": detections,
            }
        )
    return out


def slow_candidates(run: dict) -> list[dict]:
    """One candidate per place where the per-pixel time fit looks like motion."""
    out = []
    scale = config.GRID_PIXEL_ARCSEC
    for mover in run["movers"]:
        ra, dec = sky(run, mover["x"] * scale, mover["y"] * scale)
        out.append(
            {
                "kind": "slow",
                "run": run,
                "ra": ra,
                "dec": dec,
                "mjd": float(run["mjds"].mean()),
                "x_pix": mover["x"],
                "y_pix": mover["y"],
                "significance": mover["snr"],
                "rate_arcsec_yr": mover["rate_arcsec_yr"],
                "pm_east": mover["pm_east_arcsec_yr"],
                "pm_north": mover["pm_north_arcsec_yr"],
                "n_frames": len(run["field"]["frames"]),
            }
        )
    return out


# --- Rows for the candidates table ---


def to_row(candidate: dict, outcome: dict, field_name: str, source: str) -> dict:
    """A candidate and its checks in the shape of the candidates table."""
    run = candidate["run"]
    fast = candidate["kind"] == "fast"
    date = Time(candidate["mjd"], format="mjd").utc.isot[:10]
    known = candidate.get("known_as")
    if known:
        label = known[0].upper() + known[1:]
    elif fast:
        label = f"Fast track, {field_name} {run['detector']}, {date}"
    else:
        label = f"Slow candidate, {field_name} {run['detector']}"
    if fast:
        hours = candidate["span_days"] * 24
        motion = f"{candidate['rate_arcsec_hr']:.1f} arcsec/hr over {hours:.1f} hours"
    else:
        motion = (
            f"{candidate['rate_arcsec_yr']:.2f} arcsec/yr from the engine "
            "(detection only; engine rates run low)"
        )
    summary = {
        "label": label,
        "kind": candidate["kind"],
        "plate": run["plate"],
        "field": field_name,
        "detector": run["detector"],
        "also_seen_in": candidate.get("also_seen_in", []),
        "mjd": round(candidate["mjd"], 4),
        "date": date,
        "motion": motion,
        "known_as": known,
        "failed": outcome["failed"],
        "source": source,
    }
    if fast:
        summary["peak_sigma"] = round(max(d["snr"] for d in candidate["detections"]), 1)
        summary["path"] = [
            [round(d["ra"], 5), round(d["dec"], 5)] for d in candidate["detections"]
        ]
    else:
        summary["significance"] = round(candidate["significance"], 1)
    return plain(
        {
            "ra": round(candidate["ra"], 6),
            "dec": round(candidate["dec"], 6),
            "pm_ra": None if fast else round(candidate["pm_east"], 3),
            "pm_dec": None if fast else round(candidate["pm_north"], 3),
            "rate": round(candidate["rate_arcsec_hr"], 2) if fast else None,
            "frames_used": candidate["n_frames"],
            "checks": {"summary": summary, "items": outcome["items"]},
            "status": outcome["status"],
        }
    )
