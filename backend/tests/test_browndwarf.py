"""Brown dwarf score checks. All spectra here are synthetic and made for the test."""

import unittest

import numpy as np

from app import browndwarf


def synthetic_points(methane: float, continuum: float, short: float) -> np.ndarray:
    """(wavelength, flux) rows with a set flux in each band."""
    rows = []
    for band, flux in [
        (browndwarf.METHANE_BAND, methane),
        (browndwarf.CONTINUUM_BAND, continuum),
        (browndwarf.SHORT_BAND, short),
    ]:
        for wave in np.linspace(band[0] + 0.01, band[1] - 0.01, 6):
            rows.append((wave, flux * (1 + 0.01 * np.sin(40 * wave))))
    return np.array(rows)


class Features(unittest.TestCase):
    def test_methane_index_is_band_ratio(self):
        got = browndwarf.spectral_features(synthetic_points(2.0, 10.0, 3.0))
        self.assertAlmostEqual(got["methane_index"]["value"], 0.2, delta=0.01)
        self.assertAlmostEqual(got["short_over_long"]["value"], 0.3, delta=0.01)

    def test_no_index_without_continuum(self):
        got = browndwarf.spectral_features(synthetic_points(2.0, 0.0, 3.0))
        self.assertIsNone(got["methane_index"])

    def test_too_few_points_gives_no_band(self):
        points = synthetic_points(2.0, 10.0, 3.0)[:2]
        self.assertIsNone(browndwarf.band_flux(points, browndwarf.METHANE_BAND))


class Score(unittest.TestCase):
    def test_all_three_features(self):
        got = browndwarf.score(8.0, 0.5, 6.0, 5.0)
        self.assertEqual(got["score"], 3)
        self.assertIn("not an identification", got["label"])

    def test_star_with_motion_only(self):
        got = browndwarf.score(10.0, 0.8, 0.2, -0.5)
        self.assertEqual(got["score"], 1)

    def test_asteroid_scores_zero(self):
        got = browndwarf.score(240000.0, 400.0, 9.0, 9.0)
        self.assertEqual(got["score"], 0)
        self.assertTrue(got["note"])

    def test_unmeasured_features_do_not_count(self):
        got = browndwarf.score(None, None, None, None)
        self.assertEqual(got["score"], 0)


if __name__ == "__main__":
    unittest.main()
