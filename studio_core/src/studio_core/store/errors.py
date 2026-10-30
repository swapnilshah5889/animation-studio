"""Errors every ProjectStore raises, so callers never depend on one implementation."""

from __future__ import annotations


class StoreError(Exception):
    pass


class NotFound(StoreError):
    """The document or asset does not exist in that project."""


class RevConflict(StoreError):
    """The document changed since it was read (or already exists, or is missing, on create)."""


class InvalidDocument(StoreError):
    """The document breaks the envelope rules; the message says which."""
