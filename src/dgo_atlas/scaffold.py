"""Create an implementer project from the files in scaffold/."""

from __future__ import annotations

import shutil
from pathlib import Path

from .config import CONFIG_NAME
from .resources import SCAFFOLD


class ProjectExists(Exception):
    """The target directory already holds a DGO Atlas project."""


def _destination(source: Path) -> Path:
    # Files that tools would otherwise treat specially inside the package
    # are stored with a "dot-" prefix and renamed on the way out.
    rel = source.relative_to(SCAFFOLD)
    return Path(*[p.replace("dot-", ".", 1) if p.startswith("dot-") else p for p in rel.parts])


def create_project(target: Path) -> list[Path]:
    """Copy the scaffold into `target`, skipping files already there.

    Returns the created paths, relative to `target`. Raises ProjectExists if
    `target` already has a dgo-atlas.yaml.
    """
    target.mkdir(parents=True, exist_ok=True)
    if (target / CONFIG_NAME).exists():
        raise ProjectExists(f"{target / CONFIG_NAME} already exists; not overwriting a project.")
    created = []
    for source in sorted(SCAFFOLD.rglob("*")):
        if source.is_dir() or source.name == ".DS_Store" or "__pycache__" in source.parts:
            continue
        rel = _destination(source)
        dest = target / rel
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        created.append(rel)
    return created
