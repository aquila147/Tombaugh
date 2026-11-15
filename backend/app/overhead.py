"""Zenith position for a place and time, and the field that contains it."""

import numpy as np
from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord
from astropy.time import Time
from astropy.utils import iers

from app import config

# Use the tables shipped with astropy; never fetch from the network on a request
iers.conf.auto_download = False
iers.conf.iers_degraded_accuracy = "ignore"


def zenith(lat_deg: float, lon_deg: float, when: Time) -> tuple[float, float]:
    """ICRS RA and Dec of the point straight overhead.

    RA is the local sidereal time and Dec is the latitude, both of date;
    the transform to ICRS adds the precession since J2000 (about 0.4 degrees).
    """
    place = EarthLocation(lat=lat_deg * u.deg, lon=lon_deg * u.deg)
    up = SkyCoord(
        alt=90 * u.deg, az=0 * u.deg, frame=AltAz(obstime=when, location=place)
    )
    sky = up.icrs
    return float(sky.ra.deg), float(sky.dec.deg)


def field_centre(ra: float, dec: float) -> tuple[float, float, str]:
    """Snap a position to the field grid. Returns centre RA, Dec and a field id."""
    step = config.FIELD_STEP_DEG
    dec_c = round(dec / step) * step
    ra_step = step / max(np.cos(np.radians(dec_c)), 0.05)
    ra_c = (round(ra / ra_step) * ra_step) % 360
    return round(ra_c, 4), round(dec_c, 4), f"{ra_c:08.4f}_{dec_c:+08.4f}"
