"""Read what a term's semantic type refers to.

A semantic type (DGO v0.1.1) is the IRI of a class in an external ontology,
e.g. http://purl.obolibrary.org/obo/BFO_0000015. A bare IRI means nothing to
a reader, so the build reads the class's label from the class itself:

1. the Ontology Lookup Service (EBI OLS), which indexes the OBO ontologies
   and many others, and names the ontology that defines the class;
2. failing that, the IRI itself, dereferenced as RDF (linked-data content
   negotiation), for its skos:prefLabel or rdfs:label.

A class neither describes keeps only its IRI, and the build notes it. Each
IRI is looked up once per process.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from functools import cache
from urllib.parse import quote

import rdflib
from rdflib.namespace import RDFS, SKOS

OLS_URL = "https://www.ebi.ac.uk/ols4/api/terms/findByIdAndIsDefiningOntology?iri={iri}"
TIMEOUT = 20

RDF_ACCEPT = "text/turtle, application/rdf+xml;q=0.9, application/ld+json;q=0.8, application/n-triples;q=0.7"
RDF_FORMATS = {
    "text/turtle": "turtle",
    "application/x-turtle": "turtle",
    "application/rdf+xml": "xml",
    "application/ld+json": "json-ld",
    "application/n-triples": "nt",
}

LABELS = (SKOS.prefLabel, RDFS.label)


@dataclass(frozen=True)
class ClassInfo:
    """What an external class says about itself. Only `iri` is known when the lookup fails."""

    iri: str
    label: str | None = None
    ontology: str | None = None  # the defining ontology's short name, e.g. BFO

    @property
    def found(self) -> bool:
        return bool(self.label)


def _get(url: str, accept: str) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "dgo-site"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        content_type = response.headers.get_content_type()
        return response.read(), content_type


def _clean(text) -> str | None:
    """Whitespace collapsed; None for nothing."""
    return " ".join(str(text or "").split()) or None


def from_ols(iri: str) -> ClassInfo | None:
    """The class as OLS has it from its defining ontology, or None."""
    body, _ = _get(OLS_URL.format(iri=quote(iri, safe="")), "application/json")
    terms = (json.loads(body).get("_embedded") or {}).get("terms") or []
    if not terms or not terms[0].get("label"):
        return None
    return ClassInfo(iri=iri, label=_clean(terms[0]["label"]), ontology=terms[0].get("ontology_prefix"))


def _literal(graph: rdflib.Graph, subject: rdflib.URIRef, predicates) -> str | None:
    """The first English (or untagged) literal for the first predicate that has one."""
    for predicate in predicates:
        values = [v for v in graph.objects(subject, predicate) if isinstance(v, rdflib.Literal)]
        values.sort(key=lambda v: (v.language not in (None, "en"), v.language or ""))
        if values:
            return _clean(values[0])
    return None


def from_rdf(iri: str) -> ClassInfo | None:
    """The class as its IRI describes it when dereferenced as RDF, or None."""
    body, content_type = _get(iri, RDF_ACCEPT)
    fmt = RDF_FORMATS.get(content_type)
    if fmt is None:  # an HTML page, most often: nothing to read
        return None
    graph = rdflib.Graph()
    graph.parse(data=body, format=fmt, publicID=iri)
    label = _literal(graph, rdflib.URIRef(iri), LABELS)
    return ClassInfo(iri=iri, label=label) if label else None


@cache
def describe(iri: str) -> ClassInfo:
    """What the class at `iri` is, read from OLS or the IRI itself."""
    if iri.startswith(("http://", "https://")):
        for lookup in (from_ols, from_rdf):
            try:
                info = lookup(iri)
            except Exception:  # network, HTTP, JSON, or an rdflib parser's own error: try the next source
                continue
            if info:
                return info
    return ClassInfo(iri=iri)
