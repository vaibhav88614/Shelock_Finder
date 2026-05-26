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
        user_agent=os.environ.get(
            "JOBPULSE_USER_AGENT",
            "JobPulseBot/1.0 (+https://github.com/local/jobpulse)",
        ),
    )


settings = get_settings()
