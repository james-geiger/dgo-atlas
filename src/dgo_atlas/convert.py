"""Export governance data through linkml-convert.

linkml-convert takes one input file, and a project's data is many. This
validates and merges the data, writes it to one temporary file, and runs
linkml-convert on it with the authoring template, the root class and the
project's prefixes. Every other argument is passed through unchanged, e.g.
`-t ttl -o glossary.ttl` for the objects as RDF individuals of DGO's classes.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import yaml

from . import dgo, validate
from .config import Project
from .console import fail
from .resources import ROOT_CLASS


def convert(project: Project, args: list[str]) -> int:
    """Run linkml-convert on the project's merged data; return its exit code."""
    from linkml.converter.cli import cli as linkml_convert

    report = validate.validate(project.data_dir, project.root, project.prefixes)
    if not report.ok:
        return fail("The governance data is not valid; run `dgo-atlas validate`:", report.errors)
    with tempfile.TemporaryDirectory(prefix="dgo-atlas-") as directory:
        merged = Path(directory) / "governance.yaml"
        merged.write_text(yaml.safe_dump(report.dataset.merged, sort_keys=False), encoding="utf-8")
        prefixes = [arg for name, uri in project.prefixes.items() for arg in ("-P", f"{name}={uri}")]
        try:
            linkml_convert.main([str(merged), "-s", str(dgo.template_path()), "-C", ROOT_CLASS, *prefixes, *args],
                                prog_name="linkml-convert")
        except SystemExit as exc:
            return exc.code if isinstance(exc.code, int) else 1
    return 0
