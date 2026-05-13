from dash import Input, Output, State, callback, no_update

from api_client import run_evaluation, APIError
from store import make_results


@callback(
    Output("store-results",      "data"),
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
    store-results.data
        Normalized frontend evaluation result state.
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
                results_store,
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
        result = make_results([], error_message=str(exc))
        return result, False, label, ""

    result = make_results(datasets)
    return result, False, label, ""