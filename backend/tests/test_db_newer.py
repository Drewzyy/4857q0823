import sqlalchemy as sa

from clippr.db import Database


def test_older_app_starts_on_data_from_a_newer_version(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'x.db'}")
    db.migrate()
    with db.engine.begin() as c:
        c.execute(sa.text("UPDATE alembic_version SET version_num = '9999'"))  # as if a newer Vyral migrated it
    db.migrate()  # must not raise
    with db.engine.begin() as c:
        assert c.scalar(sa.text("SELECT version_num FROM alembic_version")) == "9999"
