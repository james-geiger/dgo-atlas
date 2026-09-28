"""Page facts on the variant fixture, and which terms are published.

The variant is the handoff's example (Appendix C and its §5.3 variant) plus:
a recorded creation for "clinical investigation", so the deprecated term is
published; and two terms still in creation ("direct cost" in review,
"indirect cost" drafted). "clinical study" has no creation, so it is derived
as unrecorded and left out.
"""

from linkml.validator import validate as linkml_validate

from dgo_site.derive import Deriver, related
from dgo_site.resources import VIEWMODEL
from dgo_site.semantic import ClassInfo

from .conftest import EX


def term(site, label):
    return next(t for t in site.terms if t.label == label or t.name == label)


def enum(value):
    return getattr(value, "value", value)


def history(t):
    return [(str(h.occurred_on), enum(h.process_kind), enum(h.boundary_kind)) for h in t.history or []]


# ---------------------------------------------------------------- states


def test_states(variant):
    deriver, _ = variant
    assert deriver.states == {
        "ex:clinical-trial": "approved",
        "ex:clinical-study": "unrecorded",
        "ex:clinical-investigation": "deprecated",
        "ex:direct-cost": "proposed",
        "ex:indirect-cost": "proposed",
    }


def test_clinical_trial(variant):
    _, site = variant
    t = term(site, "clinical trial")
    assert t.label == "Clinical Trial"  # pref_label is the display label
    assert enum(t.state) == "approved"
    assert [(r.role, r.bearer.label) for r in t.responsibilities] == [
        ("owner", "Clinical Trials Office"),
        ("steward", "Research Data Governance Committee"),
    ]
    assert [c.label for c in t.governing_councils] == ["Research Data Governance Committee"]
    assert history(t) == [
        ("2026-09-25", "term_creation", "drafted"),
        ("2026-09-27", "term_creation", "submitted_for_review"),
        ("2026-09-28", "term_creation", "approved"),
        ("2026-10-05", "term_modification", "drafted"),
        ("2026-10-12", "term_modification", "approved"),
        ("2026-11-01", "term_modification", "drafted"),
        ("2026-11-02", "term_modification", "submitted_for_review"),
        ("2026-11-03", "term_modification", "drafted"),
        ("2026-11-03", "term_modification", "rejected"),
    ]
    assert t.glossary.label == "Business Glossary"
    assert t.subject_area.label == "Clinical Research"
    assert t.domain.label == "Research"
    assert t.definition_source.iri == "https://grants.nih.gov/policy/clinical-trials/definition.htm"
    assert [p.label for p in t.predecessors] == ["clinical investigation"]


def test_clinical_investigation(variant):
    _, site = variant
    t = term(site, "clinical investigation")
    assert enum(t.state) == "deprecated"
    assert not t.pending_changes
    assert t.successor.label == "Clinical Trial"
    assert history(t)[0] == ("2024-03-04", "term_creation", "drafted")


def test_council_seats(variant):
    _, site = variant
    (council,) = site.councils
    assert council.label == "Research Data Governance Committee"
    assert [(s.member.label, [r.role for r in s.council_roles]) for s in council.members] == [
        ("Morgan Ellis", ["chair"])
    ]
    assert [p.label for p in council.process_chain] == [
        "Research Data Governance",
        "Data Governance at Northfield University",
    ]
    assert [t.label for t in council.governed_terms] == [
        "clinical investigation", "Clinical Trial", "Direct Cost", "Indirect Cost"]
    assert [(a.subject_area.label, a.term_count, [r.role for r in a.roles or []])
            for a in council.governed_areas] == [
        ("Clinical Research", 2, ["steward"]), ("Sponsored Programs", 2, ["steward"])]
    (member,) = [a for a in site.agents if a.label == "Morgan Ellis"]
    assert [s.council.label for s in member.memberships] == [council.label]
    assert member.job_title == "Director, Data Governance"


def agent(site, label):
    return next(a for a in site.agents if a.label == label)


def test_organization_members(variant):
    """has_member on organizations (DGO v0.1.1): members listed, and read back as member_of."""
    _, site = variant
    assert [m.label for m in agent(site, "Office of Research").organization_members] == [
        "Clinical Trials Office", "Sponsored Programs Office"]
    cto = agent(site, "Clinical Trials Office")
    assert [m.label for m in cto.organization_members] == ["Jordan Price"]
    assert [o.label for o in cto.member_of] == ["Office of Research"]
    assert [o.label for o in agent(site, "Jordan Price").member_of] == ["Clinical Trials Office"]
    assert not agent(site, "Morgan Ellis").member_of


def test_semantic_type_described_by_its_class(variant):
    deriver, _ = variant
    looked_up = []

    def describe(iri):
        looked_up.append(iri)
        return ClassInfo(iri=iri, label="process", ontology="BFO")

    d = Deriver(deriver.rec, EX, describe=describe)
    st = term(d.site(), "clinical trial").semantic_type
    assert looked_up == ["http://purl.obolibrary.org/obo/BFO_0000015"]
    assert (st.about, st.iri, st.label, st.ontology) == (
        "bfo:0000015", "http://purl.obolibrary.org/obo/BFO_0000015", "process", "BFO")
    assert not any("could not be looked up" in n for n in d.notes)


def test_semantic_type_that_cannot_be_looked_up_keeps_its_iri(variant):
    deriver, site = variant  # no describe: nothing is looked up
    st = term(site, "clinical trial").semantic_type
    assert (st.about, st.iri, st.label) == ("bfo:0000015", "http://purl.obolibrary.org/obo/BFO_0000015", None)
    assert "ex:clinical-trial: semantic_type bfo:0000015 could not be looked up, so only its IRI is shown" \
        in deriver.notes


def test_variant_stays_approved_with_one_pending_change(variant):
    _, site = variant
    t = term(site, "clinical trial")
    assert enum(t.state) == "approved"
    assert [enum(c.process_kind) for c in t.pending_changes] == ["term_modification"]
    assert t.pending_changes[0].about == "ex:clinical-trial-modification-2"


def test_variant_rejected_change_only_in_history(variant):
    _, site = variant
    t = term(site, "clinical trial")
    assert history(t)[-2:] == [
        ("2026-11-03", "term_modification", "drafted"),
        ("2026-11-03", "term_modification", "rejected"),
    ]
    assert "ex:clinical-trial-modification-3" not in [c.about for c in t.pending_changes]


def test_variant_terms_in_review_and_drafted(variant):
    """sponsored-programs.yaml: one creation submitted for review, one only drafted."""
    _, site = variant
    direct, indirect = term(site, "direct cost"), term(site, "indirect cost")
    assert enum(direct.state) == enum(indirect.state) == "proposed"
    assert history(direct)[-1] == ("2026-09-17", "term_creation", "submitted_for_review")
    assert history(indirect) == [("2026-09-20", "term_creation", "drafted")]
    assert direct.subject_area.label == "Sponsored Programs" and direct.domain.label == "Research"
    assert [r.label for r in direct.related] == ["Indirect Cost"]  # written once, on indirect cost


def test_variant_related_read_both_ways(variant):
    deriver, _ = variant
    trial, study = (deriver.idx[i] for i in ("ex:clinical-trial", "ex:clinical-study"))
    assert related(deriver.rec, trial) == ["ex:clinical-study"]
    assert related(deriver.rec, study) == ["ex:clinical-trial"]


# ---------------------------------------------------------------- publication


def test_unrecorded_term_is_not_published(variant):
    deriver, site = variant
    assert "clinical study" not in [t.label for t in site.terms]
    assert "ex:clinical-study is not published: no term creation is recorded for it" in deriver.notes


def test_links_to_unpublished_terms_are_left_off(variant):
    deriver, site = variant
    t = term(site, "clinical trial")
    assert not t.broader and not t.ancestors and not t.related
    assert "ex:clinical-trial: broader ex:clinical-study is not published, so the link is left off" in deriver.notes
    assert [a.label for a in site.subject_areas[0].terms] == ["clinical investigation", "Clinical Trial"]


def _creation(term_id, *boundaries):
    lines = ["term_creations:", f"  - id: {term_id}-creation", "    label: Creation",
             f"    has_output: {term_id}", "    part_of: ex:research-dg"]
    if boundaries:
        lines.append("term_status_boundaries:")
        for kind, date in boundaries:
            lines += [f"  - type: {kind}", f"    part_of: {term_id}-creation", f'    occurred_on: "{date}"']
    return "\n".join(lines) + "\n"


def _derive(broken, extra, drop=()):
    report = broken(extra={"extra.yaml": extra}, drop=drop)
    assert report.ok, [str(e) for e in report.errors]
    deriver = Deriver(report.record, EX)
    return deriver, {t.about: enum(t.state) for t in deriver.site().terms}


def test_creation_straight_to_approved_is_published(broken):
    _, states = _derive(broken, _creation("ex:clinical-study", ("dgo:DGO_00000026", "2026-01-01")))
    assert states["ex:clinical-study"] == "approved"


def test_creation_without_boundaries_is_published_as_proposed(broken):
    _, states = _derive(broken, _creation("ex:clinical-study"))
    assert states["ex:clinical-study"] == "proposed"


def test_rejected_creation_is_not_published(broken):
    deriver, states = _derive(broken, _creation("ex:clinical-study", ("dgo:DGO_00000024", "2026-01-01"),
                                                ("dgo:DGO_00000027", "2026-01-02")))
    assert "ex:clinical-study" not in states
    assert "ex:clinical-study is not published: its term creation was rejected" in deriver.notes


def test_deprecated_without_creation_is_not_published(broken):
    """Without its recorded creation, clinical investigation has a deprecation but no creation."""
    deriver, states = _derive(broken, "", drop=["clinical-investigation-creation.yaml"])
    assert deriver.states["ex:clinical-investigation"] == "deprecated"
    assert "ex:clinical-investigation" not in states


# ---------------------------------------------------------------- view model


def test_view_model_validates_against_its_schema(variant):
    """The derivation's output is valid against schema/viewmodel.yaml, checked by LinkML itself."""
    _, site = variant
    data = site.model_dump(mode="json", exclude_none=True)
    report = linkml_validate(data, str(VIEWMODEL), "Site")
    assert not report.results, [r.message for r in report.results]
