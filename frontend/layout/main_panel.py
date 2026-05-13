from dash import html, dcc
import dash_bootstrap_components as dbc
import plotly.graph_objects as go

from charts.palette import ACCENT, COLORS
from charts.overview import donut
from layout.components.common import card, stat_card
from layout.components.metric_card import build_metric_cards


def build_guide() -> html.Div:
    """
    Build the initial onboarding/guide panel

    Returns
    -------
    html.Div
        Guide/onboarding layout.
    """
    return html.Div(
        dbc.Row(
            dbc.Col(
                card([
                    html.H5("Metadata Quality Evaluator", className="mb-3"),
                    html.P("To get started:", className="text-muted mb-2"),
                    html.Ol([
                        html.Li("Add one or more data sources using the sidebar."),
                        html.Li("Select the quality metrics you want to evaluate."),
                        html.Li("Click Run Evaluation."),
                    ], className="ps-3"),
                    html.Hr(className="my-3"),
                    html.P([html.Strong("1 source "),
                            "→ Analysis mode: detailed per-metric breakdown."],
                           className="mb-1 small text-muted"),
                    html.P([html.Strong("2+ sources "),
                            "→ Comparison mode: side-by-side quality radar."],
                           className="mb-0 small text-muted"),
                ]),
                width={"size": 6, "offset": 3},
            ),
            className="mt-5",
        ),
        className="py-4",
    )


def build_error(message: str) -> html.Div:
    """
    Build evaluation error display panel.

    Parameters
    ----------
    message : str
        Human-readable evaluation error message.

    Returns
    -------
    html.Div
        Error alert layout.
    """
    return html.Div(
        dbc.Alert(
            [html.Strong("Evaluation error: "), message],
            color="danger", className="mt-4",
        )
    )


def build_analysis(
    datasets: list[dict],
    active_metric_id: str | None = None,
) -> html.Div:
    """
    Build single-dataset analysis layout.

    Parameters
    ----------
    datasets : list[dict]
        Evaluated dataset results.
        Analysis mode expects exactly one dataset.
    active_metric_id : str | None, optional
        Currently selected metric identifier.

    Returns
    -------
    html.Div
        Analysis dashboard layout.
    """
    dataset = datasets[0]
    label   = dataset.get("label", "Dataset")
    stats   = dataset.get("stats", {})
    overall = dataset.get("overall_score", 0.0)
    metrics = [m for m in dataset.get("metrics", [])
               if m.get("status") not in ("error", "skipped")]

    is_overview_active = active_metric_id == "__overview__"
    overall_card = dbc.Col(
        html.Div(
            card([
                html.P("Overall Score", className="text-muted mb-1",
                       style={"fontSize": "0.75rem", "textTransform": "uppercase",
                              "letterSpacing": "0.06em"}),
                dcc.Graph(figure=donut(overall), config={"displayModeBar": False},
                          style={"height": "160px"}),
            ], className="h-100"),
            id={"type": "metric-card", "index": "__overview__"},
            n_clicks=0,
            style={
                "cursor":     "pointer",
                "borderLeft": f"3px solid {ACCENT}" if is_overview_active
                              else "1px solid #dee2e6",
                "transition": "border 0.15s",
                "height":     "100%",
            },
        ),
        xs=6, md=3, className="mb-3",
    )

    return html.Div([
        html.H6(f"Analysis — {label}", className="text-muted mb-3 fw-semibold",
                style={"fontSize": "0.8rem", "textTransform": "uppercase",
                       "letterSpacing": "0.08em"}),
        dbc.Row([
            overall_card,
            stat_card("Triples",  stats.get("triple_count")),
            stat_card("Entities", stats.get("entity_count")),
            stat_card("Classes",  stats.get("class_count")),
        ], className="g-2"),
        html.Hr(className="my-2"),
        html.P("Quality Metric Scores", className="text-muted fw-semibold mb-2",
               style={"fontSize": "0.75rem", "textTransform": "uppercase",
                      "letterSpacing": "0.06em"}),
        build_metric_cards(metrics, active_metric_id),
        html.Div(id="detail-panel"),
    ], className="py-3 pe-2")


def build_comparison(
    datasets: list[dict],
    active_metric_id: str | None = None,
) -> html.Div:
    """
    Build multi-dataset comparison layout.

    Parameters
    ----------
    datasets : list[dict]
        Evaluated dataset results.
    active_metric_id : str | None, optional
        Currently selected metric identifier.

    Returns
    -------
    html.Div
        Comparison dashboard layout.
    """
    labels         = [ds.get("label", f"Dataset {i+1}") for i, ds in enumerate(datasets)]
    overall_scores = [ds.get("overall_score", 0.0) for ds in datasets]

    seen: dict[str, int] = {}
    unique_labels = []
    for lbl in labels:
        if lbl in seen:
            seen[lbl] += 1
            unique_labels.append(f"{lbl} ({seen[lbl]})")
        else:
            seen[lbl] = 0
            unique_labels.append(lbl)

    overall_fig = go.Figure(go.Bar(
        x=unique_labels,
        y=overall_scores,
        marker_color=[COLORS[i % len(COLORS)] for i in range(len(unique_labels))],
        text=[f"{round(s * 100)}%" for s in overall_scores],
        textposition="outside",
        hoverinfo="none",
    ))
    overall_fig.update_layout(
        plot_bgcolor="white", paper_bgcolor="white",
        font=dict(family="inherit", size=12),
        title=dict(text="Overall Score", font=dict(size=13)),
        height=200, margin=dict(l=8, r=8, t=36, b=8),
        yaxis=dict(range=[0, 1.2], tickformat=".0%",
                   gridcolor="rgba(0,0,0,0.05)"),
        showlegend=False,
    )

    stat_rows = []
    for sk, sl in [("triple_count", "Triples"),
                   ("entity_count", "Entities"),
                   ("class_count",  "Classes")]:
        cells = [html.Td(html.Strong(sl))]
        for ds in datasets:
            cells.append(html.Td(str(ds.get("stats", {}).get(sk, "—"))))
        stat_rows.append(html.Tr(cells))

    stats_table = dbc.Table(
        [html.Thead(html.Tr([html.Th("")] + [html.Th(l) for l in labels])),
         html.Tbody(stat_rows)],
        bordered=True, size="sm", className="mb-0",
    )

    is_overview_active = active_metric_id == "__overview__"
    overall_col = dbc.Col(
        html.Div(
            card([dcc.Graph(figure=overall_fig, config={"displayModeBar": False})],
                 className="h-100"),
            id={"type": "metric-card", "index": "__overview__"},
            n_clicks=0,
            style={
                "cursor":     "pointer",
                "borderLeft": f"3px solid {ACCENT}" if is_overview_active
                              else "1px solid #dee2e6",
                "transition": "border 0.15s",
                "height":     "100%",
            },
        ),
        md=5, className="mb-3",
    )

    all_metrics_by_id: dict = {}
    for ds in datasets:
        for m in ds.get("metrics", []):
            if (m.get("status") not in ("error", "skipped")
                    and m["metric_id"] not in all_metrics_by_id):
                all_metrics_by_id[m["metric_id"]] = m

    return html.Div([
        html.H6(f"Comparison — {' vs '.join(labels)}",
                className="text-muted mb-3 fw-semibold",
                style={"fontSize": "0.8rem", "textTransform": "uppercase",
                       "letterSpacing": "0.08em"}),
        dbc.Row([
            overall_col,
            dbc.Col(
                card([
                    html.P("Dataset Statistics", className="text-muted mb-2",
                           style={"fontSize": "0.75rem", "textTransform": "uppercase",
                                  "letterSpacing": "0.06em"}),
                    stats_table,
                ]),
                md=7, className="mb-3",
            ),
        ], className="g-2"),
        html.Hr(className="my-2"),
        html.P("Quality Metric Scores", className="text-muted fw-semibold mb-2",
               style={"fontSize": "0.75rem", "textTransform": "uppercase",
                      "letterSpacing": "0.06em"}),
        build_metric_cards(list(all_metrics_by_id.values()), active_metric_id, datasets),
        html.Div(id="detail-panel"),
    ], className="py-3 pe-2")