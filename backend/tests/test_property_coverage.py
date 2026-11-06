"""
tests/test_property_coverage.py
-------------------------------
Unit tests for how Property Coverage treats a scoped graph.

Scope filtering happens once, in the engine. Property Coverage must not
filter again, or it reports fewer classes than the other metrics for
the same scoped evaluation.

The fixture is a small local file, so the suite runs without network
access.
"""

from pathlib import Path

from rdflib import Graph, RDF

from graph.scope_filter import apply
from metrics.plugins.foundational_format_consistency import (
    FoundationalFormatConsistencyMetric,
)
from metrics.plugins.property_coverage import PropertyCoverageMetric
from models.dataset_context import DatasetContext


FIXTURE = (
    Path(__file__).parent / "evaluation" / "ontology"
    / "eq01_equivalent_classes.ttl"
)

WORK = "http://example.org/Work"
BROAD = "http://example.org/Broad"


def _scoped_context() -> DatasetContext:
    """Scope the fixture to Work, as the engine would."""

    full = Graph()
    full.parse(FIXTURE, format="turtle")
    return DatasetContext(
        "pc", "pc", apply(full, [WORK]), scope=[WORK], full_graph=full
    )


def test_scoped_run_reports_every_type_of_the_scoped_resources():
    """Broad is not selected, but the selected resources carry it."""

    context = _scoped_context()
    types = {str(t) for t in context.graph.objects(None, RDF.type)}

    result = PropertyCoverageMetric().evaluate(context)

    assert set(result.details["class_scores"]) == types
    assert BROAD in result.details["class_scores"]


def test_scoped_run_reports_the_same_classes_as_other_metrics():
    """Property Coverage and Format Consistency agree on the class rows."""

    context = _scoped_context()

    coverage = PropertyCoverageMetric().evaluate(context)
    consistency = FoundationalFormatConsistencyMetric().evaluate(context)

    assert (set(coverage.details["class_scores"])
            == set(consistency.details["uri_validity"]["class_violation_rates"]))
