"""Tombaugh API."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config

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
