import threading
from typing import Optional

_cache: dict[tuple[str, str, str], list[dict]] = {}
_lock = threading.Lock()


def store(
    dataset_id: str,
    metric_id: str,
    category: str,
    rows: list[dict],
) -> None:
    """
    Store export rows for a given dataset, metric, and category.

    Called by metric plugins during evaluate() after computing the
    full (uncapped) violation or result list for a category.

    Parameters
    ----------
    dataset_id : str
        The dataset identifier from the evaluation request.
    metric_id : str
        The metric plugin identifier, e.g. foundational_format_consistency.
    category : str
        The export category within the metric, e.g. uri_validity.
    rows : list of dict
        The complete list of rows to export. Each dict must have
        consistent keys — they become the CSV column headers.

    Returns
    -------
    None
    """
    key = (dataset_id, metric_id, category)
    with _lock:
        _cache[key] = rows


def get(
    dataset_id: str,
    metric_id: str,
    category: str,
) -> Optional[list[dict]]:
    """
    Retrieve export rows for a given dataset, metric, and category.

    Called by the export endpoint when the user requests a CSV download.

    Parameters
    ----------
    dataset_id : str
    metric_id : str
    category : str

    Returns
    -------
    list of dict or None
        The stored rows, or None if no export data exists for this
        combination (e.g. evaluate has not been called yet, or the
        metric does not support export for this category).
    """
    key = (dataset_id, metric_id, category)
    with _lock:
        return _cache.get(key)


def list_categories(dataset_id: str, metric_id: str) -> list[str]:
    """
    Return the list of available export categories for a given dataset
    and metric.

    Used by the router to populate the exports_available field in the
    evaluate response, so the frontend knows which download buttons to
    show.

    Parameters
    ----------
    dataset_id : str
    metric_id : str

    Returns
    -------
    list of str
        Sorted list of category names that have stored export data.
    """
    with _lock:
        return sorted(
            key[2]
            for key in _cache
            if key[0] == dataset_id and key[1] == metric_id
        )


def clear_dataset(dataset_id: str) -> None:
    """
    Remove all export data for a given dataset.

    Should be called when the dataset's graph cache entry is invalidated
    (e.g. after re-upload) to prevent stale export data from being served.

    Parameters
    ----------
    dataset_id : str

    Returns
    -------
    None
    """
    with _lock:
        keys = [k for k in _cache if k[0] == dataset_id]
        for k in keys:
            del _cache[k]


def clear() -> None:
    """
    Remove all export data from the cache.

    Useful for testing.

    Returns
    -------
    None
    """
    with _lock:
        _cache.clear()