"""The implementer's site configuration, dgo-atlas.yaml.

Validated against schema/config.yaml with the same LinkML validator as the
governance data, then loaded through the generated pydantic model. Paths in
it are relative to the file. Loading a project makes its DGO release active.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

from . import dgo
from .models.config import Brand, Paths, SiteConfig
from .text import Text, TextError
from .resources import CONFIG_SCHEMA

CONFIG_NAME = "dgo-atlas.yaml"


class ConfigError(Exception):
    pass


@cache
def _validator():
    from linkml.validator import Validator
    from linkml.validator.plugins import JsonschemaValidationPlugin

    return Validator(str(CONFIG_SCHEMA), validation_plugins=[JsonschemaValidationPlugin(closed=True)])


@dataclass
class Project:
    """A loaded config and the directory it lives in."""

    root: Path
    config: SiteConfig

    @property
    def dgo(self) -> dgo.Source:
        return dgo.source_for(self.config.dgo_version, self.config.dgo_source, self.root)

    @property
    def text(self) -> Text:
        overrides = {}
        for key, value in (self.config.text or {}).items():
            overrides[key] = value if isinstance(value, str) else value.value
        return Text(overrides)

    @property
    def show_identifiers(self) -> bool:
        return self.config.show_identifiers is not False

    @property
    def paths(self) -> Paths:
        return self.config.paths or Paths()

    @property
    def data_dir(self) -> Path:
        return self.root / self.paths.data

    @property
    def content_dir(self) -> Path:
        return self.root / self.paths.content

    @property
    def output_dir(self) -> Path:
        return self.root / self.paths.output

    @property
    def brand(self) -> Brand:
        return self.config.brand or Brand()

    @property
    def prefixes(self) -> dict[str, str]:
        out = {}
        for key, value in (self.config.prefixes or {}).items():
            out[key] = value if isinstance(value, str) else value.namespace
        return out

    @property
    def accents(self) -> dict[str, str]:
        out = {}
        for key, value in (self.config.pages or {}).items():
            accent = value if isinstance(value, str) else value.accent
            if accent:
                out[key] = accent
        return out

    @property
    def repo_blob_url(self) -> str | None:
        repo = self.config.repository
        if not repo:
            return None
        return f"{str(repo.url).rstrip('/')}/blob/{repo.branch or 'main'}/"


def find(start: Path) -> Path:
    """dgo-atlas.yaml in `start` or the nearest directory above it."""
    start = start.resolve()
    if start.is_file():
        return start
    for directory in [start, *start.parents]:
        candidate = directory / CONFIG_NAME
        if candidate.is_file():
            return candidate
    raise ConfigError(f"no {CONFIG_NAME} found in {start} or any directory above it. "
                      "Run `dgo-atlas init` to create a project.")


def load(path: Path) -> Project:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path.name} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path.name}: the top level must be a mapping")
    problems = [r.message for r in _validator().iter_results(raw, "SiteConfig")]
    if problems:
        raise ConfigError(f"{path.name}:\n" + "\n".join(f"  - {p}" for p in problems))
    # LinkML lets a dict-inlined list leave out each value's key slot
    # (`pages: {org:x: {accent: ...}}`); the generated pydantic model wants it.
    for slot, key in (("pages", "about"), ("prefixes", "prefix"), ("text", "key")):
        for name, value in (raw.get(slot) or {}).items():
            if isinstance(value, dict):
                value.setdefault(key, name)
    project = Project(root=path.parent, config=SiteConfig(**raw))
    try:
        project.text  # noqa: B018  (checks every override key now, not mid-build)
    except TextError as exc:
        raise ConfigError(f"{path.name}:\n{exc}") from exc
    try:
        dgo.use(project.dgo)
    except dgo.DgoError as exc:
        raise ConfigError(f"{path.name}: {exc}") from exc
    return project
