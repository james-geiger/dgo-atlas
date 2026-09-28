"""What the middleware knows about DGO, in one place.

DGO is not bundled. Each project names a DGO release (`dgo_version` in
dgo-site.yaml) and the authoring template imports that release's single-file
schema, dist/dgo.yaml, straight from the DGO repository by URL. `use()` makes
one release active for the process; everything below reads it through
SchemaView rather than restating it: which slots are references and what they
may point at, which kinds a `type` value can name, the display labels and
IRIs of DGO classes, and the pydantic model generated from it at runtime.

When DGO changes (handoff §8), this module and derive.py are where the
middleware changes.
"""

from __future__ import annotations

import re
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from linkml_runtime.utils.formatutils import camelcase
from linkml_runtime.utils.schemaview import SchemaView

from .resources import ROOT_CLASS, TEMPLATE

DGO_NAMESPACE = "https://w3id.org/dgo/"

# Where a DGO release's single-file schema lives. LinkML appends ".yaml" to an
# import, so the import location leaves it off.
RELEASE_URL = "https://raw.githubusercontent.com/james-geiger/dgo/refs/tags/{version}/dist/dgo"

# Releases this version of dgo-site has been tested against. Others are used
# if they have the classes below, with a warning.
TESTED_VERSIONS = ("0.1.0", "v0.1.1")

# The placeholder in schema/template.yaml that the import location replaces.
IMPORT_PLACEHOLDER = "DGO_IMPORT"

# The DGO classes whose subclasses `type` picks between. Objects in these
# lists have no id; their kind comes from `type` alone.
TYPED_BASES = ("governance role", "council role", "status boundary")

# Classes the derivation depends on by name. A DGO release without them
# cannot be used by this version of dgo-site.
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
    """One DGO release: its version and the location the template imports."""

    version: str
    location: str  # a URL or absolute path, without the ".yaml" LinkML appends

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
    _fetch_check(source)
    for fn in _CACHED:
        fn.cache_clear()
    previous, _active = _active, source
    missing = [c for c in REQUIRED_CLASSES if c not in view().all_classes()]
    if missing:
        _active = previous
        raise DgoError(f"DGO {source.version} ({source.location}.yaml) is missing classes dgo-site "
                       f"depends on: {', '.join(missing)}. Use a supported release: {', '.join(TESTED_VERSIONS)}.")


def active() -> Source:
    if _active is None:
        raise DgoError("no DGO release is active; call dgo.use() first")
    return _active


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
def _template(location: str) -> Path:
    text = TEMPLATE.read_text(encoding="utf-8")
    assert IMPORT_PLACEHOLDER in text
    directory = Path(tempfile.mkdtemp(prefix="dgo-site-"))
    path = directory / TEMPLATE.name
    path.write_text(text.replace(IMPORT_PLACEHOLDER, location), encoding="utf-8")
    return path


def template_path() -> Path:
    """The authoring template, importing the active DGO release."""
    return _template(active().location)


@cache
def _view(location: str) -> SchemaView:
    return SchemaView(str(_template(location)))


def view() -> SchemaView:
    return _view(active().location)


@cache
def _model(location: str):
    from linkml.generators.pydanticgen import PydanticGenerator

    return PydanticGenerator(str(_template(location))).compile_module()


def model():
    """The pydantic model generated from the template for the active release."""
    return _model(active().location)


@cache
def _json_schema(location: str) -> str:
    from linkml.generators.jsonschemagen import JsonSchemaGenerator

    text = JsonSchemaGenerator(str(_template(location)), top_class=ROOT_CLASS).serialize()
    return text if text.endswith("\n") else text + "\n"


def json_schema() -> str:
    """JSON Schema for governance files, for editor validation."""
    return _json_schema(active().location)


@dataclass(frozen=True)
class Kind:
    """One DGO class, as the site shows it."""

    name: str  # DGO's class name, e.g. "subject matter expert"; the display label
    slug: str  # e.g. "subject_matter_expert"; used in CSS classes and the view model
    curie: str  # e.g. "dgo:DGO_00000015"; the form `type` takes in data
    iri: str  # e.g. "https://w3id.org/dgo/DGO_00000015"
    description: str
    model_class: str  # the generated pydantic class name, e.g. "SubjectMatterExpert"


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


@cache
def kind(class_name: str) -> Kind:
    sv = view()
    cls = sv.get_class(class_name)
    return Kind(
        name=cls.name,
        slug=slug(cls.name),
        curie=sv.get_uri(cls, expand=False),
        iri=sv.get_uri(cls, expand=True),
        description=" ".join((cls.description or "").split()),
        model_class=camelcase(cls.name),
    )


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


def readable_type(value: str, base: str) -> Kind | None:
    """If `value` names a kind by its readable name (dgo:Approved), which one."""
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
_CACHED = (kind, kind_of_model, subkinds, accepted_types, list_ranges, reference_slots, inlined_slots)
