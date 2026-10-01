"""The validator: linkml-validate plus the checks it cannot make (handoff §6)."""

import pytest

from .conftest import FIXTURES


def messages(report):
    return [str(e) for e in report.errors]


def test_fixture_is_valid(broken):
    report = broken()
    assert report.ok, messages(report)
    assert report.record is not None


def one(report, fragment):
    found = [m for m in messages(report) if fragment in m]
    assert found, f"no error containing {fragment!r} in {messages(report)}"
    return found[0]


def test_semantic_type_needs_a_declared_prefix(broken):
    report = broken(("semantic_type: bfo:0000015", "semantic_type: obo:BFO_0000015"))
    assert "semantic_type: obo:BFO_0000015 does not use a declared prefix" in one(report, "semantic_type")


def test_semantic_type_as_full_iri(broken):
    report = broken(("semantic_type: bfo:0000015", "semantic_type: http://purl.obolibrary.org/obo/BFO_0000015"))
    assert report.ok, messages(report)


def test_unquoted_date(broken):
    report = broken(('occurred_on: "2026-09-25"', "occurred_on: 2026-09-25"))
    assert report.stage == "shape"
    msg = one(report, "unquoted date")
    assert "status_boundaries[0].occurred_on" in msg
    assert len(report.errors) == 1  # the linkml error on the same object is folded in


def test_yaml_boolean(broken):
    report = broken(("label: Morgan Ellis", "label: yes"))
    assert "people[0] (person:morgan-ellis).label" in one(report, "boolean")


def test_type_by_class_name_is_rewritten_to_the_curie(broken):
    """`type: approved` is DGO's class name; later stages, the site and exports see only the CURIE."""
    report = broken(("type: dgo:DGO_00000026           # approved\n    part_of: process:clinical-trial-creation",
                     "type: approved\n    part_of: process:clinical-trial-creation"),
                    ("type: dgo:DGO_00000025           # submitted for review",
                     "type: submitted for review"),
                    ("type: dgo:DGO_00000012       # owner\n        role_of: organization:cto",
                     "type: owner\n        role_of: organization:cto"))
    assert report.ok, messages(report)
    created = [b["type"] for b in report.dataset.merged["status_boundaries"]
               if b["part_of"] == "process:clinical-trial-creation"]
    assert created == ["dgo:DGO_00000024", "dgo:DGO_00000025", "dgo:DGO_00000026"]
    (trial,) = [t for t in report.dataset.merged["glossary_terms"] if t["id"] == "term:clinical-trial"]
    assert trial["responsibilities"][0]["type"] == "dgo:DGO_00000012"  # nested roles too
    loaded = [type(b).__name__ for b in report.record.status_boundaries if b.part_of == "process:clinical-trial-creation"]
    assert loaded == ["Drafted", "SubmittedForReview", "Approved"]


def test_role_types_by_class_name(broken):
    """Council roles and governance roles, top-level and in responsibilities, by DGO class name."""
    roles = "\n".join(f"  - type: {name}\n    role_of: person:morgan-ellis\n    realized_in: process:research-dg"
                      for name in ("council role", "compliance steward", "documentation steward",
                                   "ethics steward", "security steward"))
    report = broken(("type: dgo:DGO_00000006           # chair", "type: chair"),
                    ("type: dgo:DGO_00000013       # steward", "type: steward       #"),
                    extra={"roles.yaml": f"council_roles:\n{roles}\n"
                                         "governance_roles:\n"
                                         "  - type: custodian\n    role_of: organization:cto\n"
                                         "  - type: subject matter expert\n    role_of: person:jordan-price\n"})
    assert report.ok, messages(report)
    council = [type(r).__name__ for r in report.record.council_roles]
    assert sorted(council) == ["Chair", "ComplianceSteward", "CouncilRole", "DocumentationSteward",
                               "EthicsSteward", "SecuritySteward"]
    assert [type(r).__name__ for r in report.record.governance_roles] == ["Custodian", "SubjectMatterExpert"]
    (trial,) = [t for t in report.record.glossary_terms if t.id == "term:clinical-trial"]
    assert [r.type for r in trial.responsibilities] == ["dgo:DGO_00000012", "dgo:DGO_00000013"]


def test_class_name_of_another_kind_is_not_rewritten(broken):
    report = broken(("type: dgo:DGO_00000012       # owner", "type: drafted"))
    msg = one(report, "`type: drafted` is not a kind of governance role")
    assert "subject matter expert (dgo:DGO_00000015)" in msg


def test_other_readable_forms_get_the_class_name(broken):
    report = broken(("type: dgo:DGO_00000026           # approved\n    part_of: process:clinical-trial-creation",
                     "type: dgo:Approved\n    part_of: process:clinical-trial-creation"))
    assert "use approved (or dgo:DGO_00000026)" in one(report, "dgo:Approved")
    report = broken(("type: dgo:DGO_00000025           # submitted for review", "type: submitted_for_review"))
    assert "use submitted for review (or dgo:DGO_00000025)" in one(report, "submitted_for_review")


def test_unknown_type_lists_the_choices(broken):
    report = broken(("type: dgo:DGO_00000012       # owner", "type: dgo:DGO_00000024       # drafted"))
    msg = one(report, "is not a kind of governance role")
    assert "subject matter expert (dgo:DGO_00000015)" in msg


def test_unknown_field(broken):
    report = broken(("    definition: a study in which", "    status: approved\n    definition: a study in which"))
    one(report, "'status' was unexpected")


def test_dangling_reference(broken):
    report = broken(("      - term:clinical-study\n", "      - term:nowhere\n"))
    assert report.stage == "graph"
    one(report, "broader: term:nowhere is not defined anywhere")


def test_reference_to_wrong_kind(broken):
    report = broken(("role_of: person:morgan-ellis", "role_of: area:clinical-research"))
    one(report, "role_of: area:clinical-research is a subject area")


def test_reference_inside_responsibilities(broken):
    report = broken(("role_of: organization:cto", "role_of: glossary:business-glossary"))
    msg = one(report, "responsibilities[0]")
    assert "business glossary" in msg


def test_duplicate_id_across_files(broken):
    report = broken(extra={"more.yaml": "people:\n  - id: person:morgan-ellis\n    label: Someone else\n"})
    one(report, "id person:morgan-ellis is already defined at")


def test_undeclared_prefix(broken):
    report = broken(("id: office:cto", "id: foo:cto"), ("role_of: organization:cto", "role_of: foo:cto"))
    one(report, "foo:cto does not use a declared prefix")


def test_pref_label_must_differ_from_alt_labels(broken):
    report = broken(("pref_label: Clinical Trial ", "pref_label: interventional study "))
    one(report, "must differ from every alt label")


def test_broader_cycle(broken):
    report = broken(("    label: clinical study\n", "    label: clinical study\n    broader: [term:clinical-trial]\n"))
    one(report, "broader loops back")


def test_two_creations_of_one_term(broken):
    extra = ("lifecycle_processes:\n  - id: process:second-creation\n    type: creation\n    label: Again\n"
             "    has_output: term:clinical-trial\n    part_of: process:research-dg\n")
    report = broken(extra={"more.yaml": extra})
    one(report, "more than one creation")


def test_boundary_after_close(broken):
    extra = ("status_boundaries:\n  - type: dgo:DGO_00000025\n"
             "    part_of: process:clinical-trial-creation\n    occurred_on: \"2026-12-01\"\n")
    report = broken(extra={"more.yaml": extra})
    one(report, "after it closed on 2026-09-28")


def test_replaced_by_without_deprecation_warns(broken):
    report = broken(("    part_of: process:research-dg                # deprecated once",
                     "    part_of: process:research-dg\n    # deprecated once"),
                    (('  - type: dgo:DGO_00000026           # deprecation approved: the term is now deprecated\n'
                      '    part_of: process:clinical-investigation-deprecation\n    occurred_on: "2026-10-12"\n'), ""))
    assert report.ok, messages(report)
    assert any("no approved deprecation" in str(w) for w in report.warnings)


@pytest.mark.parametrize("text", ["- just\n- a list\n", "glossary_terms: [unclosed\n"])
def test_unreadable_file(broken, text):
    report = broken(extra={"bad.yaml": text})
    assert report.stage == "read"
    assert "bad.yaml" in messages(report)[0]


def test_former_process_lists_are_still_read(broken):
    """term_creations and the other former lists merge into lifecycle_processes, typed by the list."""
    text = (FIXTURES / "variant" / "governance" / "clinical-investigation-creation.yaml").read_text()
    old = text.replace("lifecycle_processes:", "term_creations:").replace("    type: creation\n", "")
    report = broken(extra={"clinical-investigation-creation.yaml": old})
    assert report.ok, messages(report)
    assert any("term_creations is now lifecycle_processes with `type: creation`" in str(w) for w in report.warnings)
    creation = next(p for p in report.record.lifecycle_processes if p.id == "process:clinical-investigation-creation")
    assert type(creation).__name__ == "Creation"


def test_process_of_something_the_site_does_not_show_warns(broken):
    extra = ("lifecycle_processes:\n  - id: process:area-creation\n    type: creation\n    label: Area\n"
             "    has_output: area:clinical-research\n    part_of: process:research-dg\n")
    report = broken(extra={"more.yaml": extra})
    assert report.ok, messages(report)
    assert any("the site shows only processes of glossary terms and data sets" in str(w) for w in report.warnings)
