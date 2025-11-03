"""Core package for the mail-search project."""

from .database import MailDatabase
from .indexer import MailIndexer

__all__ = ["MailDatabase", "MailIndexer"]
