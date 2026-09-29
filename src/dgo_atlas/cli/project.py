"""Commands that work on an existing project."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ..build import build as build_site
from ..build import check, load_project, print_report
from ..config import ConfigError
from ..convert import convert as convert_data
from .. import dgo, local_classes
from ..console import error, say
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
    out: Annotated[Path | None, typer.Option(help="Output directory. Default: paths.output in dgo-atlas.yaml.")] = None,
) -> None:
    """Validate, then build the site."""
    loaded = open_project(project)
    refresh_editor_schemas(loaded)
    raise typer.Exit(build_site(loaded, out=out.resolve() if out else None))


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def convert(ctx: typer.Context, project: ProjectOption = Path(".")) -> None:
    """Export the governance data with linkml-convert; other options go to it.

    The input, schema (-s), class (-C) and project prefixes (-P) are filled in.
    For example `-t ttl -o glossary.ttl` writes RDF individuals of DGO's
    classes, and `-t json` writes JSON. See `linkml-convert --help`.
    """
    raise typer.Exit(convert_data(open_project(project), ctx.args))


@app.command()
def schema(project: ProjectOption = Path(".")) -> None:
    """Refresh the editor JSON Schemas in .dgo-atlas/."""
    if not refresh_editor_schemas(open_project(project)):
        say("Editor schemas are up to date.")


@app.command("export-schema")
def export_schema(
    project: ProjectOption = Path("."),
    local_only: Annotated[bool, typer.Option(help="Only the local classes, as a schema that imports DGO by URL.")
                          ] = False,
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write to this file. Default: standard output.")
                   ] = None,
) -> None:
    """Write the project's LinkML schema, for LinkML's own generators.

    By default the template, the DGO release and the local classes, merged into
    one self-contained schema: run gen-pydantic, gen-json-schema, gen-owl or
    gen-shacl on it. With --local-only, just the local classes.
    """
    loaded = open_project(project)
    schema = local_classes.extension() if local_only else dgo.linkml_schema()
    if not schema:
        error("The governance data declares no local classes (`local_classes:`).")
        raise typer.Exit(1)
    if out:
        out.write_text(schema, encoding="utf-8")
        say(f"Wrote {out} (DGO {loaded.config.dgo_version}, "
            f"{len(dgo.active().local_classes)} local class(es))")
    else:
        say(schema.rstrip("\n"))


@app.command()
def text(
    prefix: Annotated[str, typer.Argument(help="Only keys starting with this, e.g. `term.`")] = "",
    project: ProjectOption = Path("."),
) -> None:
    """List every text key and its wording. Override any of them with `text:` in dgo-atlas.yaml."""
    try:
        wording = load_project(project).text
    except ConfigError as exc:
        if project != Path("."):
            raise config_problem(exc) from None
        wording = Text()  # not in a project: show the defaults
    for line in wording.listing(prefix):
        say(line)
