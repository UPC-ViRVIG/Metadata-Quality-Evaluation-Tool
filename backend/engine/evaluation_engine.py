from datasource.datasource_factory import DataSourceFactory
from graph.scope_filter import apply as apply_scope
from graph.scope_filter import stats as compute_stats
from metrics.metric_plugin import MetricPlugin
from models.dataset_context import DatasetContext
from models.dataset_evaluation_result import DatasetEvaluationResult
from results_aggregator.result_aggregator import ResultAggregator

import time



class EvaluationEngine:
    """
    Orchestrator of all processes needed to perform the metadata
    quality evaluation
    """

    def __init__(self):
        self.aggregator = ResultAggregator()

    def evaluate(
        self,
        datasets: list[dict],
        metrics: list[MetricPlugin],
    ) -> list[DatasetEvaluationResult]:
        """
        Parameters
        ----------
        datasets : list[dict]
            Each dict must contain:
            * dataset_id    - str
            * label         - str | None
            * source_config - dict
            * scope         - list[str] | None  (optional)

        metrics : list[MetricPlugin]
        """
        all_dataset_results = []

        for dataset in datasets:

            # Step 1: Load via Data Source (cache-aware internally)
            datasource = DataSourceFactory.create(dataset["source_config"])
            full_graph = datasource.load()

            # Step 2: Scope filtering
            scope = dataset.get("scope")
            active_graph = apply_scope(full_graph, scope)

            # Step 3: Build context
            dataset_context = DatasetContext(
                dataset_id=dataset["dataset_id"],
                label=dataset.get("label"),
                graph=active_graph,
                scope=scope,
                full_graph=full_graph,
            )

            # Step 4: Run metrics
            metric_results = []
            for metric in metrics:
                t0 = time.perf_counter()
                result = metric.evaluate(dataset_context)
                result.runtime_seconds = round(time.perf_counter() - t0, 4)
                metric_results.append(result)

            # Step 5: Aggregate
            overall_score = self.aggregator.aggregate(metric_results)

            # Step 6: Stats on the active graph
            stats = compute_stats(active_graph)

            all_dataset_results.append(DatasetEvaluationResult(
                dataset_id=dataset_context.dataset_id,
                label=dataset_context.label,
                overall_score=overall_score,
                metrics=metric_results,
                stats=stats,
            ))

        return all_dataset_results