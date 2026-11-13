"""Tiny schema upgrade: adds columns that were introduced after Phase 1."""
from sqlalchemy import inspect, text

from app import db

NEW_COLUMNS = [
    ("users", "theme", "VARCHAR(10) NOT NULL DEFAULT 'light'"),
    ("users", "hide_email", "BOOLEAN NOT NULL DEFAULT 0"),
    ("users", "reminder_notifications", "BOOLEAN NOT NULL DEFAULT 1"),
    ("users", "avatar", "VARCHAR(255)"),
    ("notes", "deleted_at", "DATETIME"),
]


def upgrade_schema():
    insp = inspect(db.engine)
    for table, column, ddl in NEW_COLUMNS:
        if not insp.has_table(table):
            continue
        existing = {c["name"] for c in insp.get_columns(table)}
        if column not in existing:
            with db.engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
