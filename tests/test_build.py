"""End to end: the fixture builds into a site with every page and no broken links."""

import json

import pytest

from dgo_site import config, linkcheck
from dgo_site.build import build

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
