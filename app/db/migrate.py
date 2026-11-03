"""Bring the database schema to the latest Alembic revision.

Databases created by the old `Base.metadata.create_all()` have tables but no
`alembic_version`; those are stamped at the baseline first so only the newer
migrations run.

Usage: python -m app.db.migrate
"""
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.core.database import engine

logger = logging.getLogger(__name__)

BASELINE = "0001_baseline"
ROOT = Path(__file__).resolve().parents[2]


def _config() -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.attributes["skip_logging_config"] = True
    return cfg


def run_migrations() -> None:
    cfg = _config()
    tables = set(inspect(engine).get_table_names())
    if "users" in tables and "alembic_version" not in tables:
        logger.info("Legacy schema detected; stamping %s", BASELINE)
        command.stamp(cfg, BASELINE)
    command.upgrade(cfg, "head")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migrations()
