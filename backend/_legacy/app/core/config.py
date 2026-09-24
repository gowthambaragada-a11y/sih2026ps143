"""Core configuration for OILTRACE-AI.

All paths are resolved relative to the repository root so that the
application works identically locally and inside Docker.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # pragma: no cover - dotenv optional
    pass

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(os.getenv("OILTRACE_DATA_DIR", REPO_ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
MASTER_DIR = DATA_DIR / "master"
MODELS_DIR = Path(os.getenv("OILTRACE_MODELS_DIR", REPO_ROOT / "models"))
ARTIFACT_DIR = Path(os.getenv("OILTRACE_ARTIFACT_DIR", REPO_ROOT / "backend" / "artifacts"))
REPORTS_DIR = ARTIFACT_DIR / "reports"
UPLOAD_DIR = ARTIFACT_DIR / "uploads"

for _d in (RAW_DIR, PROCESSED_DIR, MASTER_DIR, MODELS_DIR, ARTIFACT_DIR,
           REPORTS_DIR, UPLOAD_DIR):
    _d.mkdir(parents=True, exist_ok=True)


class Settings:
    """Runtime settings, all overridable via environment variables."""

    def __init__(self) -> None:
        self.app_name = "OILTRACE-AI"
        self.debug = os.getenv("OILTRACE_DEBUG", "1") == "1"
        self.api_prefix = "/api/v1"

        # --- Database (PostgreSQL + PostGIS). SQLite fallback for local dev. ---
        self.database_url = os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://oil:oil@localhost:5432/oiltrace",
        )
        self.use_sqlite = os.getenv("OILTRACE_USE_SQLITE", "1") == "1"
        self.sqlite_path = ARTIFACT_DIR / "oiltrace.db"

        # --- Auth ---
        self.security_enabled = os.getenv("OILTRACE_SECURITY", "0") == "1"
        self.jwt_secret = os.getenv("OILTRACE_JWT_SECRET", "dev-only-insecure-secret")
        self.jwt_algorithm = "HS256"
        self.jwt_expiry_minutes = int(os.getenv("OILTRACE_JWT_EXPIRY", "480"))

        # --- Detection model ---
        self.detection_backbone = os.getenv("OILTRACE_DETECTION_BACKBONE", "unet")
        self.detection_tile_size = int(os.getenv("OILTRACE_TILE_SIZE", "256"))

        # --- Drift ---
        self.drift_engine = os.getenv("OILTRACE_DRIFT_ENGINE", "fallback")  # "opendrift"|"fallback"

        # --- Version ---
        self.version = "0.1.0"

    @property
    def model_stores(self) -> Dict[str, Path]:
        return {
            "oil_segmentation": MODELS_DIR / "oil_segmentation",
            "origin_xgboost": MODELS_DIR / "origin_xgboost",
            "vessel_xgboost": MODELS_DIR / "vessel_xgboost",
            "ais_isolation_forest": MODELS_DIR / "ais_isolation_forest",
        }


settings = Settings()


def get_settings() -> Settings:
    return settings
