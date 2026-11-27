"""
Per-metric options: the gear next to a configurable metric, the window
with one choice per data source, and the SHACL profile viewer.

Which metrics have options, and what their choices are, comes from GET
/metrics through store-metric-options, so no metric is named here. The
chosen values are stored on each source in store-sources, because the
same metric can be configured differently for each dataset.
"""

import base64

from dash import ALL, Input, Output, State, callback, ctx, dcc, html, no_update
import dash_bootstrap_components as dbc

from api_client import (
    get_metrics, get_profiles, upload_profile, delete_profile, APIError,
)
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
    Output("shacl-upload-message",  "data", allow_duplicate=True),
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
                active_metric_id,
                upload_feedback
            )

    """
    if ctx.triggered_id == "btn-metric-options-close":
        return False, no_update, None
    if not ctx.triggered[0]["value"]:
        return no_update, no_update, no_update
    return True, ctx.triggered_id["index"], None


@callback(
    Output("metric-options-title", "children"),
    Output("metric-options-body",  "children"),
    Input("modal-metric-options",  "is_open"),
    Input("metric-options-active", "data"),
    Input("store-metric-options",  "data"),
    Input("store-profiles",        "data"),
    Input("shacl-upload-message",  "data"),
    State("store-sources",         "data"),
    State("metric-options-preview", "data"),
    prevent_initial_call=True,
)
def render_metric_options(is_open, metric_id, metric_options, profiles,
                          message, sources, preview_id):
    """
    Build one row per data source, with a control for each option.

    The body is rebuilt each time the window opens, so sources added
    since it was last open are listed, and again when the choices
    change, so a profile just added or removed shows in every row.
    The outcome of the last upload or removal is shown in the section
    it concerns: under the upload area, or above the profile preview.

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
        rows = [html.P(
            "Add a data source first. Options are chosen per source.",
            className="text-muted mb-0",
            style={"fontSize": "0.85rem"},
        )]
    else:
        rows = [dbc.Row([
            dbc.Col(html.Small("Data source", className="text-muted"), width=5),
            dbc.Col(html.Small(" · ".join(o["label"] for o in spec["options"].values()),
                               className="text-muted"), width=7),
        ], className="g-2 mb-1")]

    for source in sources or []:
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
    if "profile" in spec["options"]:
        body = rows + [
            html.Hr(className="my-3"),
            html.P("Add your own SHACL profile",
                   className="text-muted text-uppercase fw-semibold mb-2",
                   style={"fontSize": "0.75rem", "letterSpacing": "0.06em"}),
            dcc.Upload(
                id="upload-shacl-profile",
                multiple=False,
                accept=".ttl,.rdf,.xml,.nt,.n3,.jsonld,.owl",
                children=html.Div([
                    "Drag and drop a SHACL file, or ",
                    html.A("select one", style={"textDecoration": "underline"}),
                ]),
                style={
                    "borderWidth": "1px", "borderStyle": "dashed",
                    "borderColor": "#adb5bd", "borderRadius": "6px",
                    "textAlign": "center", "padding": "14px",
                    "cursor": "pointer", "backgroundColor": "#f8f9fa",
                    "fontSize": "0.8rem",
                },
            ),
            _message_alert(message, "upload"),
            html.Small(
                "Each record is scored only against the shapes that target "
                "it. The file needs at least one shape with a target "
                "(sh:targetClass, sh:targetNode, sh:targetSubjectsOf, "
                "sh:targetObjectsOf or a SPARQL target). SPARQL checks and "
                "targets are accepted when they only read the data (no SERVICE "
                "or FROM); SHACL rules are not. Sources on "
                "Auto use an added profile whenever it matches records in their "
                "data, in preference to the built-in ones.",
                className="text-muted d-block mt-1",
                style={"fontSize": "0.75rem"},
            ),
        ]

        if profiles:
            ids = [p["id"] for p in profiles]
            selected = preview_id if preview_id in ids else ids[0]
            body += [
                html.Hr(className="my-3"),
                html.P("What each profile checks",
                       className="text-muted text-uppercase fw-semibold mb-2",
                       style={"fontSize": "0.75rem", "letterSpacing": "0.06em"}),
                _message_alert(message, "preview"),
                dbc.Select(
                    id="metric-options-profile-preview",
                    options=[{"label": p["name"] + (" (added)" if p.get("uploaded") else ""),
                              "value": p["id"]} for p in profiles],
                    value=selected,
                    size="sm",
                    className="mb-3",
                ),
                html.Div(
                    _profile_preview(next(p for p in profiles if p["id"] == selected)),
                    id="metric-options-profile-definition",
                ),
            ]

    return f"{spec['name']} options", body


def _profile_preview(profile: dict | None) -> html.Div:
    """
    A profile's definition, with a remove button when a user added it.
    """
    remove = dbc.Button(
        "Remove this profile",
        id={"type": "btn-remove-profile", "index": profile["id"]},
        color="danger", outline=True, size="sm", className="mb-2",
    ) if profile and profile.get("uploaded") else html.Span()
    return html.Div([remove, build_profile_definition(profile)])


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
    return _profile_preview(profile)


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


def _refreshed_options_and_profiles():
    """
    Read the option schema and profiles again after the set changed.

    Returns
    -------
    tuple
        (store-metric-options data, store-profiles data)
    """
    metrics = get_metrics()
    options = {
        m["metric_id"]: {"name": m["name"], "options": m["options"]}
        for m in metrics if m.get("options")
    }
    return options, get_profiles()


@callback(
    Output("store-metric-options",   "data", allow_duplicate=True),
    Output("store-profiles",         "data", allow_duplicate=True),
    Output("metric-options-preview", "data", allow_duplicate=True),
    Output("shacl-upload-message",   "data", allow_duplicate=True),
    Output("upload-shacl-profile",   "contents", allow_duplicate=True),
    Output("store-sources",          "data", allow_duplicate=True),
    Input("upload-shacl-profile",    "contents"),
    State("upload-shacl-profile",    "filename"),
    State("metric-options-active",   "data"),
    State("store-sources",           "data"),
    prevent_initial_call=True,
)
def upload_shacl_profile(contents, filename, metric_id, sources):
    """
    Send a SHACL file to the backend and select it for every source.

    Uploading a profile says the user wants to evaluate with it, so it
    becomes the choice of every source listed in the window; each
    source's dropdown can still change that. On success the option
    schema and profiles are read again, so the new profile appears in
    the dropdowns and is previewed. A file the backend refuses is
    reported with its reason, and no choice changes.

    Returns
    -------
    tuple
        Structure:

            (
                metric_options,
                profiles,
                preview_id,
                feedback,
                upload_contents,
                sources
            )

    """
    if not contents:
        return no_update, no_update, no_update, no_update, None, no_update

    name = filename or "profile.ttl"
    try:
        payload = base64.b64decode(contents.split(",", 1)[-1])
    except (ValueError, TypeError):
        return no_update, no_update, no_update, _feedback(
            "upload", f"{name} was not added",
            "The browser could not read the file.", ok=False), None, no_update

    try:
        profile = upload_profile(name, payload)
        options, profiles = _refreshed_options_and_profiles()
    except APIError as exc:
        return no_update, no_update, no_update, _feedback(
            "upload", f"{name} was not added", exc.message, ok=False), None, no_update

    updated = []
    for source in sources or []:
        source = dict(source)
        chosen = {mid: dict(values)
                  for mid, values in (source.get("metric_options") or {}).items()}
        chosen.setdefault(metric_id, {})["profile"] = profile["id"]
        source["metric_options"] = chosen
        updated.append(source)

    message = ("It is now selected for every source above, and shown below. "
               "Each source's choice can still be changed.")
    if not updated:
        message = ("Add a data source to evaluate with it; it is a choice "
                   "for every source, and shown below.")
    return options, profiles, profile["id"], _feedback(
        "upload", f"Added {profile['name']}", message, ok=True), None, updated


@callback(
    Output("store-metric-options",   "data", allow_duplicate=True),
    Output("store-profiles",         "data", allow_duplicate=True),
    Output("store-sources",          "data", allow_duplicate=True),
    Output("metric-options-preview", "data", allow_duplicate=True),
    Output("shacl-upload-message",   "data", allow_duplicate=True),
    Input({"type": "btn-remove-profile", "index": ALL}, "n_clicks"),
    State("store-sources", "data"),
    prevent_initial_call=True,
)
def remove_shacl_profile(n_clicks_list, sources):
    """
    Remove a profile a user added, and stop any source from using it.

    A source still set to the removed profile would make the next run
    fail with an invalid option, so such sources go back to the default.

    Returns
    -------
    tuple
        Structure:

            (
                metric_options,
                profiles,
                sources,
                preview_id,
                feedback
            )

    """
    if not ctx.triggered[0]["value"]:
        return no_update, no_update, no_update, no_update, no_update

    profile_id = ctx.triggered_id["index"]
    try:
        delete_profile(profile_id)
        options, profiles = _refreshed_options_and_profiles()
    except APIError as exc:
        return no_update, no_update, no_update, no_update, _feedback(
            "preview", "The profile was not removed", exc.message, ok=False)

    updated = []
    reset = 0
    for source in sources or []:
        chosen = source.get("metric_options") or {}
        if any(profile_id in values.values() for values in chosen.values()):
            reset += 1
            source = dict(source)
            source["metric_options"] = {
                metric_id: {name: value for name, value in values.items()
                            if value != profile_id}
                for metric_id, values in chosen.items()
            }
            source["metric_options"] = {
                metric_id: values
                for metric_id, values in source["metric_options"].items() if values
            }
        updated.append(source)

    message = ""
    if reset:
        message = f"{reset} source(s) using it went back to Auto."
    return options, profiles, updated, None, _feedback(
        "preview", "Profile removed", message, ok=True)


def _feedback(section: str, title: str, message: str, ok: bool) -> dict:
    """
    Describe the outcome of an upload or removal for shacl-upload-message.

    Parameters
    ----------
    section : str
        Where it is shown: "upload" under the upload area, "preview"
        above the profile preview.
    title : str
        One line saying what happened.
    message : str
        The reason or detail, such as the backend's reason for a refusal.
    ok : bool
        Whether the action succeeded.
    """
    return {"section": section, "title": title, "message": message, "ok": ok}


def _message_alert(message: dict | None, section: str):
    """Show the stored outcome if it belongs to this section, else nothing."""
    if not message or message.get("section") != section:
        return None
    return dbc.Alert(
        [html.Strong(message["title"]),
         html.Div(message["message"]) if message.get("message") else None],
        color="success" if message["ok"] else "danger",
        dismissable=True,
        className="mt-2 mb-2 py-2",
        style={"fontSize": "0.8rem"},
    )
