"""
tests/test_result_archive.py
----------------------------
Unit tests for the results archive serialiser.

Covers the round trip that the import/export feature rests on: results
and their uncapped export rows survive being written to an archive and
read back after the in-memory caches are gone. Also covers the
normalisation rules that protect the frontend, the deterministic
re-keying of dataset identifiers, and the legacy CLI output format.

The suite touches only in-memory state, so it runs without a server,
without network access, and without a graph.
"""

import json
import pytest
from datetime import datetime
from pathlib import Path

from export import export_cache
from export.result_archive import (
    SCHEMA_VERSION,
    ResultArchiveError,
    build_archive,
    parse_archive,
    restore_exports,
)


CLI_RESULTS = Path(__file__).parent.parent / "cli" / "results"

URI_ROWS = [
    {"dataset_label": "Sample", "subject": "urn:a", "property": "urn:p",
     "value": "not a uri", "position": "object", "reason": "malformed"},
    {"dataset_label": "Sample", "subject": "urn:b", "property": "urn:p",
     "value": "also bad", "position": "object", "reason": "malformed"},
]


def _dataset(dataset_id="ds1", label="Sample", score=0.75):
    """Build one evaluation-shaped dataset result."""

    return {
        "dataset_id":    dataset_id,
        "label":         label,
        "overall_score": score,
        "stats":         {"triple_count": 120, "entity_count": 30,
                          "class_count": 4},
        "source_config": {"type": "rdf_file", "file_path": "valid.ttl",
                          "format": "turtle"},
        "scope":         ["http://example.org/Painting"],
        "metrics": [
            {
                "metric_id": "foundational_format_consistency",
                "name":      "Foundational and Format Consistency",
                "score":     0.91,
                "weight":    1.0,
                "status":    "computed",
                "details":   {"scores": {"uri_validity": 0.91},
                              "uri_validity": {"invalid_count": 2}},
                "exports_available": ["uri_validity"],
                "runtime_seconds": 1.25,
            },
            {
                "metric_id": "property_coverage",
                "name":      "Property Coverage",
                "score":     0.6,
                "weight":    1.0,
                "status":    "computed",
                "details":   {"total_records": 30},
            },
        ],
    }


# ------------------------------------------------------------------
# ROUND TRIP
# ------------------------------------------------------------------

def test_archive_round_trip_preserves_results():
    """Scores, stats and metric details survive a write and a read."""

    export_cache.clear()
    archive = build_archive([_dataset(), _dataset("ds2", "Other", 0.5)])
    parsed = parse_archive(archive)

    assert len(parsed["datasets"]) == 2

    first = parsed["datasets"][0]
    assert first["label"] == "Sample"
    assert first["overall_score"] == 0.75
    assert first["stats"] == {"triple_count": 120, "entity_count": 30,
                              "class_count": 4}
    assert [m["metric_id"] for m in first["metrics"]] == [
        "foundational_format_consistency", "property_coverage"
    ]
    assert first["metrics"][0]["details"]["uri_validity"]["invalid_count"] == 2
    assert first["metrics"][0]["runtime_seconds"] == 1.25
    assert parsed["datasets"][1]["overall_score"] == 0.5


def test_archive_records_provenance():
    """The envelope carries version, timestamp, source and config."""

    export_cache.clear()
    archive = build_archive([_dataset()], created_by="cli")

    assert archive["schema_version"] == SCHEMA_VERSION
    assert archive["created_by"] == "cli"
    assert archive["tool_version"]
    datetime.fromisoformat(archive["created_at"].replace("Z", "+00:00"))

    dataset = archive["datasets"][0]
    assert dataset["source_config"]["file_path"] == "valid.ttl"
    assert dataset["scope"] == ["http://example.org/Painting"]

    assert set(archive["metrics_config"]) == {
        "foundational_format_consistency", "property_coverage"
    }
    assert archive["metrics_config"]["property_coverage"]["dimension"]


def test_export_rows_survive_cache_clear():
    """Uncapped export rows come back after the cache is emptied."""

    export_cache.clear()
    export_cache.store("ds1", "foundational_format_consistency",
                       "uri_validity", URI_ROWS)

    archive = build_archive([_dataset()])
    export_cache.clear()

    parsed = parse_archive(archive)
    restored = restore_exports(parsed["datasets"])
    new_id = parsed["datasets"][0]["dataset_id"]

    assert restored == 1
    assert export_cache.get(
        new_id, "foundational_format_consistency", "uri_validity"
    ) == URI_ROWS


# ------------------------------------------------------------------
# RE-KEYING
# ------------------------------------------------------------------

def test_import_rekeys_dataset_ids_deterministically():
    """Re-keying avoids collisions and is stable across reformatting."""

    export_cache.clear()
    archive = build_archive([_dataset(), _dataset("ds2", "Other")])

    first = parse_archive(archive)
    reformatted = json.loads(json.dumps(archive, sort_keys=True))
    second = parse_archive(reformatted)

    ids = [d["dataset_id"] for d in first["datasets"]]
    assert ids[0] != ids[1]
    assert "ds1" not in ids and "ds2" not in ids
    assert ids == [d["dataset_id"] for d in second["datasets"]]
    assert first["datasets"][0]["original_dataset_id"] == "ds1"


# ------------------------------------------------------------------
# LEGACY FORMAT
# ------------------------------------------------------------------

def test_legacy_bare_list_is_importable():
    """A bare list of dataset results reads as schema version 0."""

    legacy = [{
        "dataset_id": "local_europeana",
        "label": "Europeana EDM export",
        "overall_score": 0.68,
        "stats": {"triple_count": 74000, "entity_count": 5835,
                  "class_count": 15},
        "metrics": [{
            "metric_id": "property_coverage",
            "name": "Property Coverage",
            "score": 0.68,
            "weight": 1.0,
            "status": "computed",
            "details": {"total_records": 5835},
            "runtime_seconds": 3.0,
        }],
    }]

    parsed = parse_archive(legacy)

    assert parsed["schema_version"] == 0
    assert parsed["created_at"] is None
    assert parsed["datasets"][0]["label"] == "Europeana EDM export"
    assert parsed["datasets"][0]["metrics"][0]["exports_available"] is None


@pytest.mark.parametrize(
    "path",
    sorted(CLI_RESULTS.glob("*.json")),
    ids=lambda p: p.name,
)
def test_bundled_cli_samples_parse(path):
    """Every result file shipped with the CLI stays importable."""

    parsed = parse_archive(json.loads(path.read_text(encoding="utf-8")))
    assert parsed["datasets"]


# ------------------------------------------------------------------
# NORMALISATION
# ------------------------------------------------------------------

def test_unrenderable_metrics_are_dropped():
    """Failed and scoreless metrics are reported, not returned."""

    export_cache.clear()
    dataset = _dataset()
    dataset["metrics"] = [
        {"metric_id": "connectivity", "name": "Connectivity", "score": None,
         "weight": 1.0, "status": "error", "details": {"error": "timeout"}},
        {"metric_id": "property_coverage", "name": "Property Coverage",
         "score": None, "weight": 1.0, "status": "not_applicable",
         "details": {}},
        {"metric_id": "structural_completeness",
         "name": "Structural Completeness", "score": 0.4, "weight": 1.0,
         "status": "not_applicable", "details": {"total_records": 0}},
    ]

    parsed = parse_archive(build_archive([dataset]))
    metrics = parsed["datasets"][0]["metrics"]

    assert [m["metric_id"] for m in metrics] == ["structural_completeness"]
    assert metrics[0]["status"] == "not_applicable"
    assert len(parsed["dropped_metrics"]) == 2
    assert any("connectivity" in entry for entry in parsed["dropped_metrics"])


def test_missing_label_and_name_are_backfilled():
    """Fields the frontend indexes directly are always present."""

    export_cache.clear()
    parsed = parse_archive([{
        "dataset_id": "ds9",
        "overall_score": 0.5,
        "metrics": [{"metric_id": "property_coverage", "score": 0.5,
                     "status": "computed"}],
    }])
    dataset = parsed["datasets"][0]

    assert dataset["label"] == "ds9"
    assert dataset["metrics"][0]["name"] == "property_coverage"
    assert dataset["stats"] is None


def test_exports_available_trimmed_to_present_categories():
    """A download button is never offered without rows behind it."""

    export_cache.clear()
    export_cache.store("ds1", "foundational_format_consistency",
                       "uri_validity", URI_ROWS)

    dataset = _dataset()
    dataset["metrics"][0]["exports_available"] = [
        "uri_validity", "datatype_correctness", "language_tag_format",
        "structural_issues",
    ]

    parsed = parse_archive(build_archive([dataset]))

    assert parsed["datasets"][0]["metrics"][0]["exports_available"] == [
        "uri_validity"
    ]


# ------------------------------------------------------------------
# ERROR CASES
# ------------------------------------------------------------------

def test_newer_schema_version_raises():
    """An archive from a future version is refused, not guessed at."""

    with pytest.raises(ResultArchiveError, match="newer"):
        parse_archive({"schema_version": 99, "datasets": [{}]})


def test_garbage_payload_raises():
    """Anything that is not an archive is refused with a message."""

    with pytest.raises(ResultArchiveError):
        parse_archive("not an archive")
    with pytest.raises(ResultArchiveError, match="datasets"):
        parse_archive({"schema_version": 1})
    with pytest.raises(ResultArchiveError, match="no datasets"):
        parse_archive({"schema_version": 1, "datasets": []})


def test_export_requires_datasets():
    """Building an archive from nothing is an error, not an empty file."""

    with pytest.raises(ResultArchiveError, match="Nothing to export"):
        build_archive([])


def test_missing_details_becomes_an_empty_dict():
    """Renderers reach into details unguarded, so it is never None."""

    export_cache.clear()
    parsed = parse_archive([{
        "dataset_id": "ds9",
        "label": "No details",
        "overall_score": 0.5,
        "metrics": [{"metric_id": "property_coverage", "name": "Coverage",
                     "score": 0.5, "status": "computed", "details": None}],
    }])

    assert parsed["datasets"][0]["metrics"][0]["details"] == {}
