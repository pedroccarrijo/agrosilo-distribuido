"""Persistência local. Cada requisição abre sua própria conexão SQLite."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Storage:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS silos (
                    id INTEGER PRIMARY KEY,
                    nome TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS medicoes (
                    id INTEGER PRIMARY KEY,
                    silo_id INTEGER NOT NULL REFERENCES silos(id),
                    temperatura REAL NOT NULL,
                    umidade REAL NOT NULL,
                    registrada_em TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_medicoes_silo_id
                    ON medicoes(silo_id, id DESC);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=3)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("PRAGMA synchronous = FULL")
            with db:
                yield db
        finally:
            db.close()
