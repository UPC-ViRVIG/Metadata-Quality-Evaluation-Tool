"""
Frontend API client utilities for communicating with the evaluation backend.

This module centralizes all HTTP communication between the Dash frontend
and the FastAPI backend.

Responsibilities
----------------
- Fetch metric and dimension configuration metadata
- Trigger dataset evaluation requests
- Retrieve ontology/class hierarchy data
- Normalize backend communication errors into frontend-safe exceptions

Backend Endpoints
-----------------
GET  /metrics
    Fetch available evaluation metrics.
GET  /dimensions
    Fetch quality dimension metadata.
POST /ontology
    Extract ontology/class hierarchy information for a dataset.
POST /evaluate
    Run metric evaluation for one or more datasets.
"""

import requests

# Base URL of the FastAPI backend service.
#
# During development the frontend and backend run independently:
#
#   Dash frontend  -> localhost:8050
#   FastAPI backend -> localhost:8000
#
# All API requests are routed through this base URL.
BACKEND_URL = "http://127.0.0.1:8000"


class APIError(Exception):
    """
    Frontend-facing API communication error.

    Attributes
    ----------
    message : str
        Human-readable error description suitable for UI display.

    status_code : int | None
        HTTP status code returned by the backend.

        None if the request failed before receiving a response
        (e.g. connection failure or timeout).
    """
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message     = message
        self.status_code = status_code


def get_metrics() -> list[dict]:
    """
    Retrieve available evaluation metrics from the backend.

    Endpoint
    --------
    GET /metrics

    Returns
    -------
    list[dict]
        List of metric configuration objects.
        Structure:
            [
                {
                    "metric_id": str,
                    "name": str,
                    "description": str,
                    "dimension": str,
                    "weight": float
                }
            ]

    Raises
    ------
    APIError
        Raised when:
        - the backend is unreachable
        - the request times out
        - the backend returns a non-200 response
    """
    try:
        response = requests.get(f"{BACKEND_URL}/metrics", timeout=10)
    except requests.ConnectionError:
        raise APIError("Cannot reach the backend. Make sure the FastAPI server is running.")
    except requests.Timeout:
        raise APIError("Request to /metrics timed out.")

    if response.status_code != 200:
        raise APIError(f"Unexpected response from /metrics: {response.status_code}",
                       status_code=response.status_code)
    return response.json()


def get_dimensions() -> list[dict]:
    """
    Retrieve quality dimension metadata from the backend.

    Endpoint
    --------
    GET /dimensions

    Returns
    -------
    list[dict]
        List of dimension configuration objects.
        Structure:
            [
                {
                    "name": str,
                    "description": str,
                    "tooltip": str
                }
            ]

    Raises
    ------
    APIError
        Raised when:
        - the backend is unreachable
        - the request times out
        - the backend returns a non-200 response
    """
    try:
        response = requests.get(f"{BACKEND_URL}/dimensions", timeout=10)
    except requests.ConnectionError:
        raise APIError("Cannot reach the backend.")
    except requests.Timeout:
        raise APIError("Request to /dimensions timed out.")
    if response.status_code != 200:
        raise APIError(f"Unexpected response from /dimensions: {response.status_code}",
                       status_code=response.status_code)
    return response.json()


def get_ontology(source: dict) -> dict:
    """
    Retrieve ontology hierarchy information for a dataset.

    The ontology extraction endpoint returns a recursive RDF class
    hierarchy together with property usage statistics.

    Endpoint
    --------
    POST /ontology

    Parameters
    ----------
    source : dict
        Frontend dataset source configuration.
        Expected structure:

            {
                "id": str,
                "label": str,
                "source_config": dict
            }

    Returns
    -------
    dict
        Ontology response structure:
            {
                "dataset_id": str,
                "classes": [
                    {
                        "uri": str,
                        "label": str,
                        "instance_count": int,
                        "properties": [...],
                        "children": [...]
                    }
                ]
            }

    Raises
    ------
    APIError
        Raised when:
        - the backend is unreachable
        - ontology extraction times out
        - the backend rejects the request
        - ontology extraction fails server-side
    """
    payload = {
        "dataset_id":   source["id"],
        "source_config": source["source_config"],
    }

    try:
        response = requests.post(
            f"{BACKEND_URL}/ontology",
            json=payload,
            timeout=60,
        )
    except requests.ConnectionError:
        raise APIError("Cannot reach the backend.")
    except requests.Timeout:
        raise APIError("Ontology extraction timed out.")

    if response.status_code != 200:
        detail = response.json().get("detail", "Unknown error.")
        raise APIError(f"Ontology request failed: {detail}",
                       status_code=response.status_code)

    return response.json()


def run_evaluation(sources: list[dict], metric_ids: list[str]) -> list[dict]:
    """
    Execute dataset quality evaluation.

    Sends the selected datasets and metric configuration to the backend
    evaluation pipeline and returns computed metric results.

    Endpoint
    --------
    POST /evaluate

    Parameters
    ----------
    sources : list[dict]
        Dataset source configurations selected in the frontend.
        Each entry must contain:

            {
                "id": str,
                "label": str,
                "source_config": dict
            }
        Optional fields:
            {
                "scope": list[str]
            }
        where scope restricts evaluation to resources belonging
        to selected RDF classes.

    metric_ids : list[str]
        List of metric identifiers to execute.

    Returns
    -------
    list[dict]
        List of evaluated dataset result objects.
        Structure:

            [
                {
                    "dataset_id": str,
                    "overall_score": float | None,
                    "metrics": [...],
                    "stats": {...}
                }
            ]

    Raises
    ------
    APIError
        Raised when:
        - the backend is unreachable
        - evaluation exceeds timeout limits
        - the request payload is invalid
        - the backend returns an unexpected response
    """
    payload = _build_evaluation_payload(sources, metric_ids)

    try:
        response = requests.post(
            f"{BACKEND_URL}/evaluate",
            json=payload,
            timeout=120,
        )
    except requests.ConnectionError:
        raise APIError("Cannot reach the backend.")
    except requests.Timeout:
        raise APIError("The evaluation timed out. Try reducing the dataset size or metrics.")

    if response.status_code == 400:
        detail = response.json().get("detail", "Bad request.")
        raise APIError(f"Evaluation request rejected: {detail}", status_code=400)

    if response.status_code != 200:
        raise APIError(f"Unexpected response from /evaluate: {response.status_code}",
                       status_code=response.status_code)

    return response.json()["datasets"]


def _build_evaluation_payload(sources: list[dict], metric_ids: list[str]) -> dict:
    """
    Build the request payload for POST /evaluate.

    Parameters
    ----------
    sources : list[dict]
        Frontend dataset source configurations.
    metric_ids : list[str]
        Metric identifiers selected for execution.

    Returns
    -------
    dict
        Evaluation request payload.
        Structure:
            {
                "datasets": [
                    {
                        "dataset_id": str,
                        "label": str,
                        "source_config": dict,
                        "scope": list[str]   # optional
                    }
                ],
                "metrics": [
                    {
                        "metric_id": str
                    }
                ]
            }
    """
    datasets = []
    for source in sources:
        entry = {
            "dataset_id":    source["id"],
            "label":         source["label"],
            "source_config": source["source_config"],
        }
        scope = source.get("scope")
        if scope:
            entry["scope"] = scope
        datasets.append(entry)

    return {
        "datasets": datasets,
        "metrics":  [{"metric_id": mid} for mid in metric_ids],
    }