"""Checks that need no network. All tracks here are synthetic and made for the test."""

import unittest

from app import checks, config, overhead
from astropy.time import Time


def track(points: list[tuple[float, float, float]]) -> dict:
    """A fast candidate from (hours, x arcsec, y arcsec) points."""
    detections = [
        {
            "frame": i,
            "mjd": 61000 + h / 24,
            "x_arcsec": x,
            "y_arcsec": y,
            "snr": 9.0,
            "area": 6,
        }
        for i, (h, x, y) in enumerate(points)
    ]
    return {
        "kind": "fast",
        "mjd": 61000.2,
        "n_frames": len(points),
        "detections": detections,
    }


class LineCheck(unittest.TestCase):
    def test_steady_track_passes(self):
        result = checks.check_line(track([(0, 0, 0), (5, 100, 50), (10, 200, 100)]), {})
        self.assertEqual(result["result"], "pass")

    def test_changing_speed_fails(self):
        result = checks.check_line(track([(0, 0, 0), (5, 100, 50), (10, 400, 200)]), {})
        # A changing speed also shows up as scatter about a steady-rate line
        self.assertEqual(result["result"], "fail")

    def test_one_visit_fails(self):
        result = checks.check_line(track([(0, 0, 0), (0.03, 1, 0), (0.06, 2, 0)]), {})
        self.assertEqual(result["result"], "fail")

    def test_two_visits_only_warn(self):
        result = checks.check_line(track([(0, 0, 0), (0.03, 1, 0), (6, 150, 0)]), {})
        self.assertEqual(result["result"], "warn")


class CrowdCheck(unittest.TestCase):
    def test_many_thin_tracks_from_one_night_are_flagged(self):
        candidate = track([(0, 0, 0), (5, 100, 50), (10, 200, 100)])
        thin = [{"t0": 61000.2 + 0.01 * i, "n_frames": 3} for i in range(4)]
        self.assertEqual(
            checks.check_crowd(candidate, {"tracks": thin})["result"], "fail"
        )
        self.assertIsNone(checks.check_crowd(candidate, {"tracks": thin[:2]}))

    def test_long_track_is_not_flagged(self):
        candidate = track([(h, 20 * h, 0) for h in range(0, 12, 2)])
        thin = [{"t0": 61000.2, "n_frames": 3} for _ in range(5)]
        self.assertIsNone(checks.check_crowd(candidate, {"tracks": thin}))


class Ladder(unittest.TestCase):
    def test_status_names_match_the_table(self):
        self.assertEqual(checks.STATUS_LADDER[:2], ["flagged", "passed_checks"])
        self.assertEqual(
            set(checks.STATUS_LADDER[-3:]), {"known", "artifact", "unexplained"}
        )


class Overhead(unittest.TestCase):
    def test_zenith_is_near_sidereal_time_and_latitude(self):
        when = Time("2026-11-15T12:00:00", scale="utc")
        ra, dec = overhead.zenith(1.3521, 103.8198, when)
        self.assertAlmostEqual(dec, 1.3521, delta=0.3)
        self.assertAlmostEqual(ra, 338.41, delta=0.6)

    def test_field_centre_is_on_the_grid(self):
        ra_c, dec_c, _ = overhead.field_centre(338.0648, 1.2115)
        self.assertAlmostEqual(
            dec_c / config.FIELD_STEP_DEG, round(dec_c / config.FIELD_STEP_DEG)
        )
        self.assertLess(abs(ra_c - 338.0648), config.FIELD_STEP_DEG)


if __name__ == "__main__":
    unittest.main()
