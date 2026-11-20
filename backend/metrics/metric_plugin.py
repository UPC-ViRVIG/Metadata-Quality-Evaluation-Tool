"""
metrics/metric_plugin.py
------------------------
The contract every metric implementation shares.

A metric is a plugin: it receives a DatasetContext and returns a
MetricResult, and knows nothing about HTTP, the CLI, caching, or scope
filtering. Adding a metric therefore means writing a subclass, listing
it in the registry, and describing it in metrics_config.json — the
engine itself never changes.

Display metadata (name, description, dimension, weight) is not
hardcoded in the subclass. It is read from metrics_config.json at
construction time using the subclass id, which keeps a metric's
presentation configurable without touching its logic.
"""

from abc import ABC, abstractmethod
from models.dataset_context import DatasetContext
from models.metric_result import MetricResult
from metrics.metrics_exceptions import MetricConfigurationError

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "config" / "metrics_config.json"

class MetricPlugin(ABC):
    """
    Abstract base class for all metadata quality metrics

    Each metric receives a DatasetContext object and
    returns a MetricResult describing the evaluation 
    outcome.

    Subclasses must implement the 'evaluate' method

    A subclass may declare options, a choice the user can make per
    dataset. Each option maps its name to a label, a default and a list
    of choices given as {"id", "label"}. Metrics without options leave
    this empty and are unaffected.
    """
    id : str
    options: dict = {}
    
    def __init__(self):
        """
        Load the display metadata for this metric from configuration.

        The subclass id is used to look up the metric's entry in
        metrics_config.json. Missing fields fall back to safe defaults,
        so a metric with no configuration entry is still constructible.
        """
        with open(CONFIG_PATH) as f:
            config = json.load(f)["metrics"].get(self.id, {})
        self.name        = config.get("name", self.id)
        self.description = config.get("description", "")
        self.dimension   = config.get("dimension", "")
        self.weight      = config.get("weight", 1.0)

    @classmethod
    def resolve_options(cls, given: dict | None) -> dict:
        """
        Validate chosen option values and fill in the defaults.

        This is the single check used by the API and the CLI, and by the
        metric itself when it reads its options from the context.

        Parameters
        ----------
        given : dict | None
            Option names mapped to the chosen choice ids.

        Returns
        -------
        dict
            Every declared option mapped to its chosen or default id.

        Raises
        ------
        MetricConfigurationError
            If an option is not declared by the metric, or a value is
            not one of its choices.
        """
        given = given or {}

        unknown = sorted(set(given) - set(cls.options))
        if unknown:
            raise MetricConfigurationError(
                f"Metric '{cls.id}' has no option '{unknown[0]}'."
            )

        resolved = {}
        for name, spec in cls.options.items():
            value = given.get(name, spec["default"])
            allowed = [choice["id"] for choice in spec["choices"]]
            if value not in allowed:
                raise MetricConfigurationError(
                    f"'{value}' is not a valid {spec['label']} for metric "
                    f"'{cls.id}'. Choose one of: {', '.join(allowed)}."
                )
            resolved[name] = value
        return resolved

    @abstractmethod
    def evaluate(self, context: DatasetContext) -> MetricResult:
        """
        Evaluate the metric on the provided dataset

        Parameters
        ----------
        context : DatasetContext
            Object containing dataset metadata and 
            the RDF graph to be evaluated.

        Returns
        -------
        MetricResult
            Structured evaluation result.
        """
        pass

    def error_result(self, message: str) -> MetricResult:
        """
        Create a standardized MetricResult to present a 
        failed metric evaluation.

        Parameters
        ----------
        message : str
            Human-readable description of the error that occurred during
            metric execution.

        Returns
        -------
        MetricResult
            Metric result object with status set to "error" and the error
            message stored in the details field.
        """
        return MetricResult(
            metric_id=self.id,
            name=self.name,
            score=None,
            weight=self.weight,
            status="error",
            details={"error": message}
        )