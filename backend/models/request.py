from pydantic import BaseModel
from typing import Optional, List


class SourceConfig(BaseModel):
    """
    Configuration for loading datasets.

    Attributes
    ----------
    type : str
        Data source type: rdf_file or sparql_endpoint.
    file_path : str | None
        Path to a local RDF file (rdf_file sources only).
    format : str | None
        RDF serialisation format, e.g. 'turtle', 'xml', 'n3'.
    endpoint_url : str | None
        SPARQL endpoint URL (sparql_endpoint sources only).
    query : str | None
        SPARQL CONSTRUCT/SELECT query (sparql_endpoint sources only).
    """

    type: str
    file_path: Optional[str] = None
    format: Optional[str] = None
    endpoint_url: Optional[str] = None
    query: Optional[str] = None


class DatasetRequest(BaseModel):
    """
    Dataset descriptor received from the frontend.

    Attributes
    ----------
    dataset_id : str
        Client-generated UUID that identifies the source in the sidebar.
    label : str | None
        Human-readable label shown in the UI.
    source_config : SourceConfig
        Describes how the dataset should be loaded.
    scope : List[str] | None
        Optional list of class URIs to restrict evaluation to.
        None (default) means the full graph is evaluated.
        An empty list [] is treated identically to None.
    """

    dataset_id: str
    label: Optional[str] = None
    source_config: SourceConfig
    scope: Optional[List[str]] = None


class MetricSelection(BaseModel):
    """
    Metric selection provided by the frontend.

    Attributes
    ----------
    metric_id : str
        Identifier of the metric to evaluate.
    enabled : bool
        Whether the metric is enabled.
    """

    metric_id: str
    enabled: bool = True


class EvaluationRequest(BaseModel):
    """
    Evaluation request body for POST /evaluate.

    Attributes
    ----------
    datasets : List[DatasetRequest]
        Datasets to evaluate (each may carry an optional scope).
    metrics : List[MetricSelection]
        Metrics to run.
    """
    datasets: List[DatasetRequest]
    metrics: List[MetricSelection]
    structural_shape: Optional[str] = None

class OntologyRequest(BaseModel):
    """
    Request body for POST /ontology.


    Attributes
    ----------
    dataset_id : str
    source_config : SourceConfig
        Describes how the dataset should be loaded (or retrieved from
        cache).
    """
    
    dataset_id: str
    source_config: SourceConfig