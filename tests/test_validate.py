"""The validator: linkml-validate plus the checks it cannot make (handoff §6)."""

import pytest


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


def test_unquoted_date(broken):
    report = broken(('occurred_on: "2026-09-25"', "occurred_on: 2026-09-25"))
    assert report.stage == "shape"
    msg = one(report, "unquoted date")
    assert "term_status_boundaries[0].occurred_on" in msg
    assert len(report.errors) == 1  # the linkml error on the same object is folded in


def test_yaml_boolean(broken):
    report = broken(("label: Morgan Ellis", "label: yes"))
    assert "people[0] (ex:morgan-ellis).label" in one(report, "boolean")


def test_readable_type_is_rejected_with_the_iri_to_use(broken):
    report = broken(("type: dgo:DGO_00000026           # approved\n    part_of: ex:clinical-trial-creation",
                     "type: dgo:Approved\n    part_of: ex:clinical-trial-creation"))
    assert "use dgo:DGO_00000026 (approved)" in one(report, "dgo:Approved")


def test_unknown_type_lists_the_choices(broken):
    report = broken(("type: dgo:DGO_00000012       # owner", "type: dgo:DGO_00000024       # drafted"))
    msg = one(report, "is not a kind of governance role")
    assert "dgo:DGO_00000015 (subject matter expert)" in msg


def test_unknown_field(broken):
    report = broken(("    definition: a study in which", "    status: approved\n    definition: a study in which"))
    one(report, "'status' was unexpected")


def test_dangling_reference(broken):
    report = broken(("      - ex:clinical-study\n", "      - ex:nowhere\n"))
    assert report.stage == "graph"
    one(report, "broader: ex:nowhere is not defined anywhere")


def test_reference_to_wrong_kind(broken):
    report = broken(("role_of: ex:morgan-ellis", "role_of: ex:clinical-research"))
    one(report, "role_of: ex:clinical-research is a subject area")


def test_reference_inside_responsibilities(broken):
    report = broken(("role_of: ex:cto", "role_of: ex:business-glossary"))
    msg = one(report, "responsibilities[0]")
    assert "business glossary" in msg


def test_duplicate_id_across_files(broken):
    report = broken(extra={"more.yaml": "people:\n  - id: ex:morgan-ellis\n    label: Someone else\n"})
    one(report, "id ex:morgan-ellis is already defined at")


def test_undeclared_prefix(broken):
    report = broken(("id: ex:cto", "id: foo:cto"), ("role_of: ex:cto", "role_of: foo:cto"))
    one(report, "foo:cto does not use a declared prefix")


def test_pref_label_must_differ_from_alt_labels(broken):
    report = broken(("pref_label: Clinical Trial ", "pref_label: interventional study "))
    one(report, "must differ from every alt label")


def test_broader_cycle(broken):
    report = broken(("    label: clinical study\n", "    label: clinical study\n    broader: [ex:clinical-trial]\n"))
    one(report, "broader loops back")


def test_two_creations_of_one_term(broken):
    extra = ("term_creations:\n  - id: ex:second-creation\n    label: Again\n"
             "    has_output: ex:clinical-trial\n    part_of: ex:research-dg\n")
    report = broken(extra={"more.yaml": extra})
    one(report, "more than one term creation")


def test_boundary_after_close(broken):
    extra = ("term_status_boundaries:\n  - type: dgo:DGO_00000025\n"
             "    part_of: ex:clinical-trial-creation\n    occurred_on: \"2026-12-01\"\n")
    report = broken(extra={"more.yaml": extra})
    one(report, "after it closed on 2026-09-28")


def test_replaced_by_without_deprecation_warns(broken):
    report = broken(("    part_of: ex:research-dg                # deprecated once",
                     "    part_of: ex:research-dg\n    # deprecated once"),
                    (('  - type: dgo:DGO_00000026           # deprecation approved: the term is now deprecated\n'
                      '    part_of: ex:clinical-investigation-deprecation\n    occurred_on: "2026-10-12"\n'), ""))
    assert report.ok, messages(report)
    assert any("no approved term deprecation" in str(w) for w in report.warnings)


@pytest.mark.parametrize("text", ["- just\n- a list\n", "glossary_terms: [unclosed\n"])
def test_unreadable_file(broken, text):
    report = broken(extra={"bad.yaml": text})
    assert report.stage == "read"
    assert "bad.yaml" in messages(report)[0]
