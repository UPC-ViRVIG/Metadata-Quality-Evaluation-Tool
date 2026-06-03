from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import io
import re

from engine.evaluation_engine import EvaluationEngine
from datasource.datasource_factory import DataSourceFactory
from graph.graph_cache import get_or_load
from graph.ontology_extractor import extract

from export.export_cache import get as get_export
from export.csv_writer import rows_to_csv

from models.request import EvaluationRequest, OntologyRequest
from models.response import (
    EvaluationResponse,
    DatasetEvaluationResponse,
    DatasetStatsResponse,
    MetricResultResponse,
    DimensionConfigResponse,
    MetricConfigResponse,
    OntologyResponse,
    ClassNodeResponse,
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