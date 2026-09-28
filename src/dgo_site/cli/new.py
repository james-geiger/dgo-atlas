"""`dgo-site new`: create a project, and later the pieces inside one.

Each generator is one command here. `new project` is also registered as the
top-level `dgo-site init`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ..build import load_project
from ..config import ConfigError
from ..console import error, say, warn
from ..editor import sync_editor_schemas
from ..scaffold import ProjectExists, create_project

app = typer.Typer(help="Create a project, or add to one.", no_args_is_help=True)


@app.command()
def project(
    directory: Annotated[Path, typer.Argument(help="Where to create the project. Default: here.")] = Path("."),
) -> None:
    """Start a project from the scaffold: example data, config, CI and editor settings."""
    target = directory.resolve()
    try:
        created = create_project(target)
    except ProjectExists as exc:
        error(str(exc))
        raise typer.Exit(1) from None

    say(f"Created a dgo-site project in {target}:")
    for rel in created:
        say(f"  {rel}")
    try:
        loaded = load_project(target)
        sync_editor_schemas(target)
        say(f"  .dgo-site/ (editor schemas for DGO {loaded.config.dgo_version})")
    except ConfigError as exc:
        warn(f"editor schemas were not written: {exc}\nRun `dgo-site schema` once that is fixed.")
    say("\nNext: edit dgo-site.yaml, write governance data under governance/, then run\n  dgo-site build")
