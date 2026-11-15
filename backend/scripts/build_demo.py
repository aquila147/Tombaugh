"""Build the Singapore demo field: a patch near Singapore's zenith declination
that contains a known asteroid in real SPHEREx exposures.

The asteroid was picked from cache/demo_candidates.json
(scripts/find_demo_asteroid.py). Its JPL position and rate place the field and
the search window only; the positions shown are measured on the SPHEREx frames.

The exposure list is the one found for ANCHOR, a point on the zenith strip.
SPHEREx exposures are 3.5 degrees wide, so the same exposures cover the
asteroid; the cutout service decides, exposure by exposure, whether they do.

Run from backend/:  python -m scripts.build_demo
Writes docs/data/showcase/singapore/ and adds it to summary.json
"""

import json
import logging

import numpy as np
from astropy.time import Time

from app import archive, catalogs, config, detect, engine, frames, plates
from scripts.build_showcase import OUT_DIR

log = logging.getLogger("tombaugh.demo")

KEY = "singapore"
ASTEROID = "Lachesis"
SINGAPORE_LAT = 1.35
ANCHOR = (176.9, 1.35)
# 2025-12-19 16:00 to 2025-12-20 11:00 UTC: five visits with the asteroid in view
WINDOW = (61028.66, 61029.46)
FOV_DEG = 0.3
HOURS_PER_YEAR = 8766.0
MATCH_ARCSEC = 20.0
ENGINE_DETECTOR = "D2"


def asteroid_at(mjd: float) -> dict:
    """JPL position and rate of the asteroid at a time."""
    rows = json.loads((config.CACHE_DIR / "demo_candidates.json").read_text())
    rows = sorted(
        (r for r in rows if ASTEROID in r["name"]), key=lambda r: abs(r["mjd"] - mjd)
    )
    near = rows[0]
    hours = (mjd - near["mjd"]) * 24
    guess_dec = near["dec"] + near["dec_rate_arcsec_hr"] * hours / 3600
    guess_ra = near["ra"] + near["ra_rate_arcsec_hr"] * hours / 3600 / np.cos(
        np.radians(guess_dec)
    )
    bodies = catalogs.known_small_bodies(
        round(guess_ra, 3), round(guess_dec, 3), mjd, 0.3, None, 17
    )
    body = next(b for b in bodies if ASTEROID in b["name"])
    return dict(body, mjd=mjd)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("tombaugh.archive").setLevel(logging.ERROR)
    mid = 0.5 * (WINDOW[0] + WINDOW[1])
    body = asteroid_at(mid)
    rate_hr = float(np.hypot(body["ra_rate_arcsec_hr"], body["dec_rate_arcsec_hr"]))
    ra, dec = round(body["ra"], 4), round(body["dec"], 4)
    log.info(
        "%s V %s at %.4f %+.4f, %.1f arcsec/hr",
        body["name"],
        body["vmag"],
        ra,
        dec,
        rate_hr,
    )

    # JPL position and rate as a straight line, in the units frames.position_at uses
    target = {
        "name": body["name"],
        "ra": body["ra"],
        "dec": body["dec"],
        "epoch_mjd": mid,
        "pm_ra": body["ra_rate_arcsec_hr"] * HOURS_PER_YEAR,
        "pm_dec": body["dec_rate_arcsec_hr"] * HOURS_PER_YEAR,
        "published_rate": rate_hr * HOURS_PER_YEAR,
        "search_arcsec": MATCH_ARCSEC,
        "min_baseline_yr": 0.0,
    }
    products = archive.search(*ANCHOR)

    def in_window(chosen: list[dict]) -> list[dict]:
        return [p for p in chosen if WINDOW[0] <= p["mjd"] <= WINDOW[1]]

    # --- Plates: every detector, exposures inside the window only ---
    field = frames.build_frames(
        ra,
        dec,
        FOV_DEG,
        config.DETECTORS,
        None,
        config.ENGINE_COLLECTION,
        select=in_window,
        products=products,
    )
    stacks = frames.stack_visits(field["frames"])
    motion = frames.measure_motion(stacks, field["grid"], target)
    seen = motion["points"]
    fit = motion["fit"]
    confirmation = {
        "asteroid": body["name"],
        "jpl_vmag": body["vmag"],
        "jpl_rate_arcsec_hr": round(rate_hr, 2),
        "exposures": len(field["frames"]),
        "visit_stacks": len(stacks),
        "visit_stacks_with_detection": len(seen),
        "detectors_with_detection": sorted({p["detector"] for p in seen}),
        "span_hours": (
            round(24 * float(np.ptp([p["mjd"] for p in seen])), 1) if seen else 0
        ),
        "measured_rate_arcsec_hr": (
            round(fit["rate_arcsec_yr"] / HOURS_PER_YEAR, 2) if fit else None
        ),
        "measured_rate_err_arcsec_hr": (
            round(fit["rate_err_arcsec_yr"] / HOURS_PER_YEAR, 2) if fit else None
        ),
        "track_residual_rms_arcsec": (
            round(fit["residual_rms_arcsec"], 2) if fit else None
        ),
        "measured_shift_arcsec": (
            round(fit["rate_arcsec_yr"] * fit["baseline_yr"], 1) if fit else None
        ),
    }

    # --- Engine on one detector: all its exposures for the noise, the window for display ---
    year = frames.build_frames(
        ra,
        dec,
        FOV_DEG,
        [ENGINE_DETECTOR],
        None,
        config.ENGINE_COLLECTION,
        products=products,
    )
    result = engine.clean_differences(year["frames"])
    show = [
        i for i, f in enumerate(year["frames"]) if WINDOW[0] <= f["mjd"] <= WINDOW[1]
    ]
    engine_meta = plates.write_engine_view(
        OUT_DIR / KEY / "engine", year["frames"], result["maps"], show
    )

    # Does the blind fast-mover search link the asteroid on its own?
    dets = detect.detections_table(result["maps"], "z_local")
    scale = config.GRID_PIXEL_ARCSEC
    tracks = detect.link_tracks(dets, config.LINK_FAST)
    linked = None
    for track in tracks:
        hits = 0
        for m in track["members"]:
            eph = frames.position_at(target, dets["t"][m])
            x, y = year["grid"].all_world2pix(eph[0], eph[1], 0)
            hits += (
                np.hypot(dets["x"][m] - x * scale, dets["y"][m] - y * scale)
                <= MATCH_ARCSEC
            )
        if hits >= config.LINK_MIN_FRAMES:
            linked = {
                "exposures": track["n_frames"],
                "rate_arcsec_hr": round(track["rate_arcsec_day"] / 24, 2),
                "span_hours": round(track["span_days"] * 24, 1),
            }
            break
    confirmation["engine"] = {
        "detector": ENGINE_DETECTOR,
        "exposures_in_run": len(year["frames"]),
        "exposures_in_window": len(show),
        "fast_tracks_found": len(tracks),
        "blind_track_matches_asteroid": linked,
        "mean_peaks_before": engine_meta["mean_peaks_before"],
        "mean_peaks_after": engine_meta["mean_peaks_after"],
    }

    date = Time(mid, format="mjd").utc.isot[:10]
    title = f"Above Singapore, {date}"
    plates.write_plate(
        OUT_DIR / KEY,
        KEY,
        body["name"],
        field,
        stacks,
        (ra, dec, FOV_DEG),
        catalogue={
            k: target[k]
            for k in ["ra", "dec", "epoch_mjd", "pm_ra", "pm_dec", "published_rate"]
        },
        motion=motion,
        extra={
            "kind": "asteroid",
            "title": title,
            "zenith_note": (
                f"Dec {dec:+.2f}, {abs(dec - SINGAPORE_LAT):.2f} degrees from Singapore's "
                "zenith, so this patch passes almost straight overhead once a day."
            ),
            "confirmation": confirmation,
        },
    )

    path = OUT_DIR / "summary.json"
    summary = json.loads(path.read_text())
    entry = {
        "name": body["name"],
        "title": title,
        "demo": True,
        "centre": [ra, dec, FOV_DEG],
        "detectors": sorted({s["detector"] for s in stacks}),
        "stacks": len(stacks),
        "alignment": plates.alignment_summary(field["frames"]),
        "confirmation": confirmation,
    }
    # Demo first, so the site opens on it
    summary = {KEY: entry, **{k: v for k, v in summary.items() if k != KEY}}
    path.write_text(json.dumps(summary, indent=2))
    print(json.dumps(entry, indent=2))
    for s in stacks:
        hit = [
            p
            for p in seen
            if abs(p["mjd"] - s["mjd"]) < 1e-6 and p["detector"] == s["detector"]
        ]
        text = (
            f"snr {hit[0]['snr']:7.1f} x {hit[0]['x_arcsec']:7.1f} y {hit[0]['y_arcsec']:7.1f} used {hit[0].get('used')}"
            if hit
            else "not detected"
        )
        print(
            f"  {Time(s['mjd'], format='mjd').utc.isot[:16]} {s['detector']} n={s['n_exposures']} {s['wavelength_um']:.2f} um  {text}"
        )


if __name__ == "__main__":
    main()
