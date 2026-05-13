from fastapi import APIRouter, HTTPException

from engine.evaluation_engine import EvaluationEngine
from datasource.datasource_factory import DataSourceFactory
from graph.graph_cache import get_or_load
from graph.ontology_extractor import extract, ClassNode, PropertyInfo

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
    PropertyInfoResponse,
)

from config.config_loader import load_metrics_config, load_dimensions_config
from metrics.metric_registry import METRIC_REGISTRY

router = APIRouter()
engine = EvaluationEngine()

def _class_node_to_response(node: ClassNode) -> ClassNodeResponse:
    """
    Converts an internal 'ClassNode' object into an API response model.
    """
    return ClassNodeResponse(
        uri=node.uri,
        label=node.label,
        instance_count=node.instance_count,
        properties=[
            PropertyInfoResponse(uri=p.uri, label=p.label, count=p.count)
            for p in node.properties
        ],
        children=[_class_node_to_response(child) for child in node.children],
    )


@router.get("/metrics", response_model=list[MetricConfigResponse])
def get_metrics():
    """
    Returns the list of implemented metrics, along with their details.
    """
    metric_config = load_metrics_config()
    return [
        MetricConfigResponse(
            metric_id=metric_id,
            name=config["name"],
            description=config["description"],
            tooltip=config["tooltip"],
            dimension=config["dimension"],
            weight=config["weight"],
        )
        for metric_id, config in metric_config.items()
    ]

@router.get("/dimensions", response_model=list[DimensionConfigResponse])
def get_dimensions():
    """
    Returns the list of implemented metrics, along with their details.
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
        classes=[_class_node_to_response(node) for node in class_nodes],
    )


@router.post("/evaluate", response_model=EvaluationResponse)
def evaluate(request: EvaluationRequest):
    """
    Executes metadata quality evaluation for the requested datasets.
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