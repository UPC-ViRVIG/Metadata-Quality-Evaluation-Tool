"""
tests/test_run_check.py
-----------------------
Unit tests for the check made before a run.

A profile the user chose is never replaced. Before the run, the user is
asked to confirm it when it targets no records in the data, or when
Auto would choose another profile; the warning says how many records it
covers. Auto itself is never questioned. After a confirmed run, a choice
that targets nothing is reported as not applicable, with no score.

Every test stores added profiles in a temporary folder.
"""

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph

import main
from engine.evaluation_engine import EvaluationEngine
import graph.graph_cache as graph_cache
from metrics import profile_store
from metrics.plugins.structural_completeness import (
    StructuralCompletenessMetric,
    register_profile,
)
from models.dataset_context import DatasetContext


SHAPES = b"""
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ex: <http://example.org/> .

ex:PaintingShape a sh:NodeShape ;
    sh:targetClass ex:Painting ;
    sh:property [ sh:path ex:title ; sh:minCount 1 ] .
"""

PAINTINGS = """
@prefix ex: <http://example.org/> .
ex:p1 a ex:Painting ; ex:title "A" .
ex:p2 a ex:Painting .
"""

PROXIES = """
@prefix ore: <http://www.openarchives.org/ore/terms/> .
<http://example.org/proxy> a ore:Proxy .
"""


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Keep added profiles in a temporary folder for each test."""

    monkeypatch.setattr(profile_store, "UPLOAD_DIR", tmp_path / "profiles")


def _check(data_ttl: str, profile: str | None) -> list[dict]:
    """Run the metric's check on inline data with a profile choice."""

    graph = Graph()
    graph.parse(data=data_ttl, format="turtle")
    options = {"structural_completeness": {"profile": profile}} if profile else {}
    return StructuralCompletenessMetric().check_before_run(
        DatasetContext("d", "d", graph, options=options)
    )


def test_auto_is_never_questioned():
    """Auto picks what fits, so there is nothing to confirm."""

    register_profile("museum.ttl", SHAPES)

    assert _check(PROXIES, None) == []


def test_a_fitting_choice_needs_no_confirmation():
    """Chosen, matching, and what Auto would pick: no warning."""

    profile_id = register_profile("museum.ttl", SHAPES)

    assert _check(PAINTINGS, profile_id) == []


def test_a_choice_matching_nothing_is_reported_with_both_facts():
    """No records targeted, and Auto would pick EDM: both are said."""

    profile_id = register_profile("museum.ttl", SHAPES)

    [warning] = _check(PROXIES, profile_id)

    text = " ".join(warning["lines"])
    assert "does not match" in warning["message"]
    assert "applies to 0 resource(s)" in text
    assert "not applicable" in text
    assert "Auto would choose Europeana" in text
    assert warning["action"] == "Choose another profile"


def test_a_partial_fit_states_its_coverage():
    """EDM chosen on paintings with one proxy: coverage is in the warning."""

    [warning] = _check(PAINTINGS + PROXIES, "edm")

    assert "covers only part" in warning["message"]
    assert "applies to 1 resource(s)" in warning["lines"][0]
    assert "2 of the 3 typed resource(s)" in warning["lines"][0]


def test_a_confirmed_choice_matching_nothing_is_not_applicable():
    """The run keeps the choice and gives no score, never a fallback."""

    profile_id = register_profile("museum.ttl", SHAPES)
    graph = Graph()
    graph.parse(data=PROXIES, format="turtle")

    result = StructuralCompletenessMetric().evaluate(DatasetContext(
        "d", "d", graph,
        options={"structural_completeness": {"profile": profile_id}},
    ))

    assert result.score is None
    assert result.details["not_applicable"] is True
    assert result.details["profile"] == profile_id


def test_preflight_endpoint_names_the_source_and_metric(tmp_path):
    """The API reports warnings with what the dashboard needs to act."""

    graph_cache.clear()
    profile_id = register_profile("museum.ttl", SHAPES)
    data = tmp_path / "proxies.ttl"
    data.write_text(PROXIES, encoding="utf-8")

    body = {
        "datasets": [{
            "dataset_id": "ds1", "label": "Proxies",
            "source_config": {"type": "rdf_file", "file_path": str(data)},
            "metric_options": {"structural_completeness": {"profile": profile_id}},
        }],
        "metrics": [{"metric_id": "structural_completeness"}],
    }
    response = TestClient(main.app).post("/evaluate/preflight", json=body)

    assert response.status_code == 200
    [warning] = response.json()["warnings"]
    assert warning["dataset_id"] == "ds1"
    assert warning["label"] == "Proxies"
    assert warning["metric_id"] == "structural_completeness"
    assert warning["metric_name"]


def test_engine_skips_a_dataset_it_cannot_load():
    """The run reports a load failure itself; the check stays quiet."""

    warnings = EvaluationEngine().check_before_run(
        datasets=[{"dataset_id": "x", "label": "x",
                   "source_config": {"type": "rdf_file", "path": "missing.ttl"}}],
        metrics=[StructuralCompletenessMetric()],
    )

    assert warnings == []
