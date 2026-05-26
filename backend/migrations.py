"""Migration helpers — run Alembic programmatically from `run.py`."""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from .config import REPO_ROOT, settings


def _alembic_cfg() -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "backend" / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.db_url)
    return cfg


def upgrade_to_head() -> None:
    """Run all pending migrations. Safe to call on every startup."""
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(_alembic_cfg(), "head")


def downgrade_to_base() -> None:
    command.downgrade(_alembic_cfg(), "base")
