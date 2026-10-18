"""Explicit short-lived read snapshots; no cross-request state or pooling."""
from contextlib import contextmanager, closing
from pathlib import Path
import sqlite3


@contextmanager
def read_connection(path, connection=None, *, rows=False):
    """Borrow without closing; restore row format even if a reader fails."""
    if connection is None:
        with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as owned:
            owned.execute('PRAGMA foreign_keys=ON')
            owned.execute('PRAGMA query_only=ON')
            owned.execute('BEGIN')
            with read_connection(path,owned,rows=rows) as current:
                yield current
        return
    previous=connection.row_factory
    try:
        connection.row_factory=sqlite3.Row if rows else None
        yield connection
    finally:
        connection.row_factory=previous
