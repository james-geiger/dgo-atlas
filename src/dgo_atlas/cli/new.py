"""`dgo-atlas new`: create a project, and later the pieces inside one.

Each generator is one command here. `new project` is also registered as the
top-level `dgo-atlas init`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from .. import local_classes
from ..build import load_project
from ..config import ConfigError
from ..console import error, say, warn
from ..editor import sync_editor_schemas
from ..scaffold import ProjectExists, create_project
from .common import ProjectOption, open_project

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

    say(f"Created a DGO Atlas project in {target}:")
    for rel in created:
        say(f"  {rel}")
    try:
        loaded = load_project(target)
        sync_editor_schemas(target)
        say(f"  .dgo-atlas/ (editor schemas for DGO {loaded.config.dgo_version})")
    except ConfigError as exc:
        warn(f"editor schemas were not written: {exc}\nRun `dgo-atlas schema` once that is fixed.")
    say("\nNext: edit dgo-atlas.yaml, write governance data under governance/, then run\n  dgo-atlas build")


@app.command("local-class")
def local_class(
    name: Annotated[str, typer.Argument(help="The class's name, used as a `type` value, e.g. \"data trustee\".")],
    is_a: Annotated[str, typer.Option("--is-a", help="Its parent: a DGO class (name or CURIE) or a local class.")],
    id: Annotated[str | None, typer.Option(help="Its id. Default: the first prefix in dgo-atlas.yaml and the "
                                                "name in CamelCase.")] = None,
    description: Annotated[str | None, typer.Option(help="What makes something one.")] = None,
    project: ProjectOption = Path("."),
) -> None:
    """Add a local class: your own subclass of a DGO class, in its own governance file."""
    loaded = open_project(project)
    try:
        path = local_classes.scaffold(loaded.data_dir, name, is_a, loaded.prefixes, id=id, description=description)
    except ValueError as exc:
        error(str(exc))
        raise typer.Exit(1) from None
    rel = path.relative_to(loaded.root) if path.is_relative_to(loaded.root) else path
    say(f"Created {rel}. Use it as `type: {name}`, then run\n  dgo-atlas validate")
