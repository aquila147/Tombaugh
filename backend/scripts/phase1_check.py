"""Phase 1 checkpoint: product counts for WISE 0855 and one cleaned cutout as PNG.

Run from backend/:  python -m scripts.phase1_check
"""

import logging
from collections import Counter

import numpy as np
from astropy.time import Time

from app import archive, config, flags, frames, png

RA, DEC = 133.7951, -7.2451
SIZE_DEG = 0.2

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def main() -> None:
    products = archive.search(RA, DEC)
    print(f"WISE 0855 at RA {RA}, Dec {DEC}: {len(products)} products")

    # --- Counts ---
    for name, n in sorted(Counter(p["collection"] for p in products).items()):
        print(f"  collection {name}: {n}")
    for name, n in sorted(Counter(p["detector"] for p in products).items()):
        print(f"  detector {name}: {n}")

    visits = frames.group_visits(products)
    print(f"{len(visits)} visits (gap longer than {config.VISIT_GAP_HOURS} h)")
    for i, visit in enumerate(visits):
        date = Time(visit[0]["mjd"], format="mjd").utc.isot[:16]
        per_det = Counter(p["detector"] for p in visit)
        dets = " ".join(f"{d}:{per_det[d]}" for d in sorted(per_det))
        print(f"  visit {i:2d}  {date}  {len(visit):3d} products  {dets}")

    # --- FINAST across the longest-wavelength detector ---
    d6 = [p for p in products if p["detector"] == "D6"]
    paths = archive.fetch_cutouts(d6, RA, DEC, SIZE_DEG)
    cutouts = [(p, archive.read_cutout(f)) for p, f in zip(d6, paths) if f]
    solved = [(p, c) for p, c in cutouts if c["finast"]]
    print(
        f"D6: {len(cutouts)} of {len(d6)} cutouts downloaded, FINAST solved in {len(solved)}"
    )

    # --- One cleaned cutout ---
    product, cutout = solved[0] if solved else cutouts[0]
    image = frames.clean_image(cutout)
    ny, nx = image.shape
    x, y = cutout["wcs"].all_world2pix(RA, DEC, 0)
    xi, yi = int(round(float(x))), int(round(float(y)))

    print(f"Cutout {product['obs_id']} {product['detector']} ({product['collection']})")
    print(f"  shape {ny} x {nx}, FINAST solved: {cutout['finast']}")
    print(f"  target at pixel x={float(x):.1f} y={float(y):.1f}")
    print(f"  wavelength at target: {cutout['wavelength'][yi, xi]:.4f} um")
    wave = cutout["wavelength"]
    print(
        f"  wavelength across cutout: {np.nanmin(wave):.4f} to {np.nanmax(wave):.4f} um"
    )
    print(f"  masked pixels: {np.isnan(image).mean() * 100:.1f} %")
    print(
        f"  flags at target: {flags.flag_names_at(cutout['flags'], cutout['flags_header'], yi, xi)}"
    )

    out = config.CACHE_DIR / "phase1_wise0855.png"
    png.save_png(out, png.stretch(image), negative=True, zoom=4)
    print(f"  saved {out}")


if __name__ == "__main__":
    main()
