"""DGO is imported by URL at the release a project names (dgo_version)."""

import json
import urllib.request

import pytest
import yaml

from dgo_site import config, dgo
from dgo_site.config import ConfigError
from dgo_site.resources import CONFIG_SCHEMA, TEMPLATE, VIEWMODEL

from .conftest import DGO_VERSION, FIXTURES


def test_release_url():
    source = dgo.source_for("0.1.0")
    assert source.location == "https://raw.githubusercontent.com/james-geiger/dgo/refs/tags/0.1.0/dist/dgo"
    assert source.tested


def test_template_imports_the_release():
    text = dgo.template_path().read_text()
    assert f"- https://raw.githubusercontent.com/james-geiger/dgo/refs/tags/{DGO_VERSION}/dist/dgo\n" in text
    assert dgo.IMPORT_PLACEHOLDER not in text


def test_model_generated_at_runtime():
    m = dgo.model()
    assert {"GovernanceRecord", "GlossaryTerm", "Drafted", "Owner", "TermDeprecation"} <= set(dir(m))


def test_json_schema_for_editors():
    assert '"GlossaryTerm"' in dgo.json_schema()


def test_editor_schema_accepts_type_by_class_name():
    defs = json.loads(dgo.json_schema())["$defs"]
    assert defs["Approved"]["properties"]["type"]["enum"] == ["dgo:DGO_00000026", "approved"]
    assert defs["SubmittedForReview"]["properties"]["type"]["enum"] == ["dgo:DGO_00000025", "submitted for review"]


def test_local_source_override(tmp_path):
    """dgo_source points at a local copy, relative to dgo-site.yaml (offline builds)."""
    url = dgo.source_for(DGO_VERSION).location + ".yaml"
    with urllib.request.urlopen(url, timeout=30) as response:
        (tmp_path / "dgo.yaml").write_bytes(response.read())
    project = _project(tmp_path, dgo_version=DGO_VERSION, dgo_source="dgo.yaml")
    try:
        assert project.dgo.location == str(tmp_path / "dgo")
        assert dgo.active() == project.dgo
        assert "glossary term" in dgo.view().all_classes()
    finally:
        dgo.use(dgo.source_for(DGO_VERSION))


def test_unknown_release_is_a_clear_config_error(tmp_path):
    with pytest.raises(ConfigError, match=r"not found at .*/refs/tags/9\.9\.9/dist/dgo\.yaml.*release tag"):
        _project(tmp_path, dgo_version="9.9.9")
    assert dgo.active().version == DGO_VERSION  # the active release is unchanged


def test_release_missing_classes_is_rejected(tmp_path):
    source = tmp_path / "old-dgo.yaml"
    source.write_text("id: https://example.org/old\nname: old\nimports: [linkml:types]\n"
                      "prefixes: {linkml: https://w3id.org/linkml/}\nclasses:\n  person: {}\n")
    with pytest.raises(ConfigError, match="missing classes dgo-site depends on"):
        _project(tmp_path, dgo_version="0.0.1", dgo_source="old-dgo.yaml")
    assert dgo.active().version == DGO_VERSION


def test_dgo_version_is_required(tmp_path):
    with pytest.raises(ConfigError, match="dgo_version"):
        _project(tmp_path)


def test_fixture_names_the_release():
    raw = yaml.safe_load((FIXTURES / "variant" / config.CONFIG_NAME).read_text())
    assert raw["dgo_version"] == DGO_VERSION


def test_no_dgo_namespace_minted_by_the_middleware():
    """The middleware's own schemas use their own namespace, never dgo: (handoff §3.1)."""
    for schema in (TEMPLATE, VIEWMODEL, CONFIG_SCHEMA):
        doc = yaml.safe_load(schema.read_text())
        assert doc["id"].startswith("https://w3id.org/dgo-site/")
        for kind in ("classes", "slots"):
            for name, spec in (doc.get(kind) or {}).items():
                uri = (spec or {}).get("class_uri") or (spec or {}).get("slot_uri") or ""
                assert not uri.startswith("dgo:"), f"{schema.name}: {name} is minted in dgo:"


def _project(root, **settings):
    body = {"title": "T", "prefixes": {"ex": "https://example.org/"}, **settings}
    path = root / config.CONFIG_NAME
    path.write_text(yaml.safe_dump(body))
    return config.load(path)
