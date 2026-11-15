"""SPHEREx search, cutouts, disk cache and FITS reading."""

import io
import json
import logging
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests
from astropy.io import fits
from astropy.io.votable import parse_single_table
from astropy.wcs import WCS, FITSFixedWarning

from app import config

log = logging.getLogger("tombaugh.archive")

# The wavelength WCS shares a header with SIP terms; astropy logs a long note about it
logging.getLogger("astropy").setLevel(logging.WARNING)

RETRY_STATUS = {429, 500, 502, 503, 504}

wave_lock = threading.Lock()


# --- HTTP ---


def hdu_spans(buf: bytes) -> list[tuple[str, int, int]]:
    """(name, start, end) of every HDU whose header is complete in buf."""
    spans = []
    pos = 0
    while True:
        end = pos
        found = False
        while end + 2880 <= len(buf) and not found:
            block = buf[end : end + 2880]
            found = any(block[i : i + 8] == b"END     " for i in range(0, 2880, 80))
            end += 2880
        if not found:
            return spans
        header = fits.Header.fromstring(bytes(buf[pos:end]).decode("ascii", "replace"))
        size = 0
        if header.get("NAXIS", 0) > 0:
            size = header.get("PCOUNT", 0)
            pixels = 1
            for i in range(1, header["NAXIS"] + 1):
                pixels *= header[f"NAXIS{i}"]
            size = (
                abs(header["BITPIX"]) // 8 * header.get("GCOUNT", 1) * (size + pixels)
            )
        stop = end + -(-size // 2880) * 2880
        spans.append((str(header.get("EXTNAME", "PRIMARY")).strip(), pos, stop))
        pos = stop


def read_before_psf(res: requests.Response) -> bytes:
    """Read a FITS stream and hang up when the PSF extension starts."""
    buf = bytearray()
    for chunk in res.iter_content(65536):
        buf.extend(chunk)
        for name, start, _ in hdu_spans(buf):
            if name in config.PSF_EXTENSIONS:
                res.close()
                return bytes(buf[:start])
    # No PSF seen: the stream ended early or the layout changed. The caller checks.
    return bytes(buf)


def http_get(url: str, skip_psf: bool = False) -> bytes:
    """GET with retries and backoff. IRSA returns 502/503 now and then."""
    last = ""
    for attempt in range(config.HTTP_RETRIES):
        try:
            res = requests.get(url, timeout=config.HTTP_TIMEOUT_S, stream=skip_psf)
            if res.status_code == 200:
                return read_before_psf(res) if skip_psf else res.content
            last = f"HTTP {res.status_code}"
            if res.status_code not in RETRY_STATUS:
                break
        except requests.RequestException as err:
            last = type(err).__name__
        wait = config.HTTP_BACKOFF_S * 2**attempt
        log.warning("GET failed (%s), retry in %.0f s: %s", last, wait, url)
        time.sleep(wait)
    raise RuntimeError(f"GET failed after retries ({last}): {url}")


# --- Search ---


def search_collection(
    collection: str, ra: float, dec: float, radius_deg: float
) -> list[dict]:
    url = (
        f"{config.IRSA_SIA_URL}?COLLECTION={collection}"
        f"&POS=circle+{ra:.6f}+{dec:.6f}+{radius_deg:.6f}"
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        table = parse_single_table(io.BytesIO(http_get(url))).to_table(
            use_names_over_ids=True
        )
    products = []
    for row in table:
        if str(row["dataproduct_type"]) != "image":
            continue
        products.append(
            {
                "obs_id": str(row["obs_id"]),
                "detector": str(row["energy_bandpassname"]).split("-")[-1],
                "collection": str(row["obs_collection"]),
                "access_url": str(row["access_url"]),
                "mjd": 0.5 * (float(row["t_min"]) + float(row["t_max"])),
                "exptime_s": float(row["t_exptime"]),
                "wave_min_um": float(row["em_min"]) * 1e6,
                "wave_max_um": float(row["em_max"]) * 1e6,
            }
        )
    return products


def search(
    ra: float,
    dec: float,
    radius_deg: float = config.SEARCH_RADIUS_DEG,
    collections: list[str] | None = None,
) -> list[dict]:
    """All Level 2 images covering a position, cached on disk.

    collections defaults to every release in the config. Pass one release to
    avoid asking for the others at all.
    """
    collections = collections or config.SPHEREX_COLLECTIONS
    name = f"{ra:.4f}_{dec:+.4f}_{radius_deg:.4f}_{'-'.join(collections)}.json"
    path = config.CACHE_DIR / "search" / name
    if path.is_file():
        return json.loads(path.read_text())

    # Earlier collections in the list win when an exposure is in both
    seen: dict[tuple[str, str], dict] = {}
    for collection in collections:
        for p in search_collection(collection, ra, dec, radius_deg):
            seen.setdefault((p["obs_id"], p["detector"]), p)
    products = sorted(seen.values(), key=lambda p: (p["mjd"], p["detector"]))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(products))
    return products


def cached_search_near(
    ra: float, dec: float, max_deg: float
) -> tuple[list[dict], float] | None:
    """Closest exposure list already on disk, with its distance in degrees.

    Used only when the archive search is down. Exposures are 3.5 degrees
    wide, so a list from a point close by mostly covers the same sky, and the
    cutout service rejects any exposure that does not.
    """
    best = None
    for path in (config.CACHE_DIR / "search").glob("*.json"):
        parts = path.stem.split("_")
        try:
            ra_c, dec_c = float(parts[0]), float(parts[1])
        except (ValueError, IndexError):
            continue
        sep = float(np.hypot((ra_c - ra) * np.cos(np.radians(dec)), dec_c - dec))
        if sep <= max_deg and (best is None or sep < best[1]):
            best = (path, sep)
    if best is None:
        return None
    return json.loads(best[0].read_text()), best[1]


# --- Cutouts ---


def cutout_path(product: dict, ra: float, dec: float, size_deg: float) -> Path:
    """Cache path. The name says the PSF was left out, so it is never taken for a full file."""
    name = f"{product['obs_id']}_{product['detector']}_{ra:.4f}_{dec:+.4f}_{size_deg:.3f}_nopsf.fits"
    return config.CACHE_DIR / "cutouts" / product["collection"] / name


def check_hdus(data: bytes, names: list[str]) -> None:
    """Raise unless data is exactly these HDUs after the primary, each one whole."""
    spans = hdu_spans(data)
    found = [name for name, _, _ in spans[1:]]
    if found != names:
        raise RuntimeError(f"expected extensions {names}, got {found}")
    if spans[-1][2] != len(data):
        raise RuntimeError(f"file is {len(data)} bytes, extensions need {spans[-1][2]}")


def wave_table_hdu(product: dict, url: str) -> bytes:
    """Raw WCS-WAVE extension for a detector, taken once from a full cutout.

    The table is in detector coordinates and comes from one calibration file
    per detector, so it is the same in every cutout of a collection.
    scripts/check_wave_table.py tests this on full downloads.
    """
    path = (
        config.CACHE_DIR / "wave" / f"{product['collection']}_{product['detector']}.hdu"
    )
    with wave_lock:
        if not path.is_file():
            full = http_get(url)
            spans = {name: (a, b) for name, a, b in hdu_spans(full)}
            if "WCS-WAVE" not in spans or spans["WCS-WAVE"][1] > len(full):
                raise RuntimeError(f"no complete WCS-WAVE extension in {url}")
            start, stop = spans["WCS-WAVE"]
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            tmp.write_bytes(full[start:stop])
            tmp.replace(path)
        return path.read_bytes()


def fetch_cutout(product: dict, ra: float, dec: float, size_deg: float) -> Path:
    """Download one cutout unless it is already cached. The PSF is not downloaded.

    Nothing is cached unless every plane we use arrived whole.
    """
    path = cutout_path(product, ra, dec, size_deg)
    if path.is_file():
        return path
    url = f"{product['access_url']}?center={ra:.6f},{dec:.6f}&size={size_deg:.4f}"
    last = ""
    for _ in range(2):
        try:
            data = http_get(url, skip_psf=True)
            # A stream that stopped early fails here and is thrown away
            check_hdus(data, config.CUTOUT_PLANES)
            data += wave_table_hdu(product, url)
            check_hdus(data, config.CUTOUT_PLANES + ["WCS-WAVE"])
            break
        except RuntimeError as err:
            last = str(err)
            log.warning("Bad cutout, trying again (%s): %s", last, url)
    else:
        raise RuntimeError(f"cutout incomplete ({last}): {url}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(path)
    return path


def fetch_cutouts(
    products: list[dict], ra: float, dec: float, size_deg: float
) -> list[Path | None]:
    """Download many cutouts in parallel. A failed download gives None."""

    def fetch(product: dict) -> Path | None:
        try:
            return fetch_cutout(product, ra, dec, size_deg)
        except RuntimeError as err:
            log.warning("Skipping %s: %s", product["obs_id"], err)
            return None

    with ThreadPoolExecutor(max_workers=config.DOWNLOAD_WORKERS) as pool:
        return list(pool.map(fetch, products))


# --- FITS reading ---


def read_wavelength(hdul: fits.HDUList) -> np.ndarray:
    """Central wavelength in microns at every pixel, from the WCS-WAVE lookup table."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FITSFixedWarning)
        wave_wcs = WCS(hdul["IMAGE"].header, fobj=hdul, key="W")
    wave_wcs.sip = None
    ny, nx = hdul["IMAGE"].data.shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    wave, _ = wave_wcs.wcs_pix2world(xx, yy, 0)
    return wave.astype(np.float32)


def read_cutout(path: Path) -> dict:
    """Read the planes we use. PSF is skipped."""
    with fits.open(path) as hdul:
        header = hdul["IMAGE"].header
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FITSFixedWarning)
            sky_wcs = WCS(header)
        return {
            "image": hdul["IMAGE"].data.astype(np.float32),
            "flags": hdul["FLAGS"].data.astype(np.int64),
            "variance": hdul["VARIANCE"].data.astype(np.float32),
            "zodi": hdul["ZODI"].data.astype(np.float32),
            "wavelength": read_wavelength(hdul),
            "header": header,
            "flags_header": hdul["FLAGS"].header,
            "wcs": sky_wcs,
            "finast": int(header.get("FINAST", 0)) == 1,
            "mjd": float(header["MJD-AVG"]),
        }
