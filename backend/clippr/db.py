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
    sqlite = engine.dialect.name == "sqlite"
    with engine.connect() as conn:
        # Changing a column in SQLite rebuilds the table (copy, drop the old, rename). With foreign keys enforced,
        # dropping the old table counts as deleting its rows and cascades: an update once wiped every page's
        # ready-to-upload video this way. So enforcement is off while the schema changes (it can only be switched
        # outside a transaction) and back on after, with a check that nothing was left pointing nowhere.
        if sqlite:
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            conn.commit()  # ends SQLAlchemy's automatic transaction so the update below gets its own
        try:
            with conn.begin():
                current = MigrationContext.configure(conn).get_current_revision()
                known = {sc.revision for sc in ScriptDirectory.from_config(cfg).walk_revisions()}
                if current and current not in known:
                    # A newer Vyral already upgraded this data (e.g. an older copy was reopened). Leave it as it
                    # is: migrations only go forward.
                    log.warning("data is from a newer Vyral (schema %s); leaving it as is", current)
                    return
                cfg.attributes["connection"] = conn
                command.upgrade(cfg, "head")
        finally:
            if sqlite:
                broken = conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
                if broken:
                    log.warning("after the update, %d rows point at missing rows: %s", len(broken), broken[:5])
                conn.exec_driver_sql("PRAGMA foreign_keys=ON")
                conn.commit()


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
