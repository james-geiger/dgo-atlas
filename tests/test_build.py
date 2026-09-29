"""End to end: the fixture builds into a site with every page and no broken links."""

import json

import pytest

from dgo_atlas import config, linkcheck
from dgo_atlas.build import build

from .conftest import FIXTURES


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("site")
    project = config.load(FIXTURES / "variant" / config.CONFIG_NAME)
    assert build(project, out=out) == 0
    return out


def read(site, path):
    return (site / path).read_text(encoding="utf-8")


def test_pages_exist(site):
    for path in ["index.html", "terms/index.html", "terms/clinical-trial.html", "areas/clinical-research.html",
                 "domains/research.html", "glossaries/business-glossary.html", "councils/research-committee.html",
                 "people/morgan-ellis.html", "organizations/cto.html", "directory.html", "governance.html",
                 "how-to-read-a-term.html", "404.html", "assets/site.css", "assets/search-index.js"]:
        assert (site / path).is_file(), path


def test_unpublished_term_is_not_built(site):
    """clinical study has no recorded creation, so it appears nowhere on the site."""
    assert not (site / "terms" / "clinical-study.html").exists()
    for page in site.rglob("*.html"):
        assert "clinical-study.html" not in page.read_text(), page
    assert "clinical study" not in read(site, "assets/search-index.js")


def test_no_broken_links(site):
    assert linkcheck.check(site) == []


def test_no_model_reference(site):
    assert not (site / "model").exists()
    assert "model/" not in (site / "how-to-read-a-term.html").read_text()


def test_term_page(site):
    html = read(site, "terms/clinical-trial.html")
    assert "Clinical Trial" in html
    assert "Approved definition" in html
    assert "Change under review" in html  # the open modification
    assert "https://w3id.org/dgo/data/clinical-trial" in html  # expanded IRI
    assert 'href="https://w3id.org/dgo/DGO_00000019"' in html  # the kind links to its DGO class IRI


def test_term_page_shows_what_it_denotes(site):
    html = read(site, "terms/clinical-trial.html")
    assert "Denotes" in html
    assert 'href="http://purl.obolibrary.org/obo/BFO_0000015"' in html
    assert "<code>bfo:0000015</code>" in html


def test_organization_page_lists_members(site):
    html = read(site, "organizations/office-of-research.html")
    assert 'href="../organizations/cto.html">Clinical Trials Office</a>' in html
    assert 'href="../organizations/spo.html">Sponsored Programs Office</a>' in html
    cto = read(site, "organizations/cto.html")
    assert 'href="../people/jordan-price.html">Jordan Price</a>' in cto
    assert "Clinical Trials Manager" in cto
    assert "Member of" in cto and 'href="../organizations/office-of-research.html"' in cto


def test_deprecated_term_points_at_successor(site):
    html = read(site, "terms/clinical-investigation.html")
    assert "Deprecated" in html
    assert 'href="../terms/clinical-trial.html"' in html


def test_search_index(site):
    text = read(site, "assets/search-index.js")
    entries = json.loads(text.removeprefix("window.DGO_SITE_INDEX = ").rstrip(";\n"))
    titles = {e["title"] for e in entries}
    assert {"Clinical Trial", "Research Data Governance Committee", "Morgan Ellis"} <= titles


def test_identifier_panel_shown_by_default(site):
    html = read(site, "terms/clinical-trial.html")
    assert "Identifier" in html and "Copy IRI" in html
    assert "Identifier" in read(site, "councils/research-committee.html")


def test_identifier_panel_switched_off(tmp_path):
    project = config.load(FIXTURES / "variant" / config.CONFIG_NAME)
    project.config.show_identifiers = False
    assert build(project, out=tmp_path) == 0
    term = (tmp_path / "terms" / "clinical-trial.html").read_text()
    assert "Identifier" not in term and "Copy IRI" not in term
    assert "View source" in term  # the source link stays, in its own panel
    for page in ("councils/research-committee.html", "people/morgan-ellis.html", "organizations/cto.html"):
        assert "Identifier" not in (tmp_path / page).read_text(), page


def test_base_path_404(tmp_path):
    project = config.load(FIXTURES / "variant" / config.CONFIG_NAME)
    project.config.base_path = "/glossary/"
    assert build(project, out=tmp_path) == 0
    assert 'href="/glossary/assets/site.css' in (tmp_path / "404.html").read_text()
    assert linkcheck.check(tmp_path, "/glossary/") == []


def test_accessible_structure(site):
    """The semantics WCAG 2.1 AA relies on ("Accessibility" in docs/reference.md)."""
    home = read(site, "index.html")
    assert '<html lang="en">' in home
    assert 'role="combobox"' in home and 'aria-autocomplete="list"' in home
    assert 'role="status" id="site-status"' in home
    assert 'aria-label="Switch colour theme"' not in home  # the toggle is named by its visible word
    terms = read(site, "terms/index.html")
    assert '<ul class="term-list">' in terms
    assert 'data-term-count role="status"' in terms
    assert '<span class="visually-hidden">State: </span>' in terms  # each value says which column it is in
    council = read(site, "councils/research-committee.html")
    assert '<table class="data-table">' in council and '<th scope="col">' in council
    term = read(site, "terms/clinical-trial.html")
    assert '<nav class="breadcrumb" aria-label="Breadcrumb">' in term
    assert '<h2 class="panel__label">' in term
    assert '<ol class="history">' in term


def test_site_language(tmp_path):
    project = config.load(FIXTURES / "variant" / config.CONFIG_NAME)
    project.config.language = "fr-CA"
    assert build(project, out=tmp_path) == 0
    for page in ("index.html", "404.html", "terms/clinical-trial.html"):
        assert '<html lang="fr-CA">' in (tmp_path / page).read_text(), page
