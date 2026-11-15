"""Catalogue lookups. Gaia DR3 for now; SIMBAD and asteroid lookups come later."""

import csv
import io
import json
import logging
import re
from urllib.parse import urlencode

import numpy as np
from astropy.time import Time

from app import archive, config

log = logging.getLogger("tombaugh.catalogs")


# --- Gaia DR3 ---


def gaia_stars(ra: float, dec: float, radius_deg: float) -> list[dict]:
    """Gaia DR3 stars in a cone at epoch 2016.0, brightest first, cached on disk."""
    path = config.CACHE_DIR / "gaia" / f"{ra:.4f}_{dec:+.4f}_{radius_deg:.4f}.json"
    if path.is_file():
        return json.loads(path.read_text())

    query = (
        "SELECT source_id, ra, dec, pmra, pmdec, phot_g_mean_mag "
        "FROM gaiadr3.gaia_source WHERE 1=CONTAINS(POINT('ICRS', ra, dec), "
        f"CIRCLE('ICRS', {ra:.6f}, {dec:.6f}, {radius_deg:.5f})) "
        f"AND phot_g_mean_mag < {config.GAIA_MAG_LIMIT} ORDER BY phot_g_mean_mag"
    )
    params = {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": query}
    text = archive.http_get(f"{config.GAIA_TAP_URL}?{urlencode(params)}").decode()
    stars = []
    for row in csv.DictReader(io.StringIO(text)):
        stars.append(
            {
                "id": row["source_id"],
                "ra": float(row["ra"]),
                "dec": float(row["dec"]),
                "pmra": float(row["pmra"] or 0.0),
                "pmdec": float(row["pmdec"] or 0.0),
                "g": float(row["phot_g_mean_mag"]),
            }
        )
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
    ra: float, dec: float, mjd: float, half_width_deg: float
) -> list[dict]:
    """Known asteroids and comets in a field at a time, from JPL sb_ident.

    Geocentric observer. Positions are the returned RA and Dec, not the
    rounded distance columns. A magnitude limit keeps the query from timing out.
    """
    name = f"{ra:.4f}_{dec:+.4f}_{mjd:.4f}_{half_width_deg:.3f}_{config.SB_VMAG_LIMIT}.json"
    path = config.CACHE_DIR / "sb_ident" / name
    if path.is_file():
        return json.loads(path.read_text())
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
            "fov-dec-hwidth": f"{half_width_deg:.3f}",
            "vmag-lim": str(config.SB_VMAG_LIMIT),
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
