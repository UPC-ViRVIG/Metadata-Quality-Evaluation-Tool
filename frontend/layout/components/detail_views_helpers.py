from dash import html
import dash_bootstrap_components as dbc

from charts.palette import COLORS
from layout.components.common import score_badge


def collect_ds_details(
    datasets: list[dict],
    metric_id: str,
) -> list[dict]:
    """
    Extracts metric data from each dataset into a flat list ready for
    chart functions.

    Returns
    -------
    list of dicts:
        {"label": str, "color": str, "details": dict, "score": float}
    One entry per dataset that contains the requested metric_id.
    """
    result = []
    for i, ds in enumerate(datasets):
        m = next(
            (x for x in ds.get("metrics", []) if x["metric_id"] == metric_id),
            None,
        )
        if m:
            result.append({
                "label":   ds.get("label", f"Dataset {i+1}"),
                "color":   COLORS[i % len(COLORS)],
                "details": m.get("details", {}),
                "score":   m["score"],
            })
    return result


def _description_subtitle(metric: dict) -> html.Div:
    """
    Muted description line shown below the metric name in the detail panel.
    Shows the plain-language tooltip as the subtitle if available,
    with the full technical description in a ℹ tooltip on hover.
    """
    tooltip_text = metric.get("tooltip", "")
    description  = metric.get("description", "")
    if not tooltip_text and not description:
        return html.Div()

    tip_id = f"tip-detail-{metric.get('metric_id', 'metric')}"
    return html.Div([
        html.Small([
            html.Span(tooltip_text or description,
                      className="text-muted",
                      style={"fontSize": "0.82rem"}),
            html.Span(
                " ℹ",
                id=tip_id,
                style={"fontSize": "0.70rem", "color": "#adb5bd",
                       "cursor": "help", "userSelect": "none"},
            ) if description and tooltip_text else html.Span(),
        ]),
        dbc.Tooltip(
            description,
            target=tip_id,
            placement="right",
            style={"maxWidth": "320px"},
        ) if description and tooltip_text else html.Span(),
    ], className="mb-3")


def analysis_header(name: str, score: float, metric: dict | None = None) -> html.Div:
    """Header row for single-dataset view: metric name + coloured % badge
    + description subtitle below."""
    return html.Div([
        dbc.Row([
            dbc.Col(html.H6(name, className="mb-0 fw-semibold"), width="auto"),
            dbc.Col(score_badge(score), width="auto", className="ps-0"),
        ], align="center", className="mb-1"),
        _description_subtitle(metric or {}),
    ])


def comparison_header(name: str, ds_details: list[dict],
                      metric: dict | None = None) -> html.Div:
    """Header row for comparison view: metric name + one badge per dataset
    + description subtitle below."""
    badges = [
        dbc.Badge(
            f"{d['label']}: {round(d['score'] * 100)}%",
            color="secondary",
            className="ms-2",
            style={"backgroundColor": d["color"]},
        )
        for d in ds_details
    ]
    return html.Div([
        dbc.Row(
            [dbc.Col(html.H6(name, className="mb-0 fw-semibold"), width="auto")]
            + [dbc.Col(b, width="auto") for b in badges],
            align="center",
            className="mb-1 g-1",
        ),
        _description_subtitle(metric or {}),
    ])