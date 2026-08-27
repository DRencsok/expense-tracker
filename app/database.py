import sqlite3
from pathlib import Path

from flask import g


def get_db():
    if "db" not in g:
        database_path = Path(__file__).parent.parent / "instance" / "expenses.db"
        g.db = sqlite3.connect(database_path)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")

    return g.db


def init_db():
    db = get_db()
    schema_path = Path(__file__).with_name("schema.sql")
    db.executescript(schema_path.read_text(encoding="utf-8"))
    columns = {row["name"] for row in db.execute("PRAGMA table_info(expenses)")}
    if "transaction_type" not in columns:
        db.execute(
            "ALTER TABLE expenses ADD COLUMN transaction_type TEXT NOT NULL DEFAULT 'expense'"
        )
    db.commit()


def close_db(e=None):
    db = g.pop("db", None)

    if db is not None:
        db.close()