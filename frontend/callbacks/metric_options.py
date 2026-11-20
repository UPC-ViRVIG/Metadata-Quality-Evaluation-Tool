"""
Per-metric options: the gear next to a configurable metric, the window
with one choice per data source, and the SHACL profile viewer.

Which metrics have options, and what their choices are, comes from GET
/metrics through store-metric-options, so no metric is named here. The
chosen values are stored on each source in store-sources, because the
same metric can be configured differently for each dataset.
"""

from dash import ALL, Input, Output, State, callback, ctx, html, no_update
import dash_bootstrap_components as dbc

from api_client import get_profiles, APIError
from layout.components.profile_view import build_profile_definition


@callback(
    Output("store-profiles", "data"),
    Input("store-profiles",  "id"),
)
def load_profiles(_):
    """
    Fetch the SHACL profile definitions once, on startup.

    Returns
    -------
    list[dict]
        The GET /profiles response, or an empty list when the backend
        cannot be reached.
    """
    try:
        return get_profiles()
    except APIError:
        return []


@callback(
    Output("modal-metric-options",  "is_open"),
    Output("metric-options-active", "data"),
    Input({"type": "btn-metric-options", "index": ALL}, "n_clicks"),
    Input("btn-metric-options-close", "n_clicks"),
    prevent_initial_call=True,
)
def toggle_metric_options(gear_clicks, close_clicks):
    """
    Open the options window for the metric whose gear was clicked.

    Returns
    -------
    tuple
        Structure:

            (
                modal_open,
                active_metric_id
            )

    """
    if ctx.triggered_id == "btn-metric-options-close":
        return False, no_update
    if not ctx.triggered[0]["value"]:
        return no_update, no_update
    return True, ctx.triggered_id["index"]


@callback(
    Output("metric-options-title", "children"),
    Output("metric-options-body",  "children"),
    Input("modal-metric-options",  "is_open"),
    Input("metric-options-active", "data"),
    State("store-sources",         "data"),
    State("store-metric-options",  "data"),
    State("store-profiles",        "data"),
    prevent_initial_call=True,
)
def render_metric_options(is_open, metric_id, sources, metric_options, profiles):
    """
    Build one row per data source, with a control for each option.

    The body is rebuilt each time the window opens, so sources added
    since it was last open are listed.

    Returns
    -------
    tuple
        Structure:

            (
                title,
                body
            )

    """
    spec = (metric_options or {}).get(metric_id)
    if not is_open or not spec:
        return no_update, no_update

    if not sources:
        return f"{spec['name']} options", html.P(
            "Add a data source first. Options are chosen per source.",
            className="text-muted mb-0",
            style={"fontSize": "0.85rem"},
        )

    header = dbc.Row([
        dbc.Col(html.Small("Data source", className="text-muted"), width=5),
        dbc.Col(html.Small(" · ".join(o["label"] for o in spec["options"].values()),
                           className="text-muted"), width=7),
    ], className="g-2 mb-1")

    rows = [header]
    for source in sources:
        current = (source.get("metric_options") or {}).get(metric_id, {})
        label = [source["label"]]
        if not source.get("selected"):
            label.append(html.Small(" (not selected)", className="text-muted"))

        controls = [
            dbc.Select(
                id={"type": "metric-option-select",
                    "index": f"{source['id']}::{metric_id}::{name}"},
                options=[{"label": choice["label"], "value": choice["id"]}
                         for choice in option["choices"]],
                value=current.get(name, option["default"]),
                size="sm",
                className="mb-1",
            )
            for name, option in spec["options"].items()
        ]
        rows.append(dbc.Row([
            dbc.Col(html.Span(label, style={"fontSize": "0.85rem"}), width=5),
            dbc.Col(controls, width=7),
        ], className="g-2 mb-1 align-items-center"))

    body = rows
    if "profile" in spec["options"] and profiles:
        body = rows + [
            html.Hr(className="my-3"),
            html.P("What each profile checks",
                   className="text-muted text-uppercase fw-semibold mb-2",
                   style={"fontSize": "0.75rem", "letterSpacing": "0.06em"}),
            dbc.Select(
                id="metric-options-profile-preview",
                options=[{"label": p["name"], "value": p["id"]} for p in profiles],
                value=profiles[0]["id"],
                size="sm",
                className="mb-3",
            ),
            html.Div(
                build_profile_definition(profiles[0]),
                id="metric-options-profile-definition",
            ),
        ]

    return f"{spec['name']} options", body


@callback(
    Output("metric-options-profile-definition", "children"),
    Input("metric-options-profile-preview",     "value"),
    State("store-profiles",                     "data"),
    prevent_initial_call=True,
)
def preview_profile(profile_id, profiles):
    """
    Show the definition of the profile picked in the preview list.
    """
    profile = next((p for p in profiles or [] if p["id"] == profile_id), None)
    return build_profile_definition(profile)


@callback(
    Output("store-sources", "data", allow_duplicate=True),
    Input({"type": "metric-option-select", "index": ALL}, "value"),
    State("store-sources",        "data"),
    State("store-metric-options", "data"),
    prevent_initial_call=True,
)
def save_metric_option(values, sources, metric_options):
    """
    Store a changed option on the source it belongs to.

    A value equal to the default is removed rather than stored, so a
    source with nothing changed keeps an empty metric_options and its
    requests stay exactly as they were before options existed.

    Returns
    -------
    list[dict]
        Updated store-sources state.
    """
    triggered = ctx.triggered_id
    if not sources or not isinstance(triggered, dict):
        return no_update

    source_id, metric_id, name = triggered["index"].split("::", 2)
    value   = ctx.triggered[0]["value"]
    default = (metric_options or {}).get(metric_id, {}) \
        .get("options", {}).get(name, {}).get("default")

    updated = []
    for source in sources:
        if source["id"] != source_id:
            updated.append(source)
            continue

        source = dict(source)
        options = {mid: dict(opts)
                   for mid, opts in (source.get("metric_options") or {}).items()}
        chosen = options.setdefault(metric_id, {})
        if value == default:
            chosen.pop(name, None)
        else:
            chosen[name] = value
        if not chosen:
            options.pop(metric_id)
        source["metric_options"] = options
        updated.append(source)

    return updated


@callback(
    Output("modal-profile-view", "is_open"),
    Output("profile-view-body",  "children"),
    Input({"type": "btn-view-profile", "index": ALL}, "n_clicks"),
    Input("btn-profile-view-close", "n_clicks"),
    State("store-profiles", "data"),
    prevent_initial_call=True,
)
def toggle_profile_view(view_clicks, close_clicks, profiles):
    """
    Open the definition of the profile a result was scored against.

    Returns
    -------
    tuple
        Structure:

            (
                modal_open,
                body
            )

    """
    if ctx.triggered_id == "btn-profile-view-close":
        return False, no_update
    if not ctx.triggered[0]["value"]:
        return no_update, no_update

    profile_id = ctx.triggered_id["index"].split("::", 1)[1]
    profile = next((p for p in profiles or [] if p["id"] == profile_id), None)
    return True, build_profile_definition(profile)
