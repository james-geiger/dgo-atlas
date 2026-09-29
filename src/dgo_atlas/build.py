"""Validate governance data and build the site, stopping at the first failure.

1. Load and validate dgo-atlas.yaml.
2. Validate the governance data (validate.py): shape, references, rules.
3. Derive the view model (derive.py), reading each semantic type's label
   from the class it names (semantic.py), and validate it against
   schema/viewmodel.yaml.
4. Render the pages.
5. Check every internal link.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__, content, contrast, derive, dgo, linkcheck, semantic, validate
from .config import ConfigError, Project
from .console import fail, note, say, warn
from .models import viewmodel as vm
from .render import Renderer, split_pages


@dataclass
class Outcome:
    ok: bool
    lines: list[str] = field(default_factory=list)
    site: vm.Site | None = None
    pages: int = 0


def check(project: Project) -> validate.Report:
    """Validate the project's governance data and report on the console."""
    source = project.dgo
    rel = project.data_dir.relative_to(project.root) if project.data_dir.is_relative_to(project.root) \
        else project.data_dir
    say(f"Validating {rel} against DGO {source.version} ({source.location}.yaml)")
    if not source.tested:
        warn(f"dgo-atlas {__version__} has not been tested with DGO {source.version} "
             f"(tested: {', '.join(dgo.TESTED_VERSIONS)})")
    data_dir = project.data_dir
    if not data_dir.is_dir():
        report = validate.Report(stage="read")
        report.errors.append(validate.Problem(str(data_dir), "data directory does not exist"))
        return report
    report = validate.validate(data_dir, project.root, project.prefixes)
    return report


def print_report(report: validate.Report) -> int:
    files = len(report.dataset.files) if report.dataset else 0
    for w in report.warnings:
        warn(str(w))
    if not report.ok:
        stage = {"read": "Reading", "shape": "Schema validation", "graph": "Reference and rule checks",
                 "load": "Loading"}.get(report.stage, report.stage)
        return fail(f"{stage} failed ({len(report.errors)} problem{'s' if len(report.errors) != 1 else ''}):",
                     report.errors)
    rec = report.record
    say(f"  {files} file(s) valid: {len(rec.glossary_terms or [])} term(s), "
         f"{len(rec.subject_areas or [])} subject area(s), {len(rec.councils or [])} council(s)")
    return 0


def sources_by_id(report: validate.Report) -> dict[str, str]:
    """The file each identified object was written in, for "view source" links."""
    out = {}
    for items in report.dataset.merged.values():
        for obj in items:
            origin = report.dataset.origin(obj)
            if isinstance(obj, dict) and obj.get("id") and origin:
                out[obj["id"]] = origin.file
    return out


def build(project: Project, *, out: Path | None = None) -> int:
    started = time.monotonic()
    out = out or project.output_dir

    report = check(project)
    if print_report(report):
        return 1
    for message in contrast.brand_problems(project.brand):
        warn(message)

    deriver = derive.Deriver(report.record, project.prefixes, sources=sources_by_id(report),
                             accents=project.accents, describe=semantic.describe)
    site = deriver.site()
    for message in deriver.notes:
        note(message)
    try:
        site = vm.Site.model_validate(site.model_dump())
    except Exception as exc:  # the derivation broke the view model: a middleware bug
        return fail("The derived view model is invalid (a DGO Atlas bug; please report it):", [exc])
    say("  view model derived and valid")

    try:
        pages = content.load(project.content_dir)
        split_pages(pages)  # a content file clashing with a generated page fails here, before any output
    except content.ContentError as exc:
        return fail("Authored content failed to load:", [exc])
    if pages:
        say(f"  loaded {len(pages)} authored page(s)")

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    renderer = Renderer(out, project, site, pages)
    renderer.all()
    written = len(renderer.written)

    problems = linkcheck.check(out, project.config.base_path or "/")
    if problems:
        return fail(f"{len(problems)} broken internal link(s):", problems)

    say(f"\nBuilt {written} page(s) into {out} in {time.monotonic() - started:.1f}s", style="bold green")
    return 0


def load_project(start: Path) -> Project:
    from . import config

    return config.load(config.find(start))


__all__ = ["ConfigError", "build", "check", "load_project"]
