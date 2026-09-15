from dash import html, dcc
import dash_bootstrap_components as dbc


def build_sidebar() -> html.Div:
    """
    Build the full application sidebar.

    Returns
    -------
    html.Div
        Complete sidebar layout.
    """
    return html.Div([
        _sources_section(),
        html.Hr(className="my-3"),
        _metrics_section(),
        html.Hr(className="my-3"),
        _run_section(),
        html.Hr(className="my-3"),
        _config_section(),
    ])


def _sources_section() -> html.Div:
    """
    Build the data source management section.

    Returns
    -------
    html.Div
        Source management section layout.
    """
    return html.Div([
        html.P(
            "Data Sources",
            className="text-muted text-uppercase fw-semibold mb-2",
            style={"fontSize": "0.75rem", "letterSpacing": "0.08em"}
        ),
        html.Div(id="source-list"),
        dbc.Button(
            "+ Add Source",
            id="btn-add-source",
            color="primary",
            outline=True,
            size="sm",
            className="mt-2 w-100",
        ),
    ])


def _metrics_section() -> html.Div:
    """
    Build the quality metric selection section.

    Returns
    -------
    html.Div
        Metric selection section.
    """
    return html.Div([
        html.P(
            "Quality Metrics",
            className="text-muted text-uppercase fw-semibold mb-2",
            style={"fontSize": "0.75rem", "letterSpacing": "0.08em"}
        ),

        html.Div(id="metric-accordion"),
        dcc.Store(id="metric-selection", data=[]),
    ])


def _config_section() -> html.Div:
    """
    Build metric configuration section.
    Mirrors metrics layout but only exposes config actions.
    """

    from api_client import get_metrics, APIError

    try:
        metrics = get_metrics()
    except APIError:
        metrics = []

    from collections import OrderedDict
    by_dim: dict[str, list] = OrderedDict()

    for m in metrics:
        dim = m.get("dimension", "Other")
        by_dim.setdefault(dim, []).append(m)

    items = []

    for dim, dim_metrics in by_dim.items():

        # header (same style as metrics section)
        title = html.Span([
            html.Span(dim, style={
                "fontSize": "0.82rem",
                "fontWeight": "500"
            }),
        ])

        # config buttons per metric
        config_rows = [
            dbc.Row([
                dbc.Col(
                    html.Span(m["name"], style={"fontSize": "0.85rem"}),
                    width=10,
                ),
                dbc.Col(
                    html.Button(
                        "⚙",
                        id={"type": "metric-config-btn", "index": m["metric_id"]},
                        n_clicks=0,
                        style={
                            "background": "none",
                            "border": "none",
                            "cursor": "pointer",
                            "color": "#6c757d",
                            "fontSize": "0.85rem",
                            "padding": "0",
                        },
                    ),
                    width=2,
                    style={
                        "textAlign": "right",
                        "display": "flex",
                        "alignItems": "center",
                    },
                ),
            ], className="g-0", style={"padding": "2px 0"})
            for m in dim_metrics
        ]

        items.append(
            dbc.AccordionItem(
                html.Div(config_rows),
                title=title,
            )
        )

    return html.Div([
        html.P(
            "Configuration",
            className="text-muted text-uppercase fw-semibold mb-2",
            style={"fontSize": "0.75rem", "letterSpacing": "0.08em"}
        ),
        dbc.Accordion(
            items,
            start_collapsed=True,
            always_open=True,
            flush=True,
            className="mb-1",
            style={"fontSize": "0.875rem"},
        ),
    ])

def _run_section() -> html.Div:
    """
    Build the evaluation execution section.

    Returns
    -------
    html.Div
        Evaluation control section.
    """
    from dash import dcc
    return html.Div([
        dcc.Loading(
            id="loading-run",
            type="circle",
            color="#5B6EF5",
            children=dbc.Button(
                "Run Evaluation",
                id="btn-run-evaluation",
                color="primary",
                size="sm",
                className="w-100 mb-2",
                disabled=True,
            ),
        ),
        html.Div(
            id="run-feedback",
            className="text-muted",
            style={"fontSize": "0.8rem"},
        ),
    ])


def build_source_item(source: dict) -> html.Div:
    """
    Build a single source card.

    Parameters
    ----------
    source : dict
        Source definition from store-sources.
        Structure:
            {
                "id": str,
                "label": str,
                "selected": bool,
                "expanded": bool,
                "source_config": dict,
                "scope": list[str] | None,
            }

    Returns
    -------
    html.Div
        Source card + scope tree container.

    Card Controls
    -------------
    checkbox
        Enable/disable participation in evaluation.
    expand button
        Toggle ontology scope tree visibility.
    edit button
        Open source editing modal.
    delete button
        Remove source from store.
    """
    source_id   = source["id"]
    label       = source["label"]
    selected    = source["selected"]
    expanded    = source.get("expanded", False)
    scope       = source.get("scope") or []
    config_type = source["source_config"]["type"]

    type_badge = dbc.Badge(
        "File" if config_type == "rdf_file" else "SPARQL",
        color="secondary",
        className="ms-1",
        style={"fontSize": "0.65rem"},
    )

    scope_badge = dbc.Badge(
        f"{len(scope)} classes",
        color="primary",
        className="ms-1",
        style={"fontSize": "0.65rem"},
    ) if scope else None

    expand_icon = "▾" if expanded else "▸"

    card = dbc.Card(
        dbc.CardBody(
            dbc.Row([
                dbc.Col(
                    dbc.Checkbox(
                        id={"type": "source-checkbox", "index": source_id},
                        value=selected,
                        label=html.Span(
                            [label, type_badge] + ([scope_badge] if scope_badge else [])
                        ),
                    ),
                    width=7,
                    className="d-flex align-items-center",
                ),

                dbc.Col(
                    dbc.Button(
                        expand_icon,
                        id={"type": "btn-expand-source", "index": source_id},
                        color="link",
                        size="sm",
                        className="text-muted p-0",
                        style={"lineHeight": "1", "fontSize": "0.85rem"},
                        title="Filter scope",
                    ),
                    width=1,
                    className="d-flex align-items-center justify-content-end",
                ),

                dbc.Col(
                    dbc.Button(
                        "✎",
                        id={"type": "btn-edit-source", "index": source_id},
                        color="link",
                        size="sm",
                        className="text-muted p-0",
                        style={"lineHeight": "1", "fontSize": "0.9rem"},
                        title="Edit source",
                    ),
                    width=2,
                    className="d-flex align-items-center justify-content-end",
                ),

                dbc.Col(
                    dbc.Button(
                        "✕",
                        id={"type": "btn-delete-source", "index": source_id},
                        color="link",
                        size="sm",
                        className="text-muted p-0",
                        style={"lineHeight": "1"},
                        title="Delete source",
                    ),
                    width=2,
                    className="d-flex align-items-center justify-content-end",
                ),

            ], align="center", className="g-0"),
            className="py-2 px-2",
        ),
        className="mb-0",
        style={"border": "1px solid #dee2e6", "borderRadius": "4px 4px 0 0" if expanded else "4px"},
    )

    tree_panel = html.Div(
        id={"type": "scope-tree", "index": source_id},
        style={"display": "none"},   
    )

    return html.Div([card, tree_panel], className="mb-1")


def build_scope_tree(classes: list[dict], source_id: str,
                     selected_uris: set) -> html.Div:
    """
    Renders the ontology class tree as a recursive checkbox list.

    Cascade visual rules:
      - All descendants selected  → parent checked, normal style
      - Some descendants selected → parent checked, amber badge "partial"
      - No descendants selected   → parent unchecked

    Parameters
    ----------
    classes       : list of class dicts from /ontology response
    source_id     : used to build pattern-matched checkbox ids
    selected_uris : set of URIs currently in source["scope"]
    """
    if not classes:
        return html.P("No classes found.", className="text-muted mb-0",
                      style={"fontSize": "0.8rem"})

    def _all_descendant_uris(cls: dict) -> set:
        result = set()
        for child in cls.get("children", []):
            result.add(child["uri"])
            result |= _all_descendant_uris(child)
        return result

    def _render_node(cls: dict, depth: int = 0) -> html.Div:
        uri        = cls["uri"]
        label = cls.get("label", uri.split("#")[-1].split("/")[-1])
        aliases = cls.get("aliases", [])
        if aliases:
            label = f"{label} (=" + ", =".join(aliases) + ")"
        count      = cls.get("instance_count", 0)
        children   = cls.get("children", [])
        checked    = uri in selected_uris

        # Partial selection indicator for parents with children
        partial_badge = None
        if children:
            desc_uris     = _all_descendant_uris(cls)
            selected_desc = desc_uris & selected_uris
            if selected_desc and selected_desc != desc_uris:
                partial_badge = dbc.Badge(
                    "partial", color="warning", className="ms-1",
                    style={"fontSize": "0.6rem"},
                )

        row = dbc.Row([
            dbc.Col(
                dbc.Checkbox(
                    id={"type": "scope-checkbox", "index": f"{source_id}::{uri}"},
                    value=checked,
                    label=html.Span(
                        [label,
                         dbc.Badge(str(count), color="secondary",
                                   className="ms-1",
                                   style={"fontSize": "0.6rem"})]
                        + ([partial_badge] if partial_badge else [])
                    ),
                ),
                width=12,
                style={"paddingLeft": f"{depth * 16 + 4}px"},
            ),
        ], className="g-0 mb-1")

        child_nodes = [_render_node(c, depth + 1) for c in children]
        return html.Div([row] + child_nodes)

    return html.Div([_render_node(c) for c in classes])


def build_add_source_modal() -> dbc.Modal:
    """
    Modal used for both adding and editing a source.

    - "modal-title"     — text swapped by callback ("Add" vs "Edit")
    - "modal-edit-id"   — hidden store carrying the id of the source being
                          edited, or None when adding a new one

    Returns
    -------
    dbc.Modal
        Source configuration modal.
    """
    return dbc.Modal([
        dbc.ModalHeader(
            dbc.ModalTitle("Add Data Source", id="modal-title")
        ),
        dbc.ModalBody([

            # Hidden store: source id when editing, None when adding
            dcc.Store(id="modal-edit-id", data=None),

            dbc.Label("Label", html_for="input-source-label"),
            dbc.Input(
                id="input-source-label",
                placeholder="e.g. My Local Dataset",
                className="mb-3",
            ),

            dbc.Label("Source type"),
            dbc.RadioItems(
                id="input-source-type",
                options=[
                    {"label": "RDF File",        "value": "rdf_file"},
                    {"label": "SPARQL Endpoint", "value": "sparql_endpoint"},
                ],
                value="rdf_file",
                className="mb-3",
            ),

            # RDF File fields
            html.Div(
                id="source-fields-rdf",
                children=[
                    dbc.Label("File path", html_for="input-file-path"),  # TODO change it to be able to drag and drop
                    dcc.Upload(
                        id="upload-rdf-file",
                        children=html.Div([
                            "Drag and Drop or ",
                            html.A("Select File", style={"color": "#6c8ebf", "cursor": "pointer"}),
                        ]),
                        style={
                            "borderWidth": "1px",
                            "borderStyle": "dashed",
                            "borderColor": "#adb5bd",
                            "borderRadius": "6px",
                            "textAlign": "center",
                            "padding": "20px",
                            "cursor": "pointer",
                            "backgroundColor": "#f8f9fa",
                            "marginBottom": "8px",
                        },
                    ),
                    html.Small("or enter path manually", className="text-muted my-1 d-block"),
                    dbc.Input(
                        id="input-file-path",
                        placeholder="e.g. C:\\Users\\victo\\data\\file.ttl",
                        className="mb-2",
                    ),
                    html.Div(id="upload-filename-display", className="text-muted mb-2",
                             style={"fontSize": "0.8rem"}),
                    dbc.Label("Format", html_for="input-file-format"),
                    dbc.Select(
                        id="input-file-format",
                        options=[
                            {"label": "Turtle (.ttl)",   "value": "turtle"},
                            {"label": "RDF/XML (.rdf)",  "value": "xml"},
                            {"label": "N-Triples (.nt)", "value": "nt"},
                            {"label": "N3 (.n3)",        "value": "n3"},
                        ],
                        value="turtle",
                    ),
                ],
            ),

            html.Div(
                id="source-fields-sparql",
                style={"display": "none"},
                children=[
                    dbc.Label("Endpoint URL", html_for="input-endpoint-url"),
                    dbc.Input(
                        id="input-endpoint-url",
                        placeholder="e.g. https://dbpedia.org/sparql",
                        className="mb-2",
                    ),
                    dbc.Label("CONSTRUCT query", html_for="input-sparql-query"),
                    dbc.Textarea(
                        id="input-sparql-query",
                        placeholder="CONSTRUCT { ?s ?p ?o } WHERE { ... }",
                        rows=5,
                    ),
                ],
            ),

            html.Div(
                id="modal-source-feedback",
                className="mt-2 text-danger",
                style={"fontSize": "0.8rem"},
            ),
        ]),

        dbc.ModalFooter([
            dbc.Button(
                "Cancel",
                id="btn-modal-cancel",
                color="secondary",
                outline=True,
                className="me-2",
            ),
            dbc.Button(
                "Save",
                id="btn-modal-confirm",
                color="primary",
            ),
        ]),
    ],
        id="modal-add-source",
        is_open=False,
        backdrop="static",
    )


def build_structural_completeness_modal():
    from pathlib import Path

    SHAPES_DIR = Path(__file__).resolve().parents[2] / "backend" / "metrics" / "shapes"
    files = [
        f for f in SHAPES_DIR.glob("*.ttl")
    ]

    options = [
        {"label": f.stem, "value": str(f)}
        for f in files
    ]

    return dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle("Structural Completeness Configuration")),

        dbc.ModalBody([
            dcc.Store(id="structural-config-store", data=None),

            dbc.Label("Select shape profile"),

            dbc.RadioItems(
                id="structural-shape-selection",
                options=options,
                value=options[0]["value"] if options else None,
                className="mb-2"
            ),

            html.Div(
                id="structural-config-feedback",
                className="text-muted",
                style={"fontSize": "0.8rem"}
            )
        ]),

        dbc.ModalFooter([
            dbc.Button("Save", id="btn-structural-save", color="primary"),
        ])

    ],
    id="modal-structural-config",
    is_open=False,
    backdrop="static")