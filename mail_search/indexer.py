"""Utilities for ingesting mail archives into the local database."""

from __future__ import annotations

from dataclasses import dataclass
from email.message import Message
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Iterator, Optional
import hashlib
import mailbox

from .database import MailDatabase, StoredMessage
from .semantic import EmbeddingBackend, load_default_backend


@dataclass
class IndexResult:
    """Summary of the performed indexing operation."""

    processed: int
    inserted: int


class MailIndexer:
    """High level helper used to parse Thunderbird archives."""

    def __init__(
        self,
        database: MailDatabase,
        embedder: Optional[EmbeddingBackend] = None,
    ):
        self.database = database
        self.embedder = embedder

    # -- public API ---------------------------------------------------------
    def index_mbox(self, mbox_path: Path | str) -> IndexResult:
        """Index the content of a Thunderbird ``mbox`` file."""

        path = Path(mbox_path)
        messages = list(self._read_mbox(path))
        inserted = self.database.upsert_many(messages)
        if self.embedder is None:
            self.embedder = load_default_backend()
        if self.embedder is not None and messages:
            payloads = [
                (message.message_id, self._embedding_text(message))
                for message in messages
            ]
            vectors = self.embedder.embed([text for _, text in payloads])
            serialisable = [
                (message_id, vector)
                for (message_id, _), vector in zip(payloads, vectors)
            ]
            self.database.store_embeddings(self.embedder.identifier, serialisable)
        return IndexResult(processed=len(messages), inserted=inserted)

    # -- parsing helpers ----------------------------------------------------
    def _read_mbox(self, path: Path) -> Iterator[StoredMessage]:
        mbox = mailbox.mbox(path)
        try:
            for key in mbox.iterkeys():
                raw_message = mbox.get_bytes(key)
                message = BytesParser(policy=policy.default).parsebytes(raw_message)
                yield self._convert_message(message)
        finally:
            mbox.close()

    def _convert_message(self, message: Message) -> StoredMessage:
        subject = message.get("subject", "")
        body = _extract_text_content(message)
        from_addr = _format_address(message.get("from"))
        to_addr = _format_address(message.get("to"))
        date = _format_date(message.get("date"))
        message_id = message.get("message-id") or _hash_identity(
            subject, date or "", body
        )
        return StoredMessage(
            message_id=message_id,
            subject=subject,
            body=body,
            from_addr=from_addr,
            to_addr=to_addr,
            date=date,
        )

    def _embedding_text(self, message: StoredMessage) -> str:
        subject = message.subject or ""
        body = message.body or ""
        return f"{subject}\n\n{body}".strip()


# -- helper utilities -------------------------------------------------------
def _extract_text_content(message: Message) -> str:
    parts: list[str] = []
    if message.is_multipart():
        for part in message.walk():
            if part.is_multipart():
                continue
            if part.get_content_disposition() in {"attachment", "inline"} and part.get_filename():
                continue
            if part.get_content_type() != "text/plain":
                continue
            text = _decode_payload(part)
            if text:
                parts.append(text)
    else:
        text = _decode_payload(message)
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _decode_payload(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _format_address(header_value: Optional[str]) -> Optional[str]:
    if not header_value:
        return None
    addresses = [addr for _, addr in getaddresses([header_value]) if addr]
    return ", ".join(addresses) if addresses else None


def _format_date(header_value: Optional[str]) -> Optional[str]:
    if not header_value:
        return None
    try:
        dt = parsedate_to_datetime(header_value)
    except (TypeError, ValueError):
        return header_value
    if dt is None:
        return header_value
    if dt.tzinfo:
        dt = dt.astimezone()
    return dt.isoformat(timespec="seconds")


def _hash_identity(*parts: str) -> str:
    digest = hashlib.sha1()
    for part in parts:
        digest.update(part.encode("utf-8", errors="ignore"))
    return f"generated-{digest.hexdigest()}"
