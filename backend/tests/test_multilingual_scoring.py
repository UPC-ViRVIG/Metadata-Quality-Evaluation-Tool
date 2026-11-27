"""
tests/test_multilingual_scoring.py
----------------------------------
Unit tests for which literals Multilingual Labeling Coverage counts.

Only textual literals can carry a language, so numbers, dates and
coordinates must not count as untagged text. These tests pin that rule
with the DBpedia resource it was reported on.

The fixture is a small local file, so the suite runs without network
access.
"""

from pathlib import Path

from rdflib import Graph

from metrics.plugins.multilingual_labeling_coverage import (
    SCORING_VERSION,
    MultilingualLabelingCoverageMetric,
)
from models.dataset_context import DatasetContext


FIXTURES = Path(__file__).parent / "evaluation" / "multilingual_labeling_coverage"


def _evaluate(name: str):
    """Run the metric on one fixture file."""

    graph = Graph()
    graph.parse(FIXTURES / name, format="turtle")
    return MultilingualLabelingCoverageMetric().evaluate(
        DatasetContext("d", "d", graph)
    )


def test_non_textual_literals_are_not_counted():
    """Numbers, dates and geometries no longer count as untagged text."""

    result = _evaluate("mlc07_non_textual_literals.ttl")

    assert result.score == 0.5833
    assert result.details["general_info"]["tagged_literal_count"] == 3
    assert result.details["general_info"]["untagged_literal_count"] == 1
    assert result.details["scoring_version"] == SCORING_VERSION


def test_textual_fixtures_are_unchanged():
    """Fixtures holding only text score as their comments state."""

    assert _evaluate("mlc01_typical_multilingual.ttl").score == 0.4167
    assert _evaluate("mlc04_no_literals.ttl").score == 0.5
