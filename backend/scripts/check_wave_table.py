"""Check that the WCS-WAVE table is the same in every cutout of a detector.

Downloads full, un-truncated cutouts for each detector at different sky
positions and dates and compares their tables with each other and with the
cached table that truncated downloads reuse.

Run from backend/:  python -m scripts.check_wave_table
"""

import io
import logging
from concurrent.futures import ThreadPoolExecutor

from astropy.io import fits
from astropy.time import Time

from app import archive, config

# Showcase field centres
FIELDS = {
    "wise0855": (133.7951, -7.2451),
    "barnard": (269.4463, 4.7679),
    "eps_indi_b": (331.0958, -56.8009),
    "rw_aur": (76.9565, 30.4013),
    "r_dra": (248.1975, 66.7519),
}
SIZE_DEG = 0.05


def table_key(hdu) -> bytes:
    data = hdu.data
    return data["X"].tobytes() + data["Y"].tobytes() + data["VALUES"].tobytes()


def fetch_full(job: tuple) -> tuple:
    field, (ra, dec), product = job
    url = f"{product['access_url']}?center={ra:.6f},{dec:.6f}&size={SIZE_DEG}"
    data = archive.http_get(url)
    names = [name for name, _, _ in archive.hdu_spans(data)]
    with fits.open(io.BytesIO(data)) as hdul:
        return field, product, names, table_key(hdul["WCS-WAVE"])


def cached_key(detector: str) -> bytes | None:
    path = config.CACHE_DIR / "wave" / f"spherex_dr1_{detector}.hdu"
    if not path.is_file():
        return None
    primary = io.BytesIO()
    fits.PrimaryHDU().writeto(primary)
    with fits.open(io.BytesIO(primary.getvalue() + path.read_bytes())) as hdul:
        return table_key(hdul[1])


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    jobs = []
    for i, (field, centre) in enumerate(FIELDS.items()):
        products = archive.search(*centre)
        for detector in config.DETECTORS:
            chosen = [p for p in products if p["detector"] == detector]
            if chosen:
                # A different part of the time range in each field
                jobs.append((field, centre, chosen[(len(chosen) - 1) * i // 4]))
    with ThreadPoolExecutor(max_workers=config.DOWNLOAD_WORKERS) as pool:
        results = list(pool.map(fetch_full, jobs))

    all_ok = True
    for detector in config.DETECTORS:
        rows = [r for r in results if r[1]["detector"] == detector]
        keys = {r[3] for r in rows}
        cached = cached_key(detector)
        note = "no cached table yet"
        if cached is not None:
            same = keys == {cached}
            note = "cached table matches" if same else "CACHED TABLE DIFFERS"
            all_ok &= same
        all_ok &= len(keys) == 1
        print(
            f"{detector}: {len(rows)} full cutouts, {len(keys)} distinct table(s), {note}"
        )
        for field, product, names, _ in rows:
            date = Time(product["mjd"], format="mjd").utc.isot[:10]
            print(f"    {field:11s} {date}  {product['obs_id']}  {names[1:]}")
    print(
        "RESULT:", "all tables identical per detector" if all_ok else "MISMATCH FOUND"
    )


if __name__ == "__main__":
    main()
