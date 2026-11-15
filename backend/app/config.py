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

# ESA archive first, then the Gaia partner archive at AIP Potsdam (same table)
GAIA_TAP_URLS = [
    "https://gea.esac.esa.int/tap-server/tap/sync",
    "https://gaia.aip.de/tap/sync",
]
CATALOG_TIMEOUT_S = 12
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

# --- Engine: clean differences ---

ENGINE_COLLECTION = "spherex_dr1"
ENGINE_POLY_DEGREE = 2
ENGINE_FIT_ROUNDS = 5
ENGINE_CLIP_SIGMA = 3.0
ENGINE_RIDGE = 1e-3
# Half width of the window used to match local sampling, in grid pixels
ENGINE_MATCH_HALF_PIX = 6
# Shortest time span over which a per-pixel change with time is fitted
ENGINE_MIN_TREND_YEARS = 0.3

# --- Detection and linking ---

DETECT_SIGMA = 5.0
DETECT_MIN_AREA = 3
LINK_MIN_FRAMES = 3
# Fast movers inside one pass (asteroids). Rates in arcsec per day.
LINK_FAST = {
    "max_rate": 2880.0,
    "min_gap": 0.01,
    "max_gap": 2.0,
    "min_shift": 6.0,
    "tol": 4.5,
}
# Slow movers across passes months apart (nearby stars, brown dwarfs)
LINK_SLOW = {
    "max_rate": 20.0 / 365.25,
    "min_gap": 100.0,
    "max_gap": 1000.0,
    "min_shift": 4.5,
    "tol": 3.0,
}

# Slow movers: window for the velocity fit, and the smallest rate reported
SLOW_FIT_HALF_PIX = 6
SLOW_MIN_RATE_ARCSEC_YR = 1.0
# Bright stars used to measure the field's own false velocities
SLOW_STAR_SNR = 20.0
SLOW_MIN_STARS = 8

# --- Known solar-system objects ---

SB_IDENT_URL = "https://ssd-api.jpl.nasa.gov/sb_ident.api"
SB_VMAG_LIMIT = 21

# --- Overhead lookup ---

# Field centres are snapped to this grid, so only a coarse sky patch is ever used
FIELD_STEP_DEG = 0.2

# --- Live lookups ---

LIVE_MAX_FOV_DEG = 0.3
LIVE_MAX_FRAMES = 60
LIVE_MIN_FRAMES = 8
LIVE_MAX_CANDIDATES = 10
# If the archive search is down, reuse a saved exposure list this close by
LIVE_REUSE_SEARCH_DEG = 0.6

# --- SIMBAD ---

SIMBAD_TAP_URLS = [
    "https://simbad.cds.unistra.fr/simbad/sim-tap/sync",
    "https://simbad.harvard.edu/simbad/sim-tap/sync",
]
SIMBAD_CONE_DEG = 0.12

# --- Candidate checks ---

CHECK_SB_HALF_WIDTH_DEG = 0.5
CHECK_SB_MATCH_ARCSEC = 30.0
CHECK_STAR_MATCH_ARCSEC = 9.0
CHECK_SIMBAD_MATCH_ARCSEC = 15.0
CHECK_EDGE_PIX = 3
# Slow movers: fail when more than this fraction of exposures has bad pixels there
CHECK_FLAG_FRACTION = 0.3
CHECK_LINE_RMS_ARCSEC = 3.0
CHECK_RATE_SPREAD = 0.3
CHECK_MAX_AREA_PIX = 150
# (Gaia G limit, halo radius in arcsec)
CHECK_HALO_RADII = [(9.0, 90.0), (11.0, 45.0), (13.0, 20.0)]
CHECK_CROWD_TRACKS = 3
# A click this close to an engine candidate shows that candidate's checks
CHECK_CLICK_ARCSEC = 20.0
