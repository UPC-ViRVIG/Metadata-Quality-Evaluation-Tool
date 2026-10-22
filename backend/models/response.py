"""
models/response.py
------------------
Pydantic models for outgoing API responses.

Each model corresponds to an internal domain object, and the from_domain
converters translate between the two. Keeping the two layers separate
means a change to an internal representation does not silently alter the
contract the frontend depends on.
"""

from __future__ import annotations

from pydantic import BaseModel
from typing import Optional, List

class MetricResultResponse(BaseModel):
    """
    API response model representing a single metric result.

    Attributes
    ----------
    metric_id : str
        Identifier of the metric.
    name : str
        Human-readable metric name.
    score : float | None
        Computed metric score.
    weight : float
        Weight used during score aggregation.
    status : str
        Metric execution status.
    details : dict | None
        Optional dictionary containing metric-specific display data.
        Includes capped sample lists for violation detail panels.
    exports_available : list[str] | None
        Export categories available for download via the export endpoint.
        None if the metric does not support export.
    """

    metric_id:          str
    name:               str
    score:              float | None
    weight:             float
    status:             str
    details:            dict | None
    exports_available:  Optional[List[str]] = None

    @staticmethod
    def from_domain(metric) -> "MetricResultResponse":
        """
        Convert a domain MetricResult into its API response model.

        Parameters
        ----------
        metric : MetricResult
            Domain object produced by a metric plugin.

        Returns
        -------
        MetricResultResponse
        """
        return MetricResultResponse(
            metric_id=metric.metric_id,
            name=metric.name,
            score=metric.score,
            weight=metric.weight,
            status=metric.status,
            details=metric.details,
            exports_available=metric.exports_available,
        )


class MetricConfigResponse(BaseModel):
    """
    API response for the metrics list.

    Attributes
    ----------
    metric_id : str
    name : str
    description : str
    dimension : str
    weight : float
    """

    metric_id:   str
    name:        str
    description: str
    dimension:   str
    weight:      float

class PropertyInfoResponse(BaseModel):
    """
    A single property used by instances of a class.

    Attributes
    ----------
    uri : str
        Full property URI.
    label : str
        Human-readable local name.
    count : int
        Number of class instances that use this property at least once.
    """

    uri:   str
    label: str
    count: int


class ClassNodeResponse(BaseModel):
    """
    A node in the class hierarchy tree.

    Attributes
    ----------
    uri : str
    label : str
    instance_count : int
    properties : list of PropertyInfoResponse
    children : list of ClassNodeResponse
    """

    uri:            str
    label:          str
    instance_count: int
    properties:     List[PropertyInfoResponse] = []
    children:       List["ClassNodeResponse"]  = []

    model_config = {"arbitrary_types_allowed": True}

    @classmethod
    def from_domain(cls, node) -> "ClassNodeResponse":
        """
        Recursively convert a domain ClassNode to its API response model.

        Parameters
        ----------
        node : ClassNode
            Domain object from the ontology extractor.

        Returns
        -------
        ClassNodeResponse
        """
        return cls(
            uri=node.uri,
            label=node.label,
            instance_count=node.instance_count,
            properties=[
                PropertyInfoResponse(uri=p.uri, label=p.label, count=p.count)
                for p in node.properties
            ],
            children=[cls.from_domain(child) for child in node.children],
        )

ClassNodeResponse.model_rebuild()

class OntologyResponse(BaseModel):
    """
    Response for POST /ontology.

    Attributes
    ----------
    dataset_id : str
    classes : list of ClassNodeResponse
    """

    dataset_id: str
    classes:    List[ClassNodeResponse]

class DatasetStatsResponse(BaseModel):
    """
    Basic graph statistics for a dataset.

    Attributes
    ----------
    triple_count : int
    entity_count : int
    class_count : int
    """

    triple_count: int
    entity_count: int
    class_count:  int


class DatasetEvaluationResponse(BaseModel):
    """
    API response model for dataset evaluation results.

    Attributes
    ----------
    dataset_id : str
    label : str | None
    overall_score : float | None
    metrics : list of MetricResultResponse
    stats : DatasetStatsResponse | None
    """

    dataset_id:    str
    label:         Optional[str]
    overall_score: Optional[float]
    metrics:       List[MetricResultResponse]
    stats:         Optional[DatasetStatsResponse] = None


class EvaluationResponse(BaseModel):
    """
    API response containing evaluation results for all datasets.

    Attributes
    ----------
    datasets : list of DatasetEvaluationResponse
    """

    datasets: List[DatasetEvaluationResponse]


class DimensionConfigResponse(BaseModel):
    """
    API response for a quality dimension entry.

    Attributes
    ----------
    name : str
    description : str
    tooltip : str
    """

    name:        str
    description: str
    tooltip:     str

class ResultImportResponse(BaseModel):
    """
    API response for POST /results/import.

    The datasets field reuses DatasetEvaluationResponse so an imported
    archive is shape-identical to an evaluation response and needs no
    separate rendering path in the frontend.

    Attributes
    ----------
    schema_version : int
    created_at : str | None
    tool_version : str | None
    dropped_metrics : list of str
        Metrics recorded in the archive but not renderable, named as
        dataset label / metric id (status).
    datasets : list of DatasetEvaluationResponse
    """

    schema_version:  int
    created_at:      Optional[str] = None
    tool_version:    Optional[str] = None
    dropped_metrics: List[str] = []
    datasets:        List[DatasetEvaluationResponse]
