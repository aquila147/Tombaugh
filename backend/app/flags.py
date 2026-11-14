"""FLAGS decoding. Bit names are read from each file's FLAGS header."""

import numpy as np
from astropy.io.fits import Header

from app import config


def read_flag_bits(flags_header: Header) -> dict[str, int]:
    """Map flag name to bitmask for either header style."""
    bits: dict[str, int] = {}
    for key in flags_header:
        # QR3 and DR1: MSKN#### holds the name, MSKM#### the mask
        if key.startswith("MSKN"):
            mask = flags_header.get("MSKM" + key[4:])
            if mask is not None:
                bits[str(flags_header[key]).strip()] = int(mask)
        # QR2: MP_<NAME> holds the bit number
        elif key.startswith("MP_"):
            bits[key[3:].strip()] = 1 << int(flags_header[key])
    return bits


def bad_pixel_mask(
    flags: np.ndarray, flags_header: Header, mask_outlier: bool = False
) -> np.ndarray:
    """True where a pixel should not be used.

    SOURCE is never bad. OUTLIER is kept by default because the pipeline
    sets it on moving objects.
    """
    bits = read_flag_bits(flags_header)
    names = list(config.BAD_FLAGS)
    if mask_outlier:
        names.append("OUTLIER")
    combined = 0
    for name in names:
        combined |= bits.get(name, 0)
    return (flags & combined) != 0


def flag_names_at(flags: np.ndarray, flags_header: Header, y: int, x: int) -> list[str]:
    value = int(flags[y, x])
    return [name for name, mask in read_flag_bits(flags_header).items() if value & mask]
