"""Brown dwarf score on two brown dwarfs and two negative controls.

WISE 0855 and Epsilon Indi B are the brown dwarfs. Barnard's Star (a red
dwarf) and the asteroid 120 Lachesis are the controls. Each is compared with
ordinary Gaia stars measured the same way in the same images. The motion
numbers are the ones already measured by build_showcase.py and build_demo.py.

Run from backend/:  python -m scripts.score_brown_dwarfs [target ...]
Writes docs/data/validation/browndwarf.json
"""

import json
import logging
import sys

import numpy as np

from app import archive, browndwarf, config, frames
from scripts import build_demo
from scripts.build_showcase import CENTRE_MJD, FOV_DEG, OUT_DIR, TARGETS

OUT = config.BACKEND_DIR.parent / "docs" / "data" / "validation" / "browndwarf.json"
DETECTORS = ["D4", "D5"]
MAX_PER_DETECTOR = 60
STAR_G_LIMIT = 15.0
BLANK_POSITIONS = 60
BLANK_CLEAR_ARCSEC = 30.0
ROLES = {
    "wise0855": "brown dwarf",
    "eps_indi_b": "brown dwarf",
    "barnard": "control: red dwarf star",
    "singapore": "control: asteroid",
}


def rounded(value: dict | None, digits: int = 3) -> dict | None:
    if value is None:
        return None
    return {
        k: round(v, digits) if isinstance(v, float) else v for k, v in value.items()
    }


def load_field(key: str, summary: dict) -> tuple[dict, dict, float, float]:
    """Frames, the target's track, and its measured rate in arcsec per year."""
    if key == "singapore":
        mid = 0.5 * (build_demo.WINDOW[0] + build_demo.WINDOW[1])
        body = build_demo.asteroid_at(mid)
        target = {
            "name": body["name"],
            "ra": body["ra"],
            "dec": body["dec"],
            "epoch_mjd": mid,
            "pm_ra": body["ra_rate_arcsec_hr"] * build_demo.HOURS_PER_YEAR,
            "pm_dec": body["dec_rate_arcsec_hr"] * build_demo.HOURS_PER_YEAR,
        }
        field = frames.build_frames(
            round(body["ra"], 4),
            round(body["dec"], 4),
            build_demo.FOV_DEG,
            DETECTORS,
            None,
            config.ENGINE_COLLECTION,
            select=lambda chosen: [
                p
                for p in chosen
                if build_demo.WINDOW[0] <= p["mjd"] <= build_demo.WINDOW[1]
            ],
            products=archive.search(*build_demo.ANCHOR),
        )
        c = summary[key]["confirmation"]
        rate = c["measured_rate_arcsec_hr"] * build_demo.HOURS_PER_YEAR
        err = c["measured_rate_err_arcsec_hr"] * build_demo.HOURS_PER_YEAR
        return field, target, rate, err
    target = TARGETS[key]
    ra, dec = target.get("centre") or frames.position_at(target, CENTRE_MJD)
    field = frames.build_frames(
        round(float(ra), 4),
        round(float(dec), 4),
        FOV_DEG,
        DETECTORS,
        MAX_PER_DETECTOR,
        config.ENGINE_COLLECTION,
    )
    fit = summary[key]["motion_fit"]
    return field, target, fit["rate_arcsec_yr"], fit["rate_err_arcsec_yr"]


def blank_sky(field: dict) -> dict:
    """Offset and scatter of the same photometry at positions with no Gaia star."""
    rng = np.random.default_rng(1930)
    size = field["size"]
    star_xy = np.array(
        [field["grid"].all_world2pix(s["ra"], s["dec"], 0) for s in field["stars"]]
    ).reshape(-1, 2)
    clear = BLANK_CLEAR_ARCSEC / config.GRID_PIXEL_ARCSEC
    fluxes: dict[str, list[float]] = {"methane": [], "continuum": [], "short": []}
    for x, y in rng.uniform(20, size - 20, (BLANK_POSITIONS * 5, 2)):
        if len(star_xy) and np.hypot(*(star_xy - [x, y]).T).min() < clear:
            continue
        ra, dec = (float(v) for v in field["grid"].all_pix2world(x, y, 0))
        points = browndwarf.measure_points(
            field["frames"], field["grid"], lambda mjd: (ra, dec)
        )
        if not len(points):
            continue
        for name, band in browndwarf.band_fluxes(points).items():
            if band:
                fluxes[name].append(band["flux"])
        if len(fluxes["continuum"]) >= BLANK_POSITIONS:
            break
    return {name: browndwarf.star_reference(values) for name, values in fluxes.items()}


def passing(features: list[dict], reference: dict | None) -> int | None:
    if reference is None:
        return None
    return sum(
        browndwarf.sigma_below(f, reference) >= browndwarf.FEATURE_SIGMA
        for f in features
    )


def score_target(key: str, summary: dict) -> dict:
    field, target, rate, rate_err = load_field(key, summary)
    grid = field["grid"]
    sky = blank_sky(field)

    # --- Field stars measured the same way ---
    isolated = frames.isolated_stars(field["stars"]) if field["stars"] else []
    star_methane, star_colour = [], []
    for star, ok in zip(field["stars"], isolated):
        if not ok or star["g"] > STAR_G_LIMIT:
            continue
        points = browndwarf.measure_points(
            field["frames"], grid, lambda mjd, s=star: (s["ra"], s["dec"])
        )
        if not len(points):
            continue
        got = browndwarf.spectral_features(points, sky)
        if got["methane_index"]:
            star_methane.append(got["methane_index"])
        if got["short_over_long"]:
            star_colour.append(got["short_over_long"])
    ref_methane = browndwarf.star_reference([s["value"] for s in star_methane])
    ref_colour = browndwarf.star_reference([s["value"] for s in star_colour])
    # Ordinary stars that would wrongly pass a spectral feature
    stars_passing = {
        "methane": passing(star_methane, ref_methane),
        "colour": passing(star_colour, ref_colour),
    }

    # --- The target ---
    points = browndwarf.measure_points(
        field["frames"], grid, lambda mjd: frames.position_at(target, mjd)
    )
    got = (
        browndwarf.spectral_features(points, sky)
        if len(points)
        else {"bands": {}, "methane_index": None, "short_over_long": None}
    )
    methane_sigma = browndwarf.sigma_below(got["methane_index"], ref_methane)
    colour_sigma = browndwarf.sigma_below(got["short_over_long"], ref_colour)
    result = {
        "name": summary[key]["name"],
        "role": ROLES[key],
        "exposures": len(field["frames"]),
        "exposures_measured": len(points),
        "rate_arcsec_yr": round(rate, 2),
        "rate_err_arcsec_yr": round(rate_err, 2),
        "bands": {k: rounded(v) for k, v in got["bands"].items()},
        "methane_index": rounded(got["methane_index"]),
        "short_over_long": rounded(got["short_over_long"]),
        "blank_sky": {k: rounded(v) for k, v in sky.items()},
        "field_stars": {
            "methane_index": rounded(ref_methane),
            "short_over_long": rounded(ref_colour),
        },
        "field_stars_passing": stars_passing,
        "methane_sigma_below_stars": (
            None if methane_sigma is None else round(methane_sigma, 1)
        ),
        "colour_sigma_below_stars": (
            None if colour_sigma is None else round(colour_sigma, 1)
        ),
        "result": browndwarf.score(rate, rate_err, methane_sigma, colour_sigma),
    }
    print(json.dumps(result, indent=2))
    return result


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    summary = json.loads((OUT_DIR / "summary.json").read_text())
    keys = sys.argv[1:] or list(ROLES)
    results = json.loads(OUT.read_text()) if OUT.is_file() else {}
    for key in keys:
        results[key] = score_target(key, summary)
        if len(sys.argv) == 1:
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
