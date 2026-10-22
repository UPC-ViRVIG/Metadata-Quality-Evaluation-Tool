"""
export/result_archive.py
------------------------
Serialisation of evaluation results to and from a portable archive.

An archive is a self-describing JSON document that carries everything
needed to render a past evaluation again: the per-dataset scores and
metric details, the provenance of the run (source configuration, scope,
timestamp, tool version, metric configuration snapshot), and the
complete uncapped export rows that otherwise live only in the in-memory
export cache.

This module is the single implementation used by both the API and the
CLI, so the two entry points cannot drift into separate formats.

Importing is deliberately lenient about missing values and strict about
structure. Metrics that cannot be rendered — no numeric score, or a
failed status — are recorded in the archive file but filtered out of the
parsed result, because the frontend turns a single failed metric into a
whole-view error state. The file stays faithful; only what is handed
back to the caller is filtered.
"""

import hashlib
import json
from datetime import datetime, timezone

from config.config_loader import load_metrics_config
from export import export_cache

SCHEMA_VERSION = 1
TOOL_NAME = "metadata-quality-evaluation-tool"
TOOL_VERSION = "1.0.0"

_STAT_KEYS = ("triple_count", "entity_count", "class_count")


class ResultArchiveError(ValueError):
    """
    Raised when a payload cannot be read as a results archive.

    The message is written to be shown to the user directly, because
    every case is something they can act on: wrong file, empty file, or
    an archive from a newer version of the tool.
    """


# ============================================================================
# Building
# ============================================================================

def build_archive(datasets: list[dict], created_by: str = "api") -> dict:
    """
    Build a portable archive from evaluation results.

    Export rows are read out of the export cache for every metric and
    category the dataset reports, which is what makes CSV downloads
    possible again after the archive is imported into a fresh process.

    Parameters
    ----------
    datasets : list of dict
        Dataset results in the shape the evaluate response uses:
        dataset_id, label, overall_score, stats, metrics. May also
        carry source_config and scope, which are stored as provenance.
    created_by : str, default='api'
        Which entry point produced the archive, 'api' or 'cli'.

    Returns
    -------
    dict
        The archive document, ready to be serialised as JSON.

    Raises
    ------
    ResultArchiveError
        If no dataset results were provided.
    """
    if not datasets:
        raise ResultArchiveError(
            "Nothing to export: no dataset results were provided."
        )

    metrics_config = load_metrics_config()
    archive_datasets = []
    metric_ids_seen = set()

    for dataset in datasets:
        dataset_id = str(dataset.get("dataset_id") or "")
        metrics = []
        exports = {}

        for metric in dataset.get("metrics") or []:
            metric_id = metric.get("metric_id")
            if not metric_id:
                continue

            metric_ids_seen.add(metric_id)
            metric_exports = _collect_metric_exports(dataset_id, metric_id)
            if metric_exports:
                exports[metric_id] = metric_exports

            entry = {
                "metric_id": metric_id,
                "name":      metric.get("name") or metric_id,
                "score":     metric.get("score"),
                "weight":    metric.get("weight", 1.0),
                "status":    metric.get("status", "computed"),
                "details":   metric.get("details"),
            }
            if metric.get("exports_available"):
                entry["exports_available"] = list(metric["exports_available"])
            if metric.get("runtime_seconds") is not None:
                entry["runtime_seconds"] = metric["runtime_seconds"]

            metrics.append(entry)

        archive_datasets.append({
            "dataset_id":    dataset_id,
            "label":         dataset.get("label"),
            "overall_score": dataset.get("overall_score"),
            "stats":         dataset.get("stats"),
            "source_config": dataset.get("source_config"),
            "scope":         dataset.get("scope"),
            "metrics":       metrics,
            "exports":       exports,
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "tool":           TOOL_NAME,
        "tool_version":   TOOL_VERSION,
        "created_at":     _utc_now_iso(),
        "created_by":     created_by,
        "metrics_config": {
            metric_id: config
            for metric_id, config in metrics_config.items()
            if metric_id in metric_ids_seen
        },
        "datasets": archive_datasets,
    }


def _collect_metric_exports(dataset_id: str, metric_id: str) -> dict:
    """
    Read every cached export category for one dataset and metric.

    The cache itself is asked which categories exist rather than
    trusting the metric's exports_available field, so an archive never
    claims export data it does not carry.

    Parameters
    ----------
    dataset_id : str
    metric_id : str

    Returns
    -------
    dict
        Mapping of category name to its complete row list. Empty when
        the metric stored nothing.
    """
    categories = {}
    for category in export_cache.list_categories(dataset_id, metric_id):
        rows = export_cache.get(dataset_id, metric_id, category)
        if rows is not None:
            categories[category] = rows
    return categories


# ============================================================================
# Parsing
# ============================================================================

def parse_archive(payload: dict | list) -> dict:
    """
    Validate, normalise and re-key an archive for display.

    Dataset identifiers are replaced with deterministic imported ids so
    that an archive can never collide with a live run's identifier, and
    so that re-importing the same file overwrites its export cache
    entries instead of accumulating duplicates.

    Parameters
    ----------
    payload : dict | list
        A parsed archive document, or a bare list of dataset results as
        written by older CLI runs (treated as schema version 0).

    Returns
    -------
    dict
        Structure:

            {
                "schema_version":  int,
                "created_at":      str | None,
                "tool_version":    str | None,
                "metrics_config":  dict,
                "datasets":        list[dict],
                "dropped_metrics": list[str]
            }

        Each dataset keeps its exports so they can be restored, and
        carries original_dataset_id alongside the re-keyed dataset_id.

    Raises
    ------
    ResultArchiveError
        If the payload is not an archive, carries no datasets, or
        declares a schema version this tool cannot read.
    """
    if isinstance(payload, list):
        payload = _upgrade_legacy(payload)
    elif not isinstance(payload, dict):
        raise ResultArchiveError(
            "Archive must be a JSON object or a list of dataset results."
        )

    schema_version = payload.get("schema_version", 0)
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise ResultArchiveError("Archive schema version must be a number.")
    if schema_version > SCHEMA_VERSION:
        raise ResultArchiveError(
            f"Archive schema version {schema_version} is newer than this "
            f"tool supports ({SCHEMA_VERSION})."
        )

    raw_datasets = payload.get("datasets")
    if not isinstance(raw_datasets, list):
        raise ResultArchiveError("Archive is missing the datasets list.")
    if not raw_datasets:
        raise ResultArchiveError("Archive contains no datasets.")

    metrics_config = payload.get("metrics_config")
    if not isinstance(metrics_config, dict):
        metrics_config = {}

    digest = _archive_digest(payload)
    datasets = []
    dropped_metrics = []

    for index, raw in enumerate(raw_datasets):
        if not isinstance(raw, dict):
            raise ResultArchiveError(
                "Archive contains a dataset entry that is not an object."
            )
        dataset, dropped = _normalize_dataset(
            raw, index, digest, metrics_config
        )
        datasets.append(dataset)
        dropped_metrics.extend(dropped)

    return {
        "schema_version":  schema_version,
        "created_at":      payload.get("created_at"),
        "tool_version":    payload.get("tool_version"),
        "metrics_config":  metrics_config,
        "datasets":        datasets,
        "dropped_metrics": dropped_metrics,
    }


def restore_exports(datasets: list[dict]) -> int:
    """
    Write an imported archive's export rows into the export cache.

    Called after parse_archive so that the existing CSV export endpoint
    serves imported datasets exactly as it serves freshly evaluated
    ones, keyed by the re-keyed dataset identifier.

    Parameters
    ----------
    datasets : list of dict
        Normalised datasets returned by parse_archive.

    Returns
    -------
    int
        Number of metric and category row sets restored.
    """
    restored = 0
    for dataset in datasets:
        dataset_id = dataset["dataset_id"]
        for metric_id, categories in (dataset.get("exports") or {}).items():
            for category, rows in categories.items():
                export_cache.store(dataset_id, metric_id, category, rows)
                restored += 1
    return restored


# ============================================================================
# Normalisation helpers
# ============================================================================

def _upgrade_legacy(payload: list) -> dict:
    """
    Wrap a bare list of dataset results in a schema version 0 envelope.

    Older CLI runs wrote the dataset list directly, with no envelope and
    no provenance. Those files stay importable by being lifted into the
    current shape with the unknown fields left empty.

    Parameters
    ----------
    payload : list
        Dataset results as written by an older CLI run.

    Returns
    -------
    dict
        An archive document with schema version 0.
    """
    return {
        "schema_version": 0,
        "tool":           None,
        "tool_version":   None,
        "created_at":     None,
        "created_by":     "cli",
        "metrics_config": {},
        "datasets":       payload,
    }


def _normalize_dataset(
    raw: dict,
    index: int,
    digest: str,
    metrics_config: dict,
) -> tuple[dict, list[str]]:
    """
    Normalise one archived dataset and give it an imported identifier.

    Parameters
    ----------
    raw : dict
        The archived dataset entry.
    index : int
        Position of the dataset within the archive, used in the new id.
    digest : str
        Short hash of the archive, used in the new id.
    metrics_config : dict
        The archive's metric configuration snapshot, used to recover
        display names when a metric entry has none.

    Returns
    -------
    tuple
        The normalised dataset and the list of dropped metric
        descriptions.
    """
    original_id = raw.get("dataset_id")
    original_id = str(original_id) if original_id else None

    label = raw.get("label")
    if not isinstance(label, str) or not label.strip():
        label = original_id or f"Imported dataset {index + 1}"

    source_config = raw.get("source_config")
    exports = _normalize_exports(raw.get("exports"))
    metrics = []
    dropped = []

    for raw_metric in raw.get("metrics") or []:
        if not isinstance(raw_metric, dict):
            continue
        metric = _normalize_metric(raw_metric, exports, metrics_config)
        if metric is None:
            dropped.append(
                f"{label} / {raw_metric.get('metric_id') or 'unknown'} "
                f"({raw_metric.get('status') or 'no score'})"
            )
        else:
            metrics.append(metric)

    dataset = {
        "dataset_id":          f"imported_{digest}_{index}",
        "original_dataset_id": original_id,
        "label":               label,
        "overall_score":       _numeric_or_none(raw.get("overall_score")),
        "stats":               _normalize_stats(raw.get("stats")),
        "source_config":       source_config
                               if isinstance(source_config, dict) else None,
        "scope":               _normalize_scope(raw.get("scope")),
        "metrics":             metrics,
        "exports":             exports,
    }
    return dataset, dropped


def _normalize_metric(
    raw: dict,
    exports: dict,
    metrics_config: dict,
) -> dict | None:
    """
    Normalise one archived metric result, or reject it as unrenderable.

    A metric is kept only when it has an identifier, a numeric score and
    a status other than error. Everything else is reported to the caller
    as dropped, because the frontend performs arithmetic on the score
    without guarding for None and escalates a failed metric to a
    whole-view error.

    Parameters
    ----------
    raw : dict
        The archived metric entry.
    exports : dict
        Normalised exports for the dataset, used to trim
        exports_available to the categories actually present.
    metrics_config : dict
        The archive's metric configuration snapshot.

    Returns
    -------
    dict | None
        The normalised metric, or None when it cannot be rendered.
    """
    metric_id = raw.get("metric_id")
    if not isinstance(metric_id, str) or not metric_id:
        return None

    score = _numeric_or_none(raw.get("score"))
    status = raw.get("status") or "computed"
    if score is None or status == "error":
        return None

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        name = metrics_config.get(metric_id, {}).get("name") or metric_id

    available = sorted(exports.get(metric_id, {}).keys())
    details = raw.get("details")

    return {
        "metric_id":         metric_id,
        "name":              name,
        "score":             score,
        "weight":            _numeric_or_none(raw.get("weight")) or 1.0,
        "status":            str(status),
        # An empty dict rather than None: the renderers reach into
        # details without guarding, and a live result always has one.
        "details":           details if isinstance(details, dict) else {},
        "exports_available": available or None,
        "runtime_seconds":   _numeric_or_none(raw.get("runtime_seconds")),
    }


def _normalize_exports(raw) -> dict:
    """
    Keep only export entries shaped as metric, category, row list.

    Parameters
    ----------
    raw : any
        The archived exports block.

    Returns
    -------
    dict
        Mapping of metric id to category to list of rows.
    """
    if not isinstance(raw, dict):
        return {}

    exports = {}
    for metric_id, categories in raw.items():
        if not isinstance(metric_id, str) or not isinstance(categories, dict):
            continue
        kept = {
            category: rows
            for category, rows in categories.items()
            if isinstance(category, str) and isinstance(rows, list)
        }
        if kept:
            exports[metric_id] = kept
    return exports


def _normalize_stats(raw) -> dict | None:
    """
    Keep the three graph statistics when all of them are usable.

    All three are required together because the statistics response
    model has no room for a partial set, and a fabricated zero would
    read as a real measurement.

    Parameters
    ----------
    raw : any
        The archived stats block.

    Returns
    -------
    dict | None
        Statistics with integer values, or None when any is missing or
        not numeric.
    """
    if not isinstance(raw, dict):
        return None

    stats = {}
    for key in _STAT_KEYS:
        value = raw.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        stats[key] = int(value)
    return stats


def _normalize_scope(raw) -> list[str] | None:
    """
    Keep a scope as a list of class URI strings.

    Parameters
    ----------
    raw : any
        The archived scope value.

    Returns
    -------
    list of str or None
        The class URIs, or None when the scope is absent or empty.
    """
    if not isinstance(raw, list):
        return None
    uris = [item for item in raw if isinstance(item, str) and item]
    return uris or None


def _numeric_or_none(value) -> float | None:
    """
    Return a value as a float when it is a real number.

    Parameters
    ----------
    value : any
        The value to coerce.

    Returns
    -------
    float | None
        The value as a float, or None when it is not numeric.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _archive_digest(payload: dict) -> str:
    """
    Compute a short, stable hash of an archive document.

    Keys are sorted so that reformatting a file by hand does not change
    the identifiers its datasets receive on import.

    Parameters
    ----------
    payload : dict
        The archive document.

    Returns
    -------
    str
        First eight hexadecimal characters of the SHA-256 digest.
    """
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]


def _utc_now_iso() -> str:
    """
    Return the current UTC time as an ISO 8601 string in seconds.

    Returns
    -------
    str
        Timestamp such as 2026-09-25T14:03:11Z.
    """
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
