"""Print every headline number quoted in the README, with where it comes from.

The numbers are read from the result files that the other scripts write, so
this takes seconds. To regenerate a number from the SPHEREx data, run the
script named beside it (from backend/, as python -m scripts.<name>).

Run from backend/:  python -m scripts.validate
"""

import json
import re
from collections import Counter

import requests

from app import config

DOCS = config.BACKEND_DIR.parent / "docs"
SHOWCASE = DOCS / "data" / "showcase"
VALIDATION = DOCS / "data" / "validation"
STARS = ["wise0855", "barnard", "eps_indi_b", "rw_aur", "r_dra"]
MOVERS = ["wise0855", "barnard", "eps_indi_b"]


def load(path):
    return json.loads(path.read_text())


def section(title: str, script: str) -> None:
    print(f"\n=== {title}  [scripts/{script}] ===")


def main() -> None:
    summary = load(SHOWCASE / "summary.json")
    engine = load(VALIDATION / "engine.json")
    tracks = load(VALIDATION / "track_check.json")
    sampling = load(VALIDATION / "sampling.json")
    candidates = load(DOCS / "data" / "candidates.json")

    section("Motion from centroids on visit stacks", "build_showcase.py")
    for key in MOVERS:
        s = summary[key]
        f = s["motion_fit"]
        print(
            f"{s['name']:16s} {f['rate_arcsec_yr']:.2f} +/- {f['rate_err_arcsec_yr']:.2f} arcsec/yr, "
            f"published {s['published_rate_arcsec_yr']}, {f['n_points']} visits, {f['baseline_yr']:.2f} yr"
        )
    p = summary["eps_indi_b"]["motion_fit_with_parallax"]
    print(
        f"Epsilon Indi B with parallax: {p['rate_arcsec_yr']:.2f} +/- {p['rate_err_arcsec_yr']:.2f} arcsec/yr, "
        f"parallax {p['parallax_arcsec']:.2f} +/- {p['parallax_err_arcsec']:.2f} arcsec"
    )

    section("Gaia alignment, five showcase fields", "build_showcase.py")
    for key in STARS:
        a = summary[key]["alignment"]
        print(
            f"{summary[key]['name']:16s} aligned {a['frames_aligned']}/{a['frames']}, "
            f"stars/frame {a['median_stars_per_frame']:.0f}, header offset {a['median_offset_arcsec']:.2f}, "
            f"single-star scatter {a['median_scatter_arcsec']:.2f}, frame-to-frame {a['frame_shift_std_arcsec']:.2f} arcsec"
        )
    scatter = [summary[k]["alignment"]["median_scatter_arcsec"] for k in STARS]
    shift = [summary[k]["alignment"]["frame_shift_std_arcsec"] for k in STARS]
    frames_total = sum(summary[k]["alignment"]["frames"] for k in STARS)
    finast = sum(summary[k]["alignment"]["finast_solved"] for k in STARS)
    print(f"single-star scatter range {min(scatter):.2f} to {max(scatter):.2f} arcsec")
    print(f"frame-to-frame shift range {min(shift):.2f} to {max(shift):.2f} arcsec")
    print(f"FINAST solved in {finast} of {frames_total} frames")

    section("Star brightness against single-pixel scatter", "measure_sampling.py")
    total = [s["total_brightness_rms_percent"] for s in sampling["stars"]]
    pixel = [s["centre_pixel_rms_percent"] for s in sampling["stars"]]
    print(f"{sampling['field']} {sampling['detector']}, {len(total)} stars")
    print(
        f"total brightness changes {min(total)} to {max(total)} percent between exposures"
    )
    print(
        f"centre pixel changes {min(pixel)} to {max(pixel)} percent between exposures"
    )

    section("Residual peaks per exposure at 5 sigma, DR1 only", "run_engine.py")
    for name, run in engine.items():
        p = run["peaks_per_frame_5_sigma"]
        print(
            f"{name:14s} {run['frames']:3d} exposures: plain {p['plain_vs_median']['mean']:7.2f}, "
            f"wavelength fit only {p['fit_only']['mean']:7.2f}, engine per-pixel noise "
            f"{p['fit_only_local_noise']['mean']:5.2f}, plain with per-pixel noise "
            f"{p['plain_vs_median_local_noise']['mean']:5.2f}"
        )

    section("Blind slow-mover search", "run_engine.py")
    for name, run in engine.items():
        r = run["variants"]["fit"]["target_recovery"]
        others = r["slow_mover_candidates_in_field"] - (1 if r["recovered"] else 0)
        if r["recovered"]:
            print(
                f"{name:14s} found, {r['snr']} sigma, engine rate {r['rate_arcsec_yr']} +/- "
                f"{r['rate_err_arcsec_yr']} arcsec/yr, other candidates {others}"
            )
        else:
            print(f"{name:14s} not found, other candidates {others}")

    section("Injection test, SYNTHETIC sources", "run_engine.py")
    levels: dict[int, list[int]] = {}
    for run in engine.values():
        for level in (
            run["variants"]["fit"].get("injection_synthetic", {}).get("levels", [])
        ):
            got = levels.setdefault(level["peak_snr"], [0, 0])
            got[0] += level["linked"]
            got[1] += level["planted"]
    for snr, (linked, planted) in sorted(levels.items()):
        print(
            f"peak signal to noise {snr:2d}: {linked}/{planted} linked = {100 * linked / planted:.0f} percent"
        )
    real = sum(
        run["variants"]["fit"]["fast_tracks_in_real_data"] for run in engine.values()
    )
    area = sum(run["area_sq_deg"] for run in engine.values())
    print(
        f"fast tracks in real data: {real} over {area:.2f} sq deg = {real / area:.0f} per sq deg"
    )

    section("Tracks against JPL Small-Body Identification", "check_tracks.py")
    real_tracks = [t for r in tracks.values() for t in r["real_data_tracks"]]
    extra = [
        t
        for r in tracks.values()
        for t in r.get("unmatched_tracks_in_synthetic_runs", [])
    ]
    print(
        f"real-data tracks {len(real_tracks)}, matching a known object {sum(t['known_object'] is not None for t in real_tracks)}"
    )
    print(
        f"unmatched tracks in synthetic runs {len(extra)}, matching a known object {sum(t['known_object'] is not None for t in extra)}"
    )

    section("Singapore demo field", "build_demo.py")
    demo = summary["singapore"]
    c = demo["confirmation"]
    print(f"{c['asteroid']}, JPL V {c['jpl_vmag']}, field centre {demo['centre']}")
    print(
        f"seen in {c['visit_stacks_with_detection']} of {c['visit_stacks']} visit stacks "
        f"({c['exposures']} exposures, {', '.join(c['detectors_with_detection'])}) over {c['span_hours']} hours"
    )
    print(
        f"measured {c['measured_rate_arcsec_hr']} +/- {c['measured_rate_err_arcsec_hr']} arcsec/hr, "
        f"JPL {c['jpl_rate_arcsec_hr']}, moved {c['measured_shift_arcsec']} arcsec"
    )
    e = c["engine"]
    print(
        f"engine {e['detector']}: {e['fast_tracks_found']} fast track, matches the asteroid: "
        f"{e['blind_track_matches_asteroid']}; peaks {e['mean_peaks_before']} before, {e['mean_peaks_after']} after"
    )

    section("Candidates from real engine outputs", "seed_candidates.py")
    print(
        f"{len(candidates)} candidates: {dict(Counter(r['status'] for r in candidates))}"
    )
    for r in candidates:
        if r["status"] != "flagged":
            print(f"  {r['status']:13s} {r['checks']['summary']['label']}")

    section(
        "Rows now in Supabase, read with the publishable key",
        "seed_candidates.py and live jobs",
    )
    try:
        text = (DOCS / "config.js").read_text()
        key = re.search(r'SUPABASE_ANON_KEY = "([^"]+)"', text).group(1)
        url = re.search(r'SUPABASE_URL = "([^"]+)"', text).group(1)
        rows = requests.get(
            f"{url}/rest/v1/candidates?select=status,checks->summary->>source",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=20,
        ).json()
        seeded = [r for r in rows if "seed_candidates" in r["source"]]
        print(
            f"{len(seeded)} seeded rows: {dict(Counter(r['status'] for r in seeded))}"
        )
        live = [r for r in rows if "seed_candidates" not in r["source"]]
        print(
            f"{len(live)} rows from live jobs: {dict(Counter(r['status'] for r in live))}"
        )
    except (requests.RequestException, AttributeError, KeyError, TypeError) as err:
        print(f"Supabase could not be read: {type(err).__name__}")

    print(
        "\nOther checks: check_wave_table.py (wavelength table), check_rls.py (row level security),"
    )
    print(
        "find_demo_asteroid.py (JPL strip search), python -m unittest discover -s tests -t . (unit tests)"
    )


if __name__ == "__main__":
    main()
