"""Find a bright known asteroid in SPHEREx frames near Singapore's zenith.

Singapore's zenith is at Dec +1.35. The ecliptic crosses that declination near
RA 3.1 and RA 176.9. For dates inside the SPHEREx passes over those places we
ask JPL Small-Body Identification for asteroids brighter than the limit in a
strip along the zenith declination, then count the SPHEREx exposures that
contain each one within half a day.

Run from backend/:  python -m scripts.find_demo_asteroid
Writes cache/demo_candidates.json
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from astropy.time import Time

from app import archive, catalogs, config

ZENITH_DEC = 1.35
STRIP_HALF_RA_DEG = 6.0
STRIP_HALF_DEC_DEG = 0.4
VMAG_LIMIT = 17
WINDOW_DAYS = 0.5
# (RA of the ecliptic crossing, dates inside a SPHEREx pass there)
PASSES = [
    (176.9, ["2025-05-14", "2025-05-17", "2025-05-20"]),
    (176.9, ["2025-12-18", "2025-12-21", "2025-12-24"]),
    (3.1, ["2025-06-25", "2025-06-29", "2025-07-03"]),
    (3.1, ["2025-12-13", "2025-12-18", "2025-12-23"]),
]


def strip_query(job: tuple) -> list[dict]:
    ra, date = job
    mjd = Time(f"{date}T12:00:00", scale="utc").mjd
    bodies = catalogs.known_small_bodies(
        ra, ZENITH_DEC, mjd, STRIP_HALF_RA_DEG, STRIP_HALF_DEC_DEG, VMAG_LIMIT
    )
    return [dict(b, mjd=mjd, date=date) for b in bodies]


def coverage(body: dict) -> dict:
    """SPHEREx DR1 exposures that contain the asteroid within the time window."""
    out = dict(body, exposures=0, visits=0, detectors={})
    try:
        products = archive.search(
            round(body["ra"], 4),
            round(body["dec"], 4),
            collections=[config.ENGINE_COLLECTION],
        )
    except RuntimeError:
        return out
    near = [
        p
        for p in products
        if p["collection"] == config.ENGINE_COLLECTION
        and abs(p["mjd"] - body["mjd"]) <= WINDOW_DAYS
    ]
    times = np.array(sorted({round(p["mjd"], 3) for p in near}))
    out["exposures"] = len(near)
    out["visits"] = (
        int(1 + (np.diff(times) > config.VISIT_GAP_HOURS / 24).sum())
        if len(times)
        else 0
    )
    for p in near:
        out["detectors"][p["detector"]] = out["detectors"].get(p["detector"], 0) + 1
    return out


def main() -> None:
    logging.basicConfig(level=logging.ERROR)
    jobs = [(ra, date) for ra, dates in PASSES for date in dates]
    # JPL answers 429 to parallel requests, so ask one at a time
    with ThreadPoolExecutor(max_workers=1) as pool:
        bodies = [b for group in pool.map(strip_query, jobs) for b in group]
        print(len(bodies), "asteroid positions brighter than V", VMAG_LIMIT)
    # IRSA is fine with a few searches at once; JPL is not
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(coverage, bodies))
    rows.sort(key=lambda r: (-r["visits"], float(r["vmag"] or 99)))
    (config.CACHE_DIR / "demo_candidates.json").write_text(json.dumps(rows, indent=1))
    for r in rows[:25]:
        print(
            f"{r['name']:28s} V {r['vmag']:>5} {r['date']} RA {r['ra']:8.4f} Dec {r['dec']:+7.4f}"
            f" rate {np.hypot(r['ra_rate_arcsec_hr'], r['dec_rate_arcsec_hr']):5.1f} arcsec/hr"
            f" exposures {r['exposures']:3d} visits {r['visits']} {r['detectors']}"
        )


if __name__ == "__main__":
    main()
