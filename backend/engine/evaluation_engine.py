"""
engine/evaluation_engine.py
---------------------------
Orchestration of the metadata quality evaluation pipeline.

The engine coordinates the other components and implements no data
loading or metric computation of its own. For each dataset in a request
it performs six steps:

1. Load the graph through the Data Source factory, which is cache-aware.
2. Apply the optional class scope filter.
3. Wrap the result in a DatasetContext.
4. Run each selected metric plugin, recording its runtime.
5. Aggregate the metric results into an overall dataset score.
6. Compute graph statistics for the evaluated subgraph.

Scope filtering happens here, once per dataset, and is never duplicated
inside individual metrics.

Before a run, check_before_run prepares each dataset the same way and
collects what the selected metrics ask the user to confirm, such as a
chosen SHACL profile that does not fit the data. The engine only passes
these warnings on; deciding what to warn about is each metric's job.
"""

from datasource.datasource_factory import DataSourceFactory
from graph.scope_filter import apply as apply_scope
from graph.scope_filter import stats as compute_stats
from graph.ontology_extractor import group_equivalent_classes
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
            * metric_options - dict, metric id to options (optional)

        metrics : list[MetricPlugin]
        """
        all_dataset_results = []

        for dataset in datasets:

            # Steps 1-3: Load, scope and wrap in a context
            dataset_context = self._prepare(dataset)
            scope        = dataset_context.scope
            active_graph = dataset_context.graph

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
            class_groups = group_equivalent_classes(active_graph, scope)

            all_dataset_results.append(DatasetEvaluationResult(
                dataset_id=dataset_context.dataset_id,
                label=dataset_context.label,
                overall_score=overall_score,
                metrics=metric_results,
                stats=stats,
                class_groups=class_groups,
            ))

        return all_dataset_results

    def check_before_run(
        self,
        datasets: list[dict],
        metrics: list[MetricPlugin],
    ) -> list[dict]:
        """
        Collect what each metric asks the user to confirm before a run.

        Prepares each dataset exactly as evaluate does, so a warning is
        about the graph that would really be evaluated, and the loaded
        graph is cached for the run that follows. A dataset that cannot
        be loaded yields no warnings: the run itself reports that error.

        Parameters
        ----------
        datasets : list[dict]
            As for evaluate.
        metrics : list[MetricPlugin]

        Returns
        -------
        list[dict]
            One entry per warning, the metric's own fields plus
            dataset_id, label and metric_id.
        """
        warnings = []
        for dataset in datasets:
            try:
                dataset_context = self._prepare(dataset)
            except Exception:
                continue
            for metric in metrics:
                for warning in metric.check_before_run(dataset_context):
                    warnings.append({
                        "dataset_id": dataset_context.dataset_id,
                        "label":      dataset_context.label,
                        "metric_id":  metric.id,
                        **warning,
                    })
        return warnings

    def _prepare(self, dataset: dict) -> DatasetContext:
        """
        Load, scope and wrap one dataset: steps 1 to 3 of the pipeline.

        Parameters
        ----------
        dataset : dict
            One entry of the datasets list given to evaluate.

        Returns
        -------
        DatasetContext
            The scoped graph, with the full graph and metric options.
        """
        # Step 1: Load via Data Source (cache-aware internally)
        datasource = DataSourceFactory.create(dataset["source_config"])
        full_graph = datasource.load()

        # Step 2: Scope filtering
        scope = dataset.get("scope")
        active_graph = apply_scope(full_graph, scope)

        # Step 3: Build context
        return DatasetContext(
            dataset_id=dataset["dataset_id"],
            label=dataset.get("label"),
            graph=active_graph,
            scope=scope,
            full_graph=full_graph,
            options=dataset.get("metric_options"),
        )