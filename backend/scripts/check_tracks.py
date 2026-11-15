"""Check the engine's fast tracks against known solar-system objects.

Two sets of tracks are checked with JPL Small-Body Identification:
  1. fast tracks found in the real, un-injected data (the false-alarm figure)
  2. tracks from the SYNTHETIC injection runs that match no planted source

Run from backend/:  python -m scripts.check_tracks
Writes docs/data/validation/track_check.json
"""

import json
import logging

import numpy as np

from app import catalogs, config, detect, engine, frames
from scripts import run_engine
from scripts.build_showcase import CENTRE_MJD, FOV_DEG, MAX_PER_DETECTOR, TARGETS

log = logging.getLogger("tombaugh.tracks")

OUT = config.BACKEND_DIR.parent / "docs" / "data" / "validation" / "track_check.json"
SEARCH_HALF_WIDTH_DEG = 0.5
# Geocentric positions can be off by a few pixels for near objects
MATCH_ARCSEC = 30.0
SEED = 20261115


def track_sky(field: dict, track: dict) -> tuple[float, float]:
    scale = config.GRID_PIXEL_ARCSEC
    ra, dec = field["grid"].all_pix2world(track["x0"] / scale, track["y0"] / scale, 0)
    return float(ra), float(dec)


def match_known(field: dict, centre: tuple[float, float], track: dict) -> dict | None:
    """Nearest known object to the track at the track's mean time, if close enough."""
    # One query per field and quarter day; objects are moved to the track time
    when = round(track["t0"] * 4) / 4
    bodies = catalogs.known_small_bodies(
        centre[0], centre[1], when, SEARCH_HALF_WIDTH_DEG
    )
    ra, dec = track_sky(field, track)
    hours = (track["t0"] - when) * 24
    best = None
    for body in bodies:
        body_dec = body["dec"] + body["dec_rate_arcsec_hr"] * hours / 3600
        body_ra = body["ra"] + body["ra_rate_arcsec_hr"] * hours / 3600 / np.cos(
            np.radians(body_dec)
        )
        sep = 3600 * np.hypot((body_ra - ra) * np.cos(np.radians(dec)), body_dec - dec)
        if sep <= MATCH_ARCSEC and (best is None or sep < best["separation_arcsec"]):
            best = {
                "name": body["name"],
                "vmag": body["vmag"],
                "separation_arcsec": round(float(sep), 1),
            }
    return best


def describe(field: dict, centre: tuple[float, float], track: dict) -> dict:
    ra, dec = track_sky(field, track)
    return {
        "ra": round(ra, 5),
        "dec": round(dec, 5),
        "mjd": round(track["t0"], 4),
        "frames": track["n_frames"],
        "rate_arcsec_hr": round(track["rate_arcsec_day"] / 24, 1),
        "span_hours": round(track["span_days"] * 24, 1),
        "known_object": match_known(field, centre, track),
    }


def unmatched_injection_tracks(field: dict, real_tracks: list[dict]) -> list[dict]:
    """Repeat the seeded injection runs and keep tracks that match no planted source."""
    rng = np.random.default_rng(SEED)
    sigma = run_engine.psf_sigma_pixels(field)
    scale = config.GRID_PIXEL_ARCSEC
    out = []
    for snr in run_engine.INJECT_SNR:
        for _ in range(run_engine.INJECT_RUNS):
            planted, sources = run_engine.plant_sources(
                field["frames"], snr, sigma, rng
            )
            maps = engine.clean_differences(planted)["maps"]
            dets = detect.detections_table(maps, "z_local")
            near_planted = np.zeros(len(dets["t"]), dtype=bool)
            for source in sources:
                for frame_index, (x, y) in source.items():
                    near_planted |= (dets["frame"] == frame_index) & (
                        np.hypot(dets["x"] - x * scale, dets["y"] - y * scale)
                        <= run_engine.MATCH_ARCSEC
                    )
            for track in detect.link_tracks(dets, config.LINK_FAST):
                on_planted = int(near_planted[np.array(track["members"])].sum())
                if on_planted >= config.LINK_MIN_FRAMES:
                    continue
                same_as_real = any(
                    abs(track["t0"] - real["t0"]) < 0.5
                    and np.hypot(track["x0"] - real["x0"], track["y0"] - real["y0"])
                    < 30
                    for real in real_tracks
                )
                out.append(
                    {
                        "track": track,
                        "peak_snr": snr,
                        "detections": len(track["members"]),
                        "detections_on_planted_sources": on_planted,
                        "same_as_real_data_track": same_as_real,
                    }
                )
    return out


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("tombaugh.archive").setLevel(logging.ERROR)
    results = {}
    for key in run_engine.MOVERS:
        target = TARGETS[key]
        ra, dec = target.get("centre") or frames.position_at(target, CENTRE_MJD)
        centre = (round(float(ra), 4), round(float(dec), 4))
        for i, detector in enumerate(target["detectors"]):
            field = frames.build_frames(
                *centre,
                FOV_DEG,
                [detector],
                MAX_PER_DETECTOR,
                collection=config.ENGINE_COLLECTION,
            )
            maps = engine.clean_differences(field["frames"])["maps"]
            dets = detect.detections_table(maps, "z_local")
            real = detect.link_tracks(dets, config.LINK_FAST)
            entry = {"real_data_tracks": [describe(field, centre, t) for t in real]}
            log.info("%s %s: %d real-data tracks", key, detector, len(real))
            if i == 0:
                extra = []
                for item in unmatched_injection_tracks(field, real):
                    row = describe(field, centre, item["track"])
                    row.update({k: v for k, v in item.items() if k != "track"})
                    extra.append(row)
                entry["unmatched_tracks_in_synthetic_runs"] = extra
                log.info(
                    "%s %s: %d unmatched tracks in synthetic runs",
                    key,
                    detector,
                    len(extra),
                )
            results[f"{key}_{detector}"] = entry
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps(results, indent=2))

    # --- Summary ---
    real = [t for r in results.values() for t in r["real_data_tracks"]]
    extra = [
        t
        for r in results.values()
        for t in r.get("unmatched_tracks_in_synthetic_runs", [])
    ]
    print(
        f"Real-data fast tracks: {len(real)}, matched to a known object: {sum(t['known_object'] is not None for t in real)}"
    )
    for name, r in results.items():
        for t in r["real_data_tracks"]:
            print(f"    {name}: {t}")
    print(f"Unmatched tracks in synthetic runs: {len(extra)}")
    print(
        f"    matched to a known object: {sum(t['known_object'] is not None for t in extra)}"
    )
    print(
        f"    same as a real-data track: {sum(t['same_as_real_data_track'] for t in extra)}"
    )
    print(
        f"    containing 1 or 2 detections of a planted source: {sum(t['detections_on_planted_sources'] > 0 for t in extra)}"
    )
    print(
        f"    none of the above: {sum(t['known_object'] is None and not t['same_as_real_data_track'] and t['detections_on_planted_sources'] == 0 for t in extra)}"
    )


if __name__ == "__main__":
    main()
