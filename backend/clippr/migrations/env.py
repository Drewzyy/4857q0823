from alembic import context
from sqlalchemy import create_engine

from clippr.models import Base

config = context.config
target_metadata = Base.metadata


def run() -> None:
    conn = config.attributes.get("connection")
    if conn is None:  # CLI usage: alembic -x url=sqlite:///path revision --autogenerate
        url = context.get_x_argument(as_dictionary=True).get("url", "sqlite:///./dev.db")
        conn = create_engine(url).connect()
    context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


run()
