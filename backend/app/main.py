"""Tombaugh API."""

import logging

from astropy.time import Time
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import config, jobs, overhead

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("tombaugh")

app = FastAPI(title=config.APP_NAME, version=config.APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# --- Routes ---


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "name": config.APP_NAME,
        "version": config.APP_VERSION,
        "supabase_configured": bool(
            config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY
        ),
    }


@app.get("/api/overhead")
def overhead_field(lat: float, lon: float, time: str | None = None) -> dict:
    """Zenith RA/Dec for a place and time, snapped to a field centre."""
    if not (-90 <= lat <= 90 and -180 <= lon <= 360):
        raise HTTPException(status_code=422, detail="lat or lon out of range")
    try:
        when = Time(time, scale="utc") if time else Time.now()
    except ValueError:
        raise HTTPException(
            status_code=422, detail="time must be an ISO date"
        ) from None
    ra, dec = overhead.zenith(lat, lon, when)
    ra_c, dec_c, field_id = overhead.field_centre(ra, dec)
    return {
        "zenith_ra": round(ra, 4),
        "zenith_dec": round(dec, 4),
        "field_ra": ra_c,
        "field_dec": dec_c,
        "field_id": field_id,
        "fov_deg": config.DEFAULT_FOV_DEG,
        "time_utc": when.utc.isot,
    }


class FieldRequest(BaseModel):
    ra: float
    dec: float
    fov_deg: float = config.DEFAULT_FOV_DEG
    detector: str | None = None


@app.post("/api/field")
def start_field(request: FieldRequest) -> dict:
    """Start or reuse a job that builds the plate for a sky patch."""
    if not (0 <= request.ra < 360 and -90 <= request.dec <= 90):
        raise HTTPException(status_code=422, detail="ra or dec out of range")
    if not (0.05 <= request.fov_deg <= config.LIVE_MAX_FOV_DEG):
        raise HTTPException(
            status_code=422,
            detail=f"fov_deg must be between 0.05 and {config.LIVE_MAX_FOV_DEG}",
        )
    if request.detector is not None and request.detector not in config.DETECTORS:
        raise HTTPException(status_code=422, detail="unknown detector")
    return jobs.start(request.ra, request.dec, request.fov_deg, request.detector)


@app.get("/api/field/{job_id}")
def field_status(job_id: str) -> dict:
    """Progress and, when done, where the plate files are."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="no such job")
    return job


@app.get("/api/check")
def check_position(ra: float, dec: float, job_id: str) -> dict:
    """Automatic checks for the engine candidate nearest a position in a job's field."""
    found = jobs.check_at(job_id, ra, dec)
    if found is None:
        raise HTTPException(status_code=404, detail="no finished job with that id")
    return found


# Plates built by live jobs, read by the viewer exactly like the stored ones
jobs.FIELDS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/api/files", StaticFiles(directory=jobs.FIELDS_DIR), name="files")
