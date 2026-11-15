"""Catalogue lookups. Gaia DR3 for now; SIMBAD and asteroid lookups come later."""

import csv
import io
import json
import logging
import re
import warnings
from urllib.parse import urlencode

import numpy as np
import requests
from astropy.io.votable import parse_single_table
from astropy.time import Time

from app import archive, config

log = logging.getLogger("tombaugh.catalogs")


# --- Gaia DR3 ---


def tap_rows(url: str, query: str) -> list[dict]:
    """Run one ADQL query and return the rows. Short timeout, two tries."""
    params = {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": query}
    last = ""
    for _ in range(2):
        try:
            res = requests.get(url, params=params, timeout=config.CATALOG_TIMEOUT_S)
            if res.status_code != 200:
                last = f"HTTP {res.status_code}"
                continue
            if res.text.lstrip().startswith("<"):
                # Some archives answer with a VOTable whatever format is asked for
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    table = parse_single_table(io.BytesIO(res.content)).to_table(
                        use_names_over_ids=True
                    )
                return [{name: row[name] for name in table.colnames} for row in table]
            return list(csv.DictReader(io.StringIO(res.text)))
        except requests.RequestException as err:
            last = type(err).__name__
    raise RuntimeError(f"catalogue query failed ({last}): {url}")


def number(value) -> float:
    """Float from a CSV field or a table cell; empty or masked gives 0."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    return out if np.isfinite(out) else 0.0


def gaia_stars(ra: float, dec: float, radius_deg: float) -> list[dict]:
    """Gaia DR3 stars in a cone at epoch 2016.0, brightest first, cached on disk.

    Asks the ESA Gaia archive first, then the Gaia partner archive at AIP,
    which holds the same table. Raises RuntimeError if neither answers.
    """
    path = config.CACHE_DIR / "gaia" / f"{ra:.4f}_{dec:+.4f}_{radius_deg:.4f}.json"
    if path.is_file():
        return json.loads(path.read_text())

    half_ra = radius_deg / max(np.cos(np.radians(dec)), 0.05)
    query = (
        "SELECT source_id, ra, dec, pmra, pmdec, phot_g_mean_mag AS g "
        "FROM gaiadr3.gaia_source "
        f"WHERE ra BETWEEN {ra - half_ra:.6f} AND {ra + half_ra:.6f} "
        f"AND dec BETWEEN {dec - radius_deg:.6f} AND {dec + radius_deg:.6f} "
        f"AND phot_g_mean_mag < {config.GAIA_MAG_LIMIT} ORDER BY phot_g_mean_mag"
    )
    rows, last = None, None
    for url in config.GAIA_TAP_URLS:
        try:
            rows = tap_rows(url, query)
            break
        except RuntimeError as err:
            log.warning("%s", err)
            last = err
    if rows is None:
        raise RuntimeError(f"no Gaia archive answered: {last}")
    stars = [
        {
            "id": str(row["source_id"]),
            "ra": float(row["ra"]),
            "dec": float(row["dec"]),
            "pmra": number(row["pmra"]),
            "pmdec": number(row["pmdec"]),
            "g": float(row["g"]),
        }
        for row in rows
    ]
    # The query is a box; keep the cone
    stars = [
        s
        for s in stars
        if np.hypot((s["ra"] - ra) * np.cos(np.radians(dec)), s["dec"] - dec)
        <= radius_deg
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stars))
    return stars


def gaia_at_epoch(stars: list[dict], mjd: float) -> tuple[np.ndarray, np.ndarray]:
    """RA and Dec in degrees after applying proper motion up to a date."""
    years = (mjd - config.GAIA_EPOCH_MJD) / 365.25
    ra = np.array([s["ra"] for s in stars])
    dec = np.array([s["dec"] for s in stars])
    pmra = np.array([s["pmra"] for s in stars])
    pmdec = np.array([s["pmdec"] for s in stars])
    dec_now = dec + pmdec * years / 3.6e6
    ra_now = ra + pmra * years / 3.6e6 / np.cos(np.radians(dec))
    return ra_now, dec_now


# --- JPL Small-Body Identification ---


def sexagesimal(value: float, is_dec: bool) -> str:
    """Degrees to the hh-mm-ss or dd-mm-ss form sb_ident expects (M marks minus)."""
    sign = "M" if value < 0 else ""
    total = abs(value) / (1 if is_dec else 15) * 3600
    whole, minutes, seconds = int(total // 3600), int(total % 3600 // 60), total % 60
    return f"{sign}{whole:02d}-{minutes:02d}-{seconds:05.2f}"


def parse_sexagesimal(text: str, is_dec: bool) -> float:
    parts = [float(p) for p in re.findall(r"[\d.]+", text)]
    value = parts[0] + parts[1] / 60 + parts[2] / 3600
    if text.strip().startswith("-"):
        value = -value
    return value if is_dec else value * 15


def known_small_bodies(
    ra: float,
    dec: float,
    mjd: float,
    half_width_deg: float,
    half_height_deg: float | None = None,
    vmag_limit: int = config.SB_VMAG_LIMIT,
) -> list[dict]:
    """Known asteroids and comets in a field at a time, from JPL sb_ident.

    Geocentric observer. Positions are the returned RA and Dec, not the
    rounded distance columns. A magnitude limit keeps the query from timing out.
    """
    half_height_deg = half_height_deg or half_width_deg
    name = f"{ra:.4f}_{dec:+.4f}_{mjd:.4f}_{half_width_deg:.3f}_{half_height_deg:.3f}_{vmag_limit}.json"
    path = config.CACHE_DIR / "sb_ident" / name
    if path.is_file():
        return json.loads(path.read_text())
    # Files saved before the strip height was part of the name
    legacy = path.with_name(
        f"{ra:.4f}_{dec:+.4f}_{mjd:.4f}_{half_width_deg:.3f}_{vmag_limit}.json"
    )
    if half_height_deg == half_width_deg and legacy.is_file():
        return json.loads(legacy.read_text())
    when = Time(mjd, format="mjd").utc.strftime("%Y-%m-%d_%H:%M:%S")
    bodies = []
    for kind in ("a", "c"):
        params = {
            "sb-kind": kind,
            "mpc-code": "500",
            "obs-time": when,
            "fov-ra-center": sexagesimal(ra, False),
            "fov-dec-center": sexagesimal(dec, True),
            "fov-ra-hwidth": f"{half_width_deg:.3f}",
            "fov-dec-hwidth": f"{half_height_deg:.3f}",
            "vmag-lim": str(vmag_limit),
            "two-pass": "true",
        }
        reply = json.loads(
            archive.http_get(f"{config.SB_IDENT_URL}?{urlencode(params)}")
        )
        fields = reply.get("fields_second", [])
        for row in reply.get("data_second_pass", []):
            entry = dict(zip(fields, row))
            bodies.append(
                {
                    "name": entry["Object name"],
                    "ra": parse_sexagesimal(entry["Astrometric RA (hh:mm:ss)"], False),
                    "dec": parse_sexagesimal(
                        entry["Astrometric Dec (dd mm'ss\")"], True
                    ),
                    "vmag": entry.get("Visual magnitude (V)"),
                    "ra_rate_arcsec_hr": float(entry['RA rate ("/h)']),
                    "dec_rate_arcsec_hr": float(entry['Dec rate ("/h)']),
                }
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bodies))
    return bodies


# --- SIMBAD ---


def simbad_near(ra: float, dec: float, mjd: float) -> list[dict]:
    """SIMBAD objects near a position, moved to a date with their proper motion.

    Nearby stars move by arcminutes between the catalogue epoch and now, so
    the cone is wide and each object is moved before its distance is measured.
    """
    path = config.CACHE_DIR / "simbad" / f"{ra:.4f}_{dec:+.4f}_{mjd:.0f}.json"
    if path.is_file():
        return json.loads(path.read_text())
    query = (
        "SELECT main_id, ra, dec, pmra, pmdec, otype FROM basic "
        f"WHERE CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra:.6f}, {dec:.6f}, "
        f"{config.SIMBAD_CONE_DEG})) = 1"
    )
    rows, last = None, None
    for url in config.SIMBAD_TAP_URLS:
        try:
            rows = tap_rows(url, query)
            break
        except RuntimeError as err:
            last = err
    if rows is None:
        raise RuntimeError(f"SIMBAD did not answer: {last}")
    years = (mjd - 51544.5) / 365.25
    out = []
    for row in rows:
        pm_ra, pm_dec = number(row["pmra"]), number(row["pmdec"])
        o_dec = float(row["dec"]) + pm_dec * years / 3.6e6
        o_ra = float(row["ra"]) + pm_ra * years / 3.6e6 / np.cos(np.radians(o_dec))
        sep = 3600 * np.hypot((o_ra - ra) * np.cos(np.radians(dec)), o_dec - dec)
        out.append(
            {
                "name": " ".join(str(row["main_id"]).split()),
                "type": str(row["otype"]),
                "pm_arcsec_yr": float(np.hypot(pm_ra, pm_dec)) / 1000,
                "separation_arcsec": float(sep),
            }
        )
    out.sort(key=lambda o: o["separation_arcsec"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out))
    return out
