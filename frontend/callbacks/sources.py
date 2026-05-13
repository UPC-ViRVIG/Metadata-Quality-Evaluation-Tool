"""
Sidebar state-management and dataset configuration callbacks.

Primary Shared Stores
---------------------
store-sources
    Source configuration and ontology scope state.
store-ontology
    Lazily loaded ontology hierarchy cache.
metric-selection
    Flattened list of selected metrics.
store-metric-dims
    Metric → dimension lookup mapping.
store-dimensions
    Dimension metadata cache.
"""

import uuid

from dash import Input, Output, State, ALL, callback, ctx, no_update
import dash_bootstrap_components as dbc
from dash import html

from api_client import get_metrics, get_dimensions, APIError
from layout.sidebar import build_source_item
from store import make_source

_LABEL_STYLE = {
    "display": "flex", "alignItems": "center", "gap": "8px",
    "marginBottom": "4px", "fontSize": "0.875rem", "cursor": "pointer",
}

@callback(
    Output("metric-accordion",   "children"),
    Output("metric-selection",   "data"),
    Output("store-metric-dims",  "data"),
    Output("store-dimensions",   "data"),
    Input("store-sources", "id"),
)
def populate_metrics(_):
    """
    Initialize metric selection UI and dimension metadata.

    Backend Endpoints
    -----------------
    GET /metrics
    GET /dimensions

    Outputs
    -------
    metric-accordion.children
        Dynamically generated metric accordion layout.
    metric-selection.data
        Initial empty metric selection list.
    store-metric-dims.data
        Mapping:
            metric_id -> dimension_name

    store-dimensions.data
        Cached dimension metadata.
    """
    try:
        metrics    = get_metrics()
        dimensions = get_dimensions()
    except APIError:
        return [], [], {}, {}

    dim_info = {d["name"]: d for d in dimensions}

    from collections import OrderedDict
    by_dim: dict[str, list] = OrderedDict()
    for m in metrics:
        dim = m.get("dimension", "Other")
        by_dim.setdefault(dim, []).append(m)

    items = []
    for dim, dim_metrics in by_dim.items():
        options = [
            {"label": m["name"], "value": m["metric_id"]}
            for m in dim_metrics
        ]

        # Tooltips
        tip_spans = []
        for m in dim_metrics:
            tip_id = f"tip-metric-{m['metric_id']}"
            tip_spans.append(html.Div([
                html.Span(" ℹ", id=tip_id,
                          style={"fontSize": "0.70rem", "color": "#adb5bd",
                                 "cursor": "help", "userSelect": "none"}),
                dbc.Tooltip(
                    [html.Strong(m.get("tooltip", "")), html.Br(),
                     html.Small(m.get("description", ""),
                                style={"color": "#dee2e6"})],
                    target=tip_id, placement="right",
                    style={"maxWidth": "280px"},
                ),
            ], style={"marginBottom": "4px", "lineHeight": "1.6rem"}))

        dim_tip_id     = f"tip-dim-{dim.lower().replace(' ', '-')}"
        dim_info_entry = dim_info.get(dim, {})

        title = html.Span([
            html.Span(dim, style={"fontSize": "0.82rem", "fontWeight": "500"}),
            html.Span(" ℹ", id=dim_tip_id,
                      style={"fontSize": "0.70rem", "color": "#adb5bd",
                             "cursor": "help", "userSelect": "none"}),
            dbc.Tooltip(
                [html.Strong(dim_info_entry.get("tooltip", "")), html.Br(),
                 html.Small(dim_info_entry.get("description", ""),
                            style={"color": "#dee2e6"})],
                target=dim_tip_id, placement="right",
                style={"maxWidth": "280px"},
            ),
        ])

        items.append(
            dbc.AccordionItem(
                dbc.Row([
                    dbc.Col(
                        dbc.Checklist(
                            id={"type": "dim-checklist", "index": dim},
                            options=options,
                            value=[],
                            labelStyle=_LABEL_STYLE,
                        ),
                        width=10,
                    ),
                    dbc.Col(
                        html.Div(tip_spans),
                        width=2,
                        className="ps-0",
                    ),
                ], className="g-0"),
                title=title,
            )
        )

    accordion = dbc.Accordion(
        items,
        start_collapsed=False,
        flush=True,
        className="mb-1",
        style={"fontSize": "0.875rem"},
    )

    dims_map   = {m["metric_id"]: m.get("dimension", "Other") for m in metrics}
    dims_store = {d["name"]: {"description": d["description"],
                               "tooltip":     d["tooltip"]}
                  for d in dimensions}
    return accordion, [], dims_map, dims_store


@callback(
    Output("metric-selection", "data", allow_duplicate=True),
    Input({"type": "dim-checklist", "index": ALL}, "value"),
    prevent_initial_call=True,
)
def sync_metric_selection(checklist_values):
    """
    Flatten all per-dimension checklist selections into one list.
    
    Parameters
    ----------
    checklist_values : list[list[str]]
        Per-dimension selected metric identifiers.

    Returns
    -------
    list[str]
        Flattened list of selected metric identifiers.
    """
    flat = []
    for vals in (checklist_values or []):
        flat.extend(vals or [])
    return flat

@callback(
    Output("modal-add-source",     "is_open"),
    Output("modal-title",          "children"),
    Output("modal-edit-id",        "data"),
    Output("input-source-label",   "value"),
    Output("input-source-type",    "value"),
    Output("input-file-path",      "value"),
    Output("input-file-format",    "value"),
    Output("input-endpoint-url",   "value"),
    Output("input-sparql-query",   "value"),
    Output("modal-source-feedback","children"),
    # Triggers
    Input("btn-add-source",   "n_clicks"),
    Input("btn-modal-cancel", "n_clicks"),
    Input({"type": "btn-edit-source", "index": ALL}, "n_clicks"),
    # State needed for edit pre-fill
    State("store-sources", "data"),
    prevent_initial_call=True,
)
def open_or_close_modal(
    _add, _cancel, _edit_clicks,
    sources,
):
    """
    Control the dataset/source configuration modal lifecycle.

    This callback unifies:
        - open-for-add
        - open-for-edit
        - cancel/close

    Outputs
    -------
    modal-add-source.is_open
        Modal visibility state.
    modal-title.children
        Context-sensitive modal title.
    modal-edit-id.data
        Source ID currently being edited.
        None indicates add mode.
    input-* fields
        Modal form field state.
    modal-source-feedback.children
        Validation or error feedback.
    """
    trigger = ctx.triggered_id

    # Cancel
    if trigger == "btn-modal-cancel":
        return (
            False,
            no_update, no_update, no_update, no_update,
            no_update, no_update, no_update, no_update,
            "",
        )

    # Add
    if trigger == "btn-add-source":
        return (
            True,
            "Add Data Source",
            None,          # no source being edited
            "",            # label
            "rdf_file",    # type
            "",            # file path
            "turtle",      # format
            "",            # endpoint url
            "",            # sparql query
            "",            # feedback
        )

    # Edit
    if isinstance(trigger, dict) and trigger.get("type") == "btn-edit-source":
        # Guard: only act when a click actually happened
        if not any(n for n in (_edit_clicks or []) if n):
            return (False, no_update, no_update, no_update, no_update,
                    no_update, no_update, no_update, no_update, "")

        source_id = trigger["index"]
        source    = next((s for s in (sources or []) if s["id"] == source_id), None)

        if source is None:
            return (False, no_update, no_update, no_update, no_update,
                    no_update, no_update, no_update, no_update, "")

        cfg = source["source_config"]
        return (
            True,
            "Edit Data Source",
            source_id,
            source["label"],
            cfg["type"],
            cfg.get("file_path",     ""),
            cfg.get("format",        "turtle"),
            cfg.get("endpoint_url",  ""),
            cfg.get("query",         ""),
            "",
        )

    return (False, no_update, no_update, no_update, no_update,
            no_update, no_update, no_update, no_update, "")

@callback(
    Output("source-fields-rdf",    "style"),
    Output("source-fields-sparql", "style"),
    Input("input-source-type", "value"),
)
def toggle_source_fields(source_type):
    """
    Toggle visible source configuration form sections

    Parameters
    ----------
    source_type : str
        Selected source type.
        Supported values:
            - "rdf_file"
            - "sparql_endpoint"

    Returns
    -------
    tuple[dict, dict]
        Style dictionaries controlling visibility of:
            (
                rdf_fields_style,
                sparql_fields_style
            )
    """
    if source_type == "rdf_file":
        return {}, {"display": "none"}
    return {"display": "none"}, {}

@callback(
    Output("store-sources",         "data",     allow_duplicate=True),
    Output("modal-source-feedback", "children", allow_duplicate=True),
    Output("modal-add-source",      "is_open",  allow_duplicate=True),
    Input("btn-modal-confirm", "n_clicks"),
    State("modal-edit-id",       "data"),
    State("store-sources",       "data"),
    State("input-source-label",  "value"),
    State("input-source-type",   "value"),
    State("input-file-path",     "value"),
    State("input-file-format",   "value"),
    State("input-endpoint-url",  "value"),
    State("input-sparql-query",  "value"),
    prevent_initial_call=True,
)
def confirm_modal(
    n_clicks,
    edit_id,
    sources,
    label, source_type,
    file_path, file_format,
    endpoint_url, sparql_query,
):
    """
    Persist dataset/source configuration changes. 
    Supports creating and updating sources.

    Returns
    -------
    store-sources.data
        Updated frontend source state.
    modal-source-feedback.children
        Validation feedback message.
    modal-add-source.is_open
        Modal visibility state.
    """
    if not n_clicks:
        return no_update, no_update, no_update

    label = (label or "").strip()
    if not label:
        return no_update, "Please enter a label.", no_update

    if source_type == "rdf_file":
        file_path = (file_path or "").strip()
        if not file_path:
            return no_update, "Please enter a file path.", no_update
        source_config = {
            "type":      "rdf_file",
            "file_path": file_path,
            "format":    file_format or "turtle",
        }
    else:
        endpoint_url = (endpoint_url or "").strip()
        sparql_query = (sparql_query or "").strip()
        if not endpoint_url:
            return no_update, "Please enter an endpoint URL.", no_update
        if not sparql_query:
            return no_update, "Please enter a CONSTRUCT query.", no_update
        source_config = {
            "type":         "sparql_endpoint",
            "endpoint_url": endpoint_url,
            "query":        sparql_query,
        }

    sources = sources or []

    if edit_id is not None:
        updated = []
        for s in sources:
            if s["id"] == edit_id:
                updated.append({
                    **s,
                    "label":         label,
                    "source_config": source_config,
                })
            else:
                updated.append(s)
        return updated, "", False

    new_source = make_source(
        id=str(uuid.uuid4()),
        label=label,
        source_config=source_config,
        selected=True,
    )
    return sources + [new_source], "", False

@callback(
    Output("store-sources", "data", allow_duplicate=True),
    Input({"type": "btn-delete-source", "index": ALL}, "n_clicks"),
    State("store-sources", "data"),
    prevent_initial_call=True,
)
def delete_source(n_clicks_list, sources):
    """
    Delete a dataset/source from frontend state.

    Parameters
    ----------
    n_clicks_list : list[int | None]
        Pattern-matching delete button click states.
    sources : list[dict]
        Current source configuration state.

    Returns
    -------
    list[dict]
        Updated source list with the selected source removed.
    """
    if not any(n for n in (n_clicks_list or []) if n):
        return no_update

    source_id = ctx.triggered_id["index"]
    return [s for s in (sources or []) if s["id"] != source_id]


@callback(
    Output("store-sources", "data", allow_duplicate=True),
    Input({"type": "source-checkbox", "index": ALL}, "value"),
    State("store-sources", "data"),
    prevent_initial_call=True,
)
def toggle_source_selection(checkbox_values, sources):
    """
    Synchronize dataset selection checkboxes with store-sources state.
    """
    if not sources:
        return no_update

    checked_map = {
        item["id"]["index"]: item["value"]
        for item in ctx.inputs_list[0]
    }

    updated = []
    for source in sources:
        s = dict(source)
        if source["id"] in checked_map:
            s["selected"] = bool(checked_map[source["id"]])
        updated.append(s)

    return updated

@callback(
    Output("source-list", "children"),
    Input("store-sources", "data"),
    State("source-list",   "children"),
)
def render_source_list(sources, current_children):
    """
    Render sidebar dataset/source cards.

    Returns
    -------
    list[Component]
        Rendered source card components.
    """
    if not sources:
        return html.P(
            "No sources added yet.",
            className="text-muted",
            style={"fontSize": "0.8rem"},
        )

    if ctx.triggered_id == "store-sources" and current_children:
        triggered_keys = [
            (s["id"], s["label"], s["source_config"].get("file_path", "")
             or s["source_config"].get("endpoint_url", ""))
            for s in sources
        ]
        if triggered_keys == _last_rendered_source_keys[0]:
            return no_update
        _last_rendered_source_keys[0] = triggered_keys

    return [build_source_item(s) for s in sources]


_last_rendered_source_keys = [[]]

@callback(
    Output("btn-run-evaluation", "disabled"),
    Output("btn-run-evaluation", "children"),
    Output("run-feedback",       "children"),
    Input("store-sources",    "data"),
    Input("metric-selection", "data"),
)
def update_run_button(sources, selected_metrics):
    """
    Update evaluation button enabled state and label
    """
    selected_sources = [s for s in (sources or []) if s.get("selected")]
    n_sources = len(selected_sources)
    n_metrics = len(selected_metrics or [])

    if n_sources == 0 and n_metrics == 0:
        return True, "Run Evaluation", ""
    if n_sources == 0:
        return True, "Run Evaluation", "Select at least one data source."
    if n_metrics == 0:
        return True, "Run Evaluation", "Select at least one metric."

    label = "Run Analysis" if n_sources == 1 else "Run Comparison"
    return False, label, ""

@callback(
    Output("store-sources",  "data", allow_duplicate=True),
    Output("store-ontology", "data", allow_duplicate=True),
    Input({"type": "btn-expand-source", "index": ALL}, "n_clicks"),
    State("store-sources",  "data"),
    State("store-ontology", "data"),
    prevent_initial_call=True,
)
def toggle_expand_source(n_clicks_list, sources, ontology_store):
    """
    Toggle ontology tree expansion state for a dataset/source.

    Returns
    -------
    tuple
        (
            updated_sources,
            updated_ontology_store
        )
    """
    if not any(n for n in (n_clicks_list or []) if n):
        return no_update, no_update

    source_id = ctx.triggered_id["index"]
    sources   = list(sources or [])
    ontology  = dict(ontology_store or {})

    updated = []
    for s in sources:
        if s["id"] == source_id:
            s = dict(s)
            s["expanded"] = not s.get("expanded", False)

            if s["expanded"] and source_id not in ontology:
                # Write sentinel None first — triggers render_scope_trees
                # to show the spinner before the fetch starts.
                ontology[source_id] = None
        updated.append(s)

    return updated, ontology


@callback(
    Output("store-ontology", "data", allow_duplicate=True),
    Input("store-ontology",  "data"),
    State("store-sources",   "data"),
    prevent_initial_call=True,
)
def fetch_ontology(ontology_store, sources):
    """
    Lazily fetch ontology hierarchy data from the backend.
    """
    ontology = dict(ontology_store or {})
    sources  = sources or []

    to_fetch = [
        s for s in sources
        if s.get("expanded") and ontology.get(s["id"]) is None
    ]
    if not to_fetch:
        return no_update

    updated = False
    for s in to_fetch:
        sid = s["id"]
        try:
            from api_client import get_ontology, APIError
            result = get_ontology(s)
            ontology[sid] = result
        except APIError as exc:
            ontology[sid] = {"error": str(exc)}
        updated = True

    return ontology if updated else no_update

@callback(
    Output({"type": "scope-tree", "index": ALL}, "children"),
    Output({"type": "scope-tree", "index": ALL}, "style"),
    Input("store-ontology", "data"),
    State("store-sources",  "data"),
    prevent_initial_call=True,
)
def render_scope_trees(ontology_store, sources):
    """
    Render ontology/class scope selection trees.

    Returns
    -------
    tuple
        (
            tree_children,
            tree_styles
        )
    """
    from layout.sidebar import build_scope_tree

    sources      = sources or []
    ontology     = ontology_store or {}
    children_out = []
    styles_out   = []

    base_style = {
        "border":          "1px solid #dee2e6",
        "borderTop":       "none",
        "borderRadius":    "0 0 4px 4px",
        "padding":         "8px",
        "backgroundColor": "#f8f9fa",
        "maxHeight":       "260px",
        "overflowY":       "auto",
    }

    for s in sources:
        sid      = s["id"]
        expanded = s.get("expanded", False)
        scope    = set(s.get("scope") or [])

        if not expanded:
            children_out.append(no_update)
            styles_out.append({"display": "none"})
            continue

        styles_out.append({**base_style, "display": "block"})

        tree_data = ontology.get(sid)
        if tree_data is None:
            children_out.append(
                html.Div([
                    dbc.Spinner(size="sm", color="primary",
                                spinner_style={"marginRight": "8px"}),
                    html.Span("Loading ontology…",
                              className="text-muted",
                              style={"fontSize": "0.8rem"}),
                ], style={"display": "flex", "alignItems": "center",
                          "padding": "8px 0"})
            )
        elif "error" in tree_data:
            children_out.append(
                html.P(f"Could not load ontology: {tree_data['error']}",
                       className="text-danger mb-0",
                       style={"fontSize": "0.8rem"})
            )
        else:
            children_out.append(
                build_scope_tree(tree_data.get("classes", []), sid, scope)
            )

    return children_out, styles_out

def _all_descendants(uri: str, classes: list) -> set:
    """
    Recursively collect all descendant class URIs.

    Parameters
    ----------
    uri : str
        Root class URI.
    classes : list
        Recursive ontology hierarchy tree.

    Returns
    -------
    set[str]
        All descendant class URIs.
    """
    result = set()
    for cls in classes:
        if cls["uri"] == uri:
            for child in cls.get("children", []):
                result.add(child["uri"])
                result |= _all_descendants(child["uri"], cls["children"])
        else:
            result |= _all_descendants(uri, cls.get("children", []))
    return result


def _flatten_uris(classes: list) -> set:
    """
    Flatten a recursive ontology hierarchy into a set of class URIs.

    Parameters
    ----------
    classes : list
        Recursive ontology hierarchy tree.

    Returns
    -------
    set[str]
        Set of all class URIs contained in the tree.
    """
    result = set()
    for cls in classes:
        result.add(cls["uri"])
        result |= _flatten_uris(cls.get("children", []))
    return result


@callback(
    Output("store-sources", "data", allow_duplicate=True),
    Input({"type": "scope-checkbox", "index": ALL}, "value"),
    State("store-sources",  "data"),
    State("store-ontology", "data"),
    prevent_initial_call=True,
)
def update_scope(checkbox_values, sources, ontology_store):
    """
    Update ontology class scope selection for a dataset.
    """
    if not sources:
        return no_update

    ontology = ontology_store or {}

    # Find which checkbox changed
    triggered = ctx.triggered_id
    if not triggered or not isinstance(triggered, dict):
        return no_update

    raw       = triggered["index"]   # "{source_id}::{class_uri}"
    source_id, toggled_uri = raw.split("::", 1)

    # Find the triggering checkbox value
    toggled_value = next(
        (item["value"] for item in ctx.inputs_list[0]
         if item["id"]["index"] == raw),
        False,
    )

    # Get ontology tree for this source (for cascade)
    tree_classes = ontology.get(source_id, {}).get("classes", [])
    descendants  = _all_descendants(toggled_uri, tree_classes)

    updated = []
    for s in sources:
        if s["id"] != source_id:
            updated.append(s)
            continue

        s = dict(s)
        current_scope = set(s.get("scope") or [])

        if toggled_value:
            # Check: add this URI + all descendants
            current_scope.add(toggled_uri)
            current_scope |= descendants
        else:
            # Uncheck: remove this URI + all descendants
            current_scope.discard(toggled_uri)
            current_scope -= descendants

        # None = full graph (no filter applied)
        s["scope"] = sorted(current_scope) if current_scope else None
        updated.append(s)

    return updated