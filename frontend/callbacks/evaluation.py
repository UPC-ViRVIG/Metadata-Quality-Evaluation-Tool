"""
Evaluation-triggering callback and the merge that feeds the main panel.

Calls POST /evaluate through api_client and records the response in
store-computed. Before that, POST /evaluate/preflight asks each selected
metric whether a choice looks wrong for the data; if any does, the user
confirms the run or changes the choice, and nothing is replaced for them. A second callback merges that run with any saved results
the user has selected and normalizes the combination into store-results
via make_results, which is what puts the main panel into analysis or
comparison mode.

store-results is derived state with exactly one writer, merge_results.
Nothing else may output to it, or the two sources of dataset results
would overwrite each other.
"""

from dash import ALL, Input, Output, State, callback, ctx, html, no_update
import dash_bootstrap_components as dbc

from api_client import check_before_run, run_evaluation, APIError
from store import make_results


@callback(
    Output("store-computed",     "data"),
    Output("btn-run-evaluation", "disabled",  allow_duplicate=True),
    Output("btn-run-evaluation", "children",  allow_duplicate=True),
    Output("run-feedback",       "children",  allow_duplicate=True),
    Output("modal-run-warning",  "is_open",   allow_duplicate=True),
    Output("run-warning-body",    "children"),
    Output("run-warning-actions", "children"),
    Input("btn-run-evaluation",  "n_clicks"),
    Input("btn-run-confirm",     "n_clicks"),
    State("store-sources",    "data"),
    State("metric-selection", "data"),
    prevent_initial_call=True,
)
def run_evaluation_callback(n_clicks, confirm_clicks, sources, selected_metrics):
    """
    Execute dataset evaluation through the backend API.

    Triggered when the user clicks the evaluation button. The backend is
    first asked what needs confirming; if anything does, the confirmation
    window opens instead of running. "Yes, evaluate" in that window
    triggers this callback again and runs without asking.

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
    modal-run-warning.is_open
        Open to ask for confirmation, closed once the run starts.
    run-warning-body.children, run-warning-actions.children
        The warnings, and a button per metric for changing its choice.

    Parameters
    ----------
    n_clicks : int | None
        Number of evaluation button clicks.
    confirm_clicks : int | None
        Number of clicks on "Yes, evaluate".
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
                feedback_message,
                warning_open,
                warning_body,
                warning_actions
            )

    """
    keep = (no_update, no_update, no_update)
    confirmed = ctx.triggered_id == "btn-run-confirm"
    if not (confirm_clicks if confirmed else n_clicks):
        return no_update, no_update, no_update, no_update, *keep

    selected_sources = [s for s in (sources or []) if s.get("selected")]

    if not selected_sources:
        return no_update, no_update, no_update, "Select at least one data source.", *keep
    if not selected_metrics:
        return no_update, no_update, no_update, "Select at least one metric.", *keep

    # An empty scope means every class was unselected. It must not reach
    # the backend, which would read it as no filter and evaluate the
    # whole graph.
    no_classes = [s for s in selected_sources if s.get("scope") == []]
    if no_classes:
        return (no_update, no_update, no_update,
                f"Select at least one class for {no_classes[0]['label']}.", *keep)

    label = "Run Analysis" if len(selected_sources) == 1 else "Run Comparison"

    if not confirmed:
        try:
            warnings = check_before_run(selected_sources, selected_metrics)
        except APIError as exc:
            return {"datasets": [], "error_message": str(exc)}, False, label, "", *keep
        if warnings:
            body, actions = _run_warning_content(warnings)
            return no_update, False, label, "", True, body, actions

    try:
        datasets = run_evaluation(selected_sources, selected_metrics)
    except APIError as exc:
        return ({"datasets": [], "error_message": str(exc)}, False, label, "",
                False, no_update, no_update)

    return ({"datasets": datasets, "error_message": None}, False, label, "",
            False, no_update, no_update)


def _run_warning_content(warnings: list[dict]) -> tuple[list, list]:
    """
    Lay out the warnings, grouped by source, and the buttons to act on them.

    Returns
    -------
    tuple
        (body, actions): one block per warning, and one button per metric
        that has warnings, labelled with the metric's own action.
    """
    body = []
    actions = {}
    for warning in warnings:
        body.append(html.Div([
            html.Div([
                html.Strong(warning.get("label") or warning["dataset_id"]),
                html.Span(f" · {warning.get('metric_name') or warning['metric_id']}",
                          className="text-muted"),
            ], style={"fontSize": "0.85rem"}),
            html.Div(warning["message"], className="fw-semibold",
                     style={"fontSize": "0.85rem"}),
            html.Ul([html.Li(line) for line in warning.get("lines", [])],
                    className="mb-0 ps-3", style={"fontSize": "0.8rem"}),
        ], className="border-start border-3 border-warning ps-2 mb-3"))
        actions.setdefault(warning["metric_id"], warning["action"])

    buttons = [
        dbc.Button(label, id={"type": "btn-run-warning-action", "index": metric_id},
                   color="secondary", outline=True, size="sm", className="me-2",
                   n_clicks=0)
        for metric_id, label in actions.items()
    ]
    return body, buttons


@callback(
    Output("modal-run-warning",     "is_open",  allow_duplicate=True),
    Output("modal-metric-options",  "is_open",  allow_duplicate=True),
    Output("metric-options-active", "data",     allow_duplicate=True),
    Input({"type": "btn-run-warning-action", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def change_choice_from_warning(n_clicks_list):
    """
    Leave the confirmation window for the options of the metric concerned.

    Nothing runs: the user changes the choice there and runs again.

    Returns
    -------
    tuple
        Structure:

            (
                warning_open,
                options_open,
                active_metric_id
            )

    """
    if not ctx.triggered[0]["value"]:
        return no_update, no_update, no_update
    return False, True, ctx.triggered_id["index"]


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