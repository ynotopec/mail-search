"""Persistence layer for the mail-search application.

This module provides a small wrapper around :mod:`sqlite3` that stores
basic metadata for each message alongside a lightweight full text search
index powered by the FTS5 extension.  The implementation intentionally
avoids external dependencies so that the project can run entirely
locally, in line with the objectives described in the README.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Optional
import sqlite3


@dataclass
class StoredMessage:
    """Represents a message stored inside the SQLite database."""

    message_id: str
    subject: str
    body: str
    from_addr: Optional[str]
    to_addr: Optional[str]
    date: Optional[str]


class MailDatabase:
    """Small helper around SQLite used for indexing and searching mail."""

    def __init__(self, db_path: Path | str):
        self.path = Path(db_path)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._initialise_schema()

    # -- connection helpers -------------------------------------------------
    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # -- schema management --------------------------------------------------
    def _initialise_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    subject TEXT,
                    body TEXT,
                    from_addr TEXT,
                    to_addr TEXT,
                    date TEXT
                )
                """
            )
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
                USING fts5(
                    message_id UNINDEXED,
                    subject,
                    body,
                    tokenize='porter'
                )
                """
            )

    # -- mutation operations ------------------------------------------------
    def upsert_message(self, message: StoredMessage) -> None:
        """Insert or update a message inside the database."""

        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO messages(message_id, subject, body, from_addr, to_addr, date)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                    subject=excluded.subject,
                    body=excluded.body,
                    from_addr=excluded.from_addr,
                    to_addr=excluded.to_addr,
                    date=excluded.date
                """,
                (
                    message.message_id,
                    message.subject,
                    message.body,
                    message.from_addr,
                    message.to_addr,
                    message.date,
                ),
            )
            conn.execute(
                "DELETE FROM messages_fts WHERE message_id = ?",
                (message.message_id,),
            )
            conn.execute(
                """
                INSERT INTO messages_fts(message_id, subject, body)
                VALUES (?, ?, ?)
                """,
                (message.message_id, message.subject, message.body),
            )

    def upsert_many(self, messages: Iterable[StoredMessage]) -> int:
        """Insert a collection of messages in a single transaction."""

        count = 0
        with self.transaction() as conn:
            for message in messages:
                conn.execute(
                    """
                    INSERT INTO messages(message_id, subject, body, from_addr, to_addr, date)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(message_id) DO UPDATE SET
                        subject=excluded.subject,
                        body=excluded.body,
                        from_addr=excluded.from_addr,
                        to_addr=excluded.to_addr,
                        date=excluded.date
                    """,
                    (
                        message.message_id,
                        message.subject,
                        message.body,
                        message.from_addr,
                        message.to_addr,
                        message.date,
                    ),
                )
                conn.execute(
                    "DELETE FROM messages_fts WHERE message_id = ?",
                    (message.message_id,),
                )
                conn.execute(
                    """
                    INSERT INTO messages_fts(message_id, subject, body)
                    VALUES (?, ?, ?)
                    """,
                    (message.message_id, message.subject, message.body),
                )
                count += 1
        return count

    # -- query operations ---------------------------------------------------
    def search(self, query: str, limit: int = 20) -> Iterator[sqlite3.Row]:
        """Perform a full text search query."""

        cursor = self._conn.execute(
            """
            SELECT
                m.message_id,
                m.subject,
                m.from_addr,
                m.to_addr,
                m.date,
                snippet(messages_fts, 2, '<b>', '</b>', ' … ', 16) AS snippet,
                bm25(messages_fts) AS score
            FROM messages_fts
            JOIN messages AS m USING(message_id)
            WHERE messages_fts MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            (query, limit),
        )
        for row in cursor:
            yield row

    def fetch_message(self, message_id: str) -> Optional[sqlite3.Row]:
        cursor = self._conn.execute(
            "SELECT * FROM messages WHERE message_id = ?",
            (message_id,),
        )
        return cursor.fetchone()
