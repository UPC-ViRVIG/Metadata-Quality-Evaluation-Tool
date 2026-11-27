"""
tests/test_structural_scoring.py
--------------------------------
Unit tests for how Structural Completeness scores a record.

Each record is scored only against the shapes that target it. These
tests pin that rule with the painting and sculpture example used to
agree it, and the details it depends on: a constraint broken by several
values counts once, subclass instances are targeted, every severity
counts equally, and the core profile, a single shape, is unaffected.

Shapes are written inline, so the suite runs without network access.
"""

from pathlib import Path

import pytest
from pyshacl import validate
from rdflib import Graph

from metrics import profile_store
from metrics.plugins.structural_completeness import (
    SCORING_VERSION,
    StructuralCompletenessMetric,
    compute_per_record_scores,
)
from metrics.shacl_shapes import failed_constraints, record_constraints
from models.dataset_context import DatasetContext


PREFIXES = """
@prefix sh:   <http://www.w3.org/ns/shacl#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <http://example.org/> .
"""

# Paintings must have a title, creator and date; sculptures a material
# and dimensions. Five requirements in the profile, never more than three
# for any one record.
ART_SHAPES = PREFIXES + """
ex:PaintingShape a sh:NodeShape ;
    sh:targetClass ex:Painting ;
    sh:property [ sh:path ex:title ;   sh:minCount 1 ] ;
    sh:property [ sh:path ex:creator ; sh:minCount 1 ] ;
    sh:property [ sh:path ex:date ;    sh:minCount 1 ] .

ex:SculptureShape a sh:NodeShape ;
    sh:targetClass ex:Sculpture ;
    sh:property [ sh:path ex:material ;   sh:minCount 1 ;
                  sh:severity sh:Warning ] ;
    sh:property [ sh:path ex:dimensions ; sh:minCount 1 ] .
"""

FIXTURES = Path(__file__).parent / "evaluation" / "structural_completeness"


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """
    Keep profiles users added out of these tests.

    Auto prefers added profiles, so a profile in backend/uploads that
    happens to match a fixture would otherwise change the outcome.
    """
    monkeypatch.setattr(profile_store, "UPLOAD_DIR", tmp_path / "profiles")


def _scores(shapes_ttl: str, data_ttl: str) -> dict[str, float]:
    """Score every targeted record the way the metric does."""

    shapes = Graph()
    shapes.parse(data=shapes_ttl, format="turtle")
    data = Graph()
    data.parse(data=PREFIXES + data_ttl, format="turtle")

    _, results, _ = validate(data, shacl_graph=shapes, advanced=True,
                             inference="none")
    scores = compute_per_record_scores(
        record_constraints(shapes, data), failed_constraints(results)
    )
    return {uri.rsplit("/", 1)[-1]: score for uri, score in scores.items()}


# ------------------------------------------------------------------
# THE AGREED RULE
# ------------------------------------------------------------------

def test_each_record_is_scored_only_against_its_own_class():
    """The worked example: out of 3 for paintings, out of 2 for sculptures."""

    scores = _scores(ART_SHAPES, """
        ex:p_complete a ex:Painting ;
            ex:title "A" ; ex:creator "B" ; ex:date "1900" .
        ex:p_no_date a ex:Painting ;
            ex:title "A" ; ex:creator "B" .
        ex:s_no_dimensions a ex:Sculpture ; ex:material "bronze" .
        ex:s_nothing a ex:Sculpture .
    """)

    assert scores == {
        "p_complete": 1.0,
        "p_no_date": 0.6667,
        "s_no_dimensions": 0.5,
        "s_nothing": 0.0,
    }


def test_a_record_missing_everything_it_needs_scores_zero():
    """Requirements of other classes are no longer counted as met."""

    assert _scores(ART_SHAPES, "ex:s a ex:Sculpture .") == {"s": 0.0}


def test_a_warning_counts_as_much_as_a_violation():
    """Severity does not weight the score."""

    scores = _scores(ART_SHAPES, """
        ex:missing_warning   a ex:Sculpture ; ex:dimensions "1m" .
        ex:missing_violation a ex:Sculpture ; ex:material "stone" .
    """)

    assert scores["missing_warning"] == scores["missing_violation"] == 0.5


# ------------------------------------------------------------------
# DETAILS OF COUNTING
# ------------------------------------------------------------------

def test_several_bad_values_break_one_constraint_once():
    """Three wrongly typed dates are one failed constraint, not three."""

    scores = _scores(PREFIXES + """
        ex:Shape a sh:NodeShape ;
            sh:targetClass ex:Painting ;
            sh:property [ sh:path ex:title ; sh:minCount 1 ] ;
            sh:property [ sh:path ex:date ;  sh:datatype xsd:gYear ] .
    """, """
        ex:p a ex:Painting ; ex:title "A" ; ex:date "x", "y", "z" .
    """)

    assert scores == {"p": 0.5}


def test_instances_of_a_subclass_are_targeted():
    """sh:targetClass covers subclasses, as SHACL defines."""

    scores = _scores(ART_SHAPES, """
        ex:OilPainting rdfs:subClassOf ex:Painting .
        ex:p a ex:OilPainting ; ex:title "A" .
    """)

    assert scores == {"p": 0.3333}


def test_a_record_targeted_by_two_shapes_meets_both():
    """A resource that is both a painting and a sculpture is out of 5."""

    scores = _scores(ART_SHAPES, """
        ex:x a ex:Painting, ex:Sculpture ;
            ex:title "A" ; ex:creator "B" ; ex:date "1900" ; ex:material "m" .
    """)

    assert scores == {"x": 0.8}


# ------------------------------------------------------------------
# REGISTERED PROFILES
# ------------------------------------------------------------------

def test_core_profile_scores_are_unchanged():
    """Core has a single shape, so the new rule gives the same result."""

    graph = Graph()
    graph.parse(FIXTURES / "sc04_core_fallback.ttl", format="turtle")

    result = StructuralCompletenessMetric().evaluate(
        DatasetContext("d", "d", graph)
    )

    assert result.score == 0.8333
    assert result.details["scoring_version"] == SCORING_VERSION


def test_edm_record_is_scored_out_of_its_own_requirements():
    """An empty ore:Proxy used to score 0.6667 against all 15 rules."""

    graph = Graph()
    graph.parse(data="""
        @prefix ore: <http://www.openarchives.org/ore/terms/> .
        <http://example.org/proxy> a ore:Proxy .
    """, format="turtle")

    result = StructuralCompletenessMetric().evaluate(
        DatasetContext("d", "d", graph)
    )

    assert result.score == 0.0
