from __future__ import annotations

from dash import html, dcc
import dash_bootstrap_components as dbc
import plotly.graph_objects as go

_ACCENT  = "#5B6EF5"
_GREY    = "#E9EDF5"
_COLORS  = [_ACCENT, "#F5A05B", "#5BF5A0", "#F55B6E"]


def _hex_to_rgba(hex_color: str, alpha: float = 0.15) -> str:
    """
    Convert a hex color string into rgba() CSS format.

    Parameters
    ----------
    hex_color : str
        Hexadecimal color string.
    
    Returns
    -------
    str
        CSS rgba color string.
    """
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _base_layout(**kwargs) -> dict:
    """
    Generate standardized Plotly layout configuration.

    Parameters
    ----------
    **kwargs
        Additional Plotly layout overrides.

    Returns
    -------
    dict
        Plotly layout dictionary.
    """
    return dict(
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family="inherit", size=12),
        **kwargs,
    )


def _spider(
    metric_names: list[str],
    datasets: list[dict],   # [{"label": str, "values": [float 0-1]}]
    height: int = 380,
) -> go.Figure:
    """
    Build a radar/spider comparison chart.

    Parameters
    ----------
    metric_names : list[str]
        Ordered metric labels.

    datasets : list[dict]
        Dataset comparison series.
        Structure:
            [
                {
                    "label": str,
                    "values": list[float]
                }
            ]
    height : int, optional
        Chart height in pixels.

    Returns
    -------
    go.Figure
        Plotly radar chart.

    """
    fig = go.Figure()
    for i, ds in enumerate(datasets):
        color = _COLORS[i % len(_COLORS)]
        fig.add_trace(go.Scatterpolar(
            r=ds["values"] + [ds["values"][0]],
            theta=metric_names + [metric_names[0]],
            fill="toself",
            name=ds["label"],
            line=dict(color=color),
            fillcolor=_hex_to_rgba(color, 0.15),
        ))
    fig.update_layout(_base_layout(
        height=height,
        margin=dict(l=8, r=8, t=8, b=40),
        polar=dict(radialaxis=dict(
            visible=True, range=[0, 1], tickformat=".0%",
            gridcolor="rgba(0,0,0,0.08)",
        )),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.18,
                    xanchor="center", x=0.5),
    ))
    return fig


def _hbar(
    names: list[str],
    series: list[dict],   # [{"label": str, "values": [float]}]
    height: int = 260,
    title: str = "",
) -> go.Figure:
    """
    Build a grouped horizontal bar chart.

    Parameters
    ----------
    names : list[str]
        Category labels.
    series : list[dict]
        Chart series definitions.
        Structure:
            [
                {
                    "label": str,
                    "values": list[float]
                }
            ]
    height : int, optional
        Figure height in pixels.
    title : str, optional
        Optional chart title.

    Returns
    -------
    go.Figure
        Plotly grouped horizontal bar chart.
    """
    fig = go.Figure()
    for i, s in enumerate(series):
        fig.add_bar(
            name=s["label"],
            y=names,
            x=s["values"],
            orientation="h",
            marker_color=_COLORS[i % len(_COLORS)],
            text=[f"{round(v * 100)}%" for v in s["values"]],
            textposition="outside",
        )
    fig.update_layout(_base_layout(
        height=max(height, len(names) * 36 + 60),
        margin=dict(l=8, r=48, t=36 if title else 8, b=8),
        title=dict(text=title, font=dict(size=13)) if title else None,
        barmode="group",
        xaxis=dict(range=[0, 1.18], tickformat=".0%",
                   gridcolor="rgba(0,0,0,0.05)"),
        yaxis=dict(automargin=True),
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
    ))
    return fig


def _panel_card(children) -> dbc.Card:
    """
    Wrap content inside a standardized dashboard panel card.

    Parameters
    ----------
    children
        Dash child components.

    Returns
    -------
    dbc.Card
        Styled dashboard card.
    """
    return dbc.Card(
        dbc.CardBody(children, className="p-3"),
        className="mb-3",
    )


def _section_label(text: str) -> html.P:
    """
    Build a standardized section title label.

    Parameters
    ----------
    text : str
        Section title text.

    Returns
    -------
    html.P
        Styled section label component.
    """
    return html.P(
        text,
        className="text-muted fw-semibold mb-2",
        style={"fontSize": "0.75rem", "textTransform": "uppercase",
               "letterSpacing": "0.06em"},
    )


def _score_badge(score: float) -> dbc.Badge:
    """
    Build a color-coded quality score badge.

    Parameters
    ----------
    score : float
        Quality score in range [0, 1].

    Returns
    -------
    dbc.Badge
        Styled percentage badge.
    """
    pct = round(score * 100)
    color = "success" if pct >= 75 else "warning" if pct >= 40 else "danger"
    return dbc.Badge(f"{pct}%", color=color, className="ms-2 fs-6")


def _render_overview(results: dict) -> html.Div:
    """
    Shown when no metric card is selected.
    Single dataset  → horizontal bar chart of metric scores.
    Multiple datasets → spider chart (one trace per dataset).
    Both followed by a hint to click a card.
    """
    datasets = results.get("datasets", [])
    if not datasets:
        return html.Div()

    all_metric_sets = [
        {m["name"]: (m["metric_id"], m["score"])
         for m in ds.get("metrics", []) if m.get("status") not in ("error", "skipped")}
        for ds in datasets
    ]
    if not all_metric_sets or not all_metric_sets[0]:
        return html.Div()

    # Names present in every dataset
    shared_names = list(all_metric_sets[0].keys())
    for ms in all_metric_sets[1:]:
        shared_names = [n for n in shared_names if n in ms]

    if not shared_names:
        return html.Div()

    comparison = len(datasets) > 1

    if comparison:
        spider_datasets = [
            {
                "label":  ds.get("label", f"Dataset {i+1}"),
                "values": [all_metric_sets[i][n][1] for n in shared_names],
            }
            for i, ds in enumerate(datasets)
        ]
        chart = dcc.Graph(
            figure=_spider(shared_names, spider_datasets),
            config={"displayModeBar": False},
        )
        chart_label = "Overview — all metrics"
    else:
        scores = [all_metric_sets[0][n][1] for n in shared_names]
        chart = dcc.Graph(
            figure=_hbar(
                shared_names,
                [{"label": datasets[0].get("label", "Dataset"), "values": scores}],
                title="",
                height=max(220, len(shared_names) * 38),
            ),
            config={"displayModeBar": False},
        )
        chart_label = "Metric scores"

    return html.Div([
        _section_label(chart_label),
        _panel_card([
            chart,
            html.P(
                "Click any metric card above to explore its details.",
                className="text-muted text-center mb-0 mt-2",
                style={"fontSize": "0.8rem"},
            ),
        ]),
    ])


def _render_generic(metric: dict, datasets: list[dict]) -> html.Div:
    """
    Used when no specific renderer is registered for a metric_id.

    Renders:
      - Score badge in the header
      - If multiple datasets: grouped horizontal bar of scores
      - Details dict as a structured key/value table (handles nested dicts
        and lists one level deep)
    """
    name  = metric.get("name", "Metric")
    score = metric.get("score", 0.0)

    # ── Score comparison across datasets (comparison mode) ────────────────
    if len(datasets) > 1:
        ds_scores = []
        for ds in datasets:
            m = next(
                (m for m in ds.get("metrics", [])
                 if m["metric_id"] == metric["metric_id"]),
                None,
            )
            ds_scores.append(m["score"] if m else 0.0)

        score_chart = _panel_card([
            dcc.Graph(
                figure=_hbar(
                    [ds.get("label", f"Dataset {i+1}")
                     for i, ds in enumerate(datasets)],
                    [{"label": name,
                      "values": ds_scores}],
                    title="Score by dataset",
                    height=max(160, len(datasets) * 48),
                ),
                config={"displayModeBar": False},
            )
        ])
    else:
        score_chart = html.Div()

    details = metric.get("details") or {}
    detail_block = _render_details_table(details)

    return html.Div([
        dbc.Row([
            dbc.Col(html.H6(name, className="mb-0 fw-semibold"), width="auto"),
            dbc.Col(_score_badge(score), width="auto", className="ps-0"),
        ], align="center", className="mb-3"),
        score_chart,
        detail_block,
    ])


def _render_details_table(details: dict) -> html.Div:
    """
    Renders a metric's `details` dict into a readable structure.

    Handles three value shapes:
      - scalar (float/int/str/bool)       → single row
      - flat dict  {str: scalar}          → two-column table with optional bar
      - list of dicts [{key: val, …}]     → full table (violations list etc.)
    """
    if not details:
        return html.Div(
            html.P("No additional details available.",
                   className="text-muted", style={"fontSize": "0.85rem"}),
        )

    blocks = []
    for key, val in details.items():

        # ── Nested dict: treat as per-class/per-property scores ───────────
        if isinstance(val, dict):
            rows = []
            for sub_key, sub_val in val.items():
                if isinstance(sub_val, float):
                    pct = round(sub_val * 100)
                    badge_color = ("success" if pct >= 75
                                   else "warning" if pct >= 40 else "danger")
                    rows.append(html.Tr([
                        html.Td(sub_key, style={"fontSize": "0.85rem",
                                                "wordBreak": "break-all"}),
                        html.Td(
                            dbc.Progress(
                                value=pct,
                                color=badge_color,
                                style={"height": "8px"},
                                className="my-1",
                            ),
                            style={"width": "55%"},
                        ),
                        html.Td(
                            dbc.Badge(f"{pct}%", color=badge_color),
                            className="text-end",
                        ),
                    ]))
                else:
                    rows.append(html.Tr([
                        html.Td(sub_key, style={"fontSize": "0.85rem"}),
                        html.Td(str(sub_val), colSpan=2,
                                style={"fontSize": "0.85rem"}),
                    ]))

            blocks.append(_panel_card([
                _section_label(key),
                dbc.Table(
                    [html.Tbody(rows)],
                    bordered=False, size="sm",
                    className="mb-0",
                    style={"tableLayout": "fixed"},
                ),
            ]))

        elif isinstance(val, list) and val and isinstance(val[0], dict):
            cols = list(val[0].keys())
            thead = html.Thead(html.Tr([html.Th(c) for c in cols]))
            tbody = html.Tbody([
                html.Tr([
                    html.Td(
                        (f"{round(row.get(c, 0) * 100)}%"
                         if isinstance(row.get(c), float)
                         else str(row.get(c, ""))),
                        style={"fontSize": "0.82rem", "wordBreak": "break-all"},
                    )
                    for c in cols
                ])
                for row in val[:200]    # cap at 200 rows for performance
            ])
            caption = (
                html.Caption(
                    f"Showing first 200 of {len(val)} entries.",
                    style={"fontSize": "0.75rem", "captionSide": "bottom"},
                )
                if len(val) > 200 else None
            )
            blocks.append(_panel_card([
                _section_label(key),
                html.Div(
                    dbc.Table(
                        [thead, tbody] + ([caption] if caption else []),
                        bordered=True, size="sm",
                        className="mb-0",
                    ),
                    style={"overflowX": "auto", "overflowY": "auto",
                           "maxHeight": "340px"},
                ),
            ]))

        elif isinstance(val, list):
            blocks.append(_panel_card([
                _section_label(key),
                html.Ul(
                    [html.Li(str(v), style={"fontSize": "0.85rem"})
                     for v in val[:200]],
                    className="mb-0 ps-3",
                ),
            ]))

        else:
            display = (f"{round(val * 100)}%" if isinstance(val, float)
                       else str(val))
            blocks.append(
                dbc.Row([
                    dbc.Col(
                        html.Span(key, className="text-muted",
                                  style={"fontSize": "0.82rem"}),
                        width=4,
                    ),
                    dbc.Col(
                        html.Span(display,
                                  style={"fontSize": "0.85rem",
                                         "fontWeight": "500"}),
                        width=8,
                    ),
                ], className="mb-1 g-0"),
            )

    return html.Div(blocks)



_REGISTRY: dict[str, callable] = {}


def render_detail_panel(active_metric_id: str | None, results: dict) -> html.Div:
    """
    Called by callbacks/ui.py whenever store-ui or store-results changes.

    Parameters
    ----------
    active_metric_id
        The metric_id of the selected card, or None for overview.
    results
        The full store-results dict.
    """
    if results is None or results.get("status") == "error":
        return html.Div()

    if active_metric_id in (None, "__overview__"):
        return _render_overview(results)

    datasets = results.get("datasets", [])
    if not datasets:
        return html.Div()

    metric = next(
        (m for m in datasets[0].get("metrics", [])
         if m["metric_id"] == active_metric_id),
        None,
    )
    if metric is None:
        return html.Div()

    renderer = _REGISTRY.get(active_metric_id, _render_generic)
    return html.Div([
        html.Hr(className="mt-1 mb-3"),
        renderer(metric, datasets),
    ])

def _render_structural_completeness(metric: dict, datasets: list[dict]) -> html.Div:
    """
    Two sections:
      1. Score distribution histogram (bucketed 0.0–1.0 counts).
         In comparison mode each dataset gets its own trace (normalised to %
         of records so datasets of different sizes are comparable).
      2. Class-level completeness bar (mean ± range) from class_statistics.
    """
    comparison = len(datasets) > 1

    ds_details = []
    for i, ds in enumerate(datasets):
        m = next(
            (x for x in ds.get("metrics", [])
             if x["metric_id"] == "structural_completeness"),
            None,
        )
        if m:
            ds_details.append({
                "label":   ds.get("label", f"Dataset {i+1}"),
                "color":   _COLORS[i % len(_COLORS)],
                "details": m.get("details", {}),
                "score":   m["score"],
            })

    if not ds_details:
        return html.Div()
 
    if comparison:
        header_children = [
            dbc.Col(
                html.H6("Structural Completeness", className="mb-0 fw-semibold"),
                width="auto",
            ),
        ]
        for d in ds_details:
            header_children.append(
                dbc.Col(
                    dbc.Badge(
                        f"{d['label']}: {round(d['score'] * 100)}%",
                        color="secondary",
                        className="ms-2",
                        style={"backgroundColor": d["color"]},
                    ),
                    width="auto",
                )
            )
        header = dbc.Row(header_children, align="center", className="mb-3 g-1")
    else:
        header = dbc.Row([
            dbc.Col(
                html.H6("Structural Completeness", className="mb-0 fw-semibold"),
                width="auto",
            ),
            dbc.Col(
                _score_badge(ds_details[0]["score"]),
                width="auto", className="ps-0",
            ),
        ], align="center", className="mb-3")

    dist_fig = go.Figure()
    buckets = ["0.0","0.1","0.2","0.3","0.4","0.5",
               "0.6","0.7","0.8","0.9","1.0"]

    for d in ds_details:
        raw = d["details"].get("score_distribution", {})
        total = sum(raw.get(b, 0) for b in buckets) or 1
        pcts  = [raw.get(b, 0) / total for b in buckets]
        dist_fig.add_bar(
            name=d["label"],
            x=[("100%" if b == "1.0" else f"{int(float(b)*100)}–{int(float(b)*100)+9}%") for b in buckets],
            y=pcts,
            marker_color=d["color"],
            text=[f"{round(p*100)}%" if p > 0 else "" for p in pcts],
            textposition="outside",
        )

    dist_fig.update_layout(_base_layout(
        height=280,
        margin=dict(l=8, r=8, t=8, b=8),
        barmode="group",
        yaxis=dict(tickformat=".0%", gridcolor="rgba(0,0,0,0.05)",
                   title="% of records"),
        xaxis=dict(title="Completeness bucket"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1) if comparison else None,
        showlegend=comparison,
    ))

    dist_section = _panel_card([
        _section_label("Record completeness distribution"),
        dcc.Graph(figure=dist_fig, config={"displayModeBar": False}),
    ])

    def _short(uri: str) -> str:
        return uri.split("#")[-1].split("/")[-1]

    class_fig = go.Figure()
    for d in ds_details:
        stats = d["details"].get("class_statistics", {})
        if not stats:
            continue
        classes = list(stats.keys())
        means   = [stats[c]["mean"] for c in classes]
        mins    = [stats[c]["min"]  for c in classes]
        maxs    = [stats[c]["max"]  for c in classes]
        labels  = [_short(c) for c in classes]

        class_fig.add_bar(
            name=d["label"],
            y=labels,
            x=means,
            orientation="h",
            marker_color=d["color"],
            error_x=dict(
                type="data",
                symmetric=False,
                array=[mx - mn for mn, mx in zip(means, maxs)],
                arrayminus=[mn - mi for mi, mn in zip(mins, means)],
                color="rgba(0,0,0,0.3)",
                thickness=1.5,
                width=4,
            ),
            text=[f"{round(v*100)}%" for v in means],
            textposition="outside",
        )

    if class_fig.data:
        n_classes = max(
            len(d["details"].get("class_statistics", {})) for d in ds_details
        )
        class_fig.update_layout(_base_layout(
            height=max(180, n_classes * 44 + 60),
            margin=dict(l=8, r=48, t=8, b=8),
            barmode="group",
            xaxis=dict(range=[0, 1.18], tickformat=".0%",
                       gridcolor="rgba(0,0,0,0.05)"),
            yaxis=dict(automargin=True),
            showlegend=comparison,
            legend=dict(orientation="h", yanchor="bottom", y=1.02,
                        xanchor="right", x=1),
        ))
        class_section = _panel_card([
            _section_label("Class-level completeness (mean ± range)"),
            dcc.Graph(figure=class_fig, config={"displayModeBar": False}),
        ])
    else:
        class_section = html.Div()

    def _stat_row(label, *values):
        cells = [html.Td(html.Strong(label, style={"fontSize": "0.82rem"}))]
        for v in values:
            cells.append(html.Td(v, style={"fontSize": "0.82rem"}))
        return html.Tr(cells)

    stat_rows = []
    col_headers = [html.Th("")] + [
        html.Th(d["label"], style={"fontSize": "0.82rem"}) for d in ds_details
    ] if comparison else [html.Th(""), html.Th("Value")]

    for key, fmt in [
        ("total_records",            lambda v: str(v)),
        ("median_record_completeness", lambda v: f"{round(v*100)}%"),
        ("min_record_completeness",    lambda v: f"{round(v*100)}%"),
        ("max_record_completeness",    lambda v: f"{round(v*100)}%"),
        ("profile",                    lambda v: str(v)),
    ]:
        vals = []
        for d in ds_details:
            raw = d["details"].get(key)
            vals.append(fmt(raw) if raw is not None else "—")
        stat_rows.append(_stat_row(key.replace("_", " ").title(), *vals))

    # Warning rows
    warnings = [d["details"].get("warning") for d in ds_details if d["details"].get("warning")]
    warning_block = html.Div([
        dbc.Alert(w, color="warning", className="py-2 mb-2",
                  style={"fontSize": "0.82rem"})
        for w in warnings
    ]) if warnings else html.Div()

    stats_section = _panel_card([
        _section_label("Summary statistics"),
        dbc.Table(
            [html.Thead(html.Tr(col_headers)), html.Tbody(stat_rows)],
            bordered=True, size="sm", className="mb-2",
        ),
        warning_block,
    ])

    return html.Div([header, dist_section, class_section, stats_section])


def _render_property_completeness(metric: dict, datasets: list[dict]) -> html.Div:
    """
    Three sections:
      1. Class scores — horizontal bar, one bar per class per dataset.
         Each bar is clickable (via store-ui active_class) to drill down.
      2. Top missing properties — aggregated across all classes, top 20 by
         total missing count. Grouped bars in comparison mode.
      3. Class drill-down — appears when active_class is set in store-ui.
         Sorted fill-rate bar for all properties of the selected class.
         Rendered as a separate component targeted by callbacks/ui.py.
    """
    comparison = len(datasets) > 1

    def _short(uri: str) -> str:
        return uri.split("#")[-1].split("/")[-1]

    # ── Collect per-dataset details ───────────────────────────────────────
    ds_details = []
    for i, ds in enumerate(datasets):
        m = next(
            (x for x in ds.get("metrics", [])
             if x["metric_id"] == "property_completeness"),
            None,
        )
        if m:
            ds_details.append({
                "label":   ds.get("label", f"Dataset {i+1}"),
                "color":   _COLORS[i % len(_COLORS)],
                "details": m.get("details", {}),
                "score":   m["score"],
            })

    if not ds_details:
        return html.Div()

    if comparison:
        header_children = [
            dbc.Col(
                html.H6("Property Completeness", className="mb-0 fw-semibold"),
                width="auto",
            ),
        ]
        for d in ds_details:
            header_children.append(dbc.Col(
                dbc.Badge(
                    f"{d['label']}: {round(d['score'] * 100)}%",
                    color="secondary", className="ms-2",
                    style={"backgroundColor": d["color"]},
                ),
                width="auto",
            ))
        header = dbc.Row(header_children, align="center", className="mb-3 g-1")
    else:
        header = dbc.Row([
            dbc.Col(
                html.H6("Property Completeness", className="mb-0 fw-semibold"),
                width="auto",
            ),
            dbc.Col(_score_badge(ds_details[0]["score"]),
                    width="auto", className="ps-0"),
        ], align="center", className="mb-3")

    class_fig = go.Figure()
    all_class_uris = []
    for d in ds_details:
        for uri in d["details"].get("class_scores", {}):
            if uri not in all_class_uris:
                all_class_uris.append(uri)

    for d in ds_details:
        scores = d["details"].get("class_scores", {})
        vals   = [scores.get(uri, None) for uri in all_class_uris]
        class_fig.add_bar(
            name=d["label"],
            y=[_short(u) for u in all_class_uris],
            x=[v if v is not None else 0 for v in vals],
            orientation="h",
            marker_color=d["color"],
            text=[f"{round(v*100)}%" if v is not None else "n/a" for v in vals],
            textposition="outside",
            customdata=all_class_uris,
            hovertemplate="%{customdata}<br>%{text}<extra></extra>",
        )

    n_classes = len(all_class_uris)
    class_fig.update_layout(_base_layout(
        height=max(200, n_classes * (52 if comparison else 38) + 60),
        margin=dict(l=8, r=48, t=8, b=8),
        barmode="group",
        xaxis=dict(range=[0, 1.18], tickformat=".0%",
                   gridcolor="rgba(0,0,0,0.05)"),
        yaxis=dict(automargin=True),
        showlegend=comparison,
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
    ))

    class_section = _panel_card([
        _section_label("Class completeness scores — click a bar to drill into its properties"),
        dcc.Graph(
            id="property-class-chart",
            figure=class_fig,
            config={"displayModeBar": False},
        ),
    ])

    def _top_missing(details: dict, top_n: int = 20) -> list[tuple[str, int]]:
        totals: dict[str, int] = {}
        for class_data in details.get("class_property_fill_rates", {}).values():
            for prop, stats in class_data.items():
                totals[prop] = totals.get(prop, 0) + stats.get("missing", 0)
        return sorted(totals.items(), key=lambda x: x[1], reverse=True)[:top_n]

    top_props_union: list[str] = []
    for d in ds_details:
        for prop, _ in _top_missing(d["details"]):
            if prop not in top_props_union:
                top_props_union.append(prop)
    top_props_union = top_props_union[:20]

    missing_fig = go.Figure()
    for d in ds_details:
        totals: dict[str, int] = {}
        for class_data in d["details"].get("class_property_fill_rates", {}).values():
            for prop, stats in class_data.items():
                totals[prop] = totals.get(prop, 0) + stats.get("missing", 0)
        missing_fig.add_bar(
            name=d["label"],
            y=[_short(p) for p in top_props_union],
            x=[totals.get(p, 0) for p in top_props_union],
            orientation="h",
            marker_color=d["color"],
            customdata=top_props_union,
            hovertemplate="%{customdata}<br>%{x} missing records<extra></extra>",
            text=[str(totals.get(p, 0)) for p in top_props_union],
            textposition="outside",
        )

    missing_fig.update_layout(_base_layout(
        height=max(260, len(top_props_union) * (48 if comparison else 32) + 60),
        margin=dict(l=8, r=48, t=8, b=8),
        barmode="group",
        xaxis=dict(title="Total missing records",
                   gridcolor="rgba(0,0,0,0.05)"),
        yaxis=dict(automargin=True),
        showlegend=comparison,
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
    ))

    missing_section = _panel_card([
        _section_label("Top 20 most missing properties (across all classes)"),
        dcc.Graph(figure=missing_fig, config={"displayModeBar": False}),
    ])

    drilldown_section = html.Div(id="property-drilldown-panel")

    return html.Div([
        header,
        class_section,
        missing_section,
        drilldown_section,
    ])


def build_property_drilldown(active_class: str | None, results: dict) -> html.Div:
    """
    Called by callbacks/ui.py to render the per-class property fill-rate chart.
    Exported so the callback can import it directly.

    Shows a sorted horizontal bar of fill rates for every property in the
    selected class, one trace per dataset.
    """
    if not active_class or not results:
        return html.Div(
            html.P(
                "Click a class bar above to inspect its property fill rates.",
                className="text-muted text-center mt-2",
                style={"fontSize": "0.85rem"},
            )
        )

    def _short(uri: str) -> str:
        return uri.split("#")[-1].split("/")[-1]

    datasets = results.get("datasets", [])
    ds_details = []
    for i, ds in enumerate(datasets):
        m = next(
            (x for x in ds.get("metrics", [])
             if x["metric_id"] == "property_completeness"),
            None,
        )
        if m:
            ds_details.append({
                "label":   ds.get("label", f"Dataset {i+1}"),
                "color":   _COLORS[i % len(_COLORS)],
                "fill_rates": (
                    m.get("details", {})
                     .get("class_property_fill_rates", {})
                     .get(active_class, {})
                ),
            })

    all_props: list[str] = []
    for d in ds_details:
        for p in d["fill_rates"]:
            if p not in all_props:
                all_props.append(p)

    if not all_props:
        return _panel_card([
            html.P(
                f"No property fill-rate data for {_short(active_class)}.",
                className="text-muted", style={"fontSize": "0.85rem"},
            )
        ])

    first_rates = ds_details[0]["fill_rates"] if ds_details else {}
    all_props.sort(key=lambda p: first_rates.get(p, {}).get("fill_rate", 0))

    fig = go.Figure()
    for d in ds_details:
        fill_rates = d["fill_rates"]
        vals = [fill_rates.get(p, {}).get("fill_rate", None) for p in all_props]
        fig.add_bar(
            name=d["label"],
            y=[_short(p) for p in all_props],
            x=[v if v is not None else 0 for v in vals],
            orientation="h",
            marker_color=d["color"],
            customdata=[
                (f"present: {fill_rates.get(p,{}).get('present',0)}, "
                 f"missing: {fill_rates.get(p,{}).get('missing',0)}")
                for p in all_props
            ],
            hovertemplate=(
                "%{y}<br>Fill rate: %{x:.1%}<br>%{customdata}<extra></extra>"
            ),
            text=[f"{round(v*100)}%" if v is not None else "n/a" for v in vals],
            textposition="outside",
        )

    fig.update_layout(_base_layout(
        height=max(300, len(all_props) * (44 if len(ds_details) > 1 else 28) + 60),
        margin=dict(l=8, r=48, t=8, b=8),
        barmode="group",
        xaxis=dict(range=[0, 1.18], tickformat=".0%",
                   gridcolor="rgba(0,0,0,0.05)"),
        yaxis=dict(automargin=True),
        showlegend=len(ds_details) > 1,
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
    ))

    return _panel_card([
        _section_label(f"Property fill rates — {_short(active_class)}"),
        html.Small(
            active_class,
            className="text-muted d-block mb-2",
            style={"fontSize": "0.75rem", "wordBreak": "break-all"},
        ),
        dcc.Graph(figure=fig, config={"displayModeBar": False}),
    ])


_REGISTRY["structural_completeness"] = _render_structural_completeness
_REGISTRY["property_completeness"]   = _render_property_completeness