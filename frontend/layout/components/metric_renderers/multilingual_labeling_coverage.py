from dash import html, dcc
import dash_bootstrap_components as dbc

import charts.multilingual_labeling_coverage as charts
from layout.components.common import panel_card, section_label
from layout.components.detail_views_helpers import (
    collect_ds_details,
    analysis_header,
    comparison_header,
)

METRIC_ID = "multilingual_labeling_coverage"


def render(metric: dict, datasets: list[dict],
           click_data: dict | None = None) -> html.Div:
    ds_details = collect_ds_details(datasets, METRIC_ID)
    if not ds_details:
        return html.Div()

    comparison = len(ds_details) > 1
    header = (
        comparison_header("Multilingual Labeling Coverage", ds_details,
                          metric=metric)
        if comparison else
        analysis_header("Multilingual Labeling Coverage",
                        ds_details[0]["score"], metric=metric)
    )

    drilldown = build_density_drilldown(click_data, {"datasets": datasets})

    return html.Div([
        header,
        _general_info_section(ds_details),
        _language_dist_section(ds_details),
        _heatmap_section(ds_details, comparison),
        html.Hr(className="mt-1 mb-2"),
        drilldown,
    ])


def _general_info_section(ds_details: list[dict]) -> html.Div:
    """
    Chart 1: tag distribution + literal tagging overview.
    Also shows dominant language info as a stat row below the chart.
    """
    fig = charts.general_info_chart(ds_details)

    dominant_rows = []
    for d in ds_details:
        gi    = d["details"].get("general_info", {})
        lang  = gi.get("dominant_language")
        ratio = gi.get("dominant_language_ratio", 0)
        if lang:
            prefix = f"{d['label']}: " if len(ds_details) > 1 else ""
            dominant_rows.append(
                html.Span(
                    f"{prefix}Dominant language — "
                    f"{lang.upper()} ({round(ratio*100,1)}% of resources)",
                    className="text-muted me-4",
                    style={"fontSize": "0.82rem"},
                )
            )

    literal_tip_id = "tip-literal-definition"
    literal_hint = html.Span([
        html.Span(" What is a literal?", id=literal_tip_id,
                  style={"fontSize": "0.75rem", "color": "#adb5bd",
                         "cursor": "help", "textDecoration": "underline dotted",
                         "userSelect": "none"}),
        dbc.Tooltip(
            [
                html.Strong("Literal"), html.Br(),
                html.Span(
                    "A literal is a text value in an RDF dataset — for example, "
                    "a title, description, or label. A language-tagged literal "
                    "carries a language code (e.g. @en, @fr) indicating the "
                    "language it is written in. Untagged literals have no "
                    "declared language."
                ),
            ],
            target=literal_tip_id, placement="right",
            style={"maxWidth": "320px"},
        ),
    ], className="ms-2")

    return panel_card([
        html.Div([
            section_label("Language tag coverage overview"),
            literal_hint,
        ], style={"display": "flex", "alignItems": "baseline"}),
        dcc.Graph(figure=fig, config={"displayModeBar": False}),
        html.Div(dominant_rows, className="mt-2") if dominant_rows else html.Div(),
    ])


def _language_dist_section(ds_details: list[dict]) -> html.Div:
    """Chart 2: language distribution bar chart."""
    fig = charts.language_distribution_chart(ds_details)
    return panel_card([
        section_label(
            "Language distribution — resources with ≥1 literal per language"
        ),
        dcc.Graph(figure=fig, config={"displayModeBar": False}),
    ])


def _heatmap_section(ds_details: list[dict], comparison: bool) -> html.Div:
    """
    Chart 3: class × language coverage heatmap.
    In comparison mode, one heatmap per dataset side by side.
    """
    if not comparison:
        fig = charts.heatmap_chart(ds_details, dataset_index=0)
        return panel_card([
            section_label(
                "Class × language coverage — click a cell to explore language coverage across one class"
            ),
            dcc.Graph(
                id={"type": "multilingual-heatmap", "index": 0},
                figure=fig,
                config={"displayModeBar": False},
            ),
        ])

    heatmap_cols = []
    last_idx = len(ds_details) - 1
    for idx, d in enumerate(ds_details):
        fig = charts.heatmap_chart(
            ds_details, dataset_index=idx,
            show_colorbar=(idx == last_idx),
        )
        heatmap_cols.append(
            dbc.Col([
                html.P(d["label"], className="text-muted fw-semibold mb-1",
                       style={"fontSize": "0.8rem"}),
                dcc.Graph(
                    id={"type": "multilingual-heatmap", "index": idx},
                    figure=fig,
                    config={"displayModeBar": False},
                ),
            ], md=12 // len(ds_details))
        )

    return panel_card([
        section_label(
            "Class × language coverage — click a cell to explore language coverage across one class"
        ),
        dbc.Row(heatmap_cols, className="g-2"),
    ])


def build_density_drilldown(
    click_data: dict | None,
    results: dict,
) -> html.Div:
    """
    Renders the zone breakdown bar for a clicked class + language cell.

    Resolves the class URI from the clicked cell's y-label, computes
    zone counts (No presence / Sparse / Partial / Dominant), and renders
    a stacked horizontal bar with a plain-language summary above it.

    Parameters
    ----------
    click_data : dict | None
        Plotly clickData dict from a heatmap graph, or None when no
        cell has been clicked yet.
    results : dict
        The store-results dict containing the full datasets list.

    Returns
    -------
    html.Div
        Either the drilldown panel or a hint prompting the user to
        click a heatmap cell.
    """
    if not click_data or not results:
        return _drilldown_hint()

    try:
        point               = click_data["points"][0]
        language            = point["x"]
        class_label_clicked = point["y"]
    except (KeyError, IndexError, TypeError):
        return _drilldown_hint()

    datasets_tmp = results.get("datasets", [])
    ds_tmp       = collect_ds_details(datasets_tmp, METRIC_ID)
    class_uri    = None
    for d in ds_tmp:
        for cls in d["details"].get("heatmap", {}).get("classes", []):
            if cls["class_label"] == class_label_clicked:
                class_uri = cls["class_uri"]
                break
        if class_uri:
            break

    if not class_uri or not language:
        return _drilldown_hint()

    datasets   = results.get("datasets", [])
    ds_details = collect_ds_details(datasets, METRIC_ID)

    class_label = class_uri.split("#")[-1].split("/")[-1]
    for d in ds_details:
        for cls in d["details"].get("heatmap", {}).get("classes", []):
            if cls["class_uri"] == class_uri:
                class_label = cls["class_label"]
                break

    fig = charts.density_drilldown_chart(ds_details, class_uri, language)
    if fig is None:
        return panel_card([
            html.P(f"No density data for {class_label} · {language}.",
                   className="text-muted", style={"fontSize": "0.85rem"}),
        ])

    import statistics as _st
    summary_rows = []
    for d in ds_details:
        classes   = d["details"].get("heatmap", {}).get("classes", [])
        cls_entry = next(
            (c for c in classes if c["class_uri"] == class_uri), None
        )
        if not cls_entry:
            continue
        dens  = cls_entry.get("density_data", {}).get(language, [])
        if not dens:
            continue

    summary = html.Ul(summary_rows, className="mb-2 ps-3") if summary_rows else html.Div()

    region_legend = dbc.Row([
        dbc.Col(
            html.Span([
                html.Span("■ ", style={"color": color, "fontSize": "1rem"}),
                html.Span(label, style={"fontSize": "0.78rem", "color": "#6c757d"}),
            ]),
            xs="auto",
        )
        for color, label in [
            ("#F55B6E", "Sparse (0–25%)"),
            ("#F5A05B", "Partial (25–75%)"),
            ("#5BF58E", "Dominant (75–100%)"),
        ]
    ], className="g-2 mb-2")

    return panel_card([
        dbc.Row([
            dbc.Col(
                section_label(
                    f"Distribution of {language.upper()} content within {class_label} resources"
                ),
                width="auto",
            ),
            dbc.Col(
                html.Small(
                    "How much of each resource's content is in this language",
                    className="text-muted",
                    style={"fontSize": "0.78rem"},
                ),
                className="align-self-end",
            ),
        ], className="g-2 mb-1"),
        region_legend,
        summary,
        dcc.Graph(figure=fig, config={"displayModeBar": False}),
    ])


def _drilldown_hint() -> html.Div:
    return html.Div(
        html.P(
            "Click a cell in the heatmap to explore the density distribution "
            "for that class and language.",
            className="text-muted text-center mt-2",
            style={"fontSize": "0.85rem"},
        )
    )