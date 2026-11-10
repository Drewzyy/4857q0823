"""Engine/session setup and schema migrations (Alembic, run automatically on startup)."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
log = logging.getLogger("clippr.db")


def make_engine(db_url: str) -> Engine:
    engine = create_engine(db_url, connect_args={"check_same_thread": False} if db_url.startswith("sqlite") else {})
    if db_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")  # crash-safe, concurrent readers
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

    return engine


def run_migrations(engine: Engine) -> None:
    from alembic import command
    from alembic.config import Config as AlembicConfig
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
        known = {sc.revision for sc in ScriptDirectory.from_config(cfg).walk_revisions()}
        if current and current not in known:
            # A newer Vyral already upgraded this data (e.g. an older copy was reopened). Leave it as it is:
            # migrations only go forward.
            log.warning("data is from a newer Vyral (schema %s); leaving it as is", current)
            return
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")


class Database:
    def __init__(self, db_url: str):
        self.engine = make_engine(db_url)
        self.SessionLocal = sessionmaker(self.engine, expire_on_commit=False)

    def migrate(self) -> None:
        run_migrations(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        s = self.SessionLocal()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()
