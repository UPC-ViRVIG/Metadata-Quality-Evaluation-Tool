from dash import html, dcc
import dash_bootstrap_components as dbc

import charts.property_coverage as charts
from layout.components.common import panel_card, section_label
from layout.components.detail_views_helpers import (
    collect_ds_details,
    analysis_header,
    comparison_header,
)

METRIC_ID = "property_coverage"


def render(metric: dict, datasets: list[dict]) -> html.Div:
    ds_details = collect_ds_details(datasets, METRIC_ID)
    comparison = len(ds_details) > 1

    if not ds_details:
        return html.Div()

    header = (
        comparison_header("Property Coverage", ds_details, metric=metric)
        if comparison else
        analysis_header("Property Coverage", ds_details[0]["score"], metric=metric)
    )

    if comparison:
        return _comparison_view(header, ds_details)
    else:
        return _analysis_view(header, ds_details)


# ── Analysis ──────────────────────────────────────────────────────────────

def _analysis_view(header: html.Div, ds_details: list[dict]) -> html.Div:
    fig, has_scores = charts.analysis_bubble(ds_details)

    if not has_scores:
        warning = dbc.Alert(
            [
                html.Strong("No property schema detected. "),
                html.Small(
                    "The backend found classes but no schema properties were "
                    "defined for them. Check that the dataset uses a supported "
                    "schema or that a fallback profile is available.",
                    className="text-muted",
                ),
            ],
            color="warning",
            style={"fontSize": "0.85rem"},
        )
        return html.Div([header, warning, html.Div(id="property-drilldown-panel")])

    bubble_section = panel_card([
        section_label(
            "Class property coverage — bubble size = instance count · "
            "click a bubble to explore properties"
        ),
        dcc.Graph(
            id="property-class-chart",
            figure=fig,
            config={"displayModeBar": False},
        ),
    ])

    return html.Div([
        header,
        bubble_section,
        html.Div(id="property-drilldown-panel"),
    ])


# ── Comparison ────────────────────────────────────────────────────────────

def _comparison_view(header: html.Div, ds_details: list[dict]) -> html.Div:
    fig, has_scores = charts.comparison_bubble(ds_details)

    if not has_scores:
        no_score_labels = [
            d["label"] for d in ds_details
            if not d["details"].get("class_scores")
        ]
        warning = dbc.Alert(
            [
                html.Strong("No property schema detected for: "),
                ", ".join(no_score_labels), html.Br(),
                html.Small(
                    "The backend found classes but no schema properties were "
                    "defined for them. Property completeness scores cannot be "
                    "computed.",
                    className="text-muted",
                ),
            ],
            color="warning",
            style={"fontSize": "0.85rem"},
        )
        return html.Div([header, warning, html.Div(id="property-drilldown-panel")])

    bubble_section = panel_card([
        section_label(
            "Class property coverage — bubble size = instance count · "
            "click a bubble to explore properties"
        ),
        dcc.Graph(
            id="property-class-chart",
            figure=fig,
            config={"displayModeBar": False},
        ),
    ])

    return html.Div([
        header,
        bubble_section,
        html.Div(id="property-drilldown-panel"),
    ])


# ════════════════════════════════════════════════════════════════════════════
# Drilldown builders — called by callbacks/ui.py
# ════════════════════════════════════════════════════════════════════════════

def build_analysis_drilldown(
    active_class: str | None,
    results: dict,
) -> html.Div:
    """Stacked present/missing bar with fill rate labels. No toggle."""
    if not active_class or not results:
        return _drilldown_hint()

    datasets   = results.get("datasets", [])
    ds_details = collect_ds_details(datasets, METRIC_ID)
    short      = active_class.split("#")[-1].split("/")[-1]

    fig = charts.analysis_property_drilldown(ds_details, active_class)
    if fig is None:
        return panel_card([
            html.P(f"No property data for {short}.",
                   className="text-muted", style={"fontSize": "0.85rem"}),
        ])

    return panel_card([
        dbc.Row([
            dbc.Col(section_label(f"Properties for the {short} class"), width="auto"),
            dbc.Col(
                html.Small(active_class, className="text-muted",
                           style={"fontSize": "0.72rem", "wordBreak": "break-all"}),
                className="align-self-end",
            ),
        ], className="g-2 mb-2"),
        dcc.Graph(figure=fig, config={"displayModeBar": False}),
    ])


def build_comparison_drilldown(
    active_class: str | None,
    results: dict,
) -> html.Div:
    """Grouped fill rate bar per dataset for one class."""
    if not active_class or not results:
        return _drilldown_hint()

    datasets   = results.get("datasets", [])
    ds_details = collect_ds_details(datasets, METRIC_ID)
    short      = active_class.split("#")[-1].split("/")[-1]

    fig = charts.comparison_property_drilldown(ds_details, active_class)
    if fig is None:
        return panel_card([
            html.P(f"No property data for {short}.",
                   className="text-muted", style={"fontSize": "0.85rem"}),
        ])

    return panel_card([
        dbc.Row([
            dbc.Col(section_label(f"Property fill rates for the {short} class"), width="auto"),
            dbc.Col(
                html.Small(active_class, className="text-muted",
                           style={"fontSize": "0.72rem", "wordBreak": "break-all"}),
                className="align-self-end",
            ),
        ], className="g-2 mb-2"),
        dcc.Graph(figure=fig, config={"displayModeBar": False}),
    ])


def _drilldown_hint() -> html.Div:
    return html.Div(
        html.P(
            "Click a bubble to explore its property fill rates.",
            className="text-muted text-center mt-2",
            style={"fontSize": "0.85rem"},
        )
    )