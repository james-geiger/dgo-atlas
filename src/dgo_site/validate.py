"""Validate governance data: linkml-validate, plus what it cannot check.

Stages, stopping after the first that finds errors:

1. **Read.** Every file must be YAML whose top level is a mapping. A `type`
   written as a DGO class name (`approved`, `submitted for review`) is
   rewritten to that class's CURIE, so every later stage, the site and the
   exports see exactly DGO's value.
2. **Scalars.** DGO has no boolean, number or date slots, so any such value is
   an authoring slip: an unquoted date, or a YAML boolean such as `on` or
   `no`. (`label` has no range in DGO, so linkml-validate would accept
   `label: yes` as a boolean.)
3. **Shape.** Each file is validated against the authoring template, the same
   check `linkml-validate -s template.yaml -C GovernanceRecord` makes.
4. **Graph.** The files are merged and every reference is resolved: it must
   name an object that exists and is of a kind the slot allows. linkml-validate
   checks the form of an id only. Identifiers must be unique and use a
   declared prefix, and the authoring rules in the docs are enforced.
5. **Load.** The merged data is loaded into the generated pydantic model.
"""

from __future__ import annotations

import datetime
import re
from collections import defaultdict
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from . import dgo
from .loader import Dataset, merge, read
from .resources import ROOT_CLASS


@dataclass
class Problem:
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.where}: {self.message}" if self.where else self.message


@dataclass
class Report:
    stage: str = ""
    errors: list[Problem] = field(default_factory=list)
    warnings: list[Problem] = field(default_factory=list)
    dataset: Dataset | None = None
    record: object | None = None  # the active DGO model's GovernanceRecord

    @property
    def ok(self) -> bool:
        return not self.errors


@cache
def _validator_for(template: Path):
    from linkml.validator import Validator
    from linkml.validator.plugins import JsonschemaValidationPlugin

    return Validator(str(template), validation_plugins=[JsonschemaValidationPlugin(closed=True)])


def _validator():
    """The template validator for the active DGO release."""
    return _validator_for(dgo.template_path())


# ---------------------------------------------------------------- paths


def _describe(data: dict, parts: list[str]) -> str:
    """`glossary_terms[2] (ex:foo)` for a JSON-pointer-ish path into a file."""
    out, node = [], data
    for part in parts:
        if isinstance(node, list) and part.isdigit():
            node = node[int(part)] if int(part) < len(node) else None
            out[-1] += f"[{part}]"
            if isinstance(node, dict) and node.get("id"):
                out[-1] += f" ({node['id']})"
        elif isinstance(node, dict):
            node = node.get(part)
            out.append(part)
        else:
            out.append(part)
    return ".".join(out)


def _node(data, parts: list[str]):
    node = data
    for part in parts:
        if isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        elif isinstance(node, dict):
            node = node.get(part)
        else:
            return None
    return node


def _class_at(parts: list[str]) -> str | None:
    """The DGO class the object at a path is declared as (before `type`)."""
    names = [p for p in parts if not p.isdigit()]
    if not names:
        return None
    cls = dgo.list_ranges().get(names[0])
    for slot in names[1:]:
        if cls is None:
            return None
        cls = dgo.inlined_slots(cls).get(slot)
    return cls


def _typed_base(cls: str | None) -> str | None:
    if cls is None:
        return None
    sv = dgo.view()
    for base in dgo.TYPED_BASES:
        if cls == base or base in sv.class_ancestors(cls):
            return base
    return None


# ---------------------------------------------------------------- stage 1


def name_types(data: dict) -> None:
    """Rewrite, in place, each `type` given as a DGO class name to the class's CURIE.

    Only names of the kinds the object's list allows are rewritten; anything
    else is left for the shape check to report.
    """
    for list_name, items in data.items():
        cls = dgo.list_ranges().get(list_name)
        for obj in items if cls and isinstance(items, list) else []:
            _name_type(obj, cls)


def _name_type(obj, cls: str) -> None:
    if not isinstance(obj, dict):
        return
    base = _typed_base(cls)
    value = obj.get("type")
    if base and isinstance(value, str) and value in dgo.named_types(base):
        obj["type"] = dgo.named_types(base)[value].curie
    for slot, child_cls in dgo.inlined_slots(cls).items():
        children = obj.get(slot)
        for child in children if isinstance(children, list) else []:
            _name_type(child, child_cls)


# ---------------------------------------------------------------- stage 2


def _scalar_problems(data, parts: list[str]) -> list[tuple[list[str], str]]:
    out = []
    if isinstance(data, dict):
        for key, value in data.items():
            out += _scalar_problems(value, parts + [str(key)])
    elif isinstance(data, list):
        for i, value in enumerate(data):
            out += _scalar_problems(value, parts + [str(i)])
    elif isinstance(data, bool):
        out.append((parts, (f"was read as the boolean {str(data).lower()}. YAML reads unquoted "
                            "yes/no/on/off/true/false as booleans; quote the value.")))
    elif isinstance(data, (datetime.date, datetime.datetime)):
        out.append((parts, f'is an unquoted date. Quote it: "{data.isoformat()}".'))
    elif isinstance(data, (int, float)):
        out.append((parts, f"was read as the number {data}; quote it if it is text."))
    return out


# ---------------------------------------------------------------- stage 3

_PATH = re.compile(r"\s+in\s+(/\S*)$")


def _type_hint(obj: dict, base: str) -> str | None:
    value = obj.get("type")
    accepted = dgo.accepted_types(base)
    choices = ", ".join(f"{k.name} ({k.curie})" for k in dgo.subkinds(base))
    if value is None:
        return None
    if value in accepted:
        return f"check its fields against {base}"
    readable = dgo.readable_type(str(value), base)
    if readable:
        return f"`type: {value}` is not how DGO names it; use {readable.name} (or {readable.curie})"
    return f"`type: {value}` is not a kind of {base}; use one of {choices}"


def _shape_problems(source) -> list[tuple[list[str], str]]:
    out = []
    for result in _validator().iter_results(source.data, ROOT_CLASS):
        message = result.message
        match = _PATH.search(message)
        parts = [p for p in match.group(1).split("/") if p] if match else []
        if match:
            message = message[: match.start()]
        obj = _node(source.data, parts)
        base = _typed_base(_class_at(parts))
        if "is not valid under any of the given schemas" in message and isinstance(obj, dict):
            message = "does not match any allowed kind"
            if base:
                hint = _type_hint(obj, base)
                if hint:
                    message += f": {hint}"
        out.append((parts, message))
    return out


# ---------------------------------------------------------------- stage 4


def _expandable(value: str, prefixes: dict[str, str]) -> bool:
    if value.startswith(("http://", "https://")):
        return True
    prefix, sep, _ = value.partition(":")
    return bool(sep) and (prefix in prefixes or prefix == "dgo")


def _declared_class(list_name: str, obj: dict) -> str:
    cls = dgo.list_ranges()[list_name]
    return _resolve_type(cls, obj)


def _resolve_type(cls: str, obj: dict) -> str:
    base = _typed_base(cls)
    if base and obj.get("type"):
        kind = dgo.accepted_types(base).get(obj["type"])
        if kind:
            return kind.name
    return cls


def _graph_problems(dataset: Dataset, prefixes: dict[str, str]) -> tuple[list[Problem], list[Problem]]:
    errors: list[Problem] = []
    warnings: list[Problem] = []
    merged = dataset.merged

    def where(obj) -> str:
        origin = dataset.origin(obj)
        label = f" ({obj['id']})" if isinstance(obj, dict) and obj.get("id") else ""
        return f"{origin}{label}" if origin else label.strip()

    # Identified objects, by id, with their DGO class.
    index: dict[str, tuple[str, dict]] = {}
    for list_name, items in merged.items():
        for obj in items:
            oid = obj.get("id")
            if oid is None:
                continue
            cls = _declared_class(list_name, obj)
            if oid in index:
                first = dataset.origin(index[oid][1])
                errors.append(Problem(where(obj), f"id {oid} is already defined at {first}"))
                continue
            index[oid] = (cls, obj)
            if not _expandable(oid, prefixes):
                errors.append(Problem(where(obj), f"id {oid} does not use a declared prefix; "
                                      "add it under `prefixes:` in dgo-site.yaml"))

    def check_refs(obj: dict, cls: str, at: str) -> None:
        for ref in dgo.reference_slots(cls):
            values = obj.get(ref.slot)
            if values is None:
                continue
            for value in values if isinstance(values, list) else [values]:
                target = index.get(value)
                if target is None:
                    errors.append(Problem(at, f"{ref.slot}: {value} is not defined anywhere"))
                elif target[0] not in ref.allowed:
                    allowed = " or ".join(sorted({dgo.kind(a).name for a in _top_allowed(ref)}))
                    errors.append(Problem(at, f"{ref.slot}: {value} is a {target[0]}, but "
                                              f"{ref.slot} on a {cls} must point at a {allowed}"))
        for slot, range_cls in dgo.inlined_slots(cls).items():
            for i, child in enumerate(obj.get(slot) or []):
                if isinstance(child, dict):
                    check_refs(child, _resolve_type(range_cls, child), f"{at} {slot}[{i}]")

    for list_name, items in merged.items():
        for obj in items:
            check_refs(obj, _declared_class(list_name, obj), where(obj))

    if errors:
        return errors, warnings

    # Authoring rules on terms.
    terms = merged.get("glossary_terms") or []
    for term in terms:
        at = where(term)
        tid = term["id"]
        semantic_type = term.get("semantic_type")
        if semantic_type and not _expandable(semantic_type, prefixes):
            errors.append(Problem(at, f"semantic_type: {semantic_type} does not use a declared prefix; add it "
                                      "under `prefixes:` in dgo-site.yaml, or write the full IRI"))
        pref, alts = term.get("pref_label"), term.get("alt_labels") or []
        if pref and pref in alts:
            errors.append(Problem(at, f"pref_label {pref!r} must differ from every alt label"))
        if pref and pref == term.get("label"):
            warnings.append(Problem(at, "pref_label is the same as label; it is only needed when they differ"))
        for slot in ("replaced_by", "value_of"):
            if term.get(slot) == tid:
                errors.append(Problem(at, f"{slot} points at the term itself"))
        for slot in ("broader", "related"):
            if tid in (term.get(slot) or []):
                errors.append(Problem(at, f"{slot} includes the term itself"))

    # broader must not loop back on itself.
    broader = {t["id"]: list(t.get("broader") or []) for t in terms}
    for start in broader:
        seen, todo = set(), list(broader[start])
        while todo:
            t = todo.pop()
            if t == start:
                errors.append(Problem(where(index[start][1]), "broader loops back to this term"))
                break
            if t not in seen:
                seen.add(t)
                todo += broader.get(t, [])

    # Lifecycle processes and their boundaries.
    boundaries: dict[str, list[dict]] = defaultdict(list)
    for b in merged.get("term_status_boundaries") or []:
        boundaries[b["part_of"]].append(b)
    creations: dict[str, list[dict]] = defaultdict(list)
    for proc in merged.get("term_creations") or []:
        creations[proc["has_output"]].append(proc)
    for term_id, procs in creations.items():
        if len(procs) > 1:
            ids = ", ".join(p["id"] for p in procs)
            errors.append(Problem(where(index[term_id][1]), f"has more than one term creation ({ids})"))

    closing = {dgo.kind("approved").name, dgo.kind("rejected").name}
    approved_deprecations = set()
    for list_name in ("term_creations", "term_modifications", "term_deprecations"):
        for proc in merged.get(list_name) or []:
            bs = boundaries.get(proc["id"], [])
            if not bs:
                warnings.append(Problem(where(proc), "has no status boundaries, so it counts as open"))
                continue
            kinds = [(str(b["occurred_on"]), _resolve_type("status boundary", b)) for b in bs]
            closed = sorted(d for d, k in kinds if k in closing)
            if len({k for _, k in kinds if k in closing}) > 1:
                errors.append(Problem(where(proc), "has both an approved and a rejected boundary"))
            elif closed and any(d > closed[0] for d, _ in kinds):
                errors.append(Problem(where(proc), f"has a status boundary after it closed on {closed[0]}"))
            if list_name == "term_deprecations" and any(k == "approved" for _, k in kinds):
                approved_deprecations.add(proc["has_output"])

    for term in terms:
        if term.get("replaced_by") and term["id"] not in approved_deprecations:
            warnings.append(Problem(where(term), "has replaced_by but no approved term deprecation, "
                                                 "so it is not shown as deprecated"))

    return errors, warnings


def _top_allowed(ref) -> list[str]:
    """The most general classes in an allowed set, for messages."""
    sv = dgo.view()
    allowed = set(ref.allowed)
    return [a for a in allowed if not (set(sv.class_ancestors(a, reflexive=False)) & allowed)]


# ---------------------------------------------------------------- entry point


def validate(data_dir: Path, root: Path, prefixes: dict[str, str]) -> Report:
    report = Report()
    dataset = read(data_dir, root)
    report.dataset = dataset

    report.stage = "read"
    if not dataset.files:
        report.errors.append(Problem(str(data_dir), "no .yaml files found"))
        return report
    for source in dataset.files:
        if source.error:
            report.errors.append(Problem(source.rel, source.error))
    if report.errors:
        return report
    for source in dataset.files:
        name_types(source.data)

    report.stage = "shape"
    for source in dataset.files:
        scalar = _scalar_problems(source.data, [])
        scalar_paths = ["/".join(p) for p, _ in scalar]
        for parts, message in scalar:
            report.errors.append(Problem(f"{source.rel}: {_describe(source.data, parts)}", message))
        for parts, message in _shape_problems(source):
            path = "/".join(parts)
            if any(sp == path or sp.startswith(path + "/") for sp in scalar_paths):
                continue  # already explained by the scalar check
            where = f"{source.rel}: {_describe(source.data, parts)}" if parts else source.rel
            report.errors.append(Problem(where, message))
    if report.errors:
        return report

    report.stage = "graph"
    merge(dataset)
    errors, warnings = _graph_problems(dataset, prefixes)
    report.errors += errors
    report.warnings += warnings
    if report.errors:
        return report

    report.stage = "load"
    try:
        report.record = dgo.model().GovernanceRecord(**dataset.merged)
    except Exception as exc:  # pydantic.ValidationError; should not happen after stage 3
        report.errors.append(Problem("", f"could not load the merged data: {exc}"))
    return report
