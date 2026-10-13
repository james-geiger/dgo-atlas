"""Data management (DGO 0.2.0): stores, sets, elements, classification,
certification and lineage, from validation through to the export."""

import shutil
import urllib.request

import rdflib
from rdflib import RDF, URIRef

from dgo_atlas import config, dgo
from dgo_atlas.build import build

from .conftest import DGO_VERSION, FIXTURES
from .test_cli import dgo_atlas

DATA = "https://w3id.org/dgo/data/"
DGO = rdflib.Namespace("https://w3id.org/dgo/")
OBO = rdflib.Namespace("http://purl.obolibrary.org/obo/")
LINEAGE_QUERY = f"https://raw.githubusercontent.com/james-geiger/dgo/refs/tags/{DGO_VERSION}/docs/lineage.rq"


def page(pages, about):
    (found,) = [p for p in pages if p.about == about]
    return found


# ---------------------------------------------------------------- derivation


def test_foundational_and_lineage(variant):
    _, site = variant
    source = page(site.data_sets, "ex:ctms-protocols")
    assert source.foundational and not source.lineage
    assert [r.about for r in source.derived_sets] == ["ex:warehouse-studies"]
    dashboard = page(site.data_sets, "ex:study-dashboard")
    assert not dashboard.foundational
    # Foundational data at the top, branching down to the data set itself.
    (root,) = dashboard.lineage
    assert (root.about, root.certification) == ("ex:ctms-protocols", "foundational")
    (warehouse,) = root.below
    assert (warehouse.about, warehouse.certification) == ("ex:warehouse-studies", "certified")
    (current,) = warehouse.below
    assert current.about == "ex:study-dashboard" and current.current and not current.below


def test_domains_are_inferred_from_subject_areas(variant):
    _, site = variant
    s = page(site.data_sets, "ex:warehouse-studies")
    assert [a.label for a in s.subject_areas] == ["Clinical Research", "Sponsored Programs"]
    assert [d.label for d in s.domains] == ["Research"]
    research = page(site.domains, "ex:research")
    assert {r.about for r in research.data_sets} == {"ex:ctms-protocols", "ex:warehouse-studies", "ex:study-dashboard"}


def test_terms_flow_up_from_the_data(variant):
    _, site = variant
    assert [t.label for t in page(site.data_sets, "ex:warehouse-studies").informed_terms] == ["open study"]
    assert not page(site.data_sets, "ex:study-dashboard").informed_terms
    assert [t.label for t in page(site.data_elements, "ex:ctms-open-date").informed_terms] == ["open study"]
    (term,) = [t for t in site.terms if t.about == "ex:open-study"]
    assert [(g.data_set.label, [e.about for e in g.data_elements]) for g in term.informed_by] == [
        ("Research studies", ["ex:warehouse-open-date", "ex:warehouse-protocol-status"]),
        ("Trial management protocols", ["ex:ctms-open-date", "ex:ctms-protocol-status"]),
    ]


def test_certification(variant):
    deriver, site = variant
    certified = page(site.data_sets, "ex:warehouse-studies")
    assert (certified.certification, str(certified.certified_on)) == ("certified", "2026-10-20")
    assert [c.label for c in certified.certifying_councils] == ["Research Data Governance Committee"]
    assert [(str(h.occurred_on), h.boundary_kind) for h in certified.history] == [
        ("2026-10-14", "drafted"), ("2026-10-16", "submitted_for_review"), ("2026-10-20", "approved")]
    assert page(site.data_sets, "ex:study-dashboard").certification == "in_progress"
    # Derived from nothing and never certified: foundational, not "not certified".
    assert page(site.data_sets, "ex:ctms-protocols").certification == "foundational"
    council = page(site.councils, "ex:research-committee")
    # Listings put certified sets first.
    assert [r.about for r in council.certified_sets] == ["ex:warehouse-studies", "ex:study-dashboard"]
    assert council.certified_sets[0].certification == "certified"
    # Certifications never touch term state, and the term history stays the term's.
    assert "ex:warehouse-studies-certification" not in {h.process.about for t in site.terms for h in t.history or []}


def test_classification(variant):
    _, site = variant
    element = page(site.data_elements, "ex:ctms-open-date")
    assert (element.sensitivity.label, element.sensitivity.inherited) == ("Internal", None)
    assert (element.security_level.label, element.security_level.inherited) == ("Role-based", True)
    assert [(r.label, r.inherited) for r in element.regulatory_categories] == [("PHI (HIPAA)", True)]
    levels = [(lv.axis, lv.label, lv.severity) for lv in site.classification_levels]
    assert levels[:3] == [("sensitivity_level", "Public", 1), ("sensitivity_level", "Internal", 2),
                          ("sensitivity_level", "Confidential", 3)]
    assert [lv.label for lv in site.classification_levels if lv.axis == "regulatory_category"] == ["FERPA", "PHI (HIPAA)"]
    assert element.sensitivity.url == "classification.html#internal"


def test_responsibilities_on_data(variant):
    _, site = variant
    computing = page(site.agents, "ex:research-computing")
    assert [(r.role, r.subject.about) for r in computing.responsibilities] == [
        ("custodian", "ex:ctms"), ("custodian", "ex:warehouse")]
    price = page(site.agents, "ex:jordan-price")
    (r,) = price.responsibilities
    assert (r.role, r.subject.about, r.subject.data_set.label) == (
        "subject_matter_expert", "ex:warehouse-protocol-status", "Research studies")


# ---------------------------------------------------------------- validation


DERIVED = "    derived_from:\n      - ex:ctms-protocols\n"


def test_derived_from_must_not_loop(broken):
    loop = ("data_sets:\n  - id: ex:a\n    label: A\n    derived_from: [ex:b]\n"
            "  - id: ex:b\n    label: B\n    derived_from: [ex:a]\n")
    report = broken(extra={"loop.yaml": loop})
    assert any("derived_from loops back" in str(e) for e in report.errors), report.errors


def test_derived_from_keeps_kinds_apart(broken):
    extra = "data_sets:\n  - id: ex:a\n    label: A\n    derived_from: [ex:ctms-open-date]\n"
    report = broken(extra={"mixed.yaml": extra})
    assert any("a data set can only be derived from another data set" in str(e) for e in report.errors), report.errors


def test_certification_boundaries_follow_lifecycle_rules(broken):
    late = ('status_boundaries:\n  - type: drafted\n    part_of: ex:warehouse-studies-certification\n'
            '    occurred_on: "2026-11-01"\n')
    report = broken(extra={"late.yaml": late})
    assert any("status boundary after it closed on 2026-10-20" in str(e) for e in report.errors), report.errors


def test_severity_is_an_integer_and_element_warnings(broken):
    report = broken()
    assert report.ok, report.errors
    louder = ("data_elements:\n  - id: ex:loud\n    label: loud\n    part_of: ex:study-dashboard\n"
              "    sensitivity: ex:confidential\n")
    report = broken(extra={"loud.yaml": louder})
    assert report.ok
    assert any("more severe than its data set's" in str(w) for w in report.warnings)


def test_former_list_name_still_reads(broken):
    old = ('term_status_boundaries:\n  - type: approved\n    part_of: ex:indirect-cost-creation\n'
           '    occurred_on: "2026-09-30"\n')
    report = broken(extra={"old.yaml": old})
    assert report.ok, report.errors
    assert any("term_status_boundaries is now called status_boundaries" in str(w) for w in report.warnings)
    assert any(b["part_of"] == "ex:indirect-cost-creation" and b["occurred_on"] == "2026-09-30"
               for b in report.dataset.merged["status_boundaries"])


# ---------------------------------------------------------------- earlier releases


def test_older_release_still_builds(tmp_path):
    """A 0.1.1 project, with the former list name and no data, builds unchanged."""
    project_dir = tmp_path / "project"
    shutil.copytree(FIXTURES / "variant", project_dir, ignore=shutil.ignore_patterns(".dgo-atlas", "site"))
    (project_dir / "governance" / "data.yaml").unlink()
    cfg = project_dir / config.CONFIG_NAME
    cfg.write_text(cfg.read_text().replace('dgo_version: "0.2.0"', 'dgo_version: "0.1.1"'))
    for path in (project_dir / "governance").glob("*.yaml"):
        path.write_text(path.read_text().replace("\nstatus_boundaries:", "\nterm_status_boundaries:"))
    try:
        project = config.load(cfg)
        assert "data_sets" not in dgo.list_ranges() and not dgo.has_class("data set")
        result = build(project, out=tmp_path / "site")
        assert result == 0
        assert not (tmp_path / "site" / "data.html").exists()
        assert "Data sets" not in (tmp_path / "site" / "index.html").read_text()
    finally:
        dgo.use(dgo.source_for(DGO_VERSION))


# ---------------------------------------------------------------- export


def test_export_runs_the_dgo_lineage_query(tmp_path):
    """DGO's own lineage query, over our RDF export, agrees with the derived view."""
    ttl = tmp_path / "variant.ttl"
    assert dgo_atlas("convert", "--project", FIXTURES / "variant", "-t", "ttl", "-o", ttl).exit_code == 0
    graph = rdflib.Graph().parse(ttl)
    with urllib.request.urlopen(LINEAGE_QUERY, timeout=30) as response:
        query = response.read().decode()
    rows = sorted(({k: str(v) for k, v in row.asdict().items()} for row in graph.query(query)),
                  key=lambda r: r["sourceOfTruth"])
    assert [(r["certified"], r["certifiedOn"], r["setLabel"], r["sourceOfTruth"], r["stores"], r["domains"],
             r["terms"], r["sensitivity"], r["security"], r["regulatory"]) for r in rows] == [
        (DATA + "warehouse-studies", "2026-10-20", "Research studies", "false", "Research Data Warehouse",
         "Research", "open study", "Confidential", "Role-based", "PHI (HIPAA)"),
        (DATA + "warehouse-studies", "2026-10-20", "Trial management protocols", "true",
         "Clinical Trial Management System", "Research", "open study", "Confidential", "Role-based", "PHI (HIPAA)"),
    ]


def test_export_uses_the_0_2_0_iris(tmp_path):
    ttl = tmp_path / "variant.ttl"
    assert dgo_atlas("convert", "--project", FIXTURES / "variant", "-t", "ttl", "-o", ttl).exit_code == 0
    graph = rdflib.Graph().parse(ttl)
    predicates = set(graph.predicates())
    assert {DGO.DGO_00000045, DGO.DGO_00000046, DGO.DGO_00000047, DGO.DGO_00000048, DGO.DGO_00000044,
            DGO.DGO_00000050, DGO.DGO_00000051, OBO.RO_0010001} <= predicates
    dcterms = rdflib.Namespace("http://purl.org/dc/terms/")
    assert not {dcterms.source, dcterms.isReplacedBy} & predicates
    assert (URIRef(DATA + "ctms-protocols"), RDF.type, OBO.IAO_0001000) in graph
    assert (URIRef(DATA + "ctms-protocols"), RDF.type, OBO.IAO_0000100) not in graph
