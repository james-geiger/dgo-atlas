"""Render the view model into HTML pages.

Every page is rendered from the validated view model (models.viewmodel.Site),
never from governance data directly. Every piece of wording comes from the
project's Text (text.py): templates call `t(key)` and `count(noun, n)`.

The generated index pages (all terms, people & organizations, how governance
is organized, how to read a term) take their eyebrow, title and lede from
Text, unless the content directory has a Markdown file at the same path
(content/governance.md for governance.html). Its front matter then sets the
header, and its body appears as intro prose on the page.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from markupsafe import Markup

from . import __version__, dgo
from .config import Project
from .content import ContentError, ContentPage
from .derive import DIRS, PROCESS_PAGE
from .models import viewmodel as vm
from .resources import STATIC, TEMPLATES
from .text import Text

DEFAULT_FONTS_URL = (
    "https://fonts.googleapis.com/css2?family=Oswald:wght@400;500;600;700"
    "&family=Jost:ital,wght@0,300;0,400;0,500;0,600;1,400;1,500"
    "&family=Zilla+Slab:ital,wght@0,400;0,500;0,600;1,400;1,500&display=swap"
)

# Colours cycled through for domain and subject-area cards that the site
# config gives no accent.
CARD_ACCENTS = ["var(--green)", "var(--slate)", "var(--accent)", "var(--moss)", "var(--sky)", "var(--clay)"]

ROLE_COLOURS = {
    "owner": "var(--slate)",
    "steward": "var(--green)",
    "custodian": "var(--sky)",
}

# Published term states, in the order they are explained and counted.
STATES = ("approved", "proposed", "deprecated")

# Glossary-term slots in the order a reader meets them on a term page. Their
# labels are `field.<slot>` in the text catalog; descriptions come from DGO.
# Slots the release lacks (semantic_type before 0.1.1) are left out.
TERM_FIELDS = ["pref_label", "label", "alt_labels", "definition", "definition_source", "semantic_type",
               "part_of", "in_subject_area", "responsibilities", "broader", "related", "value_of",
               "replaced_by", "id"]

# Generated pages whose header (and intro prose) a content file at the same
# path may set, with the text-catalog section holding their defaults.
OVERRIDABLE = {
    "terms/index.html": "terms_index",
    "directory.html": "directory",
    PROCESS_PAGE: "governance",
    "how-to-read-a-term.html": "how_to_read",
}


@dataclass
class NavItem:
    label: str
    url: str


@dataclass
class NavGroup:
    label: str
    items: list[NavItem]


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc
    except ValueError:
        return url
    return host.removeprefix("www.") or url


def _initials(label: str) -> str:
    words = [w for w in label.replace("-", " ").split() if w[:1].isalnum()]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[-1][0]).upper()


def _enum(value) -> str:
    """The text of a view-model enum value (pydantic may hand back the enum or its value)."""
    return getattr(value, "value", value) or ""


def _asset_version() -> str:
    """Short digest of the static assets, appended to their URLs to bust caches after a deploy."""
    digest = hashlib.sha256()
    for item in sorted(STATIC.iterdir()):
        if item.is_file():
            digest.update(item.read_bytes())
    return digest.hexdigest()[:10]


def rel_for(out_path: str) -> str:
    """Relative prefix from a page back to the site root."""
    return "../" * out_path.count("/")


def split_pages(pages: list[ContentPage]) -> tuple[list[ContentPage], dict[str, ContentPage]]:
    """Separate authored pages from those that set a generated page's header.

    A content file may share a path with one of the OVERRIDABLE pages; any
    other clash with a generated page is an error rather than a silent
    overwrite.
    """
    own, overrides = [], {}
    generated_dirs = tuple(f"{d}/" for d in (*DIRS.values(), "assets"))
    for page in pages:
        if page.url in OVERRIDABLE:
            overrides[page.url] = page
        elif page.url.startswith(generated_dirs) or page.url == "404.html":
            raise ContentError(
                f"{page.url} would replace a generated page. Content files can only set the header of "
                + ", ".join(sorted(OVERRIDABLE)) + "; move this page elsewhere.")
        else:
            own.append(page)
    return own, overrides


def make_env(text: Text) -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html", "j2"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["domain"] = _domain
    env.filters["initials"] = _initials
    env.filters["enum"] = _enum
    env.filters["state_label"] = lambda s: text(f"state.{_enum(s)}.label")
    env.filters["role_colour"] = lambda role: ROLE_COLOURS.get(role, "var(--ink-3)")
    env.globals["t"] = text
    env.globals["count"] = text.count
    return env


class Renderer:
    def __init__(self, out_dir: Path, project: Project, site: vm.Site, pages: list[ContentPage]):
        self.out = out_dir
        self.project = project
        self.cfg = project.config
        self.text = project.text
        self.site = site
        self.pages, self.overrides = split_pages(pages)
        self.env = make_env(self.text)
        self.built_on = date.today().strftime("%d %b %Y")
        self.asset_version = _asset_version()
        self.written: list[str] = []
        self.nav: list[NavGroup] = []
        self.lookup = {
            p.about: p
            for group in (site.glossaries, site.domains, site.subject_areas, site.terms,
                          site.councils, site.agents, site.processes)
            for p in group or []
        }
        accents = iter(CARD_ACCENTS * 100)
        self.card_accents = {p.about: p.accent or next(accents)
                             for p in [*(site.domains or []), *(site.subject_areas or [])]}

    def plain(self, key: str, **fields) -> str:
        """Wording as plain text (for titles, breadcrumbs and the search index; escaped later)."""
        return self.text.raw(key).format(**fields) if fields else self.text.raw(key)

    # ------------------------------------------------------------ context

    def shell(self) -> dict:
        """Context every page needs, independent of its depth (the 404 page uses only this)."""
        brand = self.project.brand
        return {
            "nav": self.nav,
            "site": self.cfg,
            "brand": brand,
            "fonts_url": brand.fonts_url or DEFAULT_FONTS_URL,
            "built_on": self.built_on,
            "contact_email": self.cfg.contact_email,
            "suggest_change_url": self.cfg.suggest_change_url,
            "repo_blob_url": self.project.repo_blob_url,
            "asset_version": self.asset_version,
            "dgo_version": self.project.dgo.version,
            "middleware_version": __version__,
            "show_identifiers": self.project.show_identifiers,
            "js_text": self.text.js(),
            "lookup": self.lookup,
            "card_accents": self.card_accents,
        }

    def context(self, out_path: str, title: str, breadcrumb=None, description=None) -> dict:
        return {
            **self.shell(),
            "rel": rel_for(out_path),
            "current_url": out_path,
            "page_title": title,
            "page_description": description,
            "breadcrumb": breadcrumb or [],
        }

    def header(self, out_path: str) -> dict:
        """Eyebrow, title, lede and intro prose for an OVERRIDABLE page."""
        section = OVERRIDABLE[out_path]
        page = self.overrides.get(out_path)
        default = {k: self.plain(f"{section}.{k}") for k in ("eyebrow", "title", "lede")}
        if page is None:
            return {**default, "html": "", "nav_label": None}
        return {
            "eyebrow": page.eyebrow if page.eyebrow is not None else default["eyebrow"],
            "title": page.title,
            "lede": page.lede if page.lede is not None else default["lede"],
            "html": Markup(page.html),
            "nav_label": page.nav_label,
        }

    def write(self, out_path: str, template: str, **context) -> None:
        destination = self.out / out_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(self.env.get_template(template).render(**context), encoding="utf-8")
        self.written.append(out_path)

    # ------------------------------------------------------------ nav

    def build_nav(self) -> None:
        groups: dict[str, list[tuple[int, NavItem]]] = {}
        for page in self.pages:
            if page.is_hub or not page.nav_group:
                continue
            groups.setdefault(page.nav_group, []).append((page.order, NavItem(page.nav_label, page.url)))

        def items(label):
            return [i for _, i in sorted(groups.pop(label, []), key=lambda p: p[0])]

        def generated(url, key):
            return NavItem(self.header(url)["nav_label"] or self.plain(key), url)

        start, glossary_label, governance_label = (
            self.plain("nav.start_here"), self.plain("nav.glossary"), self.plain("nav.governance"))
        nav = [NavGroup(start, [NavItem(self.plain("nav.home"), "index.html"), *items(start),
                                generated("how-to-read-a-term.html", "nav.how_to_read")])]
        glossary = [generated("terms/index.html", "nav.all_terms")]
        glossary += [NavItem(g.label, g.url) for g in self.site.glossaries or []]
        nav.append(NavGroup(glossary_label, glossary + items(glossary_label)))
        governance = [generated(PROCESS_PAGE, "nav.governance_overview")]
        governance += [NavItem(c.label, c.url) for c in self.site.councils or []]
        governance.append(generated("directory.html", "nav.directory"))
        nav.append(NavGroup(governance_label, governance + items(governance_label)))
        for label in list(groups):
            nav.append(NavGroup(label, items(label)))
        self.nav = nav

    # ------------------------------------------------------------ pages

    def hub(self) -> None:
        page = next((p for p in self.pages if p.is_hub), None)
        terms = self.site.terms or []
        states = [_enum(t.state) for t in terms]
        stats = [
            {"n": states.count("approved"), "label": self.text("home.stat_approved")},
            {"n": len(self.site.subject_areas or []), "label": self.text("home.stat_subject_areas")},
            {"n": len(self.site.councils or []), "label": self.text("home.stat_councils")},
            {"n": states.count("proposed") + sum(1 for t in terms if t.pending_changes),
             "label": self.text("home.stat_under_review")},
        ]
        recent = sorted(
            ({"term": t, "entry": h} for t in terms for h in t.history or []),
            key=lambda e: (str(e["entry"].occurred_on), e["entry"].process.about),
            reverse=True,
        )[:6]
        contacts: dict[str, dict] = {}
        for t in terms:
            for r in t.responsibilities or []:
                entry = contacts.setdefault(r.bearer.about, {"bearer": r.bearer, "roles": []})
                if r.role_label not in entry["roles"]:
                    entry["roles"].append(r.role_label)
        title = page.title if page else self.cfg.title
        lede = page.lede if page else self.cfg.description
        self.write(
            "index.html", "hub.html.j2",
            page=page, hero_title=title, hero_lede=lede, stats=stats,
            domains=self.site.domains or [], recent=recent,
            contacts=sorted(contacts.values(), key=lambda c: c["bearer"].label.casefold()),
            **self.context("index.html", title, description=lede),
        )

    def terms_index(self) -> None:
        url = "terms/index.html"
        head = self.header(url)
        self.write(
            url, "terms_index.html.j2", head=head,
            terms=self.site.terms or [], domains=self.site.domains or [],
            **self.context(url, head["title"], breadcrumb=[{"label": self.plain("breadcrumb.terms"), "url": None}],
                           description=head["lede"] or self.plain("terms_index.description")),
        )

    def term_page(self, term: vm.TermPage) -> None:
        self.write(
            term.url, "term.html.j2", term=term, term_kind=dgo.kind("glossary term"),
            **self.context(term.url, term.label, description=term.definition[:180], breadcrumb=[
                {"label": self.plain("breadcrumb.terms"), "url": "terms/index.html"},
                {"label": term.subject_area.label, "url": term.subject_area.url},
                {"label": term.label, "url": None},
            ]),
        )

    def glossary_page(self, g: vm.GlossaryPage) -> None:
        domains = [self.lookup[d.about] for d in g.domains or []]
        self.write(g.url, "glossary.html.j2", glossary=g, domains=domains,
                   **self.context(g.url, g.label, breadcrumb=[{"label": g.label, "url": None}]))

    def domain_page(self, d: vm.DomainPage) -> None:
        areas = [self.lookup[a.about] for a in d.subject_areas or []]
        crumbs = [{"label": d.glossary.label, "url": d.glossary.url}] if d.glossary else []
        self.write(d.url, "domain.html.j2", domain=d, areas=areas,
                   **self.context(d.url, d.label, breadcrumb=crumbs + [{"label": d.label, "url": None}]))

    def area_page(self, a: vm.SubjectAreaPage) -> None:
        counts: dict[str, int] = {}
        for t in a.terms or []:
            counts[_enum(t.state)] = counts.get(_enum(t.state), 0) + 1
        crumbs = [{"label": a.domain.label, "url": a.domain.url}, {"label": a.label, "url": None}]
        self.write(a.url, "area.html.j2", area=a,
                   state_counts=[(self.text(f"state.{s}.label"), counts[s]) for s in STATES if s in counts],
                   **self.context(a.url, a.label, breadcrumb=crumbs))

    def council_page(self, c: vm.CouncilPage) -> None:
        self.write(c.url, "council.html.j2", council=c, council_kind=dgo.kind("data governance council"),
                   **self.context(c.url, c.label, breadcrumb=[
                       {"label": self.plain("breadcrumb.governance"), "url": PROCESS_PAGE},
                       {"label": c.label, "url": None}]))

    def agent_page(self, a: vm.AgentPage) -> None:
        self.write(a.url, "agent.html.j2", agent=a, agent_kind=dgo.kind(_enum(a.kind)),
                   **self.context(a.url, a.label, breadcrumb=[
                       {"label": self.plain("breadcrumb.directory"), "url": "directory.html"},
                       {"label": a.label, "url": None}]))

    def directory(self) -> None:
        url = "directory.html"
        head = self.header(url)
        self.write(url, "directory.html.j2", head=head, agents=self.site.agents or [],
                   **self.context(url, head["title"], description=head["lede"] or None,
                                  breadcrumb=[{"label": head["title"], "url": None}]))

    def governance(self) -> None:
        head = self.header(PROCESS_PAGE)
        processes = self.site.processes or []
        roots = [p for p in processes if not p.parent]
        children = {p.about: [self.lookup[c.about] for c in p.children or []] for p in processes}
        self.write(PROCESS_PAGE, "governance.html.j2", head=head, roots=roots, children=children,
                   councils=self.site.councils or [],
                   **self.context(PROCESS_PAGE, head["title"], description=head["lede"] or None,
                                  breadcrumb=[{"label": self.plain("breadcrumb.governance"), "url": None}]))

    def how_to_read(self) -> None:
        url = "how-to-read-a-term.html"
        head = self.header(url)
        term_slots = set(dgo.class_slot_names("glossary term"))
        fields = [{"label": self.text(f"field.{name}"), **dgo.slot_facts(name)}
                  for name in TERM_FIELDS if name in term_slots]
        states = [{"name": s, "label": self.text(f"state.{s}.label"),
                   "description": self.text(f"state.{s}.description")} for s in STATES]
        self.write(
            url, "how_to_read.html.j2", head=head,
            fields=fields, states=states,
            roles=dgo.subkinds("governance role")[1:],
            council_roles=dgo.subkinds("council role")[1:],
            processes=dgo.subkinds("term lifecycle process")[1:],
            boundaries=dgo.subkinds("status boundary")[1:],
            **self.context(url, head["title"], breadcrumb=[{"label": head["title"], "url": None}],
                           description=head["lede"] or self.plain("how_to_read.description")),
        )

    def content_page(self, page: ContentPage) -> None:
        self.write(page.url, "page.html.j2", page=page,
                   **self.context(page.url, page.title, breadcrumb=[{"label": page.title, "url": None}],
                                  description=page.lede))

    def not_found(self) -> None:
        base_path = self.cfg.base_path or "/"
        self.write("404.html", "not_found.html.j2", base_path=base_path if base_path.endswith("/") else base_path + "/",
                   **self.shell())

    def all(self) -> None:
        self.build_nav()
        self.hub()
        self.terms_index()
        for t in self.site.terms or []:
            self.term_page(t)
        for g in self.site.glossaries or []:
            self.glossary_page(g)
        for d in self.site.domains or []:
            self.domain_page(d)
        for a in self.site.subject_areas or []:
            self.area_page(a)
        for c in self.site.councils or []:
            self.council_page(c)
        for a in self.site.agents or []:
            self.agent_page(a)
        self.directory()
        self.governance()
        self.how_to_read()
        for page in self.pages:
            if not page.is_hub:
                self.content_page(page)
        self.not_found()
        self.copy_static()
        self.write_search_index()

    # ------------------------------------------------------------ assets

    def copy_static(self) -> None:
        assets = self.out / "assets"
        assets.mkdir(parents=True, exist_ok=True)
        for item in STATIC.iterdir():
            if item.is_file():
                shutil.copy2(item, assets / item.name)

    def write_search_index(self) -> None:
        entries = []
        for t in self.site.terms or []:
            owner = next((r.bearer.label for r in t.responsibilities or [] if r.role == "owner"), None)
            entries.append({
                "kind": "term", "title": t.label, "alt": list(t.alt_labels or []), "url": t.url,
                "meta": " · ".join(x for x in [self.plain(f"state.{_enum(t.state)}.label"), t.subject_area.label,
                                               self.plain("search.owner", name=owner) if owner else ""] if x),
                "text": " ".join([t.label, t.name or "", *(t.alt_labels or []), t.definition]),
            })
        for group, kind in ((self.site.subject_areas, "subject_area"), (self.site.domains, "domain"),
                            (self.site.glossaries, "glossary"), (self.site.councils, "council")):
            for p in group or []:
                entries.append({"kind": kind, "title": p.label, "alt": [], "url": p.url,
                                "meta": self.plain(f"search.{kind}"), "text": p.label})
        for a in self.site.agents or []:
            entries.append({"kind": "agent", "title": a.label, "alt": [], "url": a.url,
                            "meta": " · ".join(x for x in [a.job_title, a.email] if x)
                            or dgo.kind(_enum(a.kind)).name,
                            "text": " ".join(x for x in [a.label, a.job_title, a.email] if x)})
        for page in self.pages:
            if page.is_hub:
                continue
            entries.append({"kind": "page", "title": page.title, "alt": [], "url": page.url,
                            "meta": page.nav_group or self.plain("search.guide"),
                            "text": f"{page.title} {page.lede or ''} {page.summary}"})
        payload = json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
        (self.out / "assets" / "search-index.js").write_text(
            f"window.DGO_SITE_INDEX = {payload};\n", encoding="utf-8")
