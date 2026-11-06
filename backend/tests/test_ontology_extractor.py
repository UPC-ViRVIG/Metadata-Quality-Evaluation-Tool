"""
tests/test_ontology_extractor.py
--------------------------------
Unit tests for equivalent-class handling in the ontology extractor.

Covers which classes count as equivalent, which name represents a group,
how the class tree is rewritten around a group, and how equivalence
changes on a scoped graph. Also checks that metric scores do not depend
on it, since merging is a matter of display only.

The fixture is a small local file, so the suite runs without network
access.
"""

from pathlib import Path

from rdflib import Graph

from graph.ontology_extractor import extract, group_equivalent_classes
from graph.scope_filter import apply
from metrics.plugins.property_coverage import PropertyCoverageMetric
from models.dataset_context import DatasetContext


FIXTURE = (
    Path(__file__).parent / "evaluation" / "ontology"
    / "eq01_equivalent_classes.ttl"
)

EX = "http://example.org/"
WORK = EX + "Work"
QUOTE = EX + "Quote"
BROAD = EX + "Broad"
MONUMENT = EX + "Monument"
STRUCTURE = EX + "Structure"
PAINTING = EX + "Painting"
Q838948 = "http://www.wikidata.org/entity/Q838948"


def _graph() -> Graph:
    """Load the equivalent-classes fixture."""

    graph = Graph()
    graph.parse(FIXTURE, format="turtle")
    return graph


def _flatten(nodes: list) -> list:
    """Return every node in a class tree."""

    result = []
    for node in nodes:
        result.append(node)
        result.extend(_flatten(node.children))
    return result


# ------------------------------------------------------------------
# GROUPING
# ------------------------------------------------------------------

def test_only_identical_instance_sets_are_grouped():
    """A superset is not equivalent, even when it contains the group."""

    groups = group_equivalent_classes(_graph())
    members = {uri for group in groups for uri in group}

    assert {frozenset(group) for group in groups} == {
        frozenset({WORK, QUOTE, Q838948}),
        frozenset({MONUMENT, STRUCTURE}),
    }
    assert BROAD not in members
    assert PAINTING not in members


def test_grouping_does_not_depend_on_triple_order():
    """The same data gives the same groups however it was loaded."""

    forward = Graph()
    backward = Graph()
    triples = list(_graph())
    for triple in triples:
        forward.add(triple)
    for triple in reversed(triples):
        backward.add(triple)

    assert (group_equivalent_classes(forward)
            == group_equivalent_classes(backward))


# ------------------------------------------------------------------
# REPRESENTATIVE CHOICE
# ------------------------------------------------------------------

def test_readable_name_is_preferred_over_an_opaque_identifier():
    """Q838948 is never chosen while a readable name is available."""

    group = next(g for g in group_equivalent_classes(_graph()) if WORK in g)

    assert group[-1] == Q838948


def test_name_starting_with_q_is_not_treated_as_opaque():
    """Quote is a word. Only a letter followed by digits is opaque."""

    group = next(g for g in group_equivalent_classes(_graph()) if WORK in g)

    assert group.index(QUOTE) < group.index(Q838948)


def test_shorter_name_wins():
    """Work beats Quote, and Monument beats Structure, on length."""

    groups = group_equivalent_classes(_graph())

    assert next(g for g in groups if WORK in g)[0] == WORK
    assert next(g for g in groups if MONUMENT in g)[0] == MONUMENT


def test_uri_settles_a_tie_between_equal_names():
    """Names of the same length resolve the same way on every run."""

    graph = Graph()
    graph.parse(data="""
        @prefix ex: <http://example.org/> .
        ex:a a ex:Beta, ex:Aqua .
    """, format="turtle")

    assert group_equivalent_classes(graph) == [[EX + "Aqua", EX + "Beta"]]


def test_preferred_class_names_the_group():
    """A class the user selected represents its group, even if opaque."""

    groups = group_equivalent_classes(_graph(), preferred=[Q838948])

    assert next(g for g in groups if WORK in g)[0] == Q838948


# ------------------------------------------------------------------
# CLASS TREE
# ------------------------------------------------------------------

def test_tree_lists_each_group_once_with_its_aliases():
    """Aliases are carried on the representative, not listed as nodes."""

    nodes = {n.uri: n for n in _flatten(extract(_graph()))}

    assert WORK in nodes
    assert QUOTE not in nodes
    assert Q838948 not in nodes
    assert set(nodes[WORK].aliases) == {QUOTE, Q838948}


def test_alias_declared_as_subclass_does_not_reappear():
    """Work subClassOf Q838948 collapses rather than leaving a 0-count child."""

    nodes = _flatten(extract(_graph()))

    assert Q838948 not in {n.uri for n in nodes}
    assert all(n.instance_count > 0 for n in nodes)


def test_children_of_a_merged_class_stay_attached():
    """Painting remains beneath the node its parent was merged into."""

    nodes = {n.uri: n for n in _flatten(extract(_graph()))}

    assert [child.uri for child in nodes[WORK].children] == [PAINTING]


def test_subclass_cycle_between_equivalent_classes_terminates():
    """Mutual subClassOf between aliases collapses to a single node."""

    graph = Graph()
    graph.parse(data="""
        @prefix ex:   <http://example.org/> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        ex:X rdfs:subClassOf ex:Y .
        ex:Y rdfs:subClassOf ex:X .
        ex:a a ex:X, ex:Y .
    """, format="turtle")

    nodes = _flatten(extract(graph))

    assert [n.uri for n in nodes] == [EX + "X"]
    assert nodes[0].aliases == [EX + "Y"]


# ------------------------------------------------------------------
# SCOPED GRAPHS
# ------------------------------------------------------------------

def test_superclass_becomes_equivalent_within_a_scope():
    """Only resources in scope remain, so Broad coincides with Work."""

    scoped = apply(_graph(), [WORK])

    groups = group_equivalent_classes(scoped, preferred=[WORK])

    assert len(groups) == 1
    assert groups[0][0] == WORK
    assert set(groups[0]) == {WORK, QUOTE, Q838948, BROAD}


# ------------------------------------------------------------------
# SCORES
# ------------------------------------------------------------------

def test_metric_details_keep_a_row_for_every_class():
    """Merging is display only: the metric still reports each alias."""

    result = PropertyCoverageMetric().evaluate(
        DatasetContext("eq", "eq", _graph())
    )

    assert {WORK, QUOTE, Q838948} <= set(result.details["class_scores"])
