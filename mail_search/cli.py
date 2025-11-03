"""Command line interface for the mail-search project."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Sequence

from .database import MailDatabase
from .indexer import MailIndexer
from .semantic import load_default_backend


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local search over Thunderbird archives")
    parser.add_argument(
        "--db",
        default="mail-search.db",
        help="Path to the SQLite database where the index is stored (default: %(default)s)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser("index", help="Index a Thunderbird mbox archive")
    index_parser.add_argument("source", help="Path to the mbox file to ingest")
    index_parser.add_argument(
        "--no-embeddings",
        action="store_true",
        help="Skip semantic embedding generation during indexing",
    )
    index_parser.add_argument(
        "--embedding-backend",
        help="Embedding backend to use (e.g. 'hash:512' or a sentence-transformers model)",
    )
    index_parser.set_defaults(func=_run_index)

    search_parser = subparsers.add_parser("search", help="Perform a full text search query")
    search_parser.add_argument("query", help="The FTS query to execute")
    search_parser.add_argument("--limit", type=int, default=20, help="Maximum number of results to display")
    search_parser.add_argument(
        "--mode",
        choices=("lexical", "semantic", "hybrid"),
        default="lexical",
        help="Search mode: lexical (default), semantic, or hybrid",
    )
    search_parser.add_argument(
        "--embedding-backend",
        help="Embedding backend to use for semantic search",
    )
    search_parser.set_defaults(func=_run_search)

    show_parser = subparsers.add_parser("show", help="Display the stored content of a message")
    show_parser.add_argument("message_id", help="The Message-ID of the mail to display")
    show_parser.set_defaults(func=_run_show)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    db_path = Path(args.db)
    database = MailDatabase(db_path)
    try:
        return args.func(database, args)
    finally:
        database.close()


def _run_index(database: MailDatabase, args: argparse.Namespace) -> int:
    embedder = None
    if not args.no_embeddings:
        try:
            embedder = load_default_backend(args.embedding_backend)
        except Exception as exc:  # pragma: no cover - defensive user feedback
            print(f"Unable to load embedding backend: {exc}")
            return 1
    indexer = MailIndexer(database, embedder=embedder)
    result = indexer.index_mbox(args.source)
    print(f"Processed {result.processed} messages; inserted/updated {result.inserted} records.")
    if embedder is not None:
        print(f"Stored semantic embeddings using backend: {embedder.identifier}")
    return 0


def _run_search(database: MailDatabase, args: argparse.Namespace) -> int:
    mode = args.mode
    embedder = None
    if mode in {"semantic", "hybrid"}:
        try:
            embedder = load_default_backend(args.embedding_backend)
        except Exception as exc:  # pragma: no cover - defensive user feedback
            print(f"Unable to load embedding backend: {exc}")
            return 1
        available = database.get_vector_backends()
        if embedder.identifier not in available:
            print(
                "No semantic vectors indexed for backend"
                f" {embedder.identifier!r}."
            )
            if mode == "semantic":
                return 1
            mode = "lexical"

    if mode == "lexical":
        rows = list(database.search(args.query, limit=args.limit))
        _display_lexical(rows)
        return 0

    if mode == "semantic" and embedder is not None:
        results = database.semantic_search(args.query, embedder, limit=args.limit)
        _display_semantic(results)
        return 0

    # Hybrid mode: combine lexical and semantic signals.
    lexical_rows = list(database.search(args.query, limit=args.limit * 2))
    semantic_rows = database.semantic_search(args.query, embedder, limit=args.limit * 2)
    combined = _merge_results(lexical_rows, semantic_rows, limit=args.limit)
    _display_hybrid(combined)
    return 0


def _display_lexical(rows: list[sqlite3.Row]) -> None:
    if not rows:
        print("No results found.")
        return
    for row in rows:
        print("-" * 72)
        subject = row["subject"] or "(no subject)"
        snippet = row["snippet"] or ""
        print(f"Subject: {subject}")
        if row["from_addr"]:
            print(f"From:    {row['from_addr']}")
        if row["to_addr"]:
            print(f"To:      {row['to_addr']}")
        if row["date"]:
            print(f"Date:    {row['date']}")
        if snippet:
            print()
            print(snippet)
            print()
    print("-" * 72)
    print(f"Displayed {len(rows)} result(s).")


def _display_semantic(results: list[dict[str, object]]) -> None:
    if not results:
        print("No semantic results found.")
        return
    for result in results:
        print("-" * 72)
        subject = (result.get("subject") or "(no subject)")
        print(f"Subject: {subject}")
        if result.get("from_addr"):
            print(f"From:    {result['from_addr']}")
        if result.get("to_addr"):
            print(f"To:      {result['to_addr']}")
        if result.get("date"):
            print(f"Date:    {result['date']}")
        print(f"Score:   {result['score']:.3f}")
        snippet = result.get("snippet")
        if snippet:
            print()
            print(snippet)
            print()
    print("-" * 72)
    print(f"Displayed {len(results)} semantic result(s).")


def _display_hybrid(results: list[dict[str, object]]) -> None:
    if not results:
        print("No hybrid results found.")
        return
    for result in results:
        print("-" * 72)
        subject = (result.get("subject") or "(no subject)")
        print(f"Subject: {subject}")
        if result.get("from_addr"):
            print(f"From:    {result['from_addr']}")
        if result.get("to_addr"):
            print(f"To:      {result['to_addr']}")
        if result.get("date"):
            print(f"Date:    {result['date']}")
        print(f"Score:   {result['score']:.3f}")
        snippet = result.get("snippet")
        if snippet:
            print()
            print(snippet)
            print()
    print("-" * 72)
    print(f"Displayed {len(results)} hybrid result(s).")


def _merge_results(
    lexical_rows, semantic_rows, limit: int
) -> list[dict[str, object]]:
    lexical_scores: dict[str, float] = {}
    lexical_data: dict[str, dict[str, object]] = {}
    for index, row in enumerate(lexical_rows):
        message_id = row["message_id"]
        lexical_scores[message_id] = 1.0 / (index + 1)
        lexical_data[message_id] = {
            "message_id": message_id,
            "subject": row["subject"],
            "from_addr": row["from_addr"],
            "to_addr": row["to_addr"],
            "date": row["date"],
            "snippet": row["snippet"],
        }

    semantic_scores: dict[str, float] = {}
    semantic_data: dict[str, dict[str, object]] = {}
    for entry in semantic_rows:
        message_id = entry["message_id"]
        semantic_scores[message_id] = entry["score"]  # type: ignore[index]
        semantic_data[message_id] = entry

    message_ids = set(lexical_scores) | set(semantic_scores)
    scored_results: list[tuple[float, str]] = []
    for message_id in message_ids:
        combined = lexical_scores.get(message_id, 0.0) + semantic_scores.get(message_id, 0.0)
        scored_results.append((combined, message_id))

    scored_results.sort(key=lambda item: item[0], reverse=True)
    final: list[dict[str, object]] = []
    for score, message_id in scored_results[:limit]:
        payload = lexical_data.get(message_id) or semantic_data.get(message_id, {})
        payload = dict(payload)
        payload["score"] = score
        if "snippet" not in payload and message_id in semantic_data:
            payload["snippet"] = semantic_data[message_id].get("snippet")
        final.append(payload)
    return final


def _run_show(database: MailDatabase, args: argparse.Namespace) -> int:
    row = database.fetch_message(args.message_id)
    if row is None:
        print(f"Message {args.message_id!r} not found in the index.")
        return 1
    print(f"Subject: {row['subject'] or '(no subject)'}")
    print(f"From:    {row['from_addr'] or '-'}")
    print(f"To:      {row['to_addr'] or '-'}")
    print(f"Date:    {row['date'] or '-'}")
    print()
    print(row["body"] or "(no body)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
