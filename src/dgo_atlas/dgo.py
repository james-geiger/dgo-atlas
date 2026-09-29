"""What the middleware knows about DGO, in one place.

DGO is not bundled. Each project names a DGO release (`dgo_version` in
dgo-atlas.yaml) and the authoring template imports that release's single-file
schema, dist/dgo.yaml, straight from the DGO repository by URL. `use()` makes
one release active for the process; everything below reads it through
SchemaView rather than restating it: which slots are references and what they
may point at, which kinds a `type` value can name, the display labels and
IRIs of DGO classes, and the pydantic model generated from it at runtime.

An implementer's local classes (local_classes.py), their own subclasses of DGO
classes, are imported alongside the release, so everything here reads them
exactly as it reads DGO's own subclasses.

When DGO changes (handoff §8), this module and derive.py are where the
middleware changes.
"""

from __future__ import annotations

import json
import dataclasses
import re
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml
from linkml_runtime.utils.formatutils import camelcase
from linkml_runtime.utils.schemaview import SchemaView

from .resources import ROOT_CLASS, TEMPLATE

DGO_NAMESPACE = "https://w3id.org/dgo/"

# Where a DGO release's single-file schema lives. LinkML appends ".yaml" to an
# import, so the import location leaves it off.
RELEASE_URL = "https://raw.githubusercontent.com/james-geiger/dgo/refs/tags/{version}/dist/dgo"

# Releases this version of DGO Atlas has been tested against. Others are used
# if they have the classes below, with a warning.
TESTED_VERSIONS = ("0.1.0", "0.1.1")

# The placeholder in schema/template.yaml that the import location replaces.
IMPORT_PLACEHOLDER = "DGO_IMPORT"

# Classes the derivation depends on by name. A DGO release without them
# cannot be used by this version of DGO Atlas.
REQUIRED_CLASSES = (
    "data governance", "data governance council", "person", "organization",
    "council role", "governance role", "business glossary", "domain", "subject area",
    "glossary term", "definition source", "term lifecycle process", "term creation",
    "term modification", "term deprecation", "status boundary", "drafted",
    "submitted for review", "approved", "rejected",
)


class DgoError(Exception):
    """The configured DGO release cannot be loaded or used."""


@dataclass(frozen=True)
class Source:
    """One DGO release: its version and the location the template imports.

    With the implementer's local classes, and the prefixes their ids use,
    when the data declares any (local_classes.activate).
    """

    version: str
    location: str  # a URL or absolute path, without the ".yaml" LinkML appends
    local_classes: tuple = ()  # of local_classes.LocalClass
    prefixes: tuple[tuple[str, str], ...] = ()

    @property
    def tested(self) -> bool:
        return self.version in TESTED_VERSIONS


_active: Source | None = None


def source_for(version: str, override: str | None = None, root: Path | None = None) -> Source:
    """The Source for a project: the release URL, or `override` (a URL or a path)."""
    location = override or RELEASE_URL.format(version=version)
    location = location.removesuffix(".yaml")
    if not location.startswith(("http://", "https://")) and root is not None:
        location = str((root / location).resolve())
    return Source(version=version, location=location)


def use(source: Source) -> None:
    """Make `source` the DGO release every function below reads."""
    global _active
    if source == _active:
        return
    if _active is None or (source.version, source.location) != (_active.version, _active.location):
        _fetch_check(source)
    for fn in _CACHED:
        fn.cache_clear()
    previous, _active = _active, source
    missing = [c for c in REQUIRED_CLASSES if c not in view().all_classes()]
    if missing:
        _active = previous
        raise DgoError(f"DGO {source.version} ({source.location}.yaml) is missing classes DGO Atlas "
                       f"depends on: {', '.join(missing)}. Use a supported release: {', '.join(TESTED_VERSIONS)}.")


def active() -> Source:
    if _active is None:
        raise DgoError("no DGO release is active; call dgo.use() first")
    return _active


def with_local_classes(classes: tuple, prefixes: dict[str, str]) -> None:
    """Make the active release, extended with `classes`, the active one."""
    base = active()
    use(dataclasses.replace(base, local_classes=tuple(classes),
                            prefixes=tuple(sorted(prefixes.items())) if classes else ()))


def _fetch_check(source: Source) -> None:
    """Fail early, and clearly, if the release can't be read."""
    target = source.location + ".yaml"
    if target.startswith(("http://", "https://")):
        try:
            with urllib.request.urlopen(target, timeout=30) as response:
                response.read(1)
        except urllib.error.HTTPError as exc:
            hint = " Is dgo_version a DGO release tag?" if exc.code == 404 else ""
            raise DgoError(f"DGO {source.version} not found at {target} (HTTP {exc.code}).{hint}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise DgoError(f"could not download DGO {source.version} from {target}: {exc}. "
                           "Check the network, or set dgo_source to a local copy.") from exc
    elif not Path(target).is_file():
        raise DgoError(f"DGO {source.version}: {target} does not exist")


@cache
def _release(location: str) -> SchemaView:
    """The release on its own, without the template or any local classes."""
    return SchemaView(location + ".yaml")


def release_prefixes(location: str) -> dict[str, str]:
    """The prefixes a release declares (dgo, rdfs, skos, ro...)."""
    return {p.prefix_prefix: p.prefix_reference for p in _release(location).schema.prefixes.values()}


@cache
def _template(source: Source) -> Path:
    from .local_classes import extension_schema

    text = TEMPLATE.read_text(encoding="utf-8")
    assert IMPORT_PLACEHOLDER in text
    template = yaml.safe_load(text.replace(IMPORT_PLACEHOLDER, source.location))
    # LinkML expands CURIEs with the root schema's prefixes only, so the
    # release's prefixes (rdfs, skos, ro...) are declared here too, and so are
    # the prefixes of any local class ids.
    template["prefixes"] = {**release_prefixes(source.location), **dict(source.prefixes), **template["prefixes"]}
    directory = Path(tempfile.mkdtemp(prefix="dgo-atlas-"))
    if source.local_classes:
        extension = directory / "local-classes.yaml"
        extension.write_text(yaml.safe_dump(
            extension_schema(source.local_classes, dict(source.prefixes), source.location), sort_keys=False),
            encoding="utf-8")
        template["imports"].append(str(extension.with_suffix("")))
    path = directory / TEMPLATE.name
    path.write_text(yaml.safe_dump(template, sort_keys=False), encoding="utf-8")
    return path


def template_path() -> Path:
    """The authoring template, importing the active DGO release and any local classes."""
    return _template(active())


@cache
def _view(source: Source) -> SchemaView:
    return SchemaView(str(_template(source)))


def view() -> SchemaView:
    return _view(active())


@cache
def _model(source: Source):
    from linkml.generators.pydanticgen import PydanticGenerator

    return PydanticGenerator(str(_template(source))).compile_module()


def model():
    """The pydantic model generated from the template for the active release."""
    return _model(active())


@cache
def _json_schema(source: Source) -> str:
    from linkml.generators.jsonschemagen import JsonSchemaGenerator

    schema = json.loads(JsonSchemaGenerator(str(_template(source)), top_class=ROOT_CLASS).serialize())
    # Editors accept `type` as the class name too, as validate.py does.
    names = {kind(c).curie: c for c in _view(source).all_classes()}
    for definition in schema.get("$defs", {}).values():
        values = (definition.get("properties") or {}).get("type", {}).get("enum")
        if values:
            values += [names[v] for v in list(values) if v in names]
    return json.dumps(schema, indent=4) + "\n"


def json_schema() -> str:
    """JSON Schema for governance files, for editor validation."""
    return _json_schema(active())


def linkml_schema() -> str:
    """The authoring template as one self-contained LinkML schema.

    The template, the DGO release and any local classes, merged, so LinkML's
    own generators (gen-pydantic, gen-json-schema, gen-owl...) can use it
    without network access or DGO Atlas.
    """
    from linkml_runtime.dumpers import yaml_dumper

    sv = SchemaView(str(template_path()))
    sv.merge_imports()
    schema = sv.schema
    schema.source_file = schema.source_file_date = schema.source_file_size = None  # a temporary file
    return yaml_dumper.dumps(schema)


def release_classes() -> dict[str, str]:
    """Every DGO class in the release, by name, CURIE and IRI -> its name."""
    sv = _release(active().location)
    out = {}
    for name in sv.all_classes():
        cls = sv.get_class(name)
        out[name] = out[sv.get_uri(cls, expand=False)] = out[sv.get_uri(cls, expand=True)] = name
    return out


@dataclass(frozen=True)
class Kind:
    """One DGO class, as the site shows it."""

    name: str  # DGO's class name, e.g. "subject matter expert"; the display label
    slug: str  # e.g. "subject_matter_expert"; used in CSS classes and the view model
    curie: str  # e.g. "dgo:DGO_00000015"; the form `type` takes in data
    iri: str  # e.g. "https://w3id.org/dgo/DGO_00000015"
    description: str
    model_class: str  # the generated pydantic class name, e.g. "SubjectMatterExpert"
    local: bool = False  # an implementer's local class, not DGO's
    dgo_ancestor: str = ""  # the nearest DGO class: this one, or a local class's DGO parent


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


@cache
def kind(class_name: str) -> Kind:
    sv = view()
    cls = sv.get_class(class_name)
    local = {c.name for c in active().local_classes}
    return Kind(
        name=cls.name,
        slug=slug(cls.name),
        curie=sv.get_uri(cls, expand=False),
        iri=sv.get_uri(cls, expand=True),
        description=" ".join((cls.description or "").split()),
        model_class=camelcase(cls.name),
        local=cls.name in local,
        dgo_ancestor=next(a for a in sv.class_ancestors(cls.name) if a not in local),
    )


def dgo_kind(obj) -> Kind:
    """The DGO kind of a loaded object: its own, or its local class's DGO ancestor."""
    return kind(kind_of(obj).dgo_ancestor)


@cache
def kind_of_model(model_class: str) -> Kind:
    """The Kind for a generated pydantic class name, e.g. `Owner`."""
    for name in view().all_classes():
        if camelcase(name) == model_class:
            return kind(name)
    raise KeyError(model_class)


def kind_of(obj) -> Kind:
    """The Kind of a loaded object. `type` has already resolved it to its subclass."""
    return kind_of_model(type(obj).__name__)


@cache
def typed_bases() -> tuple[str, ...]:
    """The DGO classes whose subclasses `type` picks between: those that declare
    DGO's type-designator slot. Objects in their lists have no id; their kind
    comes from `type` alone.
    """
    sv = _release(active().location)
    designators = {s for s in sv.all_slots() if sv.get_slot(s).designates_type}
    return tuple(sorted(c for c in sv.all_classes()
                        if designators & {*(sv.get_class(c).slots or []), *(sv.get_class(c).slot_usage or {})}))


@cache
def subkinds(base: str) -> tuple[Kind, ...]:
    """The concrete kinds `type` may name under a base (the base first, then its descendants)."""
    sv = view()
    names = [base] + sorted(sv.class_descendants(base, reflexive=False))
    return tuple(kind(n) for n in names)


@cache
def accepted_types(base: str) -> dict[str, Kind]:
    """`type` values accepted by linkml-validate for a base: class CURIEs and IRIs.

    The readable form (`dgo:Approved`) is not accepted by linkml-validate, so it
    is not listed here, and the validator reports it with a suggestion.
    """
    out = {}
    for k in subkinds(base):
        out[k.curie] = k
        out[k.iri] = k
    return out


@cache
def named_types(base: str) -> dict[str, Kind]:
    """`type` values written as DGO class names under a base (`approved`, `submitted for review`).

    Not DGO values themselves: validate.py rewrites each to its class CURIE as
    files are read, before anything else sees the data.
    """
    return {k.name: k for k in subkinds(base)}


def readable_type(value: str, base: str) -> Kind | None:
    """If `value` names a kind in some other readable form (dgo:Approved, submitted_for_review), which one."""
    local = value.rsplit(":", 1)[-1].rsplit("/", 1)[-1]
    for k in subkinds(base):
        if local in (k.model_class, k.slug, k.name):
            return k
    return None


@dataclass(frozen=True)
class RefSlot:
    """A slot whose value is the id of another object."""

    slot: str
    allowed: tuple[str, ...]  # DGO class names the target may be, descendants included
    multivalued: bool


@cache
def list_ranges() -> dict[str, str]:
    """Template list name -> the DGO class it holds, e.g. glossary_terms -> glossary term."""
    sv = view()
    return {s: sv.induced_slot(s, ROOT_CLASS).range for s in sv.class_slots(ROOT_CLASS)}


@cache
def reference_slots(class_name: str) -> tuple[RefSlot, ...]:
    """Every by-id reference slot on a class, with the kinds it may point at."""
    sv = view()
    classes = set(sv.all_classes())
    out = []
    for name in sv.class_slots(class_name):
        slot = sv.induced_slot(name, class_name)
        if slot.inlined or slot.inlined_as_list or slot.designates_type:
            continue
        ranges = [a.range for a in slot.any_of] if slot.any_of else [slot.range]
        ranges = [r for r in ranges if r in classes]
        if not ranges:
            continue
        allowed = set()
        for r in ranges:
            allowed |= set(sv.class_descendants(r, reflexive=True))
        out.append(RefSlot(name, tuple(sorted(allowed)), bool(slot.multivalued)))
    return tuple(out)


@cache
def inlined_slots(class_name: str) -> dict[str, str]:
    """Inlined (nested) slots of a class -> the class they hold, e.g. responsibilities."""
    sv = view()
    out = {}
    for name in sv.class_slots(class_name):
        slot = sv.induced_slot(name, class_name)
        if (slot.inlined or slot.inlined_as_list) and slot.range in sv.all_classes():
            out[name] = slot.range
    return out


def slot_description(slot_name: str, class_name: str = "glossary term") -> str:
    sv = view()
    slot = sv.induced_slot(slot_name, class_name)
    return " ".join((slot.description or "").split())


def slot_facts(slot_name: str, class_name: str = "glossary term") -> dict:
    sv = view()
    slot = sv.induced_slot(slot_name, class_name)
    return {
        "name": slot_name,
        "description": " ".join((slot.description or "").split()),
        "required": bool(slot.required),
        "multivalued": bool(slot.multivalued),
        "uri": slot.slot_uri,
    }


def class_slot_names(class_name: str) -> list[str]:
    return list(view().class_slots(class_name))


# Caches that read the active release; use() clears them when it changes.
_CACHED = (kind, kind_of_model, typed_bases, subkinds, accepted_types, named_types, list_ranges, reference_slots, inlined_slots)
