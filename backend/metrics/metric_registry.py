from metrics.plugins.structural_completeness import StructuralCompletenessMetric
from metrics.plugins.property_coverage import PropertyCoverageMetric
from metrics.plugins.multilingual_labeling_coverage import MultilingualLabelingCoverageMetric

METRIC_REGISTRY = {
    "structural_completeness": StructuralCompletenessMetric,
    "property_coverage": PropertyCoverageMetric,
    "multilingual_labeling_coverage": MultilingualLabelingCoverageMetric,
}