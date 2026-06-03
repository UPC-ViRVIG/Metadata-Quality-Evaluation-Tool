import requests

BACKEND_URL = "http://127.0.0.1:8000"


class APIError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message     = message
        self.status_code = status_code


def get_metrics() -> list[dict]:
    """
    GET /metrics — fetches available metrics on sidebar startup.
    Returns list of {metric_id, name, description, dimension, weight}.
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
    GET /dimensions — fetches quality dimension descriptions on startup.
    Returns list of {name, description, tooltip}.
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


def get_export_csv(dataset_id: str, metric_id: str, category: str) -> bytes:
    """
    GET /export/{dataset_id}/{metric_id}/{category}

    Fetches a CSV export from the backend export cache for the given
    dataset, metric, and category combination.

    Parameters
    ----------
    dataset_id : str
        The dataset UUID sent in the evaluate payload.
    metric_id : str
        The metric identifier (e.g. 'foundational_format_consistency').
    category : str
        The export category (e.g. 'uri_validity', 'datatype_correctness').

    Returns
    -------
    bytes
        Raw CSV content.

    Raises
    ------
    APIError
        If the endpoint returns a non-200 status or is unreachable.
    """
    try:
        response = requests.get(
            f"{BACKEND_URL}/export/{dataset_id}/{metric_id}/{category}",
            timeout=30,
        )
    except requests.ConnectionError:
        raise APIError("Cannot reach the backend.")
    except requests.Timeout:
        raise APIError("Export request timed out.")
    if response.status_code == 404:
        raise APIError(
            f"No export available for {metric_id}/{category}.",
            status_code=404,
        )
    if response.status_code != 200:
        raise APIError(
            f"Unexpected response from /export: {response.status_code}",
            status_code=response.status_code,
        )
    return response.content


def get_ontology(source: dict) -> dict:
    """
    POST /ontology — fetches the class/property tree for a single source.

    Called lazily when the user expands a source card in the sidebar.
    The backend caches the parsed graph so this is cheap if /evaluate
    has already been called on the same source.

    Parameters
    ----------
    source
        A single store-sources entry with 'id', 'label', 'source_config'.

    Returns
    -------
    dict
        {dataset_id, classes: [{uri, label, instance_count, properties, children}]}
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
    POST /evaluate — runs evaluation and returns the raw datasets list.

    Parameters
    ----------
    sources
        Selected store-sources entries. Each must have 'id', 'label',
        'source_config', and optionally 'scope' (list of class URIs or None).
    metric_ids
        List of metric_id strings.
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
    Builds the POST /evaluate request body.

    Includes scope per dataset when set — the backend filters the graph
    to only triples whose subject is an instance of the selected classes.
    Omitting scope (or passing None / []) evaluates the full graph.
    """
    datasets = []
    for source in sources:
        entry = {
            "dataset_id":    source["id"],
            "label":         source["label"],
            "source_config": source["source_config"],
        }
        # Only include scope when the user has made a selection
        scope = source.get("scope")
        if scope:
            entry["scope"] = scope
        datasets.append(entry)

    return {
        "datasets": datasets,
        "metrics":  [{"metric_id": mid} for mid in metric_ids],
    }