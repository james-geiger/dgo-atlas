"""The JSON Schemas a project's editor validates its YAML against."""

from __future__ import annotations

from pathlib import Path

from . import dgo
from .resources import CONFIG_JSON_SCHEMA

# Where a project keeps each schema, and where each comes from. The
# governance schema depends on the project's DGO release, so it is generated
# for the active one.
EDITOR_SCHEMAS = {
    Path(".dgo-site/governance.schema.json"): dgo.json_schema,
    Path(".dgo-site/config.schema.json"): lambda: CONFIG_JSON_SCHEMA.read_text(encoding="utf-8"),
}


def sync_editor_schemas(root: Path) -> list[Path]:
    """Write the editor schemas into the project when missing or stale.

    Returns the paths written, relative to `root`.
    """
    written = []
    for rel, generate in EDITOR_SCHEMAS.items():
        target = root / rel
        content = generate()
        if target.exists() and target.read_text(encoding="utf-8") == content:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(rel)
    return written
