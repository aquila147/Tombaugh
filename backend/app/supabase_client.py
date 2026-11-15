"""Server-side writes to Supabase with the service key.

Only the back end writes candidates. The key comes from the environment and
is never sent to the browser or logged.
"""

import logging

import numpy as np
import requests

from app import config

log = logging.getLogger("tombaugh.supabase")

TIMEOUT_S = 20
MERGE_ARCSEC = 20.0


def enabled() -> bool:
    return bool(config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY)


def headers() -> dict:
    key = config.SUPABASE_SERVICE_KEY
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def find_duplicate(row: dict) -> int | None:
    """Id of a stored candidate at the same place with the same kind of motion."""
    box = MERGE_ARCSEC / 3600
    half_ra = box / max(np.cos(np.radians(row["dec"])), 0.05)
    query = (
        f"select=id,ra,dec,rate,pm_ra&ra=gte.{row['ra'] - half_ra}&ra=lte.{row['ra'] + half_ra}"
        f"&dec=gte.{row['dec'] - box}&dec=lte.{row['dec'] + box}"
    )
    res = requests.get(
        f"{config.SUPABASE_URL}/rest/v1/candidates?{query}",
        headers=headers(),
        timeout=TIMEOUT_S,
    )
    res.raise_for_status()
    for old in res.json():
        # Fast movers carry a rate, slow movers a proper motion
        if (old["rate"] is None) == (row["rate"] is None):
            return old["id"]
    return None


def save_candidate(row: dict) -> int | None:
    """Insert a candidate, or update the one already stored at that place."""
    if not enabled():
        return None
    try:
        existing = find_duplicate(row)
        if existing is None:
            res = requests.post(
                f"{config.SUPABASE_URL}/rest/v1/candidates",
                headers=headers(),
                json=row,
                timeout=TIMEOUT_S,
            )
        else:
            res = requests.patch(
                f"{config.SUPABASE_URL}/rest/v1/candidates?id=eq.{existing}",
                headers=headers(),
                json=row,
                timeout=TIMEOUT_S,
            )
        res.raise_for_status()
        return res.json()[0]["id"]
    except (requests.RequestException, KeyError, IndexError) as err:
        log.warning("Supabase write failed: %s", type(err).__name__)
        return None


def delete_from_source(source: str) -> int:
    """Remove candidates an earlier run of the same script stored. Returns how many."""
    if not enabled():
        return 0
    try:
        res = requests.delete(
            f"{config.SUPABASE_URL}/rest/v1/candidates",
            headers=headers(),
            params={"checks->summary->>source": f"eq.{source}"},
            timeout=TIMEOUT_S,
        )
        res.raise_for_status()
        return len(res.json())
    except requests.RequestException as err:
        log.warning("Supabase delete failed: %s", type(err).__name__)
        return 0
