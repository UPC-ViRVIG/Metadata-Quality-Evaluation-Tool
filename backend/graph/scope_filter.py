from __future__ import annotations

from rdflib import Graph, RDF, URIRef


def apply(graph: Graph, scope: list[str] | None) -> Graph:
    """
    Returns a (possibly filtered) view of graph

    Parameters
    ----------
    graph : rdflib.Graph
        The full cached graph. This object is never mutated
    scope : list[str] | None
        A list of class URIs to include

    Returns
    -------
    rdflib.Graph
        If scope is empty it returns the original graph.
        Otherwise, a fresh rdflib.Graph containing only 
        the triples whose subject is an instance of at 
        least one class in scope
    """
    if not scope:
        return graph

    scope_set: set[URIRef] = {URIRef(uri) for uri in scope}

    matching_subjects: set[URIRef] = set()

    for subject, predicate, obj in graph.triples((None, RDF.type, None)):
        if isinstance(obj, URIRef) and obj in scope_set:
            if isinstance(subject, URIRef):
                matching_subjects.add(subject)

    if not matching_subjects:
        return Graph()

    filtered = Graph()

    for prefix, namespace in graph.namespaces():
        filtered.bind(prefix, namespace)

    for subject, predicate, obj in graph:
        if isinstance(subject, URIRef) and subject in matching_subjects:
            filtered.add((subject, predicate, obj))

    return filtered


def stats(graph: Graph) -> dict:
    """
    Return basic statistics about graph

    Parameters
    ----------
    graph : rdflib.Graph
        Any graph (full or already filtered).

    Returns
    -------
    dict
        Keys: triple_count, entity_count, class_count
    """
    triple_count = len(graph)

    entity_uris: set[str] = set()
    class_uris: set[str] = set()

    for subject, _, obj in graph.triples((None, RDF.type, None)):
        if isinstance(subject, URIRef):
            entity_uris.add(str(subject))
        if isinstance(obj, URIRef):
            class_uris.add(str(obj))

    return {
        "triple_count": triple_count,
        "entity_count": len(entity_uris),
        "class_count": len(class_uris),
    }