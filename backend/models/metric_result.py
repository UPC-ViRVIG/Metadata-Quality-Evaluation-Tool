class MetricResult:
    """
    The evaluation outcome of a single metric over a dataset.
 
    Attributes
    ----------
    metric_id : str
        Unique identifier of the metric.
    name : str
        Human-readable metric name.
    score : float | None
        Computed metric score. None if evaluation failed.
    weight : float
        Weight used during score aggregation.
    status : str
        Execution status: computed or error.
    details : dict | None
        Additional structured information about the evaluation.
        Contains display data for the frontend, including capped
        sample lists for violation detail panels.
    guidelines : dict | None
        Optional suggestions for improving dataset quality.
    exports_available : list[str] | None
        Names of export categories stored in the export cache for this
        metric and dataset. None if the metric does not support export.
        Example: ["uri_validity", "datatype_correctness"] for
        foundational_format_consistency.
    """
 
    def __init__(
            self,
            metric_id: str,
            name: str,
            score: float,
            weight: float,
            status: str = "computed",
            details: dict | None = None,
            guidelines: dict | None = None,
            exports_available: list[str] | None = None,
            runtime_seconds: float | None = None,
    ):
        self.metric_id         = metric_id
        self.name              = name
        self.score             = score
        self.weight            = weight
        self.status            = status
        self.details           = details
        self.guidelines        = guidelines
        self.exports_available = exports_available
        self.runtime_seconds   = runtime_seconds