"""The site's wording: defaults from text.yaml, overridden from dgo-atlas.yaml.

Templates never contain literal copy. They call `t("term.history")`, or
`count("term", n)` for a count, and the implementer can change any of it with
`text:` in dgo-atlas.yaml. Unknown keys are an error, with the closest key
suggested, so a typo can't silently fail to apply.

Values are plain text. Placeholders like {name} are filled in with escaped
values, or with links the templates build (which are already safe HTML).
"""

from __future__ import annotations

import difflib
from functools import cache

import yaml
from markupsafe import Markup

from .resources import PACKAGE

CATALOG = PACKAGE / "text.yaml"


class TextError(Exception):
    pass


def _flatten(tree: dict, prefix: str = "") -> dict[str, str]:
    out = {}
    for key, value in tree.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(_flatten(value, path + "."))
        else:
            out[path] = "" if value is None else str(value)
    return out


@cache
def defaults() -> dict[str, str]:
    """Every key and its default wording."""
    return _flatten(yaml.safe_load(CATALOG.read_text(encoding="utf-8")))


class Text:
    def __init__(self, overrides: dict[str, str] | None = None):
        known = defaults()
        problems = []
        for key, value in (overrides or {}).items():
            if key not in known:
                close = difflib.get_close_matches(key, known, n=1)
                hint = f" Did you mean {close[0]}?" if close else " Run `dgo-atlas text` to list the keys."
                problems.append(f"text: {key!r} is not a text key.{hint}")
            elif not isinstance(value, str):
                problems.append(f"text: {key} must be text; quote it.")
        if problems:
            raise TextError("\n".join(problems))
        self.values = {**known, **(overrides or {})}

    def raw(self, key: str) -> str:
        return self.values[key]

    def __call__(self, key: str, **fields) -> Markup:
        """The wording for `key`, with its {placeholders} filled in."""
        template = Markup.escape(self.values[key])
        return template.format(**fields) if fields else template

    def count(self, noun: str, n: int) -> Markup:
        return self(f"count.{noun}.{'one' if n == 1 else 'other'}", n=n)

    def js(self) -> dict[str, str]:
        """The wording site.js uses, keyed without the `js.` prefix."""
        return {k[3:]: v for k, v in self.values.items() if k.startswith("js.")}

    def overrides(self) -> dict[str, str]:
        """The keys whose wording differs from the default."""
        return {k: v for k, v in self.values.items() if v != defaults()[k]}

    def listing(self, prefix: str = "") -> list[str]:
        """One YAML line per key starting with `prefix`, marking the overridden ones."""
        changed = self.overrides()
        lines = []
        for key, value in self.values.items():
            if not key.startswith(prefix):
                continue
            rendered = yaml.safe_dump({key: value}, allow_unicode=True, width=1000).rstrip("\n")
            lines.append(rendered + ("  # overridden" if key in changed else ""))
        return lines
