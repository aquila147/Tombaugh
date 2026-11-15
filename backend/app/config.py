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

# Extension names of the PSF in different releases. Downloads stop when one starts.
PSF_EXTENSIONS = ["PSF", "EPSF"]
# Planes that must arrive whole, in file order, before a cutout is cached
CUTOUT_PLANES = ["IMAGE", "FLAGS", "VARIANCE", "ZODI"]

# --- Gaia alignment ---

GAIA_TAP_URL = "https://gea.esac.esa.int/tap-server/tap/sync"
GAIA_EPOCH_MJD = 57388.5  # J2016.0
GAIA_MAG_LIMIT = 17.0
ALIGN_MIN_SNR = 10.0
ALIGN_MAX_SHIFT_PIX = 1.5
ALIGN_ISOLATION_ARCSEC = 25.0
ALIGN_MIN_STARS_FULL_FIT = 8
CENTROID_SIGMA_PIX = 1.2

# --- Stacking and motion ---

STACK_CLIP_SIGMA = 3.0
MOTION_MIN_SNR = 5.0
# Weight width for stars whose core is masked as saturated
SATURATED_SIGMA_PIX = 4.0
# Position error model: floor plus a term that falls with signal to noise
MOTION_ERR_FLOOR_ARCSEC = 0.3
MOTION_ERR_ARCSEC = 6.0

DOWNLOAD_WORKERS = 8
HTTP_TIMEOUT_S = 60
HTTP_RETRIES = 4
HTTP_BACKOFF_S = 2.0
