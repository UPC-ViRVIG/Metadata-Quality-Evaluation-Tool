"""
HTTP client wrapping the FastAPI backend endpoints.

Every function here corresponds to one backend route and translates
connection failures, timeouts, and non-2xx responses into a single
APIError, so callbacks only need to handle one exception type regardless
of what went wrong on the network or server side.
"""

import requests

BACKEND_URL = "http://127.0.0.1:8000"


class APIError(Exception):
    """Raised for any failure reaching or interpreting a backend response."""

    def __init__(self, message: str, status_code: int | None = None):
        """
        Parameters
        ----------
        message : str
            Human-readable description shown to the user.
        status_code : int | None
            The HTTP status code returned by the backend, if any.
        """
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
            # No timeout: the connectivity metric checks every distinct
            # URI in the dataset with no sampling, which can legitimately
            # take a long time on a large or host-concentrated dataset.
            # There's no intermediary (reverse proxy, etc.) between this
            # client and the backend that would cut the connection on
            # its own, so let it run for as long as it needs.
            timeout=None,
        )
    except requests.ConnectionError:
        raise APIError("Cannot reach the backend.")

    if response.status_code != 200:
        try:
            detail = response.json().get("detail", "Unknown error.")
        except ValueError:
            detail = response.text or "Unknown error."
        raise APIError(f"Evaluation failed: {detail}",
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

def export_results(datasets: list[dict], sources: list[dict]) -> tuple[str, bytes]:
    """
    POST /results/export — builds a results archive from a run.

    The archive is assembled by the backend because the full export rows
    it carries live in the backend export cache, not in the browser.

    Parameters
    ----------
    datasets
        Dataset results as received from /evaluate.
    sources
        store-sources entries, used to attach the source configuration
        and scope each dataset was evaluated under.

    Returns
    -------
    tuple
        The suggested filename and the raw archive bytes.

    Raises
    ------
    APIError
        If the backend rejects the request or cannot be reached.
    """
    payload = _build_export_payload(datasets, sources)

    try:
        response = requests.post(
            f"{BACKEND_URL}/results/export",
            json=payload,
            timeout=120,
        )
    except requests.ConnectionError:
        raise APIError("Cannot reach the backend.")
    except requests.Timeout:
        raise APIError("Export request timed out.")

    if response.status_code != 200:
        raise APIError(_detail(response, "Could not export results."),
                       status_code=response.status_code)

    disposition = response.headers.get("Content-Disposition", "")
    filename = "results.json"
    if "filename=" in disposition:
        filename = disposition.split("filename=")[1].strip('"; ')

    return filename, response.content


def import_results(archive_bytes: bytes) -> dict:
    """
    POST /results/import — reads a results archive back.

    The file is forwarded as-is so the archive is only ever parsed and
    validated in one place, the backend.

    Parameters
    ----------
    archive_bytes
        Raw contents of the uploaded archive file.

    Returns
    -------
    dict
        Structure: {schema_version, created_at, tool_version,
        dropped_metrics, datasets}. The datasets list has the same shape
        as an /evaluate response.

    Raises
    ------
    APIError
        If the file is not a readable archive or the backend cannot be
        reached.
    """
    try:
        response = requests.post(
            f"{BACKEND_URL}/results/import",
            data=archive_bytes,
            headers={"Content-Type": "application/json"},
            timeout=120,
        )
    except requests.ConnectionError:
        raise APIError("Cannot reach the backend.")
    except requests.Timeout:
        raise APIError("Import request timed out.")

    if response.status_code == 422:
        raise APIError(
            "The uploaded file is not a valid results archive.",
            status_code=422,
        )
    if response.status_code != 200:
        raise APIError(_detail(response, "Could not import the archive."),
                       status_code=response.status_code)

    return response.json()


def _detail(response, fallback: str) -> str:
    """
    Extracts the backend's error detail from a response.

    The import and export routes phrase their 400 details for the user,
    so they are surfaced verbatim rather than wrapped.

    Parameters
    ----------
    response
        The requests response object.
    fallback : str
        Message to use when no detail could be read.

    Returns
    -------
    str
        The error message to show.
    """
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = response.text
    return detail if isinstance(detail, str) and detail else fallback


def _build_export_payload(datasets: list[dict], sources: list[dict]) -> dict:
    """
    Builds the POST /results/export request body.

    Each dataset result is joined with the source it came from so the
    archive records how the data was loaded and which classes the run
    was scoped to. A source deleted since the run simply contributes no
    provenance.
    """
    by_id = {source["id"]: source for source in (sources or [])}

    entries = []
    for dataset in datasets:
        source = by_id.get(dataset.get("dataset_id"), {})
        entries.append({
            "dataset_id":    dataset.get("dataset_id", ""),
            "label":         dataset.get("label"),
            "overall_score": dataset.get("overall_score"),
            "stats":         dataset.get("stats"),
            "metrics":       dataset.get("metrics", []),
            "source_config": source.get("source_config"),
            "scope":         source.get("scope"),
        })

    return {"datasets": entries}


def upload_source_file(filename: str, content: bytes) -> dict:
    """
    POST /sources/upload — stores an RDF file on the backend.

    The file is sent to the backend rather than written to disk here, so
    that the side which reads data files is also the side that owns
    them, and the two applications need not share a filesystem.

    Parameters
    ----------
    filename
        Name of the file chosen in the browser.
    content
        Raw file contents.

    Returns
    -------
    dict
        Structure: {file_path, filename, format, size_bytes}. file_path
        is what belongs in the source configuration.

    Raises
    ------
    APIError
        If the backend rejects the file or cannot be reached.
    """
    try:
        response = requests.post(
            f"{BACKEND_URL}/sources/upload",
            params={"filename": filename},
            data=content,
            headers={"Content-Type": "application/octet-stream"},
            timeout=300,
        )
    except requests.ConnectionError:
        raise APIError("Cannot reach the backend.")
    except requests.Timeout:
        raise APIError("Upload timed out.")

    if response.status_code != 200:
        raise APIError(_detail(response, "Could not upload the file."),
                       status_code=response.status_code)

    return response.json()
