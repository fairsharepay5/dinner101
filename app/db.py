from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from . import models  # noqa: F401  (registers tables)
    Base.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """Tiny migration: add new columns to existing SQLite tables."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    if "pantry_items" not in insp.get_table_names():
        return
    have = {c["name"] for c in insp.get_columns("pantry_items")}
    with engine.begin() as conn:
        if "piece_g" not in have:
            conn.execute(text("ALTER TABLE pantry_items ADD COLUMN piece_g FLOAT"))
        if "qty_known" not in have:
            conn.execute(text("ALTER TABLE pantry_items ADD COLUMN qty_known BOOLEAN DEFAULT 1"))
            from .catalogue import CATALOGUE, PIECE_G
            # Existing rows: an amount equal to our default was almost surely our guess, not the user's.
            for ing in CATALOGUE.values():
                conn.execute(text("UPDATE pantry_items SET qty_known = 0 WHERE key = :k AND qty = :q"),
                             {"k": ing.key, "q": float(ing.default_qty)})
            # "4 chicken fillets" that were stored as 4 grams -> 4 pieces
            for k, w in PIECE_G.items():
                conn.execute(text("UPDATE pantry_items SET piece_g = :w, qty = qty * :w "
                                  "WHERE key = :k AND unit IN ('g','ml') AND qty < 20"), {"k": k, "w": float(w)})
