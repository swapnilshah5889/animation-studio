"""Check a project document against its JSON Schema (schemas/<name>.schema.json).

The store checks the envelope and the no-paths rule for every document; this adds the shape of each
kind (project, character, background, film, act, shot, act_render). Messages name the JSON path so a
model can fix its own output, as in `studio_core.schema`.
"""

from __future__ import annotations

import json
from functools import cache

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from studio_core.config import REPO_ROOT
from studio_core.store import InvalidDocument

SCHEMA_DIR = REPO_ROOT / "schemas"
KIND_SCHEMAS = {
    "project": "project",
    "character": "character_entry",
    "background": "background_entry",
    "film": "film_spec",
    "act": "act",
    "shot": "shot_doc",
    "act_render": "act_render",
}
_SUPPORT = ("document", "asset_record")
# The store sets these; a draft document does not have them yet.
_STAMPS = {
    "rev": 1,
    "created_at": "1970-01-01T00:00:00.000Z",
    "updated_at": "1970-01-01T00:00:00.000Z",
}


@cache
def _registry() -> Registry:
    resources = []
    for name in (*_SUPPORT, *KIND_SCHEMAS.values()):
        schema = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text())
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


@cache
def _validator(name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=_registry())


def document_issues(doc: dict) -> list[str]:
    """Problems with a document's shape ([] when fine). Unknown kinds only get the envelope."""
    name = KIND_SCHEMAS.get(doc.get("kind", ""), "document")
    errors = _validator(name).iter_errors({**_STAMPS, **doc})
    out = []
    for e in sorted(errors, key=lambda e: list(map(str, e.absolute_path))):
        where = ".".join(str(p) for p in e.absolute_path) or "(root)"
        out.append(f"{where}: {e.message}")
    return out


def validate_document(doc: dict) -> None:
    issues = document_issues(doc)
    if issues:
        raise InvalidDocument(f"{doc.get('kind')} {doc.get('id')}: " + "; ".join(issues))
