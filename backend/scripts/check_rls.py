"""Check that the publishable key can only do what row level security allows.

Uses one clearly labelled test candidate, created and removed with the
service key. With the publishable key it then tries to insert, update and
delete candidates, and to update and delete a vote and a sky search.

Run from backend/:  python -m scripts.check_rls
"""

import re
import uuid

import requests

from app import config

BASE = config.SUPABASE_URL + "/rest/v1"
TIMEOUT_S = 20
LABEL = "RLS TEST ROW, safe to delete"


def headers(key: str) -> dict:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def publishable_key() -> str:
    text = (config.BACKEND_DIR.parent / "docs" / "config.js").read_text()
    return re.search(r'SUPABASE_ANON_KEY = "([^"]+)"', text).group(1)


def changed(res: requests.Response) -> int:
    """Rows a write touched. A refused write is 0."""
    return len(res.json()) if res.ok and res.text else 0


def main() -> None:
    service = headers(config.SUPABASE_SERVICE_KEY)
    anon = headers(publishable_key())
    results = []

    row = {
        "ra": 0.0,
        "dec": 89.9,
        "status": "flagged",
        "checks": {
            "summary": {"label": LABEL, "source": "scripts/check_rls.py"},
            "items": [],
        },
    }
    test_id = requests.post(
        f"{BASE}/candidates", headers=service, json=row, timeout=TIMEOUT_S
    ).json()[0]["id"]
    one = f"id=eq.{test_id}"
    try:
        # --- candidates: read only ---
        res = requests.get(
            f"{BASE}/candidates?{one}&select=id", headers=anon, timeout=TIMEOUT_S
        )
        results.append(("read candidates", "allowed", res.ok and len(res.json()) == 1))
        res = requests.post(
            f"{BASE}/candidates", headers=anon, json=row, timeout=TIMEOUT_S
        )
        results.append(("insert candidate", "blocked", changed(res) == 0))
        res = requests.patch(
            f"{BASE}/candidates?{one}",
            headers=anon,
            json={"status": "unexplained"},
            timeout=TIMEOUT_S,
        )
        results.append(("update candidate", "blocked", changed(res) == 0))
        res = requests.delete(
            f"{BASE}/candidates?{one}", headers=anon, timeout=TIMEOUT_S
        )
        results.append(("delete candidate", "blocked", changed(res) == 0))
        still = requests.get(
            f"{BASE}/candidates?{one}&select=status", headers=service, timeout=TIMEOUT_S
        ).json()
        results.append(
            ("test row unchanged afterwards", "true", still == [{"status": "flagged"}])
        )

        # --- votes: insert only ---
        vote = {
            "candidate_id": test_id,
            "device_id": str(uuid.uuid4()),
            "vote": "artifact",
        }
        res = requests.post(f"{BASE}/votes", headers=anon, json=vote, timeout=TIMEOUT_S)
        results.append(("insert vote", "allowed", changed(res) == 1))
        res = requests.post(f"{BASE}/votes", headers=anon, json=vote, timeout=TIMEOUT_S)
        results.append(("second vote, same device", "blocked", res.status_code == 409))
        mine = f"candidate_id=eq.{test_id}"
        res = requests.patch(
            f"{BASE}/votes?{mine}",
            headers=anon,
            json={"vote": "real"},
            timeout=TIMEOUT_S,
        )
        results.append(("update vote", "blocked", changed(res) == 0))
        res = requests.delete(f"{BASE}/votes?{mine}", headers=anon, timeout=TIMEOUT_S)
        results.append(("delete vote", "blocked", changed(res) == 0))

        # --- sky searches: insert only ---
        search = {
            "field_id": "rls-test",
            "ra_center": 0,
            "dec_center": 90,
            "source": "manual",
        }
        res = requests.post(
            f"{BASE}/sky_searches", headers=anon, json=search, timeout=TIMEOUT_S
        )
        results.append(("insert sky search", "allowed", changed(res) == 1))
        test = "field_id=eq.rls-test"
        res = requests.patch(
            f"{BASE}/sky_searches?{test}",
            headers=anon,
            json={"dec_center": 0},
            timeout=TIMEOUT_S,
        )
        results.append(("update sky search", "blocked", changed(res) == 0))
        res = requests.delete(
            f"{BASE}/sky_searches?{test}", headers=anon, timeout=TIMEOUT_S
        )
        results.append(("delete sky search", "blocked", changed(res) == 0))
    finally:
        # Remove only the rows this script made; the vote goes with its candidate
        requests.delete(f"{BASE}/candidates?{one}", headers=service, timeout=TIMEOUT_S)
        requests.delete(
            f"{BASE}/sky_searches?field_id=eq.rls-test",
            headers=service,
            timeout=TIMEOUT_S,
        )

    for name, expected, ok in results:
        print(f"{'OK  ' if ok else 'FAIL'} {name}: expected {expected}")
    print(
        "RESULT:",
        (
            "row level security behaves as designed"
            if all(r[2] for r in results)
            else "PROBLEM FOUND"
        ),
    )


if __name__ == "__main__":
    main()
