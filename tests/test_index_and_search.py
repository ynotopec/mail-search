from __future__ import annotations

from email.message import EmailMessage
import mailbox
from pathlib import Path

from mail_search.database import MailDatabase
from mail_search.indexer import MailIndexer
from mail_search.semantic import HashEmbeddingBackend


def _create_mbox(path: Path, messages: list[EmailMessage]) -> None:
    mbox = mailbox.mbox(path)
    try:
        for msg in messages:
            mbox.add(msg)
        mbox.flush()
    finally:
        mbox.close()


def test_index_and_search(tmp_path):
    mbox_path = tmp_path / "archive.mbox"

    msg1 = EmailMessage()
    msg1["Subject"] = "Weekly search sync"
    msg1["From"] = "alice@example.com"
    msg1["To"] = "bob@example.com"
    msg1["Date"] = "Tue, 11 Feb 2025 09:30:00 +0000"
    msg1.set_content("Let's discuss the search engine milestones.")

    msg2 = EmailMessage()
    msg2["Subject"] = "Lunch invitation"
    msg2["From"] = "carol@example.com"
    msg2["To"] = "alice@example.com"
    msg2.set_content("Fancy some ramen today?")

    msg3 = EmailMessage()
    msg3["Subject"] = "Search retrospective"
    msg3["From"] = "bob@example.com"
    msg3["To"] = "alice@example.com"
    msg3.set_content("The search workstream needs more benchmarks.")

    _create_mbox(mbox_path, [msg1, msg2, msg3])

    db_path = tmp_path / "mail.db"
    database = MailDatabase(db_path)
    indexer = MailIndexer(database)

    try:
        result = indexer.index_mbox(mbox_path)
        assert result.processed == 3
        assert result.inserted == 3

        matches = list(database.search("search"))
        subjects = [row["subject"] for row in matches]
        assert "Weekly search sync" in subjects
        assert "Search retrospective" in subjects

        match = next(row for row in matches if row["subject"] == "Weekly search sync")
        assert "milestones" in match["snippet"]
    finally:
        database.close()


def test_semantic_search(tmp_path):
    mbox_path = tmp_path / "archive.mbox"

    msg1 = EmailMessage()
    msg1["Subject"] = "Weekly search sync"
    msg1.set_content("Let's discuss the search engine milestones.")

    msg2 = EmailMessage()
    msg2["Subject"] = "Search retrospective"
    msg2.set_content("The search workstream needs more benchmarks.")

    _create_mbox(mbox_path, [msg1, msg2])

    db_path = tmp_path / "mail.db"
    database = MailDatabase(db_path)
    embedder = HashEmbeddingBackend(dimension=64)
    indexer = MailIndexer(database, embedder=embedder)

    try:
        result = indexer.index_mbox(mbox_path)
        assert result.processed == 2

        backends = database.get_vector_backends()
        assert embedder.identifier in backends

        matches = database.semantic_search("search milestones", embedder, limit=5)
        assert matches
        subjects = [match["subject"] for match in matches]
        assert subjects[0] == "Weekly search sync"
    finally:
        database.close()
