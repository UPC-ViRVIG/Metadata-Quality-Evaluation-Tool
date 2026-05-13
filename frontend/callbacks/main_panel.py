from dash import Input, Output, callback

from layout.main_panel import build_guide, build_error, build_analysis, build_comparison


@callback(
    Output("main-panel",  "children"),
    Output("store-ui",    "data", allow_duplicate=True),
    Input("store-results", "data"),
    prevent_initial_call=True,
)
def render_main_panel(results):
    """
    Render the main visualization panel based on evaluation state.

    Rendering Modes
    ---------------
    guide
        Displayed before evaluation.
    error
        Displayed when evaluation fails.
    analysis
        Single-dataset analytical visualization mode.
    comparison
        Multi-dataset comparison visualization mode.

    Outputs
    -------
    main-panel.children
        Dynamically generated frontend layout.
    store-ui.data
        Initial UI interaction state.

    Returns
    -------
    tuple
        Structure:

            (
                rendered_layout,
                ui_state
            )
    """
    if results is None:
        return build_guide(), {"active_metric": None, "active_class": None}
    if results.get("status") == "error":
        return (
            build_error(results.get("error_message", "Unknown error.")),
            {"active_metric": None, "active_class": None},
        )

    datasets = results.get("datasets", [])

    first_metric = None
    if datasets:
        metrics = [
            m for m in datasets[0].get("metrics", [])
            if m.get("status") not in ("error", "skipped")
        ]
        if metrics:
            first_metric = metrics[0]["metric_id"]

    initial_ui = {"active_metric": first_metric, "active_class": None}

    if results.get("mode") == "analysis":
        return build_analysis(datasets, active_metric_id=first_metric), initial_ui
    if results.get("mode") == "comparison":
        return build_comparison(datasets, active_metric_id=first_metric), initial_ui

    return build_guide(), {"active_metric": None, "active_class": None}