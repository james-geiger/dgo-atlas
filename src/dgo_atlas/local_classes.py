"""Local classes: an implementer's own subclasses of DGO classes.

DGO stays general; some of what it describes only has meaning locally, such
as an institution's own risk levels or a kind of steward only it has. An
implementer declares such a class in governance data:

    local_classes:
      - id: class:DataTrustee     # in the project's namespace for local classes
        name: data trustee        # the readable `type:` name
        is_a: steward             # a DGO class (name or CURIE) or another local class
        description: ...

Each one becomes a subclass of its parent in a small LinkML schema that the
authoring template imports next to DGO (dgo._template), so validation, the
editor JSON Schema, the pydantic model and every export read it exactly as
they read DGO's own subclasses. A local class adds no slots.

Local classes are read before the rest of the data is validated, since the
schema that data is checked against depends on them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from linkml_runtime.utils.formatutils import camelcase

from . import dgo
from .loader import Dataset, read
from .namespaces import Namespaces

LIST_NAME = "local_classes"
RESERVED_NAMESPACES = (dgo.DGO_NAMESPACE, "https://w3id.org/dgo-atlas/")


@dataclass(frozen=True)
class LocalClass:
    id: str  # a CURIE in the project's namespace for local classes (namespaces.py)
    name: str
    is_a: str  # the parent's class name, DGO's or local
    description: str | None = None


@dataclass
class Found:
    """What `check` found: the usable classes and the problems, as (where, message)."""

    classes: tuple[LocalClass, ...] = ()
    errors: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[tuple[str, str]] = field(default_factory=list)


def extension_schema(classes, prefixes: dict[str, str], dgo_location: str) -> dict:
    """A LinkML schema with each local class as a subclass of its parent."""
    used = {c.id.partition(":")[0] for c in classes}
    first = sorted(used)[0]
    return {
        "id": prefixes[first].rstrip("/#") + "/local-classes",
        "name": "local_classes",
        "title": "Local classes",
        "description": "Local subclasses of Data Governance Ontology classes.",
        # LinkML reads prefixes from the root schema only, so DGO's are repeated here.
        "prefixes": {**dgo.release_prefixes(dgo_location), "linkml": "https://w3id.org/linkml/",
                     **{p: prefixes[p] for p in sorted(used)}},
        "default_prefix": first,
        "imports": ["linkml:types", dgo_location],
        "classes": {
            c.name: {"is_a": c.is_a, "class_uri": c.id, **({"description": c.description} if c.description else {})}
            for c in classes
        },
    }


def check(dataset: Dataset, ns: Namespaces) -> Found:
    """Read and check every local class declared in the (parsed, unmerged) data files.

    Entries that are malformed (not a mapping, or missing `id`, `name` or
    `is_a`) are skipped here; the shape check reports them.
    """
    release = dgo.release_classes()
    dgo_names = set(release.values())
    dgo_models = {camelcase(n) for n in dgo_names}
    entries: list[tuple[str, dict]] = []
    for source in dataset.files:
        for i, entry in enumerate((source.data or {}).get(LIST_NAME) or []):
            if isinstance(entry, dict) and all(isinstance(entry.get(k), str) for k in ("id", "name", "is_a")):
                entries.append((f"{source.rel}: {LIST_NAME}[{i}] ({entry['id']})", entry))

    errors: list[tuple[str, str]] = []
    warnings: list[tuple[str, str]] = []
    by_name: dict[str, str] = {}  # local name or id -> local name
    models: dict[str, str] = {}
    for where, e in entries:
        name = e["name"]
        iri = ns.expand(e["id"]) or ""
        if iri.startswith(RESERVED_NAMESPACES):
            errors.append((where, f"id {e['id']} is in DGO's or DGO Atlas's namespace; a local class needs "
                                  "an id in your own namespace"))
        elif problem := ns.problem(LIST_NAME, e["id"]):
            errors.append((where, problem))
        e["id"] = ns.canonical(e["id"])
        if name in dgo_names or camelcase(name) in dgo_models:
            errors.append((where, f"name {name!r} is already a DGO class; choose a name of your own"))
        elif name in by_name or camelcase(name) in models:
            errors.append((where, f"name {name!r} is used by another local class"))
        by_name[name] = by_name[e["id"]] = name
        models[camelcase(name)] = name

    parents: dict[str, str] = {}
    for where, e in entries:
        parent = release.get(e["is_a"]) or by_name.get(e["is_a"])
        if parent is None:
            errors.append((where, f"is_a: {e['is_a']} is not a DGO class or a local class"))
        else:
            parents[e["name"]] = parent

    for where, e in entries:
        seen, current = [], e["name"]
        while current in parents and current not in seen:
            seen.append(current)
            current = parents[current]
        if current in seen:
            errors.append((where, f"is_a loops back to {e['name']!r}"))
            continue
        if current in dgo_names and not _typed(current):
            warnings.append((where, f"DGO gives {current} no `type` field, so no data can be declared a "
                                    f"{e['name']} yet; the class is still exported"))

    if errors:
        return Found(errors=errors, warnings=warnings)
    classes = tuple(LocalClass(e["id"], e["name"], parents[e["name"]], e.get("description") or None)
                    for _, e in entries)
    return Found(classes=classes, warnings=warnings)


def _typed(dgo_class: str) -> bool:
    ancestors = dgo._release(dgo.active().location).class_ancestors(dgo_class)
    return any(base in ancestors for base in dgo.typed_bases())


def activate(found: Found) -> None:
    """Make the active DGO release carry these local classes (none, if any had errors)."""
    dgo.with_local_classes(found.classes)


def load(data_dir: Path, root: Path, ns: Namespaces) -> Found:
    """Read the project's local classes and activate them; problems are left for validation to report."""
    found = check(read(data_dir, root), ns) if data_dir.is_dir() else Found()
    activate(found)
    return found


def extension() -> str:
    """The active local classes as a LinkML schema that imports DGO, or "" if there are none."""
    import yaml

    source = dgo.active()
    if not source.local_classes:
        return ""
    schema = extension_schema(source.local_classes, source.prefixes, source.location)
    return yaml.safe_dump(schema, sort_keys=False)


def scaffold(data_dir: Path, name: str, is_a: str, ns: Namespaces, *,
             id: str | None = None, description: str | None = None) -> Path:
    """Write a new local class to its own file under the data directory; return the file.

    Raises ValueError if the parent is unknown, the id can't be formed, or the file exists.
    """
    import yaml

    known = {**dgo.release_classes(), **{c.name: c.name for c in dgo.active().local_classes},
             **{c.id: c.name for c in dgo.active().local_classes}}
    if is_a not in known:
        raise ValueError(f"is_a: {is_a} is not a DGO class or a local class")
    if id is None:
        id = f"{ns.for_list(LIST_NAME).authoring_prefix}:{camelcase(name)}"
    elif problem := ns.problem(LIST_NAME, id):
        raise ValueError(problem)
    target = data_dir / "local-classes" / f"{dgo.slug(name).replace('_', '-')}.yaml"
    if target.exists():
        raise ValueError(f"{target} already exists")
    entry = {"id": id, "name": name, "is_a": is_a,
             "description": description or f"TODO: what makes something a {name}."}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump({LIST_NAME: [entry]}, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return target
