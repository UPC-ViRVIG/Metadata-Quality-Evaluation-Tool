"""
graph/ontology_extractor.py
---------------------------
Extraction of a class hierarchy directly from RDF data.

The hierarchy is built from what the graph actually contains — rdf:type
for instances and rdfs:subClassOf for the tree structure — so no
external schema or ontology file is required. Classes without instances
are omitted, and each class carries the properties its instances use.

Classes holding exactly the same resources are reported as one node,
with the others listed as aliases. This equivalence is a property of the
loaded data only: two classes that coincide here need not coincide in
another dataset.

This module is independent of the evaluation pipeline. It exists to let
a user explore an unfamiliar dataset and choose a meaningful scope
before running any metric.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from rdflib import Graph, RDF, RDFS, OWL, URIRef

_OPAQUE_NAME = re.compile(r"^[A-Za-z]?\d+$")

@dataclass
class PropertyInfo:
    """
    Attributes
    ----------
    uri : str
        Full predicate URI.
    label : str
        Human-readable short name extracted from the URI.
    count : int
        Number of class instances using this property.
    """
    uri: str
    label: str
    count: int


@dataclass
class ClassNode:
    """
    Represents a class in the ontology hierarchy.

    Attributes
    ----------
    uri : str
        Full class URI.
    label : str
        Human-readable class name.
    instance_count : int
        Number of RDF subjects typed as this class.
    aliases : list[str]
        URIs of other classes holding exactly the same resources.
    properties : list[PropertyInfo]
        Properties used by instances of this class.
    children : list[ClassNode]
        Child subclasses in the hierarchy tree.
    """
    uri: str
    label: str
    instance_count: int
    aliases: list[str] = field(default_factory=list)
    properties: list[PropertyInfo] = field(default_factory=list)
    children: list["ClassNode"] = field(default_factory=list)


def _local_name(uri: str) -> str:
    """
    Return the fragment or last path segment of a URI as a readable label.
    """
    if "#" in uri:
        return uri.rsplit("#", 1)[-1]
    return uri.rsplit("/", 1)[-1] or uri


def _collect_instances(graph: Graph) -> dict[str, set[str]]:
    """
    Collect all rdf:type relationships from the graph.

    Returns
    -------
    dict[str, set[str]]
        Mapping:
            {
                class_uri: {instance_uri, ...}
            }
    """
    class_instances: dict[str, set[str]] = defaultdict(set)

    for subject, _, obj in graph.triples((None, RDF.type, None)):
        if not isinstance(subject, URIRef):
            continue
        if not isinstance(obj, URIRef):
            continue
        class_instances[str(obj)].add(str(subject))

    return class_instances


def _collect_properties(
    graph: Graph,
    class_instances: dict[str, set[str]],
) -> dict[str, list[PropertyInfo]]:
    """
    Counts property usage for each class

    For each class:
        - look at all its instances
        - determine which predicates those instances use
        - count how many instances use each predicate

    Returns
    -------
    dict[str, list[PropertyInfo]]

    Structure:
        {
            class_uri: [
                PropertyInfo(...),
                ...
            ]
        }
    """
    subject_props: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for s, p, _ in graph:
        if not isinstance(s, URIRef):
            continue
        if p == RDF.type:
            continue
        subject_props[str(s)][str(p)] += 1

    result: dict[str, list[PropertyInfo]] = {}

    for class_uri, instances in class_instances.items():
        prop_instance_count: dict[str, int] = defaultdict(int)

        for inst in instances:
            for pred in subject_props.get(inst, {}):
                prop_instance_count[pred] += 1

        result[class_uri] = sorted(
            [
                PropertyInfo(
                    uri=pred,
                    label=_local_name(pred),
                    count=cnt,
                )
                for pred, cnt in prop_instance_count.items()
            ],
            key=lambda pi: pi.count,
            reverse=True,
        )

    return result


def _collect_subclass_edges(graph: Graph) -> dict[str, list[str]]:
    """
    Extract subclass relationships from the graph.
    
    Returns
    -------
    dict[str, list[str]]

    Structure:
        {
            parent_class_uri: [
                child_class_uri,
                ...
            ]
        }
    """
    children: dict[str, list[str]] = defaultdict(list)

    for child, _, parent in graph.triples((None, RDFS.subClassOf, None)):
        if isinstance(child, URIRef) and isinstance(parent, URIRef):
            children[str(parent)].append(str(child))

    return children


def _build_tree(
    roots: list[str],
    class_instances: dict[str, set[str]],
    class_properties: dict[str, list[PropertyInfo]],
    children_map: dict[str, list[str]],
    visited: set[str],
    aliases_map: dict[str, list[str]] | None = None,
) -> list[ClassNode]:
    """
    Recursively construct a hierarchy of ClassNode objects.

    Parameters
    ----------
    roots : list[str]
        Class URIs to use as the current recursion roots.
    visited : set[str]
        Prevents cycles and duplicate processing.
    aliases_map : dict[str, list[str]] | None
        Representative class URIs mapped to their equivalent classes.

    Returns
    -------
    list[ClassNode]
        Fully constructed subtree.
    """
    nodes: list[ClassNode] = []

    for class_uri in roots:
        if class_uri in visited:
            continue
        visited.add(class_uri)

        instance_count = len(class_instances.get(class_uri, set()))
        child_uris = children_map.get(class_uri, [])

        node = ClassNode(
            uri=class_uri,
            label=_local_name(class_uri),
            instance_count=instance_count,
            aliases=(aliases_map or {}).get(class_uri, []),
            properties=class_properties.get(class_uri, []),
            children=_build_tree(
                child_uris,
                class_instances,
                class_properties,
                children_map,
                visited,
                aliases_map,
            ),
        )
        nodes.append(node)

    nodes.sort(key=lambda n: n.instance_count, reverse=True)
    return nodes


def _representative_key(uri: str, preferred: set[str]) -> tuple:
    """
    Sort key that puts the best name for an equivalence group first.

    A class in preferred wins, so a class the user selected names its
    group. After that a readable name beats an opaque identifier such as
    Q838948, then a shorter name beats a longer one, and the URI settles
    any remaining tie so the choice never depends on triple order.

    Parameters
    ----------
    uri : str
        Class URI.
    preferred : set[str]
        Class URIs to favour.

    Returns
    -------
    tuple
        Sort key, lowest first.
    """
    name = _local_name(uri)
    return (
        uri not in preferred,
        bool(_OPAQUE_NAME.match(name)),
        len(name),
        uri,
    )


def group_equivalent_classes(
    graph: Graph,
    preferred: list[str] | None = None,
) -> list[list[str]]:
    """
    Find classes that hold exactly the same resources in graph.

    Equivalence depends on the graph given. On a scoped graph a broad
    class can coincide with a narrower one, because only the resources
    in scope remain.

    Parameters
    ----------
    graph : rdflib.Graph
        Any graph (full or already filtered).
    preferred : list[str] | None
        Class URIs to favour as representatives, typically the scope.

    Returns
    -------
    list[list[str]]
        One list per group of two or more classes, with the
        representative first. Groups are sorted by representative.
    """
    preferred_set = set(preferred or [])
    by_instances: dict[frozenset[str], list[str]] = defaultdict(list)

    for class_uri, instances in _collect_instances(graph).items():
        by_instances[frozenset(instances)].append(class_uri)

    return sorted(
        sorted(
            members,
            key=lambda uri: _representative_key(uri, preferred_set),
        )
        for members in by_instances.values()
        if len(members) > 1
    )


def _merge_subclass_edges(
    children_map: dict[str, list[str]],
    representative: dict[str, str],
) -> dict[str, list[str]]:
    """
    Rewrite subclass edges so they only connect representatives.

    Without this an alias declared as a subclass would reappear in the
    tree as a child with no instances.

    Parameters
    ----------
    children_map : dict[str, list[str]]
        Parent class URIs mapped to their child class URIs.
    representative : dict[str, str]
        Alias class URIs mapped to their representative.

    Returns
    -------
    dict[str, list[str]]
        Edges with aliases replaced, self-edges dropped and duplicates
        removed.
    """
    merged: dict[str, list[str]] = defaultdict(list)

    for parent, children in children_map.items():
        new_parent = representative.get(parent, parent)
        for child in children:
            new_child = representative.get(child, child)
            if new_child != new_parent and new_child not in merged[new_parent]:
                merged[new_parent].append(new_child)

    return merged


def extract(graph: Graph) -> list[ClassNode]:
    """
    Analyse graph and return a sorted class tree.

    Parameters
    ----------
    graph : rdflib.Graph
        A fully-loaded graph (typically from graph_cache.get_or_load).

    Returns
    -------
    list[ClassNode]
        Top-level class nodes (roots of the hierarchy), sorted by
        instance_count descending.  Each node may have children
        that are themselves sorted.
    """
    class_instances = _collect_instances(graph)

    if not class_instances:
        return []

    groups = group_equivalent_classes(graph)
    aliases_map = {group[0]: group[1:] for group in groups}
    representative = {
        alias: group[0] for group in groups for alias in group[1:]
    }
    class_instances = {
        uri: instances for uri, instances in class_instances.items()
        if uri not in representative
    }

    class_properties = _collect_properties(graph, class_instances)
    children_map = _merge_subclass_edges(
        _collect_subclass_edges(graph), representative
    )

    # Determine root classes
    all_children: set[str] = {
        child
        for children in children_map.values()
        for child in children
    }

    # Only include classes that actually have instances
    classes_with_instances = set(class_instances.keys())

    roots = [
        c for c in classes_with_instances
        if c not in all_children
    ]

    if not roots:
        roots = list(classes_with_instances)

    visited: set[str] = set()
    return _build_tree(
        roots, class_instances, class_properties, children_map, visited,
        aliases_map,
    )