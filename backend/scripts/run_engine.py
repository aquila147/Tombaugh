"""Phase 4 measurements for the clean-difference engine, on Data Release 1 only.

For each showcase mover field and detector this reports:
  1. residual peaks per frame at 5 sigma, before (plain differences) and after
  2. whether the known target is still recovered in the clean residuals
  3. an injection test with SYNTHETIC moving point sources

The synthetic sources exist only in memory during this test. They are never
written to the frames served by the site.

Run from backend/:  python -m scripts.run_engine [target ...]
Writes docs/data/validation/engine.json
"""

import json
import logging
import sys

import numpy as np

from app import config, detect, engine, frames
from scripts.build_showcase import CENTRE_MJD, FOV_DEG, MAX_PER_DETECTOR, TARGETS

log = logging.getLogger("tombaugh.engine")

OUT = config.BACKEND_DIR.parent / "docs" / "data" / "validation" / "engine.json"
MOVERS = ["wise0855", "barnard", "eps_indi_b"]

# Injection test settings
INJECT_SNR = [5, 7, 10, 15, 25]
INJECT_PER_RUN = 10
INJECT_RUNS = 3
INJECT_RATE_ARCSEC_HR = (5.0, 60.0)
PASS_GAP_DAYS = 3.0
MATCH_ARCSEC = 4.5
TARGET_MATCH_ARCSEC = 12.0


# --- Before and after ---


def peaks_per_frame(maps: list[dict], key: str) -> dict:
    counts = [len(detect.find_peaks(m[key])) for m in maps]
    return {
        "median": float(np.median(counts)),
        "mean": round(float(np.mean(counts)), 2),
        "total": int(np.sum(counts)),
        "frames": len(counts),
    }


def before_after(field_frames: list[dict], clean: dict) -> dict:
    first = engine.plain_differences(field_frames[1:], field_frames[0]["image"])
    median = engine.plain_differences(field_frames, engine.median_image(field_frames))
    return {
        "plain_vs_first_frame": peaks_per_frame(first, "z"),
        "plain_vs_median": peaks_per_frame(median, "z"),
        "plain_vs_median_local_noise": peaks_per_frame(median, "z_local"),
        "fit_only": peaks_per_frame(clean["fit"]["maps"], "z"),
        "fit_only_local_noise": peaks_per_frame(clean["fit"]["maps"], "z_local"),
        "fit_and_match": peaks_per_frame(clean["match"]["maps"], "z"),
        "fit_and_match_local_noise": peaks_per_frame(clean["match"]["maps"], "z_local"),
    }


# --- Target recovery ---


def target_track(
    field: dict, target: dict, mjds: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Catalogue position of the target at each date, in arcsec on the grid."""
    pos = [frames.position_at(target, mjd) for mjd in mjds]
    x, y = field["grid"].all_world2pix([p[0] for p in pos], [p[1] for p in pos], 0)
    return x * config.GRID_PIXEL_ARCSEC, y * config.GRID_PIXEL_ARCSEC


def recovery(field: dict, target: dict, result: dict, dets: dict) -> dict:
    """Is the known target found again, blind, in the engine output?

    Slow movers are searched in the per-pixel time slope. The catalogue
    position is used only afterwards, to see which candidate is the target.
    """
    maps = result["maps"]
    mjds = np.array([m["mjd"] for m in maps])
    tx, ty = target_track(field, target, mjds)
    near = np.hypot(dets["x"] - tx[dets["frame"]], dets["y"] - ty[dets["frame"]])
    movers = detect.find_slow_movers(
        result["trend"], result["trend_err"], result["mean_image"]
    )
    out = {
        "frames": len(maps),
        "span_years": round(float(np.ptp(mjds)) / 365.25, 2),
        "frames_with_residual_detection": int(
            len(np.unique(dets["frame"][near <= TARGET_MATCH_ARCSEC]))
        ),
        "slow_mover_candidates_in_field": len(movers),
        "recovered": False,
    }
    scale = config.GRID_PIXEL_ARCSEC
    for mover in sorted(movers, key=lambda m: -m["snr"]):
        offset = np.hypot(
            mover["x"] * scale - tx.mean(), mover["y"] * scale - ty.mean()
        )
        if offset <= TARGET_MATCH_ARCSEC:
            out["recovered"] = True
            out["offset_arcsec"] = round(float(offset), 1)
            out["snr"] = round(mover["snr"], 1)
            out["rate_arcsec_yr"] = round(mover["rate_arcsec_yr"], 2)
            out["rate_err_arcsec_yr"] = round(mover["rate_err_arcsec_yr"], 2)
            out["pm_east_arcsec_yr"] = round(mover["pm_east_arcsec_yr"], 2)
            out["pm_north_arcsec_yr"] = round(mover["pm_north_arcsec_yr"], 2)
            out["catalogue_pm_east_north"] = [target["pm_ra"], target["pm_dec"]]
            out["rank_in_field"] = 1 + sum(m["snr"] > mover["snr"] for m in movers)
            out["field_calibration"] = {
                k: mover[k]
                for k in [
                    "error_scale",
                    "star_drift_arcsec_yr",
                    "star_spread_arcsec_yr",
                    "stars_used",
                ]
            }
            break
    return out


# --- Injection test (synthetic sources) ---


def psf_sigma_pixels(field: dict) -> float:
    """Width of a star on the grid, from flux over peak of bright isolated stars."""
    widths = []
    ok = frames.isolated_stars(field["stars"])
    ra = [s["ra"] for s in field["stars"]]
    dec = [s["dec"] for s in field["stars"]]
    xs, ys = field["grid"].all_world2pix(ra, dec, 0)
    for frame in field["frames"][:: max(1, len(field["frames"]) // 15)]:
        image = frame["image"]
        for x, y, keep in zip(xs, ys, ok):
            xi, yi = int(round(float(x))), int(round(float(y)))
            if not keep or not (
                8 <= xi < image.shape[1] - 8 and 8 <= yi < image.shape[0] - 8
            ):
                continue
            box = image[yi - 6 : yi + 7, xi - 6 : xi + 7]
            if np.isfinite(box).all() and box.max() > 30 * frame["noise"]:
                widths.append(np.sqrt(box.sum() / (2 * np.pi * box.max())))
    return float(np.median(widths)) if widths else 1.5


def passes(mjds: np.ndarray) -> list[np.ndarray]:
    """Frame indices grouped into passes; only passes a mover could be linked in."""
    order = np.argsort(mjds)
    groups = np.split(order, np.flatnonzero(np.diff(mjds[order]) > PASS_GAP_DAYS) + 1)
    return [g for g in groups if len(g) >= 3 and np.ptp(mjds[g]) >= 0.05]


def plant_sources(
    field_frames: list[dict], snr: float, sigma: float, rng
) -> tuple[list, list]:
    """Copy the frames and add SYNTHETIC movers. Returns frames and source tracks."""
    mjds = np.array([f["mjd"] for f in field_frames])
    size = field_frames[0]["image"].shape[0]
    images = [f["image"].copy() for f in field_frames]
    yy, xx = np.mgrid[0:size, 0:size]
    groups = passes(mjds)
    sources = []
    tries = 0
    while len(sources) < INJECT_PER_RUN and tries < 500 and groups:
        tries += 1
        group = groups[rng.integers(len(groups))]
        rate = rng.uniform(*INJECT_RATE_ARCSEC_HR) * 24 / config.GRID_PIXEL_ARCSEC
        angle = rng.uniform(0, 2 * np.pi)
        x0, y0 = rng.uniform(15, size - 15, 2)
        dt = mjds[group] - mjds[group].min()
        px = x0 + rate * np.cos(angle) * dt
        py = y0 + rate * np.sin(angle) * dt
        inside = (px > 6) & (px < size - 7) & (py > 6) & (py < size - 7)
        seen = [
            i
            for i, x, y, ok in zip(group, px, py, inside)
            if ok
            and np.isfinite(field_frames[i]["image"][int(round(y)), int(round(x))])
        ]
        if len(seen) < config.LINK_MIN_FRAMES:
            continue
        where = {int(i): (float(x), float(y)) for i, x, y in zip(group, px, py)}
        shift = np.hypot(
            where[seen[-1]][0] - where[seen[0]][0],
            where[seen[-1]][1] - where[seen[0]][1],
        )
        if shift * config.GRID_PIXEL_ARCSEC < config.LINK_FAST["min_shift"]:
            continue
        for i in seen:
            x, y = where[i]
            blob = np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma**2))
            images[i] = images[i] + snr * field_frames[i]["noise"] * blob
        sources.append({i: where[i] for i in seen})
    planted = [dict(f, image=image) for f, image in zip(field_frames, images)]
    return planted, sources


def count_recovered(
    dets: dict, tracks: list[dict], sources: list[dict]
) -> tuple[int, int, int]:
    """Sources linked into a track, sources seen in 3 or more frames, tracks left over."""
    scale = config.GRID_PIXEL_ARCSEC
    matched_tracks = set()
    linked = seen3 = 0
    for source in sources:
        near = np.zeros(len(dets["t"]), dtype=bool)
        for frame_index, (x, y) in source.items():
            near |= (dets["frame"] == frame_index) & (
                np.hypot(dets["x"] - x * scale, dets["y"] - y * scale) <= MATCH_ARCSEC
            )
        seen3 += len(np.unique(dets["frame"][near])) >= config.LINK_MIN_FRAMES
        for index, track in enumerate(tracks):
            if near[np.array(track["members"])].sum() >= config.LINK_MIN_FRAMES:
                matched_tracks.add(index)
                linked += 1
                break
    return linked, seen3, len(tracks) - len(matched_tracks)


def injection_test(field: dict, match: bool, baseline_tracks: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    sigma = psf_sigma_pixels(field)
    out = {"psf_sigma_arcsec": round(sigma * config.GRID_PIXEL_ARCSEC, 2), "levels": []}
    for snr in INJECT_SNR:
        planted_total = linked_total = seen_total = extra_total = 0
        for _ in range(INJECT_RUNS):
            planted, sources = plant_sources(field["frames"], snr, sigma, rng)
            maps = engine.clean_differences(planted, match=match)["maps"]
            dets = detect.detections_table(maps, "z_local")
            tracks = detect.link_tracks(dets, config.LINK_FAST)
            linked, seen3, left = count_recovered(dets, tracks, sources)
            planted_total += len(sources)
            linked_total += linked
            seen_total += seen3
            extra_total += max(0, left - baseline_tracks)
        out["levels"].append(
            {
                "peak_snr": snr,
                "planted": planted_total,
                "seen_in_3_frames": seen_total,
                "linked": linked_total,
                "fraction_linked": round(linked_total / max(planted_total, 1), 3),
                "extra_false_tracks": extra_total,
            }
        )
        log.info(
            "  synthetic snr %s: %d of %d linked", snr, linked_total, planted_total
        )
    return out


# --- One field and detector ---


def run(key: str, detector: str, inject: bool) -> dict:
    target = TARGETS[key]
    ra, dec = target.get("centre") or frames.position_at(target, CENTRE_MJD)
    ra, dec = round(float(ra), 4), round(float(dec), 4)
    field = frames.build_frames(
        ra,
        dec,
        FOV_DEG,
        [detector],
        MAX_PER_DETECTOR,
        collection=config.ENGINE_COLLECTION,
    )
    field_frames = field["frames"]
    log.info(
        "%s %s: %d frames from %s",
        key,
        detector,
        len(field_frames),
        config.ENGINE_COLLECTION,
    )

    clean = {
        "fit": engine.clean_differences(field_frames, match=False),
        "match": engine.clean_differences(field_frames, match=True),
    }
    result = {
        "target": target["name"],
        "detector": detector,
        "collection": config.ENGINE_COLLECTION,
        "frames": len(field_frames),
        "area_sq_deg": FOV_DEG**2,
        "peaks_per_frame_5_sigma": before_after(field_frames, clean),
        "variants": {},
    }
    for name, cleaned in clean.items():
        dets = detect.detections_table(cleaned["maps"], "z_local")
        fast = detect.link_tracks(dets, config.LINK_FAST)
        variant = {
            "detections": int(len(dets["t"])),
            "target_recovery": recovery(field, target, cleaned, dets),
            "fast_tracks_in_real_data": len(fast),
        }
        if inject:
            variant["injection_synthetic"] = injection_test(
                field, name == "match", len(fast), seed=20261115
            )
        result["variants"][name] = variant
    return result


def print_summary(results: dict) -> None:
    for name, r in results.items():
        p = r["peaks_per_frame_5_sigma"]
        print(f"{name}: {r['frames']} frames, {r['collection']}")
        for label, entry in p.items():
            print(
                f"    peaks per frame  {label:30s} mean {entry['mean']:7.2f}  median {entry['median']:5.1f}"
            )
        for variant, v in r["variants"].items():
            print(f"    [{variant}] target: {v['target_recovery']}")
            print(
                f"    [{variant}] fast tracks in real data: {v['fast_tracks_in_real_data']}"
            )
            for level in v.get("injection_synthetic", {}).get("levels", []):
                print(
                    f"    [{variant}] synthetic snr {level['peak_snr']:>2}: linked {level['linked']}/{level['planted']}"
                    f" ({level['fraction_linked']:.2f}), extra false tracks {level['extra_false_tracks']}"
                )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("tombaugh.archive").setLevel(logging.ERROR)
    keys = sys.argv[1:] or MOVERS
    results = json.loads(OUT.read_text()) if OUT.is_file() else {}
    for key in keys:
        for i, detector in enumerate(TARGETS[key]["detectors"]):
            # Injection on the first detector of each field keeps the run short
            results[f"{key}_{detector}"] = run(key, detector, inject=i == 0)
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps(results, indent=2))
    print_summary(results)


if __name__ == "__main__":
    main()
