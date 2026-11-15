"""Run the automatic checks on real engine outputs and store the candidates.

Every candidate here is something the engine found in real SPHEREx Data
Release 1 exposures of the showcase fields and the Singapore demo field:
slow-mover candidates from the per-pixel time fit and fast tracks from the
residual linker. Nothing is invented and nothing synthetic is stored. Each
gets the status the checks support.

Run from backend/:  python -m scripts.seed_candidates
Writes the candidates table in Supabase (service key) and docs/data/candidates.json
"""

import json
import logging

import numpy as np
from astropy.time import Time

from app import archive, checks, config, detect, engine, frames, supabase_client
from app import candidates as engine_candidates
from scripts import build_demo
from scripts.build_showcase import CENTRE_MJD, FOV_DEG, MAX_PER_DETECTOR, TARGETS

log = logging.getLogger("tombaugh.seed")

OUT = config.BACKEND_DIR.parent / "docs" / "data" / "candidates.json"
MERGE_ARCSEC = 15.0
SOURCE = "Engine output on real SPHEREx Data Release 1 exposures (scripts/seed_candidates.py)"
# (plate, detector, the other detector processed for that field)
RUNS = [
    ("singapore", "D2", "D5"),
    ("singapore", "D5", "D2"),
    ("wise0855", "D5", "D6"),
    ("wise0855", "D6", "D5"),
    ("barnard", "D3", "D4"),
    ("barnard", "D4", "D3"),
    ("eps_indi_b", "D2", "D3"),
    ("eps_indi_b", "D3", "D2"),
]
FIELD_NAMES = {
    "singapore": "Above Singapore",
    "wise0855": "WISE 0855 field",
    "barnard": "Barnard's Star field",
    "eps_indi_b": "Epsilon Indi B field",
}


# --- Engine runs ---


def build_run(plate: str, detector: str) -> dict:
    if plate == "singapore":
        body = build_demo.asteroid_at(0.5 * sum(build_demo.WINDOW))
        centre = (round(body["ra"], 4), round(body["dec"], 4), build_demo.FOV_DEG)
        field = frames.build_frames(
            centre[0],
            centre[1],
            centre[2],
            [detector],
            None,
            config.ENGINE_COLLECTION,
            products=archive.search(*build_demo.ANCHOR),
        )
    else:
        target = TARGETS[plate]
        ra, dec = target.get("centre") or frames.position_at(target, CENTRE_MJD)
        centre = (round(float(ra), 4), round(float(dec), 4), FOV_DEG)
        field = frames.build_frames(
            centre[0],
            centre[1],
            centre[2],
            [detector],
            MAX_PER_DETECTOR,
            config.ENGINE_COLLECTION,
        )
    result = engine.clean_differences(field["frames"])
    dets = detect.detections_table(result["maps"], "z_local")
    run = {
        "plate": plate,
        "detector": detector,
        "centre": centre,
        "field": field,
        "dets": dets,
        "mjds": np.array([f["mjd"] for f in field["frames"]]),
        "tracks": detect.link_tracks(dets, config.LINK_FAST),
        "movers": detect.find_slow_movers(
            result["trend"], result["trend_err"], result["mean_image"]
        ),
    }
    log.info(
        "%s %s: %d exposures, %d fast tracks, %d slow candidates",
        plate,
        detector,
        len(field["frames"]),
        len(run["tracks"]),
        len(run["movers"]),
    )
    return run


def same_object(a: dict, b: dict) -> bool:
    """Two candidates from different detectors of one field that are one object."""
    if a["run"]["plate"] != b["run"]["plate"] or a["kind"] != b["kind"]:
        return False
    if a["run"]["detector"] == b["run"]["detector"]:
        return False
    if a["kind"] == "slow":
        return (
            checks.separation_arcsec(a["ra"], a["dec"], b["ra"], b["dec"])
            <= MERGE_ARCSEC
        )
    # Fast tracks: compare where each one is at the other's mean time
    dt = b["mjd"] - a["mjd"]
    if abs(dt) > 1.0:
        return False
    gap = np.hypot(a["x0"] + a["vx"] * dt - b["x0"], a["y0"] + a["vy"] * dt - b["y0"])
    return bool(gap <= MERGE_ARCSEC)


def merge(candidates: list[dict]) -> list[dict]:
    """One entry per object: the same thing found in two detectors is merged."""
    kept: list[dict] = []
    order = sorted(
        candidates, key=lambda c: -c.get("significance", c.get("n_frames", 0))
    )
    for c in order:
        twin = next((k for k in kept if same_object(k, c)), None)
        if twin:
            twin.setdefault("also_seen_in", []).append(c["run"]["detector"])
        else:
            kept.append(c)
    return kept


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("tombaugh.archive").setLevel(logging.ERROR)
    runs = {(plate, det): build_run(plate, det) for plate, det, _ in RUNS}
    found = []
    for run in runs.values():
        found += engine_candidates.fast_candidates(run)
        found += engine_candidates.slow_candidates(run)
    candidates = merge(found)
    literature = [TARGETS[k] for k in ("wise0855", "barnard", "eps_indi_b")]

    removed = supabase_client.delete_from_source(SOURCE)
    log.info("Replaced %d rows stored by an earlier run of this script", removed)
    rows = []
    for candidate in candidates:
        run = candidate["run"]
        other_det = next(
            o for p, d, o in RUNS if (p, d) == (run["plate"], run["detector"])
        )
        context = {
            "centre": run["centre"],
            "field": run["field"],
            "tracks": run["tracks"],
            "other": runs[(run["plate"], other_det)],
            "literature": literature,
        }
        outcome = checks.run_checks(candidate, context)
        row = engine_candidates.to_row(
            candidate, outcome, FIELD_NAMES[run["plate"]], SOURCE
        )
        row_id = supabase_client.save_candidate(row)
        rows.append({"id": row_id, **row})
        log.info("%s -> %s", row["checks"]["summary"]["label"], row["status"])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, indent=1))
    stored = sum(r["id"] is not None for r in rows)
    print(
        f"{len(found)} engine outputs, {len(rows)} candidates after merging, {stored} stored in Supabase"
    )
    for r in rows:
        s = r["checks"]["summary"]
        print(
            f"\n[{r['status']}] {s['label']}  ({s['motion']}; also in {s['also_seen_in'] or 'no other detector'})"
        )
        for i in r["checks"]["items"]:
            print(f"    {i['result']:5s} {i['title']}: {i['reason']}")


if __name__ == "__main__":
    main()
