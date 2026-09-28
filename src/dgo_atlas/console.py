"""Console output for every DGO Atlas module.

Everything the CLI and the build print goes through here, so colour and
wrapping are decided once. Messages carry user data (ids, YAML snippets like
`related: [org:x]`), so they are printed with markup off: Rich would otherwise
read the brackets as style tags. Styling comes from `style=` instead. Lines
soft-wrap, so a long message stays on one line in CI logs and tests.
"""

from __future__ import annotations

from collections.abc import Iterable

from rich.console import Console

out = Console(highlight=False, soft_wrap=True)
err = Console(stderr=True, highlight=False, soft_wrap=True)


def say(line: str = "", *, style: str | None = None) -> None:
    out.print(line, style=style, markup=False)


def warn(message: str) -> None:
    out.print(f"  warning: {message}", style="yellow", markup=False)


def note(message: str) -> None:
    out.print(f"  note: {message}", style="dim", markup=False)


def error(message: str) -> None:
    err.print(message, style="red", markup=False)


def fail(heading: str, problems: Iterable[object]) -> int:
    """Print a heading and one line per problem on stderr; return exit code 1."""
    err.print()
    err.print(heading, style="bold red", markup=False)
    for problem in problems:
        err.print(f"  - {problem}", markup=False)
    err.print()
    return 1
