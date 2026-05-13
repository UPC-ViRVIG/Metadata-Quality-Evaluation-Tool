from __future__ import annotations

from pydantic import BaseModel
from typing import Optional, List


class MetricResultResponse(BaseModel):
    """
    API response model representing the result of a single metric
    evaluation for a dataset.

    Attributes
    ----------
    metric_id : str
        Stable internal identifier of the metric.
    name : str
        Human-readable metric name displayed in the UI.
    score : float | None
        Computed metric score. None if the metric failed or 
        could not be computed.
    weight : float
        Relative contribution of the metric to the overall dataset score.
    status : str
        Metric execution status.
    details : dict | None
        Metric-specific detailed output used for frontend visualisations 
        and analysis. Structure depends on the metric implementation.
        None if no detailed output is available.
    """
    metric_id: str
    name: str
    score: float | None
    weight: float
    status: str
    details: dict | None

    @staticmethod
    def from_domain(metric) -> "MetricResultResponse":
        """
        Convert a domain MetricResult object into its API response model.

        Parameters
        ----------
        metric
            Domain-layer MetricResult instance.

        Returns
        -------
        MetricResultResponse
        Serialized API representation of the metric result.
        """
        return MetricResultResponse(
            metric_id=metric.metric_id,
            name=metric.name,
            score=metric.score,
            weight=metric.weight,
            status=metric.status,
            details=metric.details,
        )

class MetricConfigResponse(BaseModel):
    """
    API response model describing a configurable evaluation metric.

    Attributes
    ----------
    metric_id : str
        Stable internal metric identifier.
    name : str
        Human-readable metric name.
    description : str
        Detailed explanation of what the metric evaluates.
    tooltip : str
        Short UI-friendly help text.
    dimension : str
        High-level quality dimension the metric belongs to.
    weight : float
        Default contribution weight used during score aggregation.
    """
    metric_id:   str
    name:        str
    description: str
    tooltip:     str
    dimension:   str
    weight:      float

class DimensionConfigResponse(BaseModel):
    """
    API response model describing a quality dimension category.

    Attributes
    ----------
    name : str
        Name of the quality dimension.
    description : str
        Detailed explanation of the dimension.
    tooltip : str
        Short UI-oriented explanatory text.
    """
    name:        str
    description: str
    tooltip:     str

class PropertyInfoResponse(BaseModel):
    """
    A single property used by instances of a class.

    Attributes
    ----------
    uri : str
        Full property URI.
    label : str
        Human-readable local name (fragment or last path segment).
    count : int
        Number of class instances that use this property at least once.
    """

    uri: str
    label: str
    count: int


class ClassNodeResponse(BaseModel):
    """
    A node in the class hierarchy tree.

    Attributes
    ----------
    uri : str
        Full class URI.
    label : str
        Human-readable local name.
    instance_count : int
        Number of subjects typed as this class in the data.
    properties : List[PropertyInfoResponse]
        Properties actually used across instances, sorted by count desc.
    children : List[ClassNodeResponse]
        Subclasses (nested, recursive), sorted by instance_count desc.
    """

    uri: str
    label: str
    instance_count: int
    properties: List[PropertyInfoResponse] = []
    children: List["ClassNodeResponse"] = []

    model_config = {"arbitrary_types_allowed": True}


ClassNodeResponse.model_rebuild()

class OntologyResponse(BaseModel):
    """
    Response for POST /ontology.

    Attributes
    ----------
    dataset_id : str
        Echoes the dataset_id from the request.
    classes : List[ClassNodeResponse]
        Top-level class nodes (roots of the hierarchy).
    """

    dataset_id: str
    classes: List[ClassNodeResponse]


class DatasetStatsResponse(BaseModel):
    """
    Basic graph statistics for a dataset.

    Shown in the frontend sidebar as triple_count, entity_count,
    class_count (displayed as "—" if absent).
    """

    triple_count: int
    entity_count: int
    class_count: int


class DatasetEvaluationResponse(BaseModel):
    """
    API response model for dataset evaluation results.

    Attributes
    ----------
    dataset_id : str
    label : str | None
    overall_score : float | None
    metrics : List[MetricResultResponse]
    stats : DatasetStatsResponse | None
        Basic graph statistics; None if stats could not be computed.
    """

    dataset_id: str
    label: Optional[str]
    overall_score: Optional[float]
    metrics: List[MetricResultResponse]
    stats: Optional[DatasetStatsResponse] = None


class EvaluationResponse(BaseModel):
    """
    API response containing evaluation results for all datasets.
    """

    datasets: List[DatasetEvaluationResponse]