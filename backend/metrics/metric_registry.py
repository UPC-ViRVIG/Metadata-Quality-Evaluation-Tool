"""
metrics/metric_registry.py
--------------------------
Mapping from metric identifier to plugin class.

The API layer and the CLI both resolve requested metric IDs through this
registry. An ID that appears in metrics_config.json but is missing here
is a configuration inconsistency rather than user error, and is reported
as a server-side failure.
"""

from metrics.plugins.structural_completeness import StructuralCompletenessMetric
from metrics.plugins.property_coverage import PropertyCoverageMetric
from metrics.plugins.multilingual_labeling_coverage import MultilingualLabelingCoverageMetric
from metrics.plugins.foundational_format_consistency import FoundationalFormatConsistencyMetric
from metrics.plugins.connectivity import ConnectivityMetric
from metrics.plugins.licensing_rights import LicensingRightsMetric

METRIC_REGISTRY = {
    "structural_completeness": StructuralCompletenessMetric,
    "property_coverage": PropertyCoverageMetric,
    "multilingual_labeling_coverage": MultilingualLabelingCoverageMetric,
    "foundational_format_consistency": FoundationalFormatConsistencyMetric,
    "connectivity": ConnectivityMetric,
    "licensing_rights": LicensingRightsMetric,
}


def resolve_metric_options(metric_options: dict | None) -> dict:
    """
    Validate the per-metric options chosen for one dataset.

    Parameters
    ----------
    metric_options : dict | None
        Metric ids mapped to their chosen option values.

    Returns
    -------
    dict
        The same metric ids mapped to complete, validated options.

    Raises
    ------
    MetricConfigurationError
        If a metric id is not registered, or one of its options is not
        valid.
    """
    from metrics.metrics_exceptions import MetricConfigurationError

    resolved = {}
    for metric_id, options in (metric_options or {}).items():
        metric_class = METRIC_REGISTRY.get(metric_id)
        if metric_class is None:
            raise MetricConfigurationError(
                f"Options were given for unknown metric '{metric_id}'."
            )
        resolved[metric_id] = metric_class.resolve_options(options)
    return resolved
