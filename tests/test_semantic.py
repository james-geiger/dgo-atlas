"""Reading a semantic type's label from the class it names."""

import json

import pytest

from dgo_site import semantic

BFO_PROCESS = "http://purl.obolibrary.org/obo/BFO_0000015"


@pytest.fixture(autouse=True)
def fresh_cache():
    semantic.describe.cache_clear()
    yield
    semantic.describe.cache_clear()


def serve(monkeypatch, responses):
    """Answer _get from `responses` ({url prefix: (body, content type)}); anything else fails."""
    def get(url, accept):
        for prefix, response in responses.items():
            if url.startswith(prefix):
                return response
        raise OSError(f"no network in this test: {url}")
    monkeypatch.setattr(semantic, "_get", get)


OLS_PROCESS = json.dumps({"_embedded": {"terms": [{
    "label": " process\n", "ontology_prefix": "BFO",
}]}}).encode()

TURTLE = f"""
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<{BFO_PROCESS}> rdfs:label "Prozess"@de, "process"@en .
""".encode()


def test_read_from_ols(monkeypatch):
    serve(monkeypatch, {"https://www.ebi.ac.uk/ols4/": (OLS_PROCESS, "application/json")})
    info = semantic.describe(BFO_PROCESS)
    assert (info.label, info.ontology) == ("process", "BFO")


def test_read_from_the_iri_when_ols_does_not_know_it(monkeypatch):
    serve(monkeypatch, {
        "https://www.ebi.ac.uk/ols4/": (b'{"page": {"totalElements": 0}}', "application/json"),
        BFO_PROCESS: (TURTLE, "text/turtle"),
    })
    info = semantic.describe(BFO_PROCESS)
    assert (info.label, info.ontology) == ("process", None)  # English preferred


def test_html_at_the_iri_is_not_read(monkeypatch):
    serve(monkeypatch, {BFO_PROCESS: (b"<html>process</html>", "text/html")})
    info = semantic.describe(BFO_PROCESS)
    assert not info.found and info.iri == BFO_PROCESS


def test_unreachable_class_keeps_only_its_iri(monkeypatch):
    serve(monkeypatch, {})
    info = semantic.describe(BFO_PROCESS)
    assert info == semantic.ClassInfo(iri=BFO_PROCESS)


def test_each_iri_looked_up_once(monkeypatch):
    calls = []
    serve(monkeypatch, {"https://www.ebi.ac.uk/ols4/": (OLS_PROCESS, "application/json")})
    get = semantic._get
    monkeypatch.setattr(semantic, "_get", lambda url, accept: calls.append(url) or get(url, accept))
    semantic.describe(BFO_PROCESS)
    semantic.describe(BFO_PROCESS)
    assert len(calls) == 1
