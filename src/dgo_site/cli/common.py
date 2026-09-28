"""Options and helpers shared by the dgo-site commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ..build import load_project
from ..config import ConfigError, Project
from ..console import error, say
from ..editor import sync_editor_schemas

ProjectOption = Annotated[Path, typer.Option(help="The project directory or its dgo-site.yaml.")]


def config_problem(exc: ConfigError) -> typer.Exit:
    """Report a configuration problem; the caller raises the returned exit."""
    error(f"Configuration problem: {exc}")
    return typer.Exit(1)


def open_project(path: Path) -> Project:
    """Load the project at `path`, or report why it can't be loaded and exit 1."""
    try:
        return load_project(path)
    except ConfigError as exc:
        raise config_problem(exc) from None


def refresh_editor_schemas(project: Project) -> list[Path]:
    """Bring the project's editor schemas up to date and say which were written."""
    written = sync_editor_schemas(project.root)
    for rel in written:
        say(f"  updated {rel} (editor validation schema)")
    return written
