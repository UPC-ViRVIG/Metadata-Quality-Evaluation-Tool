"""
Evaluation-triggering callback and the merge that feeds the main panel.

Calls POST /evaluate through api_client and records the response in
store-computed. A second callback merges that run with any saved results
the user has selected and normalizes the combination into store-results
via make_results, which is what puts the main panel into analysis or
comparison mode.

store-results is derived state with exactly one writer, merge_results.
Nothing else may output to it, or the two sources of dataset results
would overwrite each other.
"""

from dash import Input, Output, State, callback, ctx, no_update

from api_client import run_evaluation, APIError
from store import make_results


@callback(
    Output("store-computed",     "data"),
    Output("btn-run-evaluation", "disabled",  allow_duplicate=True),
    Output("btn-run-evaluation", "children",  allow_duplicate=True),
    Output("run-feedback",       "children",  allow_duplicate=True),
    Input("btn-run-evaluation",  "n_clicks"),
    State("store-sources",    "data"),
    State("metric-selection", "data"),
    prevent_initial_call=True,
)
def run_evaluation_callback(n_clicks, sources, selected_metrics):
    """
    Execute dataset evaluation through the backend API.

    Triggered when the user clicks the evaluation button.

    State Inputs
    ------------
    store-sources.data
        All configured frontend dataset sources.
    metric-selection.data
        Selected metric identifiers.

    Outputs
    -------
    store-computed.data
        Datasets returned by the run, or the error that stopped it.
    btn-run-evaluation.disabled
        Re-enable evaluation button after execution completes.
    btn-run-evaluation.children
        Restore button label after execution.
    run-feedback.children
        Validation or status feedback message.

    Parameters
    ----------
    n_clicks : int | None
        Number of evaluation button clicks.
    sources : list[dict]
        Frontend source configuration state.
    selected_metrics : list[str]
        Selected metric identifiers.

    Returns
    -------
    tuple
        Structure:

            (
                computed_store,
                button_disabled,
                button_label,
                feedback_message
            )

    """
    if not n_clicks:
        return no_update, no_update, no_update, no_update

    selected_sources = [s for s in (sources or []) if s.get("selected")]

    if not selected_sources:
        return no_update, no_update, no_update, "Select at least one data source."
    if not selected_metrics:
        return no_update, no_update, no_update, "Select at least one metric."

    label = "Run Analysis" if len(selected_sources) == 1 else "Run Comparison"

    try:
        datasets = run_evaluation(selected_sources, selected_metrics)
    except APIError as exc:
        return {"datasets": [], "error_message": str(exc)}, False, label, ""

    return {"datasets": datasets, "error_message": None}, False, label, ""


@callback(
    Output("store-results",  "data"),
    Input("store-computed",  "data"),
    Input("store-imported",  "data"),
    State("store-results",   "data"),
    prevent_initial_call=True,
)
def merge_results(computed, imported, current):
    """
    Combine the latest run with the selected saved results.

    This is the only writer of store-results. The computed run is placed
    first because the detail panel and the chart colours key off the
    first dataset, so a fresh run leads and saved results read as
    baselines after it.

    Importing a file only adds an unselected entry, so it does not reach
    the view. The main panel is left untouched in that case rather than
    re-rendered with identical content, which would reset the drilldown
    the user is looking at.

    Inputs
    ------
    store-computed.data
        Datasets from the most recent evaluation, or its error.
    store-imported.data
        Saved results keyed by dataset id, each with a selected flag.

    Outputs
    -------
    store-results.data
        Normalized frontend evaluation result state, or None to return
        the main panel to its guide.

    Parameters
    ----------
    computed : dict | None
        Latest run state.
    imported : dict | None
        Saved results loaded from archive files.
    current : dict | None
        The store-results value currently displayed.

    Returns
    -------
    dict | None
        Canonical store-results structure, or None when nothing is
        selected.

    """
    computed = computed or {}
    error_message = computed.get("error_message")

    if error_message and ctx.triggered_id == "store-computed":
        return make_results([], error_message=error_message)

    datasets = list(computed.get("datasets") or [])
    computed_labels = {ds.get("label") for ds in datasets}

    for entry in (imported or {}).values():
        if not entry.get("selected"):
            continue
        dataset = dict(entry["dataset"])
        # Distinguish a saved result from a live one only when the two
        # would otherwise carry the same name in the comparison view.
        if dataset.get("label") in computed_labels:
            dataset["label"] = f"{dataset.get('label')} (imported)"
        datasets.append(dataset)

    if ctx.triggered_id == "store-imported":
        shown = [d.get("dataset_id") for d in (current or {}).get("datasets", [])]
        if [d.get("dataset_id") for d in datasets] == shown:
            return no_update

    if not datasets:
        return None

    return make_results(datasets)