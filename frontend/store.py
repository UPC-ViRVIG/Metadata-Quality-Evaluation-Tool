"""
Shared frontend state model definitions and default store values.
The application uses dcc.Store components as the primary mechanism
for synchronizing state between independent Dash callbacks.

Stores are intentionally normalized into distinct domains:
store-sources
    Dataset/source configuration and selection state.
store-results
    Evaluation results and execution state.
store-ontology
    Cached ontology hierarchy data.
store-ui
    Transient frontend interaction state.
"""

# ============================================================================
# store-sources
# ============================================================================
SOURCES_DEFAULT = []


def make_source(id, label, source_config, selected=False):
    """
    Create a normalized frontend source configuration object.

    Parameters
    ----------
    id : str
        Unique source identifier.
    label : str
        Human-readable source label.
    source_config : dict
        Backend-compatible source configuration.
    selected : bool, default=False
        Initial evaluation selection state.

    Returns
    -------
    dict
        Canonical store-sources entry structure.

    """
    return {
        "id":            id,
        "label":         label,
        "selected":      selected,
        "expanded":      False,
        "source_config": source_config,
        "scope":         None,
    }


# ============================================================================
# store-results
# ============================================================================
RESULTS_DEFAULT = None


def make_results(datasets, error_message=None):
    """
    Construct normalized frontend evaluation result state.

    Parameters
    ----------
    datasets : list[dict]
        Dataset evaluation results returned by the backend.
    error_message : str | None, optional
        Explicit frontend error message.

    Returns
    -------
    dict
        Canonical store-results structure.

    Result Modes
    ------------
    analysis
        Activated when exactly one dataset is evaluated.
    comparison
        Activated when multiple datasets are evaluated.
    """
    if error_message is not None:
        return {
            "status":        "error",
            "mode":          None,
            "error_message": error_message,
            "datasets":      [],
        }

    for dataset in datasets:
        for metric in dataset.get("metrics", []):
            if metric.get("status") == "error":
                return {
                    "status":        "error",
                    "mode":          None,
                    "error_message": (
                        f"Metric '{metric['name']}' failed on dataset "
                        f"'{dataset['label']}': {metric.get('details', 'no details')}"
                    ),
                    "datasets":      datasets,
                }

    return {
        "status":        "ok",
        "mode":          "analysis" if len(datasets) == 1 else "comparison",
        "error_message": None,
        "datasets":      datasets,
    }


# ============================================================================
# store-ontology
# ============================================================================
ONTOLOGY_DEFAULT = {}

# ============================================================================
# store-ui
# ============================================================================
UI_DEFAULT = {
    "active_metric": None,
    "active_class":  None,
}