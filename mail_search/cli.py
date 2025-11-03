"""Command line interface for the mail-search project."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .database import MailDatabase
from .indexer import MailIndexer


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
    index_parser.set_defaults(func=_run_index)

    search_parser = subparsers.add_parser("search", help="Perform a full text search query")
    search_parser.add_argument("query", help="The FTS query to execute")
    search_parser.add_argument("--limit", type=int, default=20, help="Maximum number of results to display")
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
    indexer = MailIndexer(database)
    result = indexer.index_mbox(args.source)
    print(f"Processed {result.processed} messages; inserted/updated {result.inserted} records.")
    return 0


def _run_search(database: MailDatabase, args: argparse.Namespace) -> int:
    rows = list(database.search(args.query, limit=args.limit))
    if not rows:
        print("No results found.")
        return 0
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
    return 0


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
