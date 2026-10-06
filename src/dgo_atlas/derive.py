"""Derive page facts from validated governance data (handoff §5, Appendix A).

The input is a GovernanceRecord loaded through the generated pydantic model,
so `type` has already resolved each role and status boundary to its subclass
and kinds are isinstance checks. A local class counts as its DGO ancestor
(dgo.dgo_kind): its slug, and the rules, are DGO's; its name and IRI its own. The output is a view-model `Site`: every
page's facts, derived and denormalised, ready to render. Governance data never
stores these facts; the view model always does.

Only published terms reach the site (see `unpublished_reason`): a term exists
once a term creation is recorded for it, unless that creation was rejected.
Links from a published term to an unpublished one are left off, and each
omission is recorded in `Deriver.notes` for the build to report.

The derivation does no I/O of its own. What a term's semantic type refers to
is read through `describe` (semantic.describe in a build); without it, a
semantic type keeps only its IRI.
"""

from __future__ import annotations

import re
from collections import defaultdict

from collections.abc import Callable

from . import dgo
from .models import viewmodel as vm
from .semantic import ClassInfo


class _ActiveModel:
    """The pydantic classes generated for the active DGO release (`m.Drafted`, ...)."""

    def __getattr__(self, name):
        return getattr(dgo.model(), name)


m = _ActiveModel()

# Same-day tie-break for status boundaries: drafted < submitted < approved/rejected.
BOUNDARY_ORDER = {"Drafted": 0, "SubmittedForReview": 1, "Approved": 2, "Rejected": 2}
PROCESS_ORDER = {"TermCreation": 0, "TermModification": 1, "TermDeprecation": 2}

# Where each kind of page lives.
DIRS = {
    "glossary": "glossaries",
    "domain": "domains",
    "subject_area": "areas",
    "term": "terms",
    "council": "councils",
    "person": "people",
    "organization": "organizations",
}
PROCESS_PAGE = "governance.html"


class Namespaces:
    """Expands CURIEs with the implementer's prefixes (and dgo:)."""

    def __init__(self, prefixes: dict[str, str]):
        self.prefixes = {"dgo": dgo.DGO_NAMESPACE, **prefixes}

    def expand(self, value: str) -> str:
        if value.startswith(("http://", "https://")):
            return value
        prefix, _, local = value.partition(":")
        return self.prefixes.get(prefix, "") + local


def _slug(value: str) -> str:
    local = re.split(r"[:/#]", value.rstrip("/"))[-1]
    return re.sub(r"[^a-z0-9]+", "-", local.lower()).strip("-") or "item"


class Deriver:
    def __init__(self, rec: m.GovernanceRecord, prefixes: dict[str, str], *,
                 sources: dict[str, str] | None = None, accents: dict[str, str] | None = None,
                 describe: Callable[[str], ClassInfo] | None = None):
        self.rec = rec
        self.ns = Namespaces(prefixes)
        self.sources = sources or {}
        self.accents = accents or {}
        self.describe = describe or (lambda iri: ClassInfo(iri=iri))
        self.idx = index(rec)
        self.urls: dict[str, str] = {}
        self._assign_urls()

        self.terms = list(rec.glossary_terms or [])
        self.processes_by_term: dict[str, list[m.TermLifecycleProcess]] = defaultdict(list)
        for obj in self.idx.values():
            if isinstance(obj, m.TermLifecycleProcess):
                self.processes_by_term[obj.has_output].append(obj)
        self.boundaries_by_process: dict[str, list[m.StatusBoundary]] = defaultdict(list)
        for b in rec.term_status_boundaries or []:
            self.boundaries_by_process[b.part_of].append(b)
        for bs in self.boundaries_by_process.values():
            bs.sort(key=lambda b: (str(b.occurred_on), BOUNDARY_ORDER[dgo.dgo_kind(b).model_class]))
        self.states = {t.id: term_state(self, t.id) for t in self.terms}
        self.notes: list[str] = []
        self.published: set[str] = set()
        for t in self.terms:
            reason = unpublished_reason(self, t.id)
            if reason:
                self.notes.append(f"{t.id} is not published: {reason}")
            else:
                self.published.add(t.id)
        self.terms = [t for t in self.terms if t.id in self.published]

    # ------------------------------------------------------------ urls and refs

    def _assign_urls(self) -> None:
        groups = [
            ("glossary", self.rec.business_glossaries),
            ("domain", self.rec.domains),
            ("subject_area", self.rec.subject_areas),
            ("term", self.rec.glossary_terms),
            ("council", self.rec.councils),
            ("person", self.rec.people),
            ("organization", self.rec.organizations),
        ]
        for kind, items in groups:
            taken: set[str] = set()
            for obj in items or []:
                slug = _slug(obj.id)
                if slug in taken:  # same local name under another prefix
                    slug = _slug(obj.id.replace(":", "-"))
                taken.add(slug)
                self.urls[obj.id] = f"{DIRS[kind]}/{slug}.html"
        taken = set()
        for proc in self.rec.processes or []:
            slug = _slug(proc.id)
            while slug in taken:
                slug += "-x"
            taken.add(slug)
            self.urls[proc.id] = f"{PROCESS_PAGE}#{slug}"

    def ref(self, oid: str) -> vm.Ref:
        obj = self.idx[oid]
        kind = None
        if isinstance(obj, m.Person):
            kind = vm.AgentKind.person
        elif isinstance(obj, m.Organization):
            kind = vm.AgentKind.organization
        elif isinstance(obj, m.DataGovernanceCouncil):
            kind = vm.AgentKind.council
        return vm.Ref(
            about=oid,
            url=self.urls.get(oid),
            label=display_label(obj),
            state=self.states.get(oid) if isinstance(obj, m.GlossaryTerm) else None,
            kind=kind,
        )

    def linked(self, term, slot: str, ids) -> list[str]:
        """The published terms among `ids`; notes each unpublished one left off."""
        out = []
        for i in ids:
            if i in self.published:
                out.append(i)
            else:
                self.notes.append(f"{term.id}: {slot} {i} is not published, so the link is left off")
        return out

    def refs(self, ids, sort=True) -> list[vm.Ref]:
        out = [self.ref(i) for i in ids]
        return sorted(out, key=lambda r: r.label.casefold()) if sort else out

    def page(self, obj) -> dict:
        return {"about": obj.id, "iri": self.ns.expand(obj.id), "url": self.urls[obj.id],
                "label": display_label(obj)}

    # ------------------------------------------------------------ §5.1 rules

    def outcome(self, proc) -> str:
        bs = self.boundaries_by_process.get(proc.id, [])
        if not bs:
            return "open"
        return {"Approved": "approved", "Rejected": "rejected"}.get(dgo.dgo_kind(bs[-1]).model_class, "open")

    def change(self, proc) -> vm.Change:
        kind = dgo.kind_of(proc)
        return vm.Change(about=proc.id, label=proc.label, process_kind=dgo.kind(kind.dgo_ancestor).slug,
                         process_label=kind.name, outcome=self.outcome(proc))

    def pending(self, term_id: str) -> list[vm.Change]:
        return [self.change(p) for p in self._processes(term_id)
                if isinstance(p, (m.TermModification, m.TermDeprecation)) and self.outcome(p) == "open"]

    def _processes(self, term_id: str):
        return sorted(self.processes_by_term.get(term_id, []),
                      key=lambda p: (PROCESS_ORDER[dgo.dgo_kind(p).model_class], p.id))

    def history(self, term_id: str) -> list[vm.HistoryEntry]:
        rows = []
        for proc in self._processes(term_id):
            change = self.change(proc)
            for b in self.boundaries_by_process.get(proc.id, []):
                kind, base = dgo.kind_of(b), dgo.dgo_kind(b)
                rows.append(((str(b.occurred_on), BOUNDARY_ORDER[base.model_class],
                              PROCESS_ORDER[dgo.dgo_kind(proc).model_class]),
                             vm.HistoryEntry(occurred_on=b.occurred_on, process=change,
                                             process_kind=change.process_kind,
                                             process_label=change.process_label,
                                             boundary_kind=base.slug, boundary_label=kind.name)))
        return [row for _, row in sorted(rows, key=lambda r: r[0])]

    def process_chain(self, gov: str | None) -> list[str]:
        """A governance process and every process it is part of, innermost first."""
        chain = []
        while gov and gov not in chain:
            chain.append(gov)
            gov = getattr(self.idx.get(gov), "part_of", None)
        return chain

    def governing_councils(self, term_id: str) -> list[str]:
        out = set()
        for proc in self.processes_by_term.get(term_id, []):
            chain = self.process_chain(proc.part_of)
            out |= {c.id for c in self.rec.councils or [] if c.participates_in in chain}
        return sorted(out)

    def responsibilities(self, term) -> list[vm.Responsibility]:
        out = []
        for role in term.responsibilities or []:
            if not role.role_of:
                continue
            kind = dgo.kind_of(role)
            out.append(vm.Responsibility(role=dgo.dgo_kind(role).slug, role_label=kind.name, role_iri=kind.iri,
                                         term=self.ref(term.id), bearer=self.ref(role.role_of)))
        return out

    def above(self, tid) -> list[str]:
        """A term's published broader terms."""
        return [b for b in self.idx[tid].broader or [] if b in self.published]

    def hierarchy(self, term) -> list[vm.HierarchyNode]:
        """The terms above `term`, broadest first, branching down to it.

        Empty when the broader terms are all at the top, since the broader
        list already says everything. Where two paths meet, the shared term is
        expanded the first time and marked repeated after that.
        """
        ancestors, todo = set(), self.above(term.id)
        while todo:
            t = todo.pop()
            if t not in ancestors:
                ancestors.add(t)
                todo += self.above(t)
        if all(not self.above(b) for b in self.above(term.id)):
            return []
        below = defaultdict(list)
        for t in ancestors | {term.id}:
            for b in self.above(t):
                below[b].append(t)
        seen = set()

        def nodes(ids):
            out = []
            for ref in self.refs(ids):
                node = vm.HierarchyNode(**ref.model_dump(), current=ref.about == term.id or None)
                if ref.about in seen and below[ref.about]:
                    node.repeated = True
                else:
                    seen.add(ref.about)
                    node.below = nodes(below[ref.about])
                out.append(node)
            return out

        return nodes(t for t in ancestors if not self.above(t))

    def semantic_type(self, term) -> vm.SemanticType | None:
        """The external class a term denotes (DGO 0.1.1), described by the class itself."""
        value = getattr(term, "semantic_type", None)
        if not value:
            return None
        info = self.describe(self.ns.expand(value))
        if not info.found:
            self.notes.append(f"{term.id}: semantic_type {value} could not be looked up, so only its IRI is shown")
        return vm.SemanticType(about=value, iri=info.iri, label=info.label, ontology=info.ontology)

    def seats(self, council) -> list[vm.Seat]:
        seats = []
        for member in council.has_member or []:
            held = [r for r in self.rec.council_roles or []
                    if r.role_of == member and council.participates_in
                    and r.realized_in == council.participates_in]
            roles = []
            for r in held:
                kind = dgo.kind_of(r)
                roles.append(vm.CouncilRoleHeld(role=dgo.dgo_kind(r).slug, role_label=kind.name, role_iri=kind.iri))
            seats.append(vm.Seat(member=self.ref(member), council=self.ref(council.id), council_roles=roles))
        seats.sort(key=lambda s: (not s.council_roles, s.member.label.casefold()))
        return seats

    def governed_areas(self, term_pages, governed: set[str], held) -> list[vm.GovernedArea]:
        """The subject areas of a council's terms (governed or held a role on), with the
        roles it holds there, so its page links to each area once instead of listing terms."""
        mine = governed | {r.term.about for r in held if r.term}
        areas = {}  # area id -> (page of the first term seen, term count, roles by class IRI)
        for page in term_pages:
            if page.about not in mine:
                continue
            first, n, roles = areas.get(page.subject_area.about, (page, 0, {}))
            for r in held:
                if r.term and r.term.about == page.about:
                    roles.setdefault(r.role_iri, vm.RoleKind(role=r.role, role_label=r.role_label, role_iri=r.role_iri))
            areas[page.subject_area.about] = (first, n + 1, roles)
        out = [vm.GovernedArea(subject_area=p.subject_area, domain=p.domain, term_count=n, roles=list(roles.values()))
               for p, n, roles in areas.values()]
        return sorted(out, key=lambda a: (a.domain.label.casefold(), a.subject_area.label.casefold()))

    # ------------------------------------------------------------ pages

    def term_page(self, term) -> vm.TermPage:
        sa = self.idx[term.in_subject_area]
        source = None
        if term.definition_source:
            src = self.idx.get(term.definition_source)
            source = vm.SourceRef(iri=self.ns.expand(term.definition_source),
                                  label=src.label if src else term.definition_source)
        tid = term.id
        successor = self.linked(term, "replaced_by", [term.replaced_by] if term.replaced_by else [])
        value_of = self.linked(term, "value_of", [term.value_of] if term.value_of else [])
        return vm.TermPage(
            **self.page(term),
            name=term.label if term.pref_label and term.pref_label != term.label else None,
            alt_labels=list(term.alt_labels or []),
            definition=term.definition,
            definition_source=source,
            semantic_type=self.semantic_type(term),
            state=self.states[tid],
            glossary=self.ref(term.part_of),
            subject_area=self.ref(sa.id),
            domain=self.ref(sa.part_of),
            responsibilities=self.responsibilities(term),
            governing_councils=self.refs(self.governing_councils(tid)),
            pending_changes=self.pending(tid),
            history=self.history(tid),
            successor=self.ref(successor[0]) if successor else None,
            predecessors=self.refs(t.id for t in self.terms if t.replaced_by == tid),
            broader=self.refs(self.linked(term, "broader", term.broader or [])),
            hierarchy=self.hierarchy(term),
            narrower=self.refs(t.id for t in self.terms if tid in (t.broader or [])),
            related=self.refs(self.linked(term, "related", related(self.rec, term))),
            value_of=self.ref(value_of[0]) if value_of else None,
            values=self.refs(t.id for t in self.terms if t.value_of == tid),
            source_file=self.sources.get(tid),
        )

    def site(self) -> vm.Site:
        rec = self.rec
        terms_in_area = defaultdict(list)
        for t in self.terms:
            terms_in_area[t.in_subject_area].append(t.id)
        areas_in_domain = defaultdict(list)
        for sa in rec.subject_areas or []:
            areas_in_domain[sa.part_of].append(sa.id)
        domains_in_glossary = defaultdict(list)
        for d in rec.domains or []:
            if d.part_of:
                domains_in_glossary[d.part_of].append(d.id)

        term_pages = sorted((self.term_page(t) for t in self.terms), key=lambda p: p.label.casefold())
        governed = defaultdict(set)
        for page in term_pages:
            for c in page.governing_councils or []:
                governed[c.about].add(page.about)
        held = defaultdict(list)  # bearer id -> responsibilities
        for page in term_pages:
            for r in page.responsibilities or []:
                held[r.bearer.about].append(r)
        for role in rec.governance_roles or []:
            if role.role_of:
                kind = dgo.kind_of(role)
                held[role.role_of].append(vm.Responsibility(
                    role=dgo.dgo_kind(role).slug, role_label=kind.name, role_iri=kind.iri,
                    bearer=self.ref(role.role_of)))

        glossaries = [
            vm.GlossaryPage(**self.page(g), domains=self.refs(domains_in_glossary[g.id]),
                            term_count=sum(1 for t in self.terms if t.part_of == g.id))
            for g in rec.business_glossaries or []
        ]
        domains = [
            vm.DomainPage(**self.page(d), glossary=self.ref(d.part_of) if d.part_of else None,
                          subject_areas=self.refs(areas_in_domain[d.id]),
                          term_count=sum(len(terms_in_area[a]) for a in areas_in_domain[d.id]),
                          accent=self.accents.get(d.id))
            for d in rec.domains or []
        ]
        areas = []
        for sa in rec.subject_areas or []:
            domain = self.idx[sa.part_of]
            areas.append(vm.SubjectAreaPage(
                **self.page(sa), domain=self.ref(domain.id),
                glossary=self.ref(domain.part_of) if domain.part_of else None,
                terms=self.refs(terms_in_area[sa.id]),
                accent=self.accents.get(sa.id) or self.accents.get(domain.id)))
        councils = []
        for c in rec.councils or []:
            councils.append(vm.CouncilPage(
                **self.page(c),
                participates_in=self.ref(c.participates_in) if c.participates_in else None,
                process_chain=self.refs(self.process_chain(c.participates_in), sort=False),
                members=self.seats(c),
                responsibilities=held.get(c.id, []),
                governed_terms=self.refs(governed[c.id]),
                governed_areas=self.governed_areas(term_pages, governed[c.id], held.get(c.id, []))))
        agents = []
        # Organization membership (has_member on organizations, from DGO 0.1.1).
        org_members = {o.id: list(getattr(o, "has_member", None) or []) for o in rec.organizations or []}
        for kind, items in ((vm.AgentKind.person, rec.people), (vm.AgentKind.organization, rec.organizations)):
            for a in items or []:
                memberships = [s for c in rec.councils or [] if a.id in (c.has_member or [])
                               for s in self.seats(c) if s.member.about == a.id]
                agents.append(vm.AgentPage(
                    **self.page(a), kind=kind, email=a.email,
                    job_title=getattr(a, "title", None), memberships=memberships,
                    organization_members=self.refs(org_members.get(a.id, [])),
                    member_of=self.refs(o for o, members in org_members.items() if a.id in members),
                    responsibilities=held.get(a.id, [])))
        processes = []
        for p in rec.processes or []:
            processes.append(vm.ProcessPage(
                **self.page(p),
                parent=self.ref(p.part_of) if p.part_of else None,
                children=self.refs(q.id for q in rec.processes or [] if q.part_of == p.id),
                councils=self.refs(c.id for c in rec.councils or [] if c.participates_in == p.id)))

        by_label = lambda p: p.label.casefold()
        return vm.Site(
            glossaries=sorted(glossaries, key=by_label),
            domains=sorted(domains, key=by_label),
            subject_areas=sorted(areas, key=by_label),
            terms=term_pages,
            councils=sorted(councils, key=by_label),
            agents=sorted(agents, key=by_label),
            processes=processes,
        )


# ---------------------------------------------------------------- module-level rules


def index(rec: m.GovernanceRecord) -> dict:
    """Every identified object by id, across all lists."""
    out = {}
    for name in type(rec).model_fields:
        for obj in getattr(rec, name) or []:
            if getattr(obj, "id", None):
                out[obj.id] = obj
    return out


def display_label(obj) -> str:
    """`pref_label`, else `label`."""
    return getattr(obj, "pref_label", None) or obj.label


def related(rec: m.GovernanceRecord, term) -> list[str]:
    """skos:related is symmetric but written once: collect both directions."""
    back = [t.id for t in rec.glossary_terms or [] if term.id in (t.related or [])]
    return sorted(set(term.related or []) | set(back))


def unpublished_reason(d: Deriver, term_id: str) -> str | None:
    """Why a term is left out of the site, or None if it is published.

    A term exists once a term creation is recorded for it, whatever boundaries
    that creation has reached, unless the creation was rejected.
    """
    created = [p for p in d.processes_by_term.get(term_id, []) if isinstance(p, m.TermCreation)]
    if not created:
        return "no term creation is recorded for it"
    if d.outcome(created[0]) == "rejected":
        return "its term creation was rejected"
    return None


def term_state(d: Deriver, term_id: str) -> str:
    """A term's state (handoff §5.2; provisional until DGO confirms it).

    1. deprecated: a term deprecation of the term has an approved boundary.
    2. otherwise, from the term creation's latest boundary: approved, rejected,
       or proposed while the creation is open.
    3. unrecorded: no creation in the data.

    Modifications never change the state: an approved one is already reflected
    in the term's content, a rejected one only appears in history, and an open
    one is a pending change.

    Only approved, proposed and deprecated terms are published; rejected and
    unrecorded ones never reach the view model (see unpublished_reason).
    """
    procs = d.processes_by_term.get(term_id, [])
    if any(isinstance(p, m.TermDeprecation) and d.outcome(p) == "approved" for p in procs):
        return "deprecated"
    created = [p for p in procs if isinstance(p, m.TermCreation)]
    if not created:
        return "unrecorded"
    return {"approved": "approved", "rejected": "rejected"}.get(d.outcome(created[0]), "proposed")


def derive(rec: m.GovernanceRecord, prefixes: dict[str, str], *,
           sources: dict[str, str] | None = None, accents: dict[str, str] | None = None,
           describe: Callable[[str], ClassInfo] | None = None) -> vm.Site:
    return Deriver(rec, prefixes, sources=sources, accents=accents, describe=describe).site()
