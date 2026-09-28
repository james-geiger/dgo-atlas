"""The command surface: its commands, their exit codes, and the Typer-only rule."""

import json
import re
from pathlib import Path

import rdflib
from rdflib.namespace import RDF, RDFS
from typer.testing import CliRunner

from dgo_site import dgo
from dgo_site.cli import app

runner = CliRunner()
SRC = Path(__file__).resolve().parents[1] / "src"


def dgo_site(*args):
    return runner.invoke(app, [str(a) for a in args])


def files_under(root: Path) -> set[Path]:
    return {p.relative_to(root) for p in root.rglob("*") if p.is_file()}


def test_help_lists_every_command():
    result = dgo_site("--help")
    assert result.exit_code == 0
    for command in ("init", "new", "validate", "build", "convert", "schema", "text", "linkcheck"):
        assert command in result.stdout, command
    assert "project" in dgo_site("new", "--help").stdout


def test_new_project_is_init(tmp_path):
    assert dgo_site("init", tmp_path / "a").exit_code == 0
    assert dgo_site("new", "project", tmp_path / "b").exit_code == 0
    assert files_under(tmp_path / "a") == files_under(tmp_path / "b")


def test_missing_project_is_a_configuration_problem(tmp_path):
    result = dgo_site("validate", "--project", tmp_path)
    assert result.exit_code == 1
    assert "Configuration problem" in result.stderr


def test_text_outside_a_project_shows_the_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = dgo_site("text", "count.term.")
    assert result.exit_code == 0
    assert "count.term.one:" in result.stdout


def test_linkcheck(tmp_path):
    assert dgo_site("linkcheck", tmp_path / "missing").exit_code == 1

    (tmp_path / "about.html").write_text("<p>About</p>")
    (tmp_path / "index.html").write_text('<a href="about.html">About</a>')
    result = dgo_site("linkcheck", tmp_path)
    assert result.exit_code == 0
    assert "All internal links resolve across 2 page(s)" in result.stdout

    (tmp_path / "index.html").write_text('<a href="gone.html">Gone</a>')
    result = dgo_site("linkcheck", tmp_path)
    assert result.exit_code == 1
    assert "gone.html" in result.stderr


def test_every_cli_is_typer():
    """No hand-rolled argument parsing: argparse, raw click, or sys.argv."""
    forbidden = re.compile(r"^\s*(import argparse|from argparse|import click|from click)|sys\.argv", re.MULTILINE)
    offenders = [str(p.relative_to(SRC)) for p in SRC.rglob("*.py") if forbidden.search(p.read_text())]
    assert offenders == [], "use Typer (see CLAUDE.md)"


def test_convert_passes_through_to_linkml_convert(tmp_path):
    variant = Path(__file__).parent / "fixtures" / "variant"
    ttl = tmp_path / "glossary.ttl"
    assert dgo_site("convert", "--project", variant, "-t", "ttl", "-o", ttl).exit_code == 0
    graph = rdflib.Graph().parse(ttl)
    term = rdflib.URIRef("https://w3id.org/dgo/data/indirect-cost")
    assert (term, RDF.type, rdflib.URIRef(dgo.kind("glossary term").iri)) in graph
    assert (term, RDFS.label, rdflib.Literal("indirect cost")) in graph  # prefixes from DGO expand

    result = dgo_site("convert", "--project", variant, "-t", "json")
    assert result.exit_code == 0
    assert json.loads(result.stdout)["glossary_terms"]

    assert dgo_site("convert", "--project", variant, "--no-such-option").exit_code == 2
