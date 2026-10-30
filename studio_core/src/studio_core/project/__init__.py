"""Projects: characters, backgrounds and films by reference, acts, and staleness (D-082, D-083)."""

from studio_core.project.project import (
    ImmutableVersionError,
    Project,
    ResolvedVersion,
    check_versions_append_only,
    slugify,
)
from studio_core.project.staleness import act_cache_key, content_hash, is_stale
from studio_core.project.validation import document_issues, validate_document

__all__ = [
    "ImmutableVersionError",
    "Project",
    "ResolvedVersion",
    "act_cache_key",
    "check_versions_append_only",
    "content_hash",
    "document_issues",
    "is_stale",
    "slugify",
    "validate_document",
]
