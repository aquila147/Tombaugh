"""Live field jobs: build a plate for a sky patch that has none stored.

One job runs at a time. Finished fields stay on disk and are reused.
"""

import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from app import (
    archive,
    candidates,
    checks,
    config,
    detect,
    engine,
    frames,
    overhead,
    plates,
    supabase_client,
)

log = logging.getLogger("tombaugh.jobs")

FIELDS_DIR = config.CACHE_DIR / "fields"
STEPS_TOTAL = 6

jobs: dict[str, dict] = {}
lock = threading.Lock()
worker = ThreadPoolExecutor(max_workers=1)


def public(job: dict) -> dict:
    return {k: v for k, v in job.items() if not k.startswith("_")}


# --- Starting and reusing ---


def start(ra: float, dec: float, fov_deg: float, detector: str | None) -> dict:
    """Start a job for the field that contains a position, or reuse one."""
    ra_c, dec_c, field_id = overhead.field_centre(ra, dec)
    with lock:
        for job in jobs.values():
            same = job["_key"] == (field_id, detector)
            if same and job["status"] in ("queued", "running", "done"):
                return public(job)
        job = {
            "job_id": uuid.uuid4().hex[:12],
            "status": "queued",
            "step": "Waiting for a free slot.",
            "steps_done": 0,
            "steps_total": STEPS_TOTAL,
            "error": None,
            "centre": [ra_c, dec_c, fov_deg],
            "base_url": "/api/files",
            "_key": (field_id, detector),
            "_field": field_id,
            "_detector": detector,
        }
        jobs[job["job_id"]] = job
    worker.submit(run, job)
    return public(job)


def get(job_id: str) -> dict | None:
    job = jobs.get(job_id)
    return public(job) if job else None


# --- The work ---


def advance(job: dict, text: str, done: int | None = None) -> None:
    job["step"] = text
    if done is not None:
        job["steps_done"] = done
    log.info("%s: %s", job["job_id"], text)


def choose_detector(products: list[dict], wanted: str | None) -> str | None:
    """The asked-for detector, or the one with the most exposures."""
    counts: dict[str, int] = {}
    for p in products:
        counts[p["detector"]] = counts.get(p["detector"], 0) + 1
    if wanted in counts:
        return wanted
    return max(sorted(counts), key=lambda d: counts[d]) if counts else None


def sky(field: dict, x_arcsec: float, y_arcsec: float) -> tuple[float, float]:
    scale = config.GRID_PIXEL_ARCSEC
    ra, dec = field["grid"].all_pix2world(x_arcsec / scale, y_arcsec / scale, 0)
    return round(float(ra), 5), round(float(dec), 5)


def find_candidates(
    field: dict, result: dict, key: str, name: str, centre: list
) -> list[dict]:
    """Engine candidates with their automatic checks, stored by the back end.

    Each one is saved to the candidates table with the service key and kept
    in the plate's own file, so the checks can be shown without Supabase.
    """
    dets = detect.detections_table(result["maps"], "z_local")
    run_info = {
        "plate": key,
        "detector": field["frames"][0]["detector"],
        "centre": tuple(centre),
        "field": field,
        "dets": dets,
        "mjds": np.array([f["mjd"] for f in field["frames"]]),
        "tracks": detect.link_tracks(dets, config.LINK_FAST),
        "movers": detect.find_slow_movers(
            result["trend"], result["trend_err"], result["mean_image"]
        ),
    }
    found = candidates.slow_candidates(run_info) + candidates.fast_candidates(run_info)
    context = {
        "centre": run_info["centre"],
        "field": field,
        "tracks": run_info["tracks"],
    }
    out = []
    for candidate in found[: config.LIVE_MAX_CANDIDATES]:
        outcome = checks.run_checks(candidate, context)
        row = candidates.to_row(
            candidate,
            outcome,
            name,
            "Live engine run on SPHEREx Data Release 1 exposures",
        )
        row_id = supabase_client.save_candidate(row)
        fast = candidate["kind"] == "fast"
        out.append(
            {
                "id": row_id,
                "kind": candidate["kind"],
                "ra": row["ra"],
                "dec": row["dec"],
                "rate": round(
                    candidate["rate_arcsec_hr" if fast else "rate_arcsec_yr"], 2
                ),
                "unit": "arcsec/hr" if fast else "arcsec/yr",
                "frames": candidate["n_frames"],
                "significance": row["checks"]["summary"].get("significance"),
                "status": row["status"],
                "row": row,
            }
        )
    return out


def check_at(job_id: str, ra: float, dec: float) -> dict | None:
    """Stored checks of the engine candidate nearest a position in a job's field."""
    job = jobs.get(job_id)
    if not job or job.get("status") != "done":
        return None
    meta = json.loads((FIELDS_DIR / job["field_id"] / "meta.json").read_text())
    best = None
    for candidate in meta.get("candidates", []):
        sep = float(
            checks.separation_arcsec(candidate["ra"], candidate["dec"], ra, dec)
        )
        if sep <= config.CHECK_CLICK_ARCSEC and (best is None or sep < best[0]):
            best = (sep, candidate)
    if best is None:
        return {
            "candidate": None,
            "reason": f"The engine has no candidate within {config.CHECK_CLICK_ARCSEC:.0f} "
            "arcsec of this position.",
        }
    return {"candidate": best[1], "separation_arcsec": round(best[0], 1)}


def run(job: dict) -> None:
    try:
        job["status"] = "running"
        ra, dec, fov = job["centre"]
        advance(job, "Searching the SPHEREx archive.", 0)
        note = None
        try:
            products = archive.search(ra, dec, collections=[config.ENGINE_COLLECTION])
        except RuntimeError as err:
            near = archive.cached_search_near(ra, dec, config.LIVE_REUSE_SEARCH_DEG)
            if near is None:
                raise RuntimeError(
                    "the SPHEREx archive search is not answering right now; try again later"
                ) from err
            products, sep = near
            note = (
                "The SPHEREx archive search was not answering, so this plate uses the "
                f"exposure list saved for a point {sep:.2f} degrees away. Some exposures "
                "of this patch may be missing."
            )
            log.warning("%s: %s", job["job_id"], note)
        products = [p for p in products if p["collection"] == config.ENGINE_COLLECTION]
        detector = choose_detector(products, job["_detector"])
        if detector is None:
            raise RuntimeError("SPHEREx Data Release 1 has no images of this patch")
        key = f"{job['_field']}_{detector}"
        out_dir = FIELDS_DIR / key
        name = f"RA {ra:.2f} Dec {dec:+.2f}, {detector}"
        job.update(field_id=key, name=name)

        if not (out_dir / "meta.json").is_file():
            field = frames.build_frames(
                ra,
                dec,
                fov,
                [detector],
                config.LIVE_MAX_FRAMES,
                collection=config.ENGINE_COLLECTION,
                progress=lambda text: advance(job, text, min(job["steps_done"] + 1, 2)),
                products=products,
            )
            if len(field["frames"]) < config.LIVE_MIN_FRAMES:
                raise RuntimeError(
                    f"only {len(field['frames'])} usable {detector} exposures of this patch"
                )
            advance(job, "Stacking each visit.", 3)
            stacks = frames.stack_visits(field["frames"])
            advance(job, "Running the engine: per-pixel noise and time fit.", 4)
            result = engine.clean_differences(field["frames"])
            found = find_candidates(field, result, key, name, job["centre"])
            advance(job, "Writing the plates.", 5)
            show = frames.pick_evenly(list(range(len(field["frames"]))), 40)
            plates.write_engine_view(
                out_dir / "engine", field["frames"], result["maps"], show
            )
            plates.write_plate(
                out_dir,
                key,
                name,
                field,
                stacks,
                (ra, dec, fov),
                extra={"kind": "live", "candidates": found, "note": note},
            )
        meta = json.loads((out_dir / "meta.json").read_text())
        job["candidates"] = len(meta.get("candidates", []))
        job["frames"] = len(meta["frames"])
        advance(job, "Done.", STEPS_TOTAL)
        job["status"] = "done"
    except Exception as err:  # noqa: BLE001 - report every failure to the visitor
        log.exception("job %s failed", job["job_id"])
        job["status"] = "failed"
        job["error"] = str(err) or type(err).__name__
        job["step"] = "Stopped."
