"""
models/dataset_evaluation_result.py
-----------------------------------
The complete evaluation outcome for a single dataset.

Produced by the engine once every metric has run and the aggregator has
combined their scores. This is the internal domain object; the API layer
converts it into the corresponding response model before serialisation.
"""


class DatasetEvaluationResult:
    """
    Aggregated evaluation result for a dataset.

    Attributes
    ----------
    dataset_id : str
        Unique identifier of the evaluated dataset.
    label : str | None
        Human-readable dataset label.
    overall_score : float | None
        Aggregated score computed from all evaluated metrics.
        May be None if no numeric metrics are available.
    metrics : list
        List of ``MetricResult`` objects for the dataset.
    stats : dict | None
        Basic graph statistics::
            {"triple_count": int, "entity_count": int, "class_count": int}

        None if stats were not computed.
    class_groups : list | None
        Classes holding exactly the same resources in the evaluated
        graph, one list per group with the representative first.
    """

    def __init__(
        self,
        dataset_id: str,
        label: str | None,
        overall_score: float | None,
        metrics: list,
        stats: dict | None = None,
        class_groups: list | None = None,
    ):
        self.dataset_id = dataset_id
        self.label = label
        self.overall_score = overall_score
        self.metrics = metrics
        self.stats = stats
        self.class_groups = class_groups or []