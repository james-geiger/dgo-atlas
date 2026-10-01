"""Each kind of object is minted in its own namespace under iri_base, and every page lives at its IRI."""

import json
import re

import pytest
import yaml

from dgo_atlas import config, dgo
from dgo_atlas.build import build
from dgo_atlas.config import ConfigError
from dgo_atlas.derive import Deriver
from dgo_atlas.namespaces import NamespaceError, Namespaces, defaults
from dgo_atlas.render import page_clashes

from .conftest import BASE, DGO_VERSION, FIXTURES, NS, OVERRIDES
from .test_validate import one


def pages_at_iris(site):
    return [p for group in (site.glossaries, site.domains, site.subject_areas, site.terms, site.councils,
                            site.agents, site.data_stores, site.data_sets, site.data_elements, site.local_classes,
                            site.redirects) for p in group or []]


# ---------------------------------------------------------------- defaults and overrides


def test_defaults_come_from_the_template():
    kinds = {k.kind: k for k in defaults()}
    assert (kinds["organization"].iri_segment, kinds["organization"].authoring_prefix) == ("organizations", "organization")
    assert kinds["process"].lists == ("processes", "lifecycle_processes")
    assert kinds["data"].lists == ("data_stores", "data_sets", "data_elements")
    assert kinds["classification"].lists == ("sensitivity_levels", "security_levels", "regulations")
    assert kinds["local_class"].authoring_prefix == "class"


def test_only_iri_base_is_needed():
    ns = Namespaces.build("https://w3id.org/acme")  # a missing trailing slash is added
    assert ns.expand("organization:abc") == "https://w3id.org/acme/organizations/abc"
    assert ns.page_path(ns.expand("organization:abc")) == "organizations/abc.html"


def test_segment_override_moves_iris_and_pages():
    ns = Namespaces.build(BASE, {"organization": {"iri_segment": "offices"}})
    iri = ns.expand("organization:spo")
    assert iri == BASE + "offices/spo"
    assert ns.page_path(iri) == "offices/spo.html"


def test_prefix_override_changes_only_the_canonical_curie():
    ns = Namespaces.build(BASE, {"organization": {"authoring_prefix": "office"}})
    assert ns.expand("office:spo") == BASE + "organizations/spo"
    assert ns.canonical(BASE + "organizations/spo") == "office:spo"
    assert ns.expand("organization:spo") is None  # no longer defined, unless declared as an alias
    aliased = Namespaces.build(BASE, {"organization": {"authoring_prefix": "office"}},
                               {"organization": BASE + "organizations/"})
    assert aliased.canonical("organization:spo") == "office:spo"


def test_both_overrides():
    ns = Namespaces.build(BASE, {"organization": {"iri_segment": "offices", "authoring_prefix": "office"}})
    assert ns.expand("office:spo") == BASE + "offices/spo"
    assert ns.for_list("organizations").authoring_prefix == "office"


def test_kinds_may_share_a_namespace_and_its_prefix():
    """An implementer whose councils and organizations were both minted under offices/."""
    shared = {"iri_segment": "offices", "authoring_prefix": "office"}
    ns = Namespaces.build(BASE, {"council": shared, "organization": shared})
    assert ns.expand("office:board") == BASE + "offices/board"
    assert ns.canonical(BASE + "offices/board") == "office:board"
    assert ns.problem("councils", "office:board") is None
    assert ns.problem("organizations", "office:spo") is None


def test_fragment_ids():
    ns = Namespaces.build(BASE)
    iri = ns.expand("classification:levels#high")
    assert iri == BASE + "classifications/levels#high"
    assert ns.page_path(iri) == "classifications/levels.html"
    assert ns.problem("sensitivity_levels", "classification:levels#high") is None
    assert "may use only letters" in ns.problem("sensitivity_levels", "classification:levels#a#b")


@pytest.mark.parametrize("overrides, declared, fragment", [
    ({"organization": {"iri_segment": "councils"}}, {}, "both use iri_segment 'councils'"),
    ({"organization": {"iri_segment": "councils", "authoring_prefix": "office"}}, {}, "must share both"),
    ({"organization": {"authoring_prefix": "term"}}, {}, "both use authoring_prefix 'term'"),
    ({"organization": {"iri_segment": "a/b"}}, {}, "must be one path segment"),
    ({"organization": {"iri_segment": "assets"}}, {}, "must be one path segment"),
    ({"organization": {"authoring_prefix": "dgo"}}, {}, "must be a name"),
    ({"office": {"iri_segment": "offices"}}, {}, "office is not a kind"),
    ({}, {"term": "https://example.org/terms/"}, "term is the authoring prefix for term ids"),
])
def test_bad_namespaces(overrides, declared, fragment):
    with pytest.raises(NamespaceError, match=fragment):
        Namespaces.build(BASE, overrides, declared)


def test_redefining_a_dgo_prefix_is_a_config_error(tmp_path):
    (tmp_path / config.CONFIG_NAME).write_text(yaml.safe_dump({
        "dgo_version": DGO_VERSION, "title": "T", "iri_base": "https://example.org/",
        "prefixes": {"org": "https://example.org/organizations/"}}))
    with pytest.raises(ConfigError, match="org is already DGO's prefix"):
        config.load(tmp_path / config.CONFIG_NAME)


def test_bad_namespaces_are_a_config_error(tmp_path):
    (tmp_path / config.CONFIG_NAME).write_text(yaml.safe_dump({
        "dgo_version": DGO_VERSION, "title": "T", "iri_base": "https://example.org/",
        "namespaces": {"organization": {"iri_segment": "councils"}}}))
    with pytest.raises(ConfigError, match="both use iri_segment"):
        config.load(tmp_path / config.CONFIG_NAME)


# ---------------------------------------------------------------- validation


def test_id_in_another_kinds_namespace(broken):
    report = broken(("id: organization:office-of-research", "id: person:office-of-research"))
    one(report, "id person:office-of-research (https://w3id.org/northfield/people/office-of-research) is not in "
                "the namespace for organization ids, https://w3id.org/northfield/organizations/; "
                "write it as organization:office-of-research")


def test_id_outside_iri_base(broken):
    report = broken(("id: organization:office-of-research", "id: https://example.org/office-of-research"))
    one(report, "is outside the namespace for organization ids")


def test_local_name_must_be_a_path(broken):
    report = broken(("id: organization:office-of-research", "id: organization:office of research"))
    one(report, "may use only letters, digits")


def test_alias_and_full_iri_are_the_same_object(variant):
    """governance.yaml declares office:cto (an alias) and sponsored-programs.yaml
    references the SPO by its full IRI; both are rewritten to organization:."""
    _, site = variant
    agents = {a.about: a for a in site.agents}
    assert "organization:cto" in agents and "office:cto" not in agents
    bearers = {r.bearer.about for t in site.terms for r in t.responsibilities or []}
    assert "organization:spo" in bearers
    assert all(not b.startswith("https://") for b in bearers)


def test_segment_override_invalidates_ids_minted_under_the_default(broken):
    """The segment is part of the IRI, so overriding it is not a rename."""
    ns = Namespaces.build(BASE, {**OVERRIDES, "organization": {"iri_segment": "offices"}}, dict(NS.declared))
    one(broken(ns=ns), "is not in the namespace for organization ids, https://w3id.org/northfield/offices/")


def test_prefix_override_keeps_iris_and_pages(broken):
    ns = Namespaces.build(BASE, {**OVERRIDES, "organization": {"authoring_prefix": "unit"}},
                          {**dict(NS.declared), "organization": BASE + "organizations/"})
    report = broken(ns=ns)
    assert report.ok, [str(e) for e in report.errors]
    site = Deriver(report.record, ns).site()
    cto = next(a for a in site.agents if a.label == "Clinical Trials Office")
    assert (cto.about, cto.iri, cto.url) == ("unit:cto", BASE + "organizations/cto", "organizations/cto.html")


# ---------------------------------------------------------------- pages


def test_every_page_is_at_its_iri(variant):
    _, site = variant
    for page in pages_at_iris(site):
        assert page.iri.startswith(BASE), page.about
        assert page.url == page.iri[len(BASE):] + ".html", page.about


def test_processes_redirect_to_where_they_are_shown(variant):
    _, site = variant
    redirects = {r.about: r for r in site.redirects}
    assert redirects["process:research-dg"].url == "processes/research-dg.html"
    assert redirects["process:research-dg"].target == "governance.html#research-dg"
    assert redirects["process:clinical-trial-creation"].target == "terms/clinical-trial.html#history"
    # clinical study is unpublished, so neither is its creation's IRI
    assert not any(r.target.startswith("terms/clinical-study.html") for r in site.redirects)
    assert {p.url for p in site.processes} >= {"governance.html#research-dg", "governance.html#northfield-dg"}


def test_data_pages_are_at_their_iris(variant):
    """Data stores, sets and elements share the data namespace; an element's id may nest under its set's."""
    _, site = variant
    assert next(s for s in site.data_sets if s.about == "data:warehouse-studies").url == "data/warehouse-studies.html"
    assert next(s for s in site.data_stores if s.about == "data:ctms").url == "data/ctms.html"
    nested = next(e for e in site.data_elements if e.about == "data:warehouse-studies/open-date")
    assert (nested.iri, nested.url) == (BASE + "data/warehouse-studies/open-date", "data/warehouse-studies/open-date.html")


def test_certifications_redirect_to_their_data_set(variant):
    _, site = variant
    redirects = {r.about: r for r in site.redirects}
    assert redirects["process:warehouse-studies-certification"].target == "data/warehouse-studies.html#history"


def test_fragment_iris_share_a_redirect(variant):
    """data:sensitivity#internal and its siblings are one document, data/sensitivity, whose
    page sends each fragment to its level's anchor on the classification page."""
    _, site = variant
    page = next(r for r in site.redirects if r.url == "data/sensitivity.html")
    assert page.iri == BASE + "data/sensitivity"
    assert page.target == "classification.html"
    assert {f.fragment: f.target for f in page.fragments}["internal"] == "classification.html#sensitivity-internal"
    level = next(lv for lv in site.classification_levels if lv.about == "data:sensitivity#internal")
    assert level.iri == BASE + "data/sensitivity#internal"


def test_local_class_pages(variant):
    _, site = variant
    classes = {c.about: c for c in site.local_classes}
    trustee = classes["class:DataTrustee"]
    assert trustee.url == "classes/DataTrustee.html"  # case is kept
    assert trustee.parent_label == "steward" and trustee.parent_url is None
    assert "term:indirect-cost" in {r.about for r in trustee.used_by}


def test_page_on_a_generated_path_is_refused(broken):
    report = broken(extra={"index.yaml": (
        "glossary_terms:\n"
        "  - id: term:index\n"
        "    label: index\n"
        "    definition: A term whose page would replace the list of terms.\n"
        "    part_of: glossary:business-glossary\n"
        "    in_subject_area: area:clinical-research\n"
        "term_creations:\n"
        "  - id: process:index-creation\n"
        "    label: Index creation\n"
        "    has_output: term:index\n"
        "    part_of: process:research-dg\n")})
    assert report.ok, [str(e) for e in report.errors]
    site = Deriver(report.record, NS).site()
    [problem] = page_clashes(site, [])
    assert problem.startswith("term:index (https://w3id.org/northfield/terms/index) would be published at "
                              "terms/index.html, which is already a generated page")


def test_built_site_serves_every_iri(tmp_path):
    project = config.load(FIXTURES / "variant" / config.CONFIG_NAME)
    assert build(project, out=tmp_path) == 0  # includes the link check
    assert (tmp_path / "organizations" / "cto.html").is_file()
    assert (tmp_path / "classes" / "DataTrustee.html").is_file()
    stub = (tmp_path / "processes" / "research-dg.html").read_text()
    assert 'content="0; url=../governance.html#research-dg"' in stub
    assert 'id="research-dg"' in (tmp_path / "governance.html").read_text()
    assert 'href="classes/DataTrustee.html"' in (tmp_path / "how-to-read-a-term.html").read_text()
    assert (tmp_path / "data" / "warehouse-studies.html").is_file()
    assert (tmp_path / "data" / "warehouse-studies" / "open-date.html").is_file()
    levels = (tmp_path / "data" / "sensitivity.html").read_text()
    assert '"classification.html#sensitivity-internal"' in levels
    assert 'id="sensitivity-internal"' in (tmp_path / "classification.html").read_text()


# ---------------------------------------------------------------- editor schema


def test_editor_schema_patterns_and_snippets():
    config.load(FIXTURES / "variant" / config.CONFIG_NAME)
    try:
        defs = json.loads(dgo.json_schema())["$defs"]
        org_id = defs["Organization"]["properties"]["id"]
        assert org_id["defaultSnippets"][0]["body"] == "organization:${1:name}"
        for good in ("organization:cto", "office:cto", BASE + "organizations/cto"):
            assert re.match(org_id["pattern"], good), good
        for bad in ("person:cto", BASE + "people/cto", "organization:c t o"):
            assert not re.match(org_id["pattern"], bad), bad
        subject_area = defs["GlossaryTerm"]["properties"]["in_subject_area"]
        assert re.match(subject_area["pattern"], "area:clinical-research")
        assert not re.match(subject_area["pattern"], "term:clinical-research")
    finally:
        dgo.use(dgo.source_for(DGO_VERSION))
