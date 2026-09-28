"""Commands that work on an existing project."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ..build import build as build_site
from ..build import check, load_project, print_report
from ..config import ConfigError
from ..console import say
from ..text import Text
from .common import ProjectOption, config_problem, open_project, refresh_editor_schemas

app = typer.Typer()


@app.command()
def validate(project: ProjectOption = Path(".")) -> None:
    """Validate the governance data."""
    loaded = open_project(project)
    refresh_editor_schemas(loaded)
    raise typer.Exit(print_report(check(loaded)))


@app.command()
def build(
    project: ProjectOption = Path("."),
    out: Annotated[Path | None, typer.Option(help="Output directory. Default: paths.output in dgo-site.yaml.")] = None,
) -> None:
    """Validate, then build the site."""
    loaded = open_project(project)
    refresh_editor_schemas(loaded)
    raise typer.Exit(build_site(loaded, out=out.resolve() if out else None))


@app.command()
def schema(project: ProjectOption = Path(".")) -> None:
    """Refresh the editor JSON Schemas in .dgo-site/."""
    if not refresh_editor_schemas(open_project(project)):
        say("Editor schemas are up to date.")


@app.command()
def text(
    prefix: Annotated[str, typer.Argument(help="Only keys starting with this, e.g. `term.`")] = "",
    project: ProjectOption = Path("."),
) -> None:
    """List every text key and its wording. Override any of them with `text:` in dgo-site.yaml."""
    try:
        wording = load_project(project).text
    except ConfigError as exc:
        if project != Path("."):
            raise config_problem(exc) from None
        wording = Text()  # not in a project: show the defaults
    for line in wording.listing(prefix):
        say(line)
