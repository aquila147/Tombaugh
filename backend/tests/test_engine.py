"""Engine and linking tests. Every image here is synthetic and made for the test."""

import unittest

import numpy as np

from app import config, detect, engine

SIZE = 60
SIGMA = 1.5
NOISE = 0.01


def blob(x: float, y: float) -> np.ndarray:
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    return np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * SIGMA**2))


def synthetic_frames(n: int, rng, mover=None, transient=None) -> list[dict]:
    """A star whose brightness depends on wavelength, plus optional extras."""
    out = []
    for i in range(n):
        wavelength = 1.0 + 0.5 * rng.random()
        years = i / (n - 1) - 0.5
        image = (1.0 + 2.0 * (wavelength - 1.0)) * blob(20, 20)
        if mover:
            image = image + 0.5 * blob(40 + mover * years, 40)
        if transient == i:
            image = image + 0.3 * blob(45, 15)
        image = image + rng.normal(0, NOISE, image.shape)
        out.append(
            {
                "image": image.astype(np.float32),
                "wavelength": np.full(image.shape, wavelength, dtype=np.float32),
                "noise": NOISE,
                "mjd": 61000.0 + 365.25 * years,
            }
        )
    return out


class EngineTests(unittest.TestCase):
    def test_star_cancels_and_transient_remains(self):
        rng = np.random.default_rng(1)
        frames = synthetic_frames(40, rng, transient=7)
        result = engine.clean_differences(frames)
        peaks = detect.find_peaks(result["maps"][7]["z"])
        self.assertEqual(len(peaks), 1)
        self.assertAlmostEqual(peaks[0]["x"], 45, delta=1.5)
        self.assertAlmostEqual(peaks[0]["y"], 15, delta=1.5)
        others = sum(
            len(detect.find_peaks(m["z"]))
            for i, m in enumerate(result["maps"])
            if i != 7
        )
        self.assertEqual(others, 0)

    def test_plain_difference_leaves_the_star(self):
        rng = np.random.default_rng(2)
        frames = synthetic_frames(40, rng)
        plain = engine.plain_differences(frames[1:], frames[0]["image"])
        self.assertGreater(sum(len(detect.find_peaks(m["z"])) for m in plain), 5)

    def test_slow_mover_found_with_direction(self):
        rng = np.random.default_rng(3)
        rate_pix = 1.0
        frames = synthetic_frames(40, rng, mover=rate_pix)
        result = engine.clean_differences(frames)
        movers = detect.find_slow_movers(
            result["trend"], result["trend_err"], result["mean_image"]
        )
        self.assertEqual(len(movers), 1)
        self.assertAlmostEqual(movers[0]["x"], 40, delta=2)
        self.assertAlmostEqual(movers[0]["y"], 40, delta=2)
        # Grid x runs west, so +x motion is towards the west
        expected = -rate_pix * config.GRID_PIXEL_ARCSEC
        self.assertAlmostEqual(
            movers[0]["pm_east_arcsec_yr"], expected, delta=0.3 * abs(expected)
        )


class LinkTests(unittest.TestCase):
    def test_line_is_linked_and_scatter_is_not(self):
        rng = np.random.default_rng(4)
        times = 61000 + np.array([0.0, 0.07, 0.14, 0.5, 0.57])
        x = 100 + 300 * (times - times[0])
        y = 200 - 150 * (times - times[0])
        extra = 30
        dets = {
            "t": np.concatenate([times, 61000 + rng.uniform(0, 0.6, extra)]),
            "x": np.concatenate([x, rng.uniform(0, 720, extra)]),
            "y": np.concatenate([y, rng.uniform(0, 720, extra)]),
            "frame": np.concatenate([np.arange(5), rng.integers(5, 40, extra)]),
            "snr": np.full(5 + extra, 8.0),
        }
        tracks = detect.link_tracks(dets, config.LINK_FAST)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(sorted(tracks[0]["members"]), [0, 1, 2, 3, 4])
        self.assertAlmostEqual(
            tracks[0]["rate_arcsec_day"], np.hypot(300, 150), delta=5
        )


if __name__ == "__main__":
    unittest.main()
