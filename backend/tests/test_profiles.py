"""
tests/test_profiles.py
----------------------
Unit tests for choosing the SHACL profile of Structural Completeness.

Covers per-profile detection, the validation shared by the API and the
CLI, what a result records about the profile it used, the message when a
chosen profile matches nothing, the readable profile descriptions, and
how options travel through the API and the results archive.

Fixtures are small local files, so the suite runs without network
access.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph

import main
from export import export_cache
from export.result_archive import build_archive, parse_archive
from metrics.metric_registry import resolve_metric_options
from metrics.metrics_exceptions import MetricConfigurationError
from metrics.plugins.structural_completeness import (
    StructuralCompletenessMetric,
    describe_profiles,
    detect_profile,
)
from models.dataset_context import DatasetContext


FIXTURES = Path(__file__).parent / "evaluation" / "structural_completeness"
EDM_DATA = FIXTURES / "sc02_perfect_dataset.ttl"
CORE_DATA = FIXTURES / "sc04_core_fallback.ttl"
METRIC = "structural_completeness"


def _graph(path: Path) -> Graph:
    """Load a Turtle fixture."""

    graph = Graph()
    graph.parse(path, format="turtle")
    return graph


def _evaluate(path: Path, profile: str | None = None):
    """Run Structural Completeness, optionally with a chosen profile."""

    options = {METRIC: {"profile": profile}} if profile else {}
    context = DatasetContext("d", "d", _graph(path), options=options)
    return StructuralCompletenessMetric().evaluate(context)


# ------------------------------------------------------------------
# DETECTION
# ------------------------------------------------------------------

def test_edm_data_is_detected_as_edm():
    """edm: and ore: URIs count together towards the EDM profile."""

    assert detect_profile(_graph(EDM_DATA))[0] == "edm"


def test_data_with_no_known_vocabulary_falls_back_to_core():
    """No registered namespace present means the core profile."""

    assert detect_profile(_graph(CORE_DATA))[0] == "core"


# ------------------------------------------------------------------
# OPTION VALIDATION
# ------------------------------------------------------------------

def test_missing_options_resolve_to_auto():
    """No choice is the same as choosing automatic detection."""

    assert StructuralCompletenessMetric.resolve_options(None) == {"profile": "auto"}


def test_every_profile_is_a_valid_choice():
    """Each registered profile can be chosen by its id."""

    for profile_id in ("auto", "edm", "core"):
        resolved = StructuralCompletenessMetric.resolve_options(
            {"profile": profile_id}
        )
        assert resolved == {"profile": profile_id}


@pytest.mark.parametrize("given,fragment", [
    ({"profile": "dublin_core"}, "not a valid"),
    ({"profile": "../../etc/passwd"}, "not a valid"),
    ({"colour": "red"}, "has no option"),
])
def test_invalid_options_are_refused(given, fragment):
    """Only declared options and listed choices are accepted, never paths."""

    with pytest.raises(MetricConfigurationError, match=fragment):
        StructuralCompletenessMetric.resolve_options(given)


def test_options_for_an_unknown_metric_are_refused():
    """A typo in a metric id is reported rather than ignored."""

    with pytest.raises(MetricConfigurationError, match="unknown metric"):
        resolve_metric_options({"structural_completenes": {"profile": "edm"}})


def test_metrics_without_options_accept_none():
    """A metric that declares no options resolves to an empty set."""

    assert resolve_metric_options({"property_coverage": {}}) == {
        "property_coverage": {}
    }


# ------------------------------------------------------------------
# WHAT A RESULT RECORDS
# ------------------------------------------------------------------

def test_auto_records_the_detected_profile():
    """Detection is named as the source, and no warning is added."""

    details = _evaluate(EDM_DATA).details

    assert details["profile"] == "edm"
    assert details["profile_source"] == "detected"
    assert details["profile_name"] == "Europeana Data Model (EDM)"
    assert "warning" not in details


def test_selected_profile_matching_detection_adds_no_warning():
    """Choosing what detection would pick is not a mismatch."""

    details = _evaluate(EDM_DATA, "edm").details

    assert details["profile_source"] == "selected"
    assert "detected_profile" not in details
    assert "warning" not in details


def test_selection_differing_from_detection_is_reported():
    """Overriding detection is visible, not silent."""

    details = _evaluate(EDM_DATA, "core").details

    assert details["profile"] == "core"
    assert details["profile_source"] == "selected"
    assert details["detected_profile"] == "edm"
    assert "was selected" in details["warning"]


def test_selected_profile_matching_no_records_names_the_profile():
    """The failure says which profile matched nothing, and what fits."""

    result = _evaluate(CORE_DATA, "edm")

    assert result.status == "error"
    message = str(result.details)
    assert "Europeana Data Model (EDM)" in message
    assert "found no matching records" in message
    assert "Generic core profile" in message


# ------------------------------------------------------------------
# PROFILE DESCRIPTIONS
# ------------------------------------------------------------------

def test_profiles_describe_their_targets_and_requirements():
    """EDM lists its target classes and the properties it requires."""

    profiles = {p["id"]: p for p in describe_profiles()}
    edm = profiles["edm"]

    targets = {t["label"] for s in edm["shapes"] for t in s["targets"]}
    paths = {p["path"] for s in edm["shapes"] for p in s["properties"]}

    assert "ore:Proxy" in targets
    assert "dc:title" in paths
    assert not edm["is_fallback"]
    assert profiles["core"]["is_fallback"]


def test_alternative_requirements_are_listed_as_one():
    """Core's title-or-label rule appears once, naming every option."""

    core = next(p for p in describe_profiles() if p["id"] == "core")
    paths = [p["path"] for s in core["shapes"] for p in s["properties"]]

    assert any(" or " in path and "rdfs:label" in path for path in paths)


# ------------------------------------------------------------------
# API AND ARCHIVE
# ------------------------------------------------------------------

def test_api_lists_options_and_profiles():
    """The frontend learns the choices from the API, not from code."""

    client = TestClient(main.app)
    metrics = {m["metric_id"]: m for m in client.get("/metrics").json()}
    choices = [c["id"] for c in metrics[METRIC]["options"]["profile"]["choices"]]

    assert choices == ["auto", "edm", "core"]
    assert metrics["property_coverage"]["options"] == {}
    assert client.get("/profiles").status_code == 200


def test_api_refuses_invalid_options_with_400():
    """A bad choice is a client error, reported before anything runs."""

    client = TestClient(main.app)
    response = client.post("/evaluate", json={
        "datasets": [{
            "dataset_id": "d",
            "source_config": {"type": "rdf_file", "file_path": str(EDM_DATA)},
            "metric_options": {METRIC: {"profile": "/etc/passwd"}},
        }],
        "metrics": [{"metric_id": METRIC}],
    })

    assert response.status_code == 400
    assert "not a valid" in response.json()["detail"]


def test_archive_keeps_the_options_each_dataset_ran_with():
    """Provenance includes the profile choice, and old files have none."""

    export_cache.clear()
    options = {METRIC: {"profile": "core"}}
    archive = build_archive([{
        "dataset_id": "d", "label": "D", "metrics": [],
        "metric_options": options,
    }])

    assert parse_archive(archive)["datasets"][0]["metric_options"] == options
    legacy = parse_archive([{"dataset_id": "old", "label": "Old", "metrics": []}])
    assert legacy["datasets"][0]["metric_options"] == {}
