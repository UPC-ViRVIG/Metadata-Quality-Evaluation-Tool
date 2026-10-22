"""
api/evaluation_controller.py
----------------------------
HTTP interface for the evaluation backend.

This module deliberately contains no evaluation logic. It validates and
deserialises incoming requests, delegates to the Evaluation Engine or the
Ontology Extractor, and serialises the outcome into response models.

Endpoints
---------
GET /metrics
    Implemented metrics and their display metadata, read from
    metrics_config.json.
GET /dimensions
    The quality dimensions that metrics are grouped into.
POST /ontology
    Lazy class-hierarchy extraction, used to configure scope filtering.
POST /evaluate
    Runs the selected metrics over the requested datasets.
GET /export/{dataset_id}/{metric_id}/{category}
    Streams the cached export rows for one metric category as CSV.
POST /results/export
    Serialises evaluation results into a portable results archive.
POST /results/import
    Reads a results archive back and restores its export rows.
POST /sources/upload
    Stores an RDF file uploaded from the dashboard as a local source.

Graph loading, caching, and scope filtering all happen further down the
stack — the router never touches a graph directly.
"""

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
import io
import json
import re

from engine.evaluation_engine import EvaluationEngine
from datasource.datasource_factory import DataSourceFactory
from datasource.upload_store import save as save_upload, UploadError
from graph.graph_cache import get_or_load
from graph.ontology_extractor import extract

from export.export_cache import get as get_export
from export.csv_writer import rows_to_csv
from export.result_archive import (
    build_archive,
    parse_archive,
    restore_exports,
    ResultArchiveError,
)

from models.request import (
    EvaluationRequest,
    OntologyRequest,
    ResultExportRequest,
)
from models.response import (
    EvaluationResponse,
    DatasetEvaluationResponse,
    DatasetStatsResponse,
    MetricResultResponse,
    DimensionConfigResponse,
    MetricConfigResponse,
    OntologyResponse,
    ClassNodeResponse,
    ResultImportResponse,
    FileUploadResponse,
)

from config.config_loader import load_metrics_config, load_dimensions_config
from metrics.metric_registry import METRIC_REGISTRY

router = APIRouter()
engine = EvaluationEngine()

@router.get("/metrics", response_model=list[MetricConfigResponse])
def get_metrics():
    """
    Returns the list of available metrics from metrics_config.json.
    Used by the frontend to populate the metric selection checklist.
    """
    metric_config = load_metrics_config()
    return [
        MetricConfigResponse(
            metric_id=metric_id,
            name=config["name"],
            description=config["description"],
            dimension=config["dimension"],
            weight=config["weight"],
        )
        for metric_id, config in metric_config.items()
    ]


@router.get("/dimensions", response_model=list[DimensionConfigResponse])
def get_dimensions():
    """
    Returns the list of quality dimensions from metrics_config.json.
    Used by the frontend to populate the metric accordion headers.
    """
    dimensions = load_dimensions_config()
    return [
        DimensionConfigResponse(
            name=name,
            description=config["description"],
            tooltip=config["tooltip"],
        )
        for name, config in dimensions.items()
    ]

@router.post("/ontology", response_model=OntologyResponse)
def get_ontology(request: OntologyRequest):
    """
    Returns the class hierarchy found in the dataset.

    Uses get_or_load so that a subsequent /evaluate call for the same
    source reuses the cached graph at zero cost.

    Parameters
    ----------
    request : OntologyRequest

    Returns
    -------
    OntologyResponse

    Raises
    ------
    HTTPException 422
        If the dataset cannot be loaded.
    """
    source_config = request.source_config.model_dump()

    try:
        def _load():
            datasource = DataSourceFactory.create(source_config)
            return datasource.load()

        graph = get_or_load(source_config, _load)

    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Could not load dataset: {exc}",
        ) from exc

    class_nodes = extract(graph)

    return OntologyResponse(
        dataset_id=request.dataset_id,
        classes=[ClassNodeResponse.from_domain(node) for node in class_nodes],
    )


@router.post("/evaluate", response_model=EvaluationResponse)
def evaluate(request: EvaluationRequest):
    """
    Executes metadata quality evaluation for the requested datasets.

    Graph loading, caching, and scope filtering are handled by the
    Evaluation Engine and Data Source layer. The router resolves metric
    plugins, passes a clean dataset list to the engine, and serialises
    results into the response.

    Export data stored by metrics during evaluation is available via
    GET /export/{dataset_id}/{metric_id}/{category}.

    Parameters
    ----------
    request : EvaluationRequest

    Returns
    -------
    EvaluationResponse

    Raises
    ------
    HTTPException 400
        If a metric ID is not defined in configuration.
    HTTPException 500
        If no plugin is registered for a metric ID.
    HTTPException 422
        If evaluation fails for any dataset.
    """
    metric_config = load_metrics_config()
    metrics = []

    for metric in request.metrics:
        metric_id = metric.metric_id

        if metric_id not in metric_config:
            raise HTTPException(
                status_code=400,
                detail=f"Metric '{metric_id}' is not defined in configuration.",
            )

        metric_class = METRIC_REGISTRY.get(metric_id)
        if not metric_class:
            raise HTTPException(
                status_code=500,
                detail=f"No plugin registered for metric '{metric_id}'.",
            )

        metrics.append(metric_class())

    datasets = [
        {
            "dataset_id":    dataset_req.dataset_id,
            "label":         dataset_req.label,
            "source_config": dataset_req.source_config.model_dump(),
            "scope":         dataset_req.scope,
        }
        for dataset_req in request.datasets
    ]

    try:
        results = engine.evaluate(datasets=datasets, metrics=metrics)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Evaluation failed: {exc}",
        ) from exc

    response_datasets = []

    for dataset_result in results:
        metric_responses = [
            MetricResultResponse(
                metric_id=m.metric_id,
                name=m.name,
                score=m.score,
                weight=m.weight,
                status=m.status,
                details=m.details,
                exports_available=m.exports_available,
            )
            for m in dataset_result.metrics
        ]

        stats_response = None
        if dataset_result.stats:
            stats_response = DatasetStatsResponse(**dataset_result.stats)

        response_datasets.append(
            DatasetEvaluationResponse(
                dataset_id=dataset_result.dataset_id,
                label=dataset_result.label,
                overall_score=dataset_result.overall_score,
                metrics=metric_responses,
                stats=stats_response,
            )
        )

    return EvaluationResponse(datasets=response_datasets)


@router.get("/export/{dataset_id}/{metric_id}/{category}")
def export_csv(dataset_id: str, metric_id: str, category: str, label: str = ""):
    """
    Stream a CSV file containing the full (uncapped) export data for
    a given dataset, metric, and category.

    This endpoint is called by the frontend when the user clicks a
    category export button on a metric card. It reads from the export
    cache populated during the most recent /evaluate call.

    The CSV columns are inferred from the keys of the first row stored
    in the cache — the metric is fully in control of the column schema.

    Parameters
    ----------
    dataset_id : str
        The dataset identifier from the evaluation request.
    metric_id : str
        The metric plugin identifier.
    category : str
        The export category within the metric.

    Returns
    -------
    StreamingResponse
        A CSV file streamed as application/octet-stream with a
        Content-Disposition header suggesting a filename.

    Raises
    ------
    HTTPException 404
        If no export data exists for the requested combination. This
        happens if /evaluate has not been called yet, or if the metric
        does not export data for this category.
    HTTPException 500
        If CSV serialisation fails unexpectedly.
    """
    rows = get_export(dataset_id, metric_id, category)

    if rows is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No export data found for dataset '{dataset_id}', "
                f"metric '{metric_id}', category '{category}'. "
                f"Run /evaluate first."
            ),
        )

    if not rows:
        # Metric ran successfully but found zero violations — return
        # an empty CSV with a single header row if possible.
        csv_content = "no_violations\n"
    else:
        try:
            csv_content = rows_to_csv(rows)
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to serialise export data: {exc}",
            ) from exc

    safe_label = re.sub(r"[^\w\-]", "_", label) if label else dataset_id
    filename = f"{safe_label}_{metric_id}_{category}.csv"

    return StreamingResponse(
        io.StringIO(csv_content),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )

@router.post("/results/export")
def export_results(request: ResultExportRequest):
    """
    Serialise evaluation results into a portable results archive.

    The archive carries the scores and metric details the client already
    holds, the provenance of the run, and the complete export rows read
    out of the export cache, so that the run can be rendered again in a
    later session or a fresh process.

    Parameters
    ----------
    request : ResultExportRequest
        Dataset results to archive, optionally with the source
        configuration and scope they were evaluated under.

    Returns
    -------
    Response
        The archive as indented JSON, with a Content-Disposition header
        suggesting a filename.

    Raises
    ------
    HTTPException 400
        If no dataset results were provided.
    """
    datasets = [dataset.model_dump() for dataset in request.datasets]

    try:
        archive = build_archive(datasets, created_by="api")
    except ResultArchiveError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    first_label = datasets[0].get("label") or datasets[0].get("dataset_id", "")
    safe_label = re.sub(r"[^\w\-]", "_", first_label) or "results"
    stamp = re.sub(r"[^\w]", "", archive["created_at"])
    filename = f"results_{safe_label}_{stamp}.json"

    return Response(
        content=json.dumps(archive, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/results/import", response_model=ResultImportResponse)
def import_results(payload: dict | list = Body(...)):
    """
    Read a results archive back into evaluation response form.

    The body is accepted untyped because archives written by older CLI
    runs are a bare list of dataset results rather than an envelope;
    parse_archive is what decides whether a payload is readable.

    Export rows travelling with the archive are written back into the
    export cache under the re-keyed dataset identifiers, so the CSV
    export endpoint serves imported datasets exactly as it serves
    freshly evaluated ones.

    Parameters
    ----------
    payload : dict | list
        A results archive, or a legacy list of dataset results.

    Returns
    -------
    ResultImportResponse
        The archive's provenance, the datasets in evaluation response
        form, and the names of any metrics that could not be rendered.

    Raises
    ------
    HTTPException 400
        If the payload is not a readable archive, carries no datasets,
        or declares a schema version this tool cannot read.
    """
    try:
        parsed = parse_archive(payload)
    except ResultArchiveError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    restore_exports(parsed["datasets"])

    response_datasets = []
    for dataset in parsed["datasets"]:
        metric_responses = [
            MetricResultResponse(
                metric_id=metric["metric_id"],
                name=metric["name"],
                score=metric["score"],
                weight=metric["weight"],
                status=metric["status"],
                details=metric["details"],
                exports_available=metric["exports_available"],
            )
            for metric in dataset["metrics"]
        ]

        stats = (
            DatasetStatsResponse(**dataset["stats"])
            if dataset["stats"] else None
        )

        response_datasets.append(
            DatasetEvaluationResponse(
                dataset_id=dataset["dataset_id"],
                label=dataset["label"],
                overall_score=dataset["overall_score"],
                metrics=metric_responses,
                stats=stats,
            )
        )

    return ResultImportResponse(
        schema_version=parsed["schema_version"],
        created_at=parsed["created_at"],
        tool_version=parsed["tool_version"],
        dropped_metrics=parsed["dropped_metrics"],
        datasets=response_datasets,
    )


@router.post("/sources/upload", response_model=FileUploadResponse)
async def upload_source_file(filename: str, request: Request):
    """
    Store an RDF file uploaded from the dashboard.

    The file arrives as the raw request body rather than as a multipart
    form, which keeps the backend free of an additional dependency, and
    the filename travels as a query parameter. The stored path is
    returned so the client can use it as an ordinary rdf_file source.

    This is the only asynchronous endpoint in the module: reading the
    request body is awaited.

    Parameters
    ----------
    filename : str
        Name of the uploaded file, used to derive the stored name and to
        guess the serialisation format.
    request : Request
        Carries the raw file contents as its body.

    Returns
    -------
    FileUploadResponse
        Where the file was stored, its name, guessed format and size.

    Raises
    ------
    HTTPException 400
        If the file is empty or has no usable name.
    HTTPException 413
        If the file exceeds the upload size limit.
    """
    content = await request.body()

    try:
        stored = save_upload(filename, content)
    except UploadError as exc:
        status = 413 if "larger than" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc

    return FileUploadResponse(**stored)
