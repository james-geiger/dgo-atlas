"""Local classes: an implementer's own subclasses of DGO classes."""

import json
import subprocess
from pathlib import Path

import pytest
import rdflib
from rdflib.namespace import RDF
from typer.testing import CliRunner

from dgo_atlas import config, dgo
from dgo_atlas.cli import app

from .conftest import EX, FIXTURES

runner = CliRunner()
VARIANT = FIXTURES / "variant"
EXN = rdflib.Namespace(EX["ex"])


def dgo_atlas(*args):
    return runner.invoke(app, [str(a) for a in args])


def messages(report):
    return [str(e) for e in report.errors]


@pytest.fixture
def variant_active():
    """The variant's release and local classes, active whatever ran before."""
    config.load(VARIANT / config.CONFIG_NAME)


def local(extra: str) -> dict:
    """A second local-classes file for the `broken` fixture."""
    return {"more-local-classes.yaml": "local_classes:\n" + extra}


# ---------------------------------------------------------------- resolution


def test_readable_name_resolves_to_the_local_curie(broken):
    report = broken()
    assert report.ok, messages(report)
    roles = [r["type"] for t in report.dataset.merged["glossary_terms"] for r in t.get("responsibilities") or []]
    assert "ex:DataTrustee" in roles


def test_local_class_is_a_subclass_in_the_model(variant_active):
    model = dgo.model()
    assert issubclass(model.DataTrustee, model.Steward)
    assert issubclass(model.ApprovedWithConditions, model.Approved)
    trustee = dgo.kind("data trustee")
    assert (trustee.local, trustee.dgo_ancestor, trustee.curie) == (True, "steward", "ex:DataTrustee")
    assert not dgo.kind("steward").local


def test_local_class_counts_as_its_dgo_ancestor(variant):
    deriver, site = variant
    # Its creation closed with "approved with conditions": still deprecated, not open.
    assert deriver.states["ex:clinical-investigation"] == "deprecated"
    (term,) = [t for t in site.terms if t.about == "ex:indirect-cost"]
    (trustee,) = [r for r in term.responsibilities if r.role_label == "data trustee"]
    assert trustee.role == "steward"  # DGO's slug, for styling and rules
    assert trustee.role_iri == EX["ex"] + "DataTrustee"


def test_editor_schema_lists_the_local_kind(variant_active):
    schema = dgo.json_schema()
    assert "ex:DataTrustee" in schema and "data trustee" in schema


def test_typed_bases_come_from_the_release():
    assert set(dgo.typed_bases()) == {"governance role", "council role", "status boundary"}


def test_local_class_of_a_local_class(broken):
    report = broken(extra=local("  - {id: ex:LeadTrustee, name: lead trustee, is_a: data trustee}\n"))
    assert report.ok, messages(report)
    assert dgo.kind("lead trustee").dgo_ancestor == "steward"


def test_untyped_parent_warns(broken):
    report = broken(extra=local("  - {id: ex:KeyTerm, name: key term, is_a: glossary term}\n"))
    assert report.ok, messages(report)
    assert any("no `type` field" in str(w) for w in report.warnings)


# ---------------------------------------------------------------- problems


def test_unknown_parent(broken):
    report = broken(extra=local("  - {id: ex:X, name: x, is_a: nonsense}\n"))
    assert report.stage == "read"
    assert any("more-local-classes.yaml: local_classes[0] (ex:X): is_a: nonsense is not" in m
               for m in messages(report))


def test_name_clashes_with_dgo(broken):
    report = broken(extra=local("  - {id: ex:Owner, name: owner, is_a: steward}\n"))
    assert any("name 'owner' is already a DGO class" in m for m in messages(report))


def test_id_in_dgo_namespace(broken):
    report = broken(extra=local("  - {id: dgo:Mine, name: mine, is_a: steward}\n"))
    assert any("more-local-classes.yaml" in m and "DGO's or DGO Atlas's namespace" in m for m in messages(report))


def test_cycle(broken):
    report = broken(extra=local("  - {id: ex:A, name: a, is_a: b}\n  - {id: ex:B, name: b, is_a: a}\n"))
    assert any("is_a loops back to 'a'" in m for m in messages(report))


def test_no_local_classes_leaves_the_release_as_is(broken):
    data = VARIANT / "governance"
    plain = {name: (data / name).read_text().replace(f"type: {local}", f"type: {parent}")
             for name, local, parent in (("sponsored-programs.yaml", "data trustee", "steward"),
                                         ("clinical-investigation-creation.yaml", "approved with conditions",
                                          "approved"))}
    report = broken(extra=plain, drop=["local-classes.yaml"])
    assert report.ok, messages(report)
    assert dgo.active().local_classes == ()


# ---------------------------------------------------------------- export


def test_convert_keeps_local_types(tmp_path):
    out = tmp_path / "g.json"
    assert dgo_atlas("convert", "--project", VARIANT, "-t", "json", "-o", out).exit_code == 0
    assert "ex:DataTrustee" in out.read_text()
    ttl = tmp_path / "g.ttl"
    assert dgo_atlas("convert", "--project", VARIANT, "-t", "ttl", "-o", ttl).exit_code == 0
    graph = rdflib.Graph().parse(ttl)
    assert (None, RDF.type, EXN.DataTrustee) in graph


def test_export_schema(tmp_path):
    full, only = tmp_path / "full.yaml", tmp_path / "local.yaml"
    assert dgo_atlas("export-schema", "--project", VARIANT, "-o", full).exit_code == 0
    assert dgo_atlas("export-schema", "--project", VARIANT, "--local-only", "-o", only).exit_code == 0
    assert "\nimports:" not in full.read_text()  # self-contained: DGO and the local classes merged in
    assert "source_file" not in full.read_text()
    for schema in (full, only):
        owl = subprocess.run(["gen-owl", "--no-use-native-uris", str(schema)], capture_output=True, text=True)
        assert owl.returncode == 0, owl.stderr
        graph = rdflib.Graph().parse(data=owl.stdout, format="turtle")
        parent = rdflib.URIRef(dgo.kind("steward").iri)
        assert (EXN.DataTrustee, rdflib.RDFS.subClassOf, parent) in graph, schema.name


def test_export_schema_to_stdout():
    result = dgo_atlas("export-schema", "--project", VARIANT, "--local-only")
    assert result.exit_code == 0
    assert "class_uri: ex:DataTrustee" in result.stdout


def test_export_local_only_without_local_classes(tmp_path):
    assert dgo_atlas("init", tmp_path).exit_code == 0
    result = dgo_atlas("export-schema", "--project", tmp_path, "--local-only")
    assert result.exit_code == 1
    assert "no local classes" in result.stderr


# ---------------------------------------------------------------- scaffold


def test_new_local_class(tmp_path):
    assert dgo_atlas("init", tmp_path).exit_code == 0
    result = dgo_atlas("new", "local-class", "high risk", "--is-a", "steward", "--project", tmp_path)
    assert result.exit_code == 0, result.output
    created = tmp_path / "governance" / "local-classes" / "high-risk.yaml"
    assert "is_a: steward" in created.read_text()
    assert dgo_atlas("validate", "--project", tmp_path).exit_code == 0
    assert "high risk" in dgo.named_types("governance role")
    # Once it exists, it can be a parent, and the same name can't be added twice.
    assert dgo_atlas("new", "local-class", "higher risk", "--is-a", "high risk", "--project", tmp_path).exit_code == 0
    assert dgo_atlas("new", "local-class", "high risk", "--is-a", "steward", "--project", tmp_path).exit_code == 1


def test_new_local_class_unknown_parent(tmp_path):
    assert dgo_atlas("init", tmp_path).exit_code == 0
    result = dgo_atlas("new", "local-class", "x", "--is-a", "nonsense", "--project", tmp_path)
    assert result.exit_code == 1
    assert "is not a DGO class" in result.stderr
    assert not (tmp_path / "governance" / "local-classes").exists()
