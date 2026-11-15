"""Cutout cache guards. All FITS data here is synthetic and made for the test."""

import io
import unittest

import numpy as np
from astropy.io import fits

from app import archive, config


def synthetic_cutout() -> bytes:
    hdus = [fits.PrimaryHDU()]
    for name in config.CUTOUT_PLANES:
        hdus.append(fits.ImageHDU(np.zeros((40, 40), dtype=np.float32), name=name))
    hdus.append(fits.ImageHDU(np.zeros((90, 90), dtype=np.float64), name="EPSF"))
    hdus.append(fits.ImageHDU(np.zeros((4, 4), dtype=np.float32), name="WCS-WAVE"))
    out = io.BytesIO()
    fits.HDUList(hdus).writeto(out)
    return out.getvalue()


class FakeResponse:
    def __init__(self, data: bytes):
        self.data = data

    def iter_content(self, size: int):
        for i in range(0, len(self.data), 1000):
            yield self.data[i : i + 1000]

    def close(self) -> None:
        pass


class CutoutGuards(unittest.TestCase):
    def setUp(self):
        self.full = synthetic_cutout()
        self.spans = {name: (a, b) for name, a, b in archive.hdu_spans(self.full)}

    def test_stream_stops_at_psf(self):
        data = archive.read_before_psf(FakeResponse(self.full))
        self.assertEqual(len(data), self.spans["EPSF"][0])
        archive.check_hdus(data, config.CUTOUT_PLANES)

    def test_stream_cut_inside_a_plane_is_rejected(self):
        for name in config.CUTOUT_PLANES:
            start, stop = self.spans[name]
            for cut in (start + 100, start + 2880, stop - 1):
                data = archive.read_before_psf(FakeResponse(self.full[:cut]))
                with self.assertRaises(RuntimeError):
                    archive.check_hdus(data, config.CUTOUT_PLANES)

    def test_full_file_is_not_accepted_as_truncated(self):
        with self.assertRaises(RuntimeError):
            archive.check_hdus(self.full, config.CUTOUT_PLANES)

    def test_appended_wave_table_passes(self):
        data = archive.read_before_psf(FakeResponse(self.full))
        start, stop = self.spans["WCS-WAVE"]
        data += self.full[start:stop]
        archive.check_hdus(data, config.CUTOUT_PLANES + ["WCS-WAVE"])
        with fits.open(io.BytesIO(data)) as hdul:
            self.assertEqual(hdul[-1].name, "WCS-WAVE")


if __name__ == "__main__":
    unittest.main()
