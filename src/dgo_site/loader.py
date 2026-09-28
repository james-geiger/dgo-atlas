"""Find, read and merge governance data files.

Implementers may split their data across any number of YAML files under the
data directory (for example one file per term). Each file is a partial
GovernanceRecord: a mapping of list names to lists. Files are merged by
concatenating their lists, in path order; every object remembers the file and
position it came from so problems can be reported where they were written.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Origin:
    file: str  # path relative to the project root
    list_name: str
    index: int

    def __str__(self) -> str:
        return f"{self.file}: {self.list_name}[{self.index}]"


@dataclass
class SourceFile:
    path: Path
    rel: str
    data: dict | None = None
    error: str | None = None


@dataclass
class Dataset:
    files: list[SourceFile]
    merged: dict[str, list] = field(default_factory=dict)
    # id(obj) of every merged top-level object -> where it was written
    origins: dict[int, Origin] = field(default_factory=dict)

    def origin(self, obj) -> Origin | None:
        return self.origins.get(id(obj))


def discover(data_dir: Path) -> list[Path]:
    return sorted(p for p in data_dir.rglob("*") if p.suffix in (".yaml", ".yml") and p.is_file())


def read(data_dir: Path, root: Path) -> Dataset:
    """Parse every data file. Parse errors are recorded, not raised."""
    files = []
    for path in discover(data_dir):
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            rel = str(path)
        source = SourceFile(path=path, rel=rel)
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            source.error = f"not valid YAML: {exc}"
        else:
            if loaded is None:
                loaded = {}
            if not isinstance(loaded, dict):
                source.error = "the top level must be a mapping of list names (e.g. `glossary_terms:`) to lists"
            else:
                source.data = loaded
        files.append(source)
    return Dataset(files=files)


def merge(dataset: Dataset) -> Dataset:
    """Concatenate every file's lists. Call only when every file parsed."""
    merged: dict[str, list] = {}
    for source in dataset.files:
        for list_name, items in (source.data or {}).items():
            if not isinstance(items, list):
                continue
            bucket = merged.setdefault(list_name, [])
            for index, item in enumerate(items):
                bucket.append(item)
                dataset.origins[id(item)] = Origin(source.rel, list_name, index)
    dataset.merged = merged
    return dataset
