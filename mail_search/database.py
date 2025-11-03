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

from .semantic import (
    EmbeddingBackend,
    body_preview,
    cosine_similarity,
    deserialise_vector,
    serialise_vector,
)


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
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS message_vectors (
                    message_id TEXT PRIMARY KEY,
                    backend TEXT NOT NULL,
                    embedding BLOB NOT NULL
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

    # -- embedding operations ----------------------------------------------
    def store_embeddings(
        self,
        backend: str,
        embeddings: Iterable[tuple[str, list[float]]],
    ) -> None:
        """Persist embeddings associated with messages."""

        with self.transaction() as conn:
            for message_id, vector in embeddings:
                payload = serialise_vector(vector)
                conn.execute(
                    """
                    INSERT INTO message_vectors(message_id, backend, embedding)
                    VALUES (?, ?, ?)
                    ON CONFLICT(message_id) DO UPDATE SET
                        backend=excluded.backend,
                        embedding=excluded.embedding
                    """,
                    (message_id, backend, payload),
                )

    def get_vector_backends(self) -> set[str]:
        cursor = self._conn.execute(
            "SELECT DISTINCT backend FROM message_vectors"
        )
        return {row[0] for row in cursor}

    def semantic_search(
        self,
        query: str,
        embedder: EmbeddingBackend,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        """Return semantic search matches ordered by cosine similarity."""

        query_vectors = embedder.embed([query])
        if not query_vectors or all(component == 0.0 for component in query_vectors[0]):
            return []
        query_vector = query_vectors[0]

        cursor = self._conn.execute(
            """
            SELECT mv.message_id, mv.embedding, m.subject, m.from_addr,
                   m.to_addr, m.date, m.body
            FROM message_vectors AS mv
            JOIN messages AS m USING(message_id)
            WHERE mv.backend = ?
            """,
            (embedder.identifier,),
        )

        scored: list[tuple[float, sqlite3.Row]] = []
        for row in cursor:
            vector = deserialise_vector(row["embedding"])
            score = cosine_similarity(query_vector, vector)
            if score <= 0.0:
                continue
            scored.append((score, row))

        scored.sort(key=lambda item: item[0], reverse=True)
        results: list[dict[str, object]] = []
        for score, row in scored[:limit]:
            results.append(
                {
                    "message_id": row["message_id"],
                    "subject": row["subject"],
                    "from_addr": row["from_addr"],
                    "to_addr": row["to_addr"],
                    "date": row["date"],
                    "snippet": body_preview(row["body"] or ""),
                    "score": score,
                }
            )
        return results

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
