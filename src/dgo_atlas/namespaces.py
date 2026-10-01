"""Where each kind of identified object is minted, and how people write it.

A project names one root namespace, `iri_base`. Each kind of identified
object (term, council, organization...) has its own namespace under it,
`<iri_base><iri_segment>/`, and an authoring prefix for writing ids in it:

    iri_base: https://w3id.org/acme/
    organization:sponsored-programs  ->  https://w3id.org/acme/organizations/sponsored-programs

The defaults are annotations on the template's lists (schema/template.yaml),
so the list an object is written in decides its namespace. `namespaces:` in
dgo-atlas.yaml overrides a kind's segment, its prefix, or both. The segment
is part of every IRI and so is permanent once published; the prefix is only
an abbreviation and may change at any time. Kinds may share a namespace (an
implementer's councils and organizations both under `offices/`, say) as long
as they also share its prefix, so every IRI still has one spelling.

Every page lives at its IRI: the page path is the IRI less `iri_base`, plus
".html", so one resolver rule (`^<base>(.*)$ -> <site>/$1.html`) serves them all.
An id may end in a fragment (`data:levels#high`): the page is the document's
(`data/levels.html`), and the browser keeps the fragment.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from functools import cache

import yaml

from .dgo import DGO_NAMESPACE
from .resources import TEMPLATE

RESERVED_PREFIXES = ("dgo", "dgoatlas", "linkml")
RESERVED_SEGMENTS = ("assets",)
SEGMENT = re.compile(r"^[A-Za-z0-9._~-]+$")
NCNAME = re.compile(r"^[A-Za-z_][A-Za-z0-9._-]*$")
# A local name: segments of URL-safe characters, so the IRI path is the file path as
# written, and an optional fragment.
LOCAL = re.compile(r"^[A-Za-z0-9._~-]+(/[A-Za-z0-9._~-]+)*(#[A-Za-z0-9._~-]+)?$")


class NamespaceError(ValueError):
    """The project's namespace settings are inconsistent; one problem per line."""


@dataclass(frozen=True)
class Kind:
    """One kind of identified object and the namespace it is minted in."""

    kind: str  # e.g. "organization"
    lists: tuple[str, ...]  # the template lists holding it, e.g. ("organizations",)
    iri_segment: str  # e.g. "organizations"
    authoring_prefix: str  # e.g. "organization"


@cache
def defaults() -> tuple[Kind, ...]:
    """The kinds and their default namespaces, from the template's list annotations."""
    template = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    kinds: dict[str, Kind] = {}
    for name, spec in template["slots"].items():
        annotations = (spec or {}).get("annotations") or {}
        if "kind" not in annotations:
            continue
        kind = Kind(annotations["kind"], (name,), annotations["iri_segment"], annotations["authoring_prefix"])
        known = kinds.get(kind.kind)
        if known is None:
            kinds[kind.kind] = kind
        elif (known.iri_segment, known.authoring_prefix) != (kind.iri_segment, kind.authoring_prefix):
            raise AssertionError(f"template.yaml: lists of kind {kind.kind} disagree on its namespace")
        else:
            kinds[kind.kind] = dataclasses.replace(known, lists=known.lists + (name,))
    return tuple(kinds.values())


@dataclass(frozen=True)
class Namespaces:
    """A project's effective namespaces: `iri_base`, one per kind, and its declared prefixes."""

    iri_base: str
    kinds: tuple[Kind, ...]
    declared: tuple[tuple[str, str], ...] = ()  # `prefixes:` in dgo-atlas.yaml: aliases and foreign ones

    @classmethod
    def build(cls, iri_base: str, overrides: dict[str, dict[str, str | None]] | None = None,
              declared: dict[str, str] | None = None) -> Namespaces:
        """Apply `namespaces:` overrides to the defaults; raise NamespaceError on any problem."""
        problems = []
        if not iri_base.endswith("/"):  # every kind namespace is a path under it
            iri_base += "/"
        by_kind = {k.kind: k for k in defaults()}
        for name, override in (overrides or {}).items():
            if name not in by_kind:
                problems.append(f"namespaces: {name} is not a kind; use one of {', '.join(by_kind)}")
                continue
            changes = {key: value for key, value in (override or {}).items() if value is not None}
            by_kind[name] = dataclasses.replace(by_kind[name], **changes)
        kinds = tuple(by_kind.values())
        for k in kinds:
            if not SEGMENT.match(k.iri_segment) or k.iri_segment in RESERVED_SEGMENTS:
                problems.append(f"namespaces: {k.kind}: iri_segment {k.iri_segment!r} must be one path segment of "
                                f"letters, digits, - . _ ~ and not {', '.join(RESERVED_SEGMENTS)}")
            if not NCNAME.match(k.authoring_prefix) or k.authoring_prefix in RESERVED_PREFIXES:
                problems.append(f"namespaces: {k.kind}: authoring_prefix {k.authoring_prefix!r} must be a name "
                                f"(letters, digits, - . _) and not {', '.join(RESERVED_PREFIXES)}")
        for attr, other in (("iri_segment", "authoring_prefix"), ("authoring_prefix", "iri_segment")):
            seen: dict[str, Kind] = {}
            for k in kinds:
                first = seen.setdefault(getattr(k, attr), k)
                if getattr(first, other) != getattr(k, other):
                    problems.append(f"namespaces: {k.kind} and {first.kind} both use {attr} {getattr(k, attr)!r} "
                                    f"but not the same {other}; kinds that share a namespace must share both")
        ns = cls(iri_base, kinds, tuple((declared or {}).items()))
        for name, uri in ns.declared:
            kind = next((k for k in kinds if k.authoring_prefix == name), None)
            if kind and uri != ns.namespace(kind):
                problems.append(f"prefixes: {name} is the authoring prefix for {kind.kind} ids "
                                f"({ns.namespace(kind)}); it can't also mean {uri}")
        if problems:
            raise NamespaceError("\n".join(problems))
        return ns

    # ------------------------------------------------------------ lookups

    def namespace(self, kind: Kind) -> str:
        return f"{self.iri_base}{kind.iri_segment}/"

    def get(self, kind: str) -> Kind:
        return next(k for k in self.kinds if k.kind == kind)

    def for_list(self, list_name: str) -> Kind | None:
        return next((k for k in self.kinds if list_name in k.lists), None)

    @property
    def prefixes(self) -> dict[str, str]:
        """Every prefix ids may use: each kind's authoring prefix, then the declared ones."""
        return {**{k.authoring_prefix: self.namespace(k) for k in self.kinds}, **dict(self.declared)}

    @property
    def canonical_prefixes(self) -> dict[str, str]:
        """`prefixes` less the aliases for a kind's namespace: what exports and schemas declare,
        since every id is canonical by then, and a serializer would otherwise pick either name."""
        namespaces = {self.namespace(k) for k in self.kinds}
        authoring = {k.authoring_prefix for k in self.kinds}
        return {p: uri for p, uri in self.prefixes.items() if p in authoring or uri not in namespaces}

    def expand(self, value: str) -> str | None:
        """The IRI a CURIE (or IRI) names, or None if its prefix isn't declared."""
        if value.startswith(("http://", "https://")):
            return value
        prefix, sep, local = value.partition(":")
        base = DGO_NAMESPACE if prefix == "dgo" else self.prefixes.get(prefix)
        return base + local if sep and base is not None else None

    def kind_of(self, iri: str) -> Kind | None:
        """The kind whose namespace an IRI is minted in, if any."""
        return next((k for k in self.kinds if iri.startswith(self.namespace(k)) and iri != self.namespace(k)), None)

    def local(self, iri: str) -> str:
        """The part of an IRI after its kind's namespace."""
        kind = self.kind_of(iri)
        return iri[len(self.namespace(kind)):] if kind else iri

    def canonical(self, value: str) -> str:
        """`value` written with its kind's authoring prefix, if it's minted in a kind's namespace."""
        iri = self.expand(value) if isinstance(value, str) else None
        kind = self.kind_of(iri) if iri else None
        return f"{kind.authoring_prefix}:{iri[len(self.namespace(kind)):]}" if kind else value

    def page_path(self, iri: str) -> str:
        """Where the page for an IRI lives in the site: the IRI less `iri_base` and any
        fragment, plus .html."""
        return iri.partition("#")[0][len(self.iri_base):] + ".html"

    def problem(self, list_name: str, value: str) -> str | None:
        """Why `value` can't be the id of an object in `list_name`, or None if it can."""
        kind = self.for_list(list_name)
        if kind is None:
            return None
        iri = self.expand(value)
        example = f"{kind.authoring_prefix}:{_example(value)}"
        if iri is None:
            return (f"id {value} does not use a declared prefix; write it as {example}, "
                    "or declare the prefix under `prefixes:` in dgo-atlas.yaml")
        if not iri.startswith(self.namespace(kind)):
            where = "is outside" if not iri.startswith(self.iri_base) else "is not in"
            return (f"id {value} ({iri}) {where} the namespace for {kind.kind} ids, "
                    f"{self.namespace(kind)}; write it as {example}")
        rest = iri[len(self.namespace(kind)):]
        if not LOCAL.match(rest) or any(part in (".", "..") for part in rest.split("/")):
            return (f"id {value}: the part after {kind.authoring_prefix}: may use only letters, digits "
                    "and - . _ ~ (with / between parts, and one # before a fragment), so its IRI is also "
                    "its page's path")
        return None


def _example(value: str) -> str:
    local = re.split(r"[:/]", value.rstrip("/"))[-1]
    return local or "local-name"
