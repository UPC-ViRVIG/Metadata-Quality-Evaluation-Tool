"""
Shared frontend state model definitions and default store values.
The application uses dcc.Store components as the primary mechanism
for synchronizing state between independent Dash callbacks.

Stores are intentionally normalized into distinct domains:
store-sources
    Dataset/source configuration and selection state.
store-computed
    Results of the most recent evaluation run.
store-imported
    Results loaded from saved archive files.
store-results
    Evaluation results and execution state, derived from the computed
    and imported stores.
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
# store-computed / store-imported
# ============================================================================
COMPUTED_DEFAULT = None
IMPORTED_DEFAULT = {}


def make_imported(dataset, filename, created_at, schema_version, selected=False):
    """
    Create a normalized saved-result entry for store-imported.

    Parameters
    ----------
    dataset : dict
        One dataset result as returned by the import endpoint, already
        in evaluation response shape.
    filename : str
        Name of the archive file the result was read from.
    created_at : str | None
        When the archive was written, if it recorded a timestamp.
    schema_version : int
        Archive format version the file declared.
    selected : bool, default=False
        Whether the result is included in the current view. Imports
        start out excluded so that loading a file never changes what is
        already on screen.

    Returns
    -------
    dict
        Canonical store-imported entry structure.

    """
    return {
        "dataset":  dataset,
        "selected": selected,
        "archive":  {
            "filename":       filename,
            "created_at":     created_at,
            "schema_version": schema_version,
        },
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