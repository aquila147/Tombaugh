"""Tombaugh settings: collections, sizes, limits and URLs in one place."""

import os
from pathlib import Path

APP_NAME = "Tombaugh"
APP_VERSION = "0.1.0"

BACKEND_DIR = Path(__file__).resolve().parent.parent


# --- Environment ---


def load_env_file(path: Path) -> None:
    """Read KEY=VALUE lines into os.environ without overriding existing values."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_env_file(BACKEND_DIR / ".env")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

# Comma-separated list of front-end origins, or * for any
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o.strip()
]

CACHE_DIR = Path(os.environ.get("CACHE_DIR", BACKEND_DIR / "cache"))


# --- SPHEREx archive ---

IRSA_SIA_URL = "https://irsa.ipac.caltech.edu/SIA"

# Checked against the IRSA SIA collection list on 2026-11-15. Newest first.
SPHEREX_COLLECTIONS = ["spherex_qr3", "spherex_dr1"]

SEARCH_RADIUS_DEG = 0.01

# Exposures closer together than this belong to one visit
VISIT_GAP_HOURS = 1.0

# Flags that make a pixel unusable. SOURCE and OUTLIER are left out on purpose.
BAD_FLAGS = [
    "TRANSIENT",
    "OVERFLOW",
    "SUR_ERROR",
    "NONFUNC",
    "MISSING_DATA",
    "HOT",
    "COLD",
    "NONLINEAR",
    "PERSIST",
    "GHOST",
    "STREAK",
    "BLOOM",
    "SNOWBALL",
    "HALO",
]

DETECTORS = ["D1", "D2", "D3", "D4", "D5", "D6"]
NATIVE_PIXEL_ARCSEC = 6.15
GRID_PIXEL_ARCSEC = 3.0

DEFAULT_FOV_DEG = 0.2
MAX_FOV_DEG = 0.5

DOWNLOAD_WORKERS = 8
HTTP_TIMEOUT_S = 60
HTTP_RETRIES = 4
HTTP_BACKOFF_S = 2.0
