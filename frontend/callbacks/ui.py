
"""
Interactive metric-detail and drilldown callbacks.

This module manages:
- metric card interaction state
- detail panel rendering
- class-level drilldowns
- multilingual heatmap interactions
- visual selection synchronization

Primary Interaction State
-------------------------
store-ui.active_metric
    Currently selected metric card.
store-ui.active_class
    Currently selected ontology class.
store-ui.multilingual_click
    Latest multilingual heatmap click payload.
"""
from dash import Input, Output, State, ALL, callback, ctx, no_update

from layout.components.detail_views import render_detail_panel as _render_detail_panel
from layout.components.metric_renderers.property_coverage import (
    build_analysis_drilldown,
    build_comparison_drilldown,
)
from layout.components.metric_renderers.multilingual_labeling_coverage import (
    build_density_drilldown,
)


@callback(
    Output("store-ui", "data", allow_duplicate=True),
    Input({"type": "metric-card", "index": ALL}, "n_clicks"),
    State("store-ui", "data"),
    prevent_initial_call=True,
)
def update_active_metric(n_clicks_list, ui_state):
    """
    Update the currently active metric selection.

    Parameters
    ----------
    n_clicks_list : list[int | None]
        Pattern-matching metric card click counts.
    ui_state : dict
        Current frontend interaction state.

    Returns
    -------
    dict
        Updated store-ui state.
    """
    if not any(n for n in (n_clicks_list or []) if n):
        return no_update
    triggered_id = ctx.triggered_id
    if not isinstance(triggered_id, dict):
        return no_update
    clicked = triggered_id["index"]
    current = (ui_state or {}).get("active_metric")
    return {
        **(ui_state or {}),
        "active_metric": None if clicked == current else clicked,
        "active_class":  None,
    }


@callback(
    Output({"type": "metric-card", "index": ALL}, "style"),
    Input("store-ui", "data"),
    State({"type": "metric-card", "index": ALL}, "id"),
    State({"type": "metric-card", "index": ALL}, "style"),
    prevent_initial_call=True,
)
def update_card_styles(ui_state, card_ids, current_styles):
    """
    Update metric card visual selection styling.

    Returns
    -------
    list[dict]
        Updated style dictionaries for all metric cards.
    """
    active = (ui_state or {}).get("active_metric")
    new_styles, changed = [], False
    for i, cid in enumerate(card_ids or []):
        is_active = cid["index"] == active
        new_style = {
            "cursor":     "pointer",
            "borderLeft": "3px solid #5B6EF5" if is_active else "1px solid #dee2e6",
            "transition": "border 0.15s",
        }
        new_styles.append(new_style)
        old = (current_styles or [])[i] if i < len(current_styles or []) else {}
        if old.get("borderLeft") != new_style["borderLeft"]:
            changed = True
    return new_styles if changed else [no_update] * len(card_ids or [])


@callback(
    Output("detail-panel", "children"),
    Input("store-ui",      "data"),
    Input("store-results", "data"),
    State("store-ui",      "data"),   # previous value via triggered check
    prevent_initial_call=True,
)
def render_detail_panel_callback(ui_state, results, _ui_state_prev):
    """
    Render the active metric detail panel.

    Parameters
    ----------
    ui_state : dict
        Current frontend interaction state.
    results : dict
        Current evaluation result state.

    Returns
    -------
    Component | no_update
        Rendered metric detail panel.
    """
    if not results or results.get("status") == "error":
        return no_update

    triggered = ctx.triggered_id
    if triggered == "store-ui":
        active_class = (ui_state or {}).get("active_class")
        active_metric = (ui_state or {}).get("active_metric")
        if (active_metric == "property_coverage"
                and active_class is not None):
            return no_update

        if active_metric == "multilingual_labeling_coverage":
            pass   

    active_metric_id = (ui_state or {}).get("active_metric")
    return _render_detail_panel(active_metric_id, results, ui_state=ui_state)


@callback(
    Output("store-ui", "data", allow_duplicate=True),
    Input("property-class-chart", "clickData"),
    State("store-ui", "data"),
    prevent_initial_call=True,
)
def update_active_class(click_data, ui_state):
    """
    Update active ontology class selection from property coverage charts.

    Parameters
    ----------
    click_data : dict | None
        Plotly click event payload.
    ui_state : dict
        Current frontend interaction state.

    Returns
    -------
    dict
        Updated store-ui state.
    """
    if not click_data:
        return no_update
    try:
        raw = click_data["points"][0]["customdata"]
        class_uri = raw[0] if isinstance(raw, (list, tuple)) else raw
    except (KeyError, IndexError, TypeError):
        return no_update
    current = (ui_state or {}).get("active_class")
    return {
        **(ui_state or {}),
        "active_class": None if class_uri == current else class_uri,
    }


@callback(
    Output("property-drilldown-panel", "children"),
    Input("store-ui",      "data"),
    Input("store-results", "data"),
    prevent_initial_call=True,
)
def render_property_drilldown(ui_state, results):
    """
    Render property coverage drilldown content.

    Rendering Modes
    ---------------
    analysis
        Single-dataset class drilldown.
    comparison
        Multi-dataset class comparison drilldown.

    Parameters
    ----------
    ui_state : dict
        Current frontend interaction state.
    results : dict
        Evaluation results.

    Returns
    -------
    Component | no_update
        Drilldown visualization content.
    """
    if (ui_state or {}).get("active_metric") != "property_coverage":
        return no_update
    active_class = (ui_state or {}).get("active_class")
    comparison   = (results or {}).get("mode") == "comparison"

    if comparison:
        return build_comparison_drilldown(active_class, results or {})
    else:
        return build_analysis_drilldown(active_class, results or {})


@callback(
    Output("store-ui", "data", allow_duplicate=True),
    Input({"type": "multilingual-heatmap", "index": ALL}, "clickData"),
    State("store-ui", "data"),
    prevent_initial_call=True,
)
def update_multilingual_click(click_multi, ui_state):
    """
    Store multilingual heatmap interaction state.

    Parameters
    ----------
    click_multi : list[dict | None]
        Pattern-matching heatmap click payloads.
    ui_state : dict
        Current frontend interaction state.

    Returns
    -------
    dict
        Updated store-ui state including multilingual_click payload.
    """
    click_data = next(
        (cd for cd in (click_multi or []) if cd is not None),
        None,
    )
    if not click_data:
        return no_update
    return {**(ui_state or {}), "multilingual_click": click_data}