"""Automatic candidate checks and the first rungs of the status ladder.

Every check returns a plain-language reason. Nothing here calls a candidate
real: the best outcome is "passed automatic checks", which only means it is
worth a human look.
"""

import logging

import numpy as np

from app import archive, catalogs, config, flags

log = logging.getLogger("tombaugh.checks")

STATUS_LADDER = [
    "flagged",
    "passed_checks",
    "community_confirmed",
    "team_reviewed",
    "known",
    "artifact",
    "unexplained",
]


def item(key: str, title: str, result: str, reason: str) -> dict:
    """result is one of pass, fail, warn, known, na."""
    return {"key": key, "title": title, "result": result, "reason": reason}


def separation_arcsec(ra1, dec1, ra2, dec2):
    return 3600 * np.hypot(
        (np.asarray(ra1) - ra2) * np.cos(np.radians(dec2)), np.asarray(dec1) - dec2
    )


# --- 1. Not a known object ---


def check_known(candidate: dict, context: dict) -> dict:
    title = "Not a known object"
    ra, dec, mjd = candidate["ra"], candidate["dec"], candidate["mjd"]
    if candidate["kind"] == "fast":
        centre = context["centre"]
        when = round(mjd * 4) / 4
        try:
            bodies = catalogs.known_small_bodies(
                centre[0], centre[1], when, config.CHECK_SB_HALF_WIDTH_DEG
            )
        except RuntimeError:
            return item(
                "known",
                title,
                "warn",
                "JPL could not be reached, so this was not checked.",
            )
        hours = (mjd - when) * 24
        best = None
        for body in bodies:
            b_dec = body["dec"] + body["dec_rate_arcsec_hr"] * hours / 3600
            b_ra = body["ra"] + body["ra_rate_arcsec_hr"] * hours / 3600 / np.cos(
                np.radians(b_dec)
            )
            sep = float(separation_arcsec(b_ra, b_dec, ra, dec))
            if sep <= config.CHECK_SB_MATCH_ARCSEC and (best is None or sep < best[1]):
                best = (body, sep)
        if best:
            name = best[0]["name"].split(" (")[0]
            candidate["known_as"] = f"asteroid {name}"
            return item(
                "known",
                title,
                "known",
                f"This is asteroid {name} (V {best[0]['vmag']}), {best[1]:.0f} arcsec from "
                "the JPL position at that time.",
            )
        return item(
            "known",
            title,
            "pass",
            f"No asteroid or comet brighter than V {config.SB_VMAG_LIMIT} is within "
            f"{config.CHECK_SB_MATCH_ARCSEC:.0f} arcsec in JPL Small-Body Identification.",
        )

    # Slow movers. Known moving objects first: Gaia stars with large motion,
    # SIMBAD, then the published targets these fields were centred on. Only
    # after that does a nearby star that barely moves count against it.
    stars = context["field"]["stars"]
    still_star = None
    if stars:
        s_ra, s_dec = catalogs.gaia_at_epoch(stars, mjd)
        sep = separation_arcsec(s_ra, s_dec, ra, dec)
        i = int(np.argmin(sep))
        if sep[i] <= config.CHECK_STAR_MATCH_ARCSEC:
            pm = float(np.hypot(stars[i]["pmra"], stars[i]["pmdec"])) / 1000
            if pm >= config.SLOW_MIN_RATE_ARCSEC_YR:
                candidate["known_as"] = f"Gaia DR3 {stars[i]['id']}"
                return item(
                    "known",
                    title,
                    "known",
                    f"This is Gaia DR3 {stars[i]['id']}, a known star moving {pm:.2f} arcsec/yr.",
                )
            still_star = (pm, stars[i]["g"], float(sep[i]))
    simbad_note = "SIMBAD"
    try:
        for obj in catalogs.simbad_near(ra, dec, mjd):
            close = obj["separation_arcsec"] <= config.CHECK_SIMBAD_MATCH_ARCSEC
            if close and obj["pm_arcsec_yr"] >= config.SLOW_MIN_RATE_ARCSEC_YR:
                candidate["known_as"] = obj["name"]
                return item(
                    "known",
                    title,
                    "known",
                    f"This is {obj['name']} in SIMBAD (type {obj['type']}, {obj['pm_arcsec_yr']:.2f} "
                    f"arcsec/yr), {obj['separation_arcsec']:.0f} arcsec from its position at that date.",
                )
    except RuntimeError:
        simbad_note = "SIMBAD could not be reached, so only Gaia was checked"
    for target in context.get("literature", []):
        years = (mjd - target["epoch_mjd"]) / 365.25
        t_dec = target["dec"] + target["pm_dec"] * years / 3600
        t_ra = target["ra"] + target["pm_ra"] * years / 3600 / np.cos(np.radians(t_dec))
        sep = float(separation_arcsec(t_ra, t_dec, ra, dec))
        if sep <= config.CHECK_SIMBAD_MATCH_ARCSEC:
            candidate["known_as"] = target["name"]
            return item(
                "known",
                title,
                "known",
                f"This is {target['name']}, the published object this field was centred on "
                f"({sep:.0f} arcsec from its published position and motion).",
            )
    if still_star:
        return item(
            "known",
            title,
            "fail",
            f"A Gaia star that moves only {still_star[0]:.2f} arcsec/yr sits {still_star[2]:.0f} "
            f"arcsec away (G {still_star[1]:.1f}). The apparent motion is most likely an "
            "artifact of that star.",
        )
    return item(
        "known",
        title,
        "pass",
        f"No moving object is listed here in Gaia DR3 or {simbad_note}.",
    )


# --- 2. No bad flags in the aperture ---


def aperture_flags(
    context: dict, frame: dict, ra: float, dec: float
) -> set[str] | None:
    """Bad flag names in a 3 by 3 pixel aperture of the original exposure.

    OUTLIER and SOURCE are ignored on purpose. Returns None if the position is
    off the cutout.
    """
    centre = context["centre"]
    path = archive.cutout_path(frame, centre[0], centre[1], centre[2])
    if not path.is_file():
        return None
    cutout = archive.read_cutout(path)
    x, y = cutout["wcs"].all_world2pix(ra, dec, 0, quiet=True)
    xi, yi = int(round(float(x))), int(round(float(y)))
    ny, nx = cutout["flags"].shape
    if not (0 <= xi < nx and 0 <= yi < ny):
        return None
    found = set()
    if min(xi, yi, nx - 1 - xi, ny - 1 - yi) < config.CHECK_EDGE_PIX:
        found.add("EDGE")
    box = cutout["flags"][max(yi - 1, 0) : yi + 2, max(xi - 1, 0) : xi + 2]
    bits = flags.read_flag_bits(cutout["flags_header"])
    for name in config.BAD_FLAGS:
        if name in bits and (box & bits[name]).any():
            found.add(name)
    return found


def check_flags(candidate: dict, context: dict) -> dict:
    title = "No bad pixels in the aperture"
    frames_list = context["field"]["frames"]
    if candidate["kind"] == "fast":
        looks = [
            (frames_list[d["frame"]], d["ra"], d["dec"])
            for d in candidate["detections"]
        ]
    else:
        looks = [(f, candidate["ra"], candidate["dec"]) for f in frames_list]
    bad, seen, names = 0, 0, set()
    for frame, ra, dec in looks:
        found = aperture_flags(context, frame, ra, dec)
        if found is None:
            continue
        seen += 1
        if found:
            bad += 1
            names |= found
    if seen == 0:
        return item(
            "flags",
            title,
            "warn",
            "The original exposures were not available to check.",
        )
    limit = 0 if candidate["kind"] == "fast" else config.CHECK_FLAG_FRACTION * seen
    listed = ", ".join(sorted(names)).lower()
    if bad > limit:
        return item(
            "flags",
            title,
            "fail",
            f"Flagged pixels ({listed}) in the aperture in {bad} of {seen} exposures.",
        )
    extra = f" ({bad} with {listed})" if bad else ""
    return item(
        "flags",
        title,
        "pass",
        f"Clean aperture in {seen - bad} of {seen} exposures{extra}. "
        "The outlier flag is ignored because the pipeline sets it on moving objects.",
    )


# --- 3. Astrometry solved in the frames used ---


def check_astrometry(candidate: dict, context: dict) -> dict:
    title = "Astrometry checked in the frames used"
    frames_list = context["field"]["frames"]
    if candidate["kind"] == "fast":
        used = [
            frames_list[i]
            for i in sorted({d["frame"] for d in candidate["detections"]})
        ]
    else:
        used = frames_list
    aligned = sum(f["align"]["offset_arcsec"] is not None for f in used)
    note = (
        "FINAST is 0 in every Data Release 1 header we have read, so each frame is "
        "checked against Gaia stars instead."
    )
    if aligned == len(used):
        scatter = np.median([f["align"]["scatter_arcsec"] for f in used])
        return item(
            "astrometry",
            title,
            "pass",
            f"All {len(used)} frames aligned to Gaia, single-star scatter {scatter:.2f} arcsec. {note}",
        )
    return item(
        "astrometry",
        title,
        "fail",
        f"Only {aligned} of {len(used)} frames could be aligned to Gaia. {note}",
    )


# --- 4. Detected at 5 sigma in at least three frames ---


def check_significance(candidate: dict, context: dict) -> dict:
    title = "Seen at 5 sigma or more in at least three frames"
    if candidate["kind"] == "fast":
        strong = {
            d["frame"]
            for d in candidate["detections"]
            if d["snr"] >= config.DETECT_SIGMA
        }
        result = "pass" if len(strong) >= config.LINK_MIN_FRAMES else "fail"
        peak = max(d["snr"] for d in candidate["detections"])
        return item(
            "significance",
            title,
            result,
            f"{len(strong)} exposures at {config.DETECT_SIGMA:.0f} sigma or more, strongest {peak:.0f} sigma.",
        )
    n = len(context["field"]["frames"])
    ok = (
        candidate["significance"] >= config.DETECT_SIGMA and n >= config.LINK_MIN_FRAMES
    )
    return item(
        "significance",
        title,
        "pass" if ok else "fail",
        f"Motion signal of {candidate['significance']:.1f} sigma from a fit over {n} exposures. "
        "A slow mover is not a separate spot in any single frame.",
    )


# --- 5. Straight line at a steady rate ---


def check_line(candidate: dict, context: dict) -> dict:
    title = "Positions on a straight line at a steady rate"
    if candidate["kind"] != "fast":
        return item(
            "line",
            title,
            "na",
            "Not applicable: the slow-mover search fits one straight line in time to the whole data set.",
        )
    dets = sorted(candidate["detections"], key=lambda d: d["mjd"])
    t = np.array([d["mjd"] for d in dets])
    x = np.array([d["x_arcsec"] for d in dets])
    y = np.array([d["y_arcsec"] for d in dets])
    tm = t - t.mean()
    fit_x, fit_y = np.polyfit(tm, x, 1), np.polyfit(tm, y, 1)
    rms = float(
        np.sqrt(
            np.mean((x - np.polyval(fit_x, tm)) ** 2 + (y - np.polyval(fit_y, tm)) ** 2)
        )
    )
    # Group into visits and compare the speed between successive visits
    groups = np.split(
        np.arange(len(t)), np.flatnonzero(np.diff(t) > config.VISIT_GAP_HOURS / 24) + 1
    )
    centres = [(t[g].mean(), x[g].mean(), y[g].mean()) for g in groups]
    speeds = [
        np.hypot(b[1] - a[1], b[2] - a[2]) / ((b[0] - a[0]) * 24)
        for a, b in zip(centres, centres[1:])
    ]
    detail = f"Scatter about the line {rms:.1f} arcsec over {len(groups)} visits"
    if rms > config.CHECK_LINE_RMS_ARCSEC:
        return item(
            "line",
            title,
            "fail",
            f"{detail}, more than {config.CHECK_LINE_RMS_ARCSEC} allowed.",
        )
    if len(groups) < 2:
        return item(
            "line",
            title,
            "fail",
            "All detections come from one visit a few minutes long, so no rate can be tested.",
        )
    if len(speeds) >= 2:
        spread = (max(speeds) - min(speeds)) / max(np.mean(speeds), 1e-9)
        if spread > config.CHECK_RATE_SPREAD:
            return item(
                "line",
                title,
                "fail",
                f"{detail}, but the speed changes from {min(speeds):.1f} to {max(speeds):.1f} arcsec/hr between visits.",
            )
        return item(
            "line",
            title,
            "pass",
            f"{detail}; speed steady at {np.mean(speeds):.1f} arcsec/hr between visits (within {spread * 100:.0f}%).",
        )
    return item(
        "line",
        title,
        "warn",
        f"{detail}, but only two visits, so a steady rate cannot be tested: any two points lie on a line.",
    )


# --- 6. Seen in more than one detector ---


def check_detectors(candidate: dict, context: dict) -> dict:
    title = "Seen in more than one detector where coverage allows"
    also = candidate.get("also_seen_in", [])
    if also:
        return item("detectors", title, "pass", f"Also found in {', '.join(also)}.")
    other = context.get("other")
    if not other:
        return item(
            "detectors", title, "na", "No second detector was processed for this field."
        )
    name = other["detector"]
    if candidate["kind"] == "fast":
        dt = other["dets"]["t"] - candidate["mjd"]
        vx, vy = candidate["vx"], candidate["vy"]
        off = np.hypot(
            other["dets"]["x"] - (candidate["x0"] + vx * dt),
            other["dets"]["y"] - (candidate["y0"] + vy * dt),
        )
        span = candidate["span_days"] / 2 + 0.05
        hits = int(((off <= config.LINK_FAST["tol"]) & (np.abs(dt) <= span)).sum())
        looked = int((np.abs(other["mjds"] - candidate["mjd"]) <= span).sum())
        if hits:
            return item(
                "detectors",
                title,
                "pass",
                f"{name} shows it too, in {hits} exposures on the same path.",
            )
        if looked == 0:
            return item(
                "detectors",
                title,
                "na",
                f"{name} did not look at this spot during those hours.",
            )
        return item(
            "detectors",
            title,
            "warn",
            f"{name} took {looked} exposures during those hours and shows nothing on this path.",
        )
    scale = config.GRID_PIXEL_ARCSEC
    for mover in other["movers"]:
        if (
            np.hypot(mover["x"] - candidate["x_pix"], mover["y"] - candidate["y_pix"])
            * scale
            <= 15
        ):
            return item(
                "detectors",
                title,
                "pass",
                f"{name} finds it too, at {mover['rate_arcsec_yr']:.1f} arcsec/yr.",
            )
    return item(
        "detectors",
        title,
        "warn",
        f"{name} was searched the same way and does not find it.",
    )


# --- 7. Star-like, and not in a bright star's halo ---


def check_shape(candidate: dict, context: dict) -> dict:
    title = "Star-like, and not in the halo of a bright star"
    stars = context["field"]["stars"]
    ra, dec, mjd = candidate["ra"], candidate["dec"], candidate["mjd"]
    if stars:
        s_ra, s_dec = catalogs.gaia_at_epoch(stars, mjd)
        sep = separation_arcsec(s_ra, s_dec, ra, dec)
        for limit_g, radius in config.CHECK_HALO_RADII:
            for i in np.flatnonzero(sep <= radius):
                # A slow candidate sitting on the star itself is handled by the first check
                if stars[i]["g"] <= limit_g and sep[i] > config.CHECK_STAR_MATCH_ARCSEC:
                    return item(
                        "shape",
                        title,
                        "fail",
                        f"It lies {sep[i]:.0f} arcsec from a bright star (G {stars[i]['g']:.1f}), inside its halo.",
                    )
    if candidate["kind"] == "fast":
        area = float(np.median([d["area"] for d in candidate["detections"]]))
        if area > config.CHECK_MAX_AREA_PIX:
            return item(
                "shape",
                title,
                "fail",
                f"The patches are {area:.0f} pixels across the threshold, larger than a point source.",
            )
        return item(
            "shape",
            title,
            "pass",
            f"Compact patches (median {area:.0f} grid pixels) and no bright star nearby.",
        )
    return item(
        "shape",
        title,
        "pass",
        "No bright star close enough for its halo to reach here.",
    )


# --- 8. Survives the engine ---


def check_engine(candidate: dict, context: dict) -> dict:
    title = "Survives the clean-difference engine"
    if candidate["kind"] == "fast":
        return item(
            "engine",
            title,
            "pass",
            "Every detection is above 5 sigma against that pixel's own measured noise.",
        )
    return item(
        "engine",
        title,
        "pass",
        "Found in the per-pixel time fit, with significance set by the field's own stars.",
    )


# --- Extra warning: many thin tracks from one night ---


def check_crowd(candidate: dict, context: dict) -> dict | None:
    if candidate["kind"] != "fast" or candidate["n_frames"] > config.LINK_MIN_FRAMES:
        return None
    same = [
        t
        for t in context.get("tracks", [])
        if abs(t["t0"] - candidate["mjd"]) <= 0.5
        and t["n_frames"] <= config.LINK_MIN_FRAMES
    ]
    if len(same) < config.CHECK_CROWD_TRACKS:
        return None
    return item(
        "crowd",
        "Not one of many thin tracks from one night",
        "fail",
        f"This is one of {len(same)} tracks from the same night in this field, each with only "
        f"{config.LINK_MIN_FRAMES} exposures. Chance line-ups of leftover residuals look like this.",
    )


# --- All checks and the status they give ---


def run_checks(candidate: dict, context: dict) -> dict:
    """Run every check. Returns the checklist and the ladder status it supports."""
    items = [
        check(candidate, context)
        for check in (
            check_known,
            check_flags,
            check_astrometry,
            check_significance,
            check_line,
            check_detectors,
            check_shape,
            check_engine,
        )
    ]
    crowd = check_crowd(candidate, context)
    if crowd:
        items.append(crowd)
    failed = [i["title"] for i in items if i["result"] == "fail"]
    if items[0]["result"] == "known":
        status = "known"
    elif failed:
        status = "flagged"
    else:
        status = "passed_checks"
    return {"items": items, "status": status, "failed": failed}
