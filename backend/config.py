"""Application configuration and paths.

Centralizes filesystem locations so every entrypoint (CLI, scraper, server)
agrees on where the SQLite DB and run artifacts live. Local-only by design:
no env vars are required, but a few are honored if set.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
SEEDS_DIR = REPO_ROOT / "seeds"
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


@dataclass(frozen=True)
class Settings:
    db_path: Path
    data_dir: Path
    seeds_dir: Path
    frontend_dist: Path
    host: str
    port: int
    api_key: str | None
    retention_days: int
    posted_within_days_max: int
    store_raw_payload: bool
    extra_cors_origins: tuple[str, ...]
    user_agent: str

    @property
    def db_url(self) -> str:
        # SQLAlchemy URL for SQLite, file-based.
        return f"sqlite:///{self.db_path.as_posix()}"


def get_settings() -> Settings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return Settings(
        db_path=Path(os.environ.get("JOBPULSE_DB", DATA_DIR / "jobpulse.db")),
        data_dir=DATA_DIR,
        seeds_dir=SEEDS_DIR,
        frontend_dist=FRONTEND_DIST,
        host=os.environ.get("JOBPULSE_HOST", "127.0.0.1"),
        port=int(os.environ.get("JOBPULSE_PORT", "8000")),
        api_key=os.environ.get("JOBPULSE_API_KEY") or None,
        retention_days=int(os.environ.get("JOBPULSE_RETENTION_DAYS", "15")),
        # Upper bound for the `posted_within_days` API filter. Default 15
        # matches the dashboard's rolling-window UX; power users / scripts
        # can widen via env var without touching code.
        posted_within_days_max=int(
            os.environ.get("JOBPULSE_POSTED_WITHIN_DAYS_MAX", "15")
        ),
        # Opt-in retention of raw adapter payloads on each `jobs` row
        # (truncated to 200 KB). Off by default to keep the DB lean —
        # nothing in the read path consumes this column. Set to `1`/`true`
        # if debugging adapter normalization.
        store_raw_payload=os.environ.get("JOBPULSE_STORE_RAW_PAYLOAD", "").lower()
        in {"1", "true", "yes", "on"},
        # Extra CORS origins (comma-separated) for contributors running the
        # dashboard on a non-default port. The defaults in `serve.py` already
        # cover the standard Vite ports.
        extra_cors_origins=tuple(
            o.strip()
            for o in os.environ.get("JOBPULSE_DEV_ORIGINS", "").split(",")
            if o.strip()
        ),
        user_agent=os.environ.get(
            "JOBPULSE_USER_AGENT",
            # Browser-class UA to avoid blanket CDN/Cloudflare bot blocks
            # (Personio, Teamtailor, some Workday tenants 403/429 generic bot UAs).
            # Override with JOBPULSE_USER_AGENT to identify yourself explicitly.
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36",
        ),
    )


settings = get_settings()
