"""The dgo-site command.

Every command is a Typer function in a module of this package, grouped by
what it works on. This file only assembles them, so it is the one place that
shows the whole command surface:

    dgo-site init [DIR]          start a project from the scaffold (same as `new project`)
    dgo-site new project [DIR]   start a project from the scaffold
    dgo-site validate            validate the governance data
    dgo-site build               validate, then build the site
    dgo-site schema              refresh the editor JSON Schemas
    dgo-site text [PREFIX]       list every text key and its wording
    dgo-site linkcheck [SITE]    check a built site's internal links
    dgo-site --version           this package and the DGO releases it is tested with

Commands stay thin: parse options, call the library (build, scaffold, editor,
linkcheck, text), print through dgo_site.console, and end with
`raise typer.Exit(code)` when the code can be non-zero.
"""

from __future__ import annotations

from typing import Annotated

import typer

from .. import __version__, dgo
from ..console import say
from . import new, project, site

app = typer.Typer(
    name="dgo-site",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_show_locals=False,
)
app.add_typer(project.app)
app.add_typer(site.app)
app.add_typer(new.app, name="new")
app.command("init")(new.project)


def version_text() -> str:
    return (f"dgo-site {__version__}\n"
            f"Tested with Data Governance Ontology {', '.join(dgo.TESTED_VERSIONS)}; "
            "each project names its release in dgo-site.yaml (dgo_version)")


def _show_version(value: bool) -> None:
    if value:
        say(version_text())
        raise typer.Exit()


@app.callback()
def root(
    version: Annotated[bool, typer.Option("--version", callback=_show_version, is_eager=True,
                                          help="Show this package's version and the DGO releases it is tested with.")
                       ] = False,
) -> None:
    """Govern a business glossary with the Data Governance Ontology and publish it as a site."""


def main() -> None:
    app()
