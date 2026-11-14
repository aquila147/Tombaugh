"""Catalogue lookups. Gaia DR3 for now; SIMBAD and asteroid lookups come later."""

import csv
import io
import json
import logging
from urllib.parse import urlencode

import numpy as np

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
