from __future__ import annotations

from dash import html, dcc
import dash_bootstrap_components as dbc

from charts.overview import spider, metric_score_bar
from charts.palette import COLORS
import charts.property_coverage as property_charts

from layout.components.common import panel_card, section_label
from layout.components.detail_views_helpers import collect_ds_details

from layout.components.metric_renderers import structural_completeness
from layout.components.metric_renderers import property_coverage
from layout.components.metric_renderers import multilingual_labeling_coverage

_REGISTRY: dict[str, callable] = {
    multilingual_labeling_coverage.METRIC_ID: multilingual_labeling_coverage.render,
    structural_completeness.METRIC_ID: structural_completeness.render,
    property_coverage.METRIC_ID:   property_coverage.render,
}


# ════════════════════════════════════════════════════════════════════════════
# Overview panel 
# ════════════════════════════════════════════════════════════════════════════
def _render_overview(results: dict) -> html.Div:
    datasets = results.get("datasets", [])
    if not datasets:
        return html.Div()

    all_metric_sets = [
        {m["name"]: m["score"]
         for m in ds.get("metrics", [])
         if m.get("status") not in ("error", "skipped")}
        for ds in datasets
    ]
    if not all_metric_sets or not all_metric_sets[0]:
        return html.Div()

    shared = list(all_metric_sets[0].keys())
    for ms in all_metric_sets[1:]:
        shared = [n for n in shared if n in ms]
    if not shared:
        return html.Div()

    comparison = len(datasets) > 1

    # Use spider only when comparison mode AND enough metrics to be meaningful.
    use_spider = comparison and len(shared) >= 3

    if use_spider:
        fig = spider(
            shared,
            [{"label":  ds.get("label", f"Dataset {i+1}"),
              "values": [all_metric_sets[i][n] for n in shared]}
             for i, ds in enumerate(datasets)],
        )
        label = "Overview — all metrics"
    elif comparison:
        from charts.overview import grouped_metric_bar
        fig = grouped_metric_bar(
            shared,
            [{"label":  ds.get("label", f"Dataset {i+1}"),
              "values": [all_metric_sets[i][n] for n in shared]}
             for i, ds in enumerate(datasets)],
        )
        label = "Overview — all metrics"
    else:
        fig   = metric_score_bar(shared, [all_metric_sets[0][n] for n in shared])
        label = "Overview"

    return html.Div([
        section_label(label),
        panel_card([
            dcc.Graph(figure=fig, config={"displayModeBar": False}),
            html.P(
                "👆 Click a metric card above to explore its detailed analysis.",
                className="text-muted text-center mb-0 mt-2",
                style={"fontSize": "0.8rem"},
            ),
        ]),
    ])


# ════════════════════════════════════════════════════════════════════════════
# Generic fallback renderer
# ════════════════════════════════════════════════════════════════════════════
def _render_generic(metric: dict, datasets: list[dict]) -> html.Div:
    """
    Used when no specific renderer is registered for a metric_id.
    Shows score header and the details dict as a structured table.
    """
    from layout.components.detail_views_helpers import (
        analysis_header, comparison_header,
    )
    from layout.components.detail_views_table import render_details_table
    from charts.primitives import hbar

    name  = metric.get("name", "Metric")
    score = metric.get("score", 0.0)

    ds_details = collect_ds_details(datasets, metric["metric_id"])
    header = (
        comparison_header(name, ds_details)
        if len(datasets) > 1 else
        analysis_header(name, score)
    )

    score_chart = html.Div()
    if len(datasets) > 1:
        score_chart = panel_card([
            dcc.Graph(
                figure=hbar(
                    [d["label"] for d in ds_details],
                    [{"label": name, "values": [d["score"] for d in ds_details]}],
                    height=max(160, len(ds_details) * 48),
                ),
                config={"displayModeBar": False},
            )
        ])

    return html.Div([
        header,
        score_chart,
        render_details_table(metric.get("details") or {}),
    ])


# ════════════════════════════════════════════════════════════════════════════
# Property drilldown  
# ════════════════════════════════════════════════════════════════════════════
def build_property_drilldown(active_class: str | None, results: dict) -> html.Div:
    def _short(uri: str) -> str:
        return uri.split("#")[-1].split("/")[-1]

    if not active_class or not results:
        return html.Div(
            html.P(
                "Click a class bar above to inspect its property fill rates.",
                className="text-muted text-center mt-2",
                style={"fontSize": "0.85rem"},
            )
        )

    datasets   = results.get("datasets", [])
    ds_details = collect_ds_details(datasets, "property_coverage")
    fig        = property_charts.property_fill_rates(ds_details, active_class)

    if fig is None:
        return panel_card([
            html.P(f"No property data for {_short(active_class)}.",
                   className="text-muted", style={"fontSize": "0.85rem"}),
        ])

    return panel_card([
        section_label(f"Property fill rates — {_short(active_class)}"),
        html.Small(active_class, className="text-muted d-block mb-2",
                   style={"fontSize": "0.75rem", "wordBreak": "break-all"}),
        dcc.Graph(figure=fig, config={"displayModeBar": False}),
    ])


# ════════════════════════════════════════════════════════════════════════════
# Public entry point
# ════════════════════════════════════════════════════════════════════════════
def render_detail_panel(
    active_metric_id: str | None,
    results: dict,
    ui_state: dict | None = None,
) -> html.Div:
    if not results or results.get("status") == "error":
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

    if active_metric_id == multilingual_labeling_coverage.METRIC_ID:
        click_data = (ui_state or {}).get("multilingual_click")
        content = multilingual_labeling_coverage.render(
            metric, datasets, click_data=click_data
        )
    else:
        content = renderer(metric, datasets)

    return html.Div([
        html.Hr(className="mt-1 mb-3"),
        content,
    ])