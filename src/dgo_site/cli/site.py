"""Commands that work on a built site."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ..console import error, fail, say
from ..linkcheck import check as check_links

app = typer.Typer()


@app.command()
def linkcheck(site: Annotated[Path, typer.Argument(help="The built site.")] = Path("site")) -> None:
    """Check that every internal link in a built site resolves."""
    if not site.exists():
        error(f"{site} does not exist; build the site first")
        raise typer.Exit(1)
    problems = check_links(site)
    if problems:
        raise typer.Exit(fail(f"{len(problems)} broken internal link(s):", problems))
    pages = len(list(site.rglob("*.html")))
    say(f"All internal links resolve across {pages} page(s).", style="green")
