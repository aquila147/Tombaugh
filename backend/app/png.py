"""Greyscale PNG writer using only the standard library."""

import struct
import zlib
from pathlib import Path

import numpy as np


def limits(
    image: np.ndarray, lo_pct: float = 25.0, hi_pct: float = 99.7
) -> tuple[float, float]:
    good = image[np.isfinite(image)]
    if good.size == 0:
        return 0.0, 1.0
    lo, hi = np.percentile(good, [lo_pct, hi_pct])
    return float(lo), float(hi)


def stretch(image: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Asinh stretch to 0..1 between fixed limits. NaN pixels map to 0."""
    scaled = np.clip((image - lo) / max(hi - lo, 1e-12), 0, 1)
    out = np.arcsinh(10 * scaled) / np.arcsinh(10)
    return np.nan_to_num(out, nan=0.0).astype(np.float32)


def save_png(
    path: Path, image01: np.ndarray, negative: bool = True, zoom: int = 1
) -> None:
    """Write a 0..1 image as 8-bit grey. Row 0 of the array ends up at the bottom."""
    grey = (255 * (1 - image01 if negative else image01)).astype(np.uint8)[::-1]
    grey = np.kron(grey, np.ones((zoom, zoom), dtype=np.uint8))
    h, w = grey.shape
    raw = b"".join(b"\x00" + row.tobytes() for row in grey)

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
