"""SQLite connection helpers shared by EEEE's durable stores."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class ContextClosingConnection(sqlite3.Connection):
    """Commit/rollback and close a connection when its context exits.

    The stdlib SQLite context manager only handles the transaction. It does
    not close the connection, which leaves database handles behind on Windows
    when stores use the natural ``with connect(...)`` form.
    """

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> Any:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect_sqlite(path: str | Path, **kwargs: Any) -> sqlite3.Connection:
    """Return a context-closing SQLite connection."""

    kwargs.setdefault("factory", ContextClosingConnection)
    return sqlite3.connect(path, **kwargs)
