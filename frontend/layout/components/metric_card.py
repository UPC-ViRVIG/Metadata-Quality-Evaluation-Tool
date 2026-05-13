from collections import defaultdict

from dash import html, dcc
import dash_bootstrap_components as dbc
import plotly.graph_objects as go

from charts.palette import ACCENT, COLORS
from charts.palette import base_layout


def build_metric_cards(
    metrics: list[dict],
    active_metric_id: str | None = None,
    datasets: list[dict] | None = None,
) -> html.Div:
    """
    Renders a grid of clickable metric cards grouped by quality dimension.

    Grouping uses metric_dims ({metric_id: dimension}), populated from
    GET /metrics on startup. Falls back to m.get("dimension") if not provided,
    and finally to "Other" — so the function is always safe to call.

    Analysis mode  (datasets=None or single dataset):
        Each card shows the metric name and a coloured % badge.

    Comparison mode (datasets with 2+ entries):
        Each card shows the metric name and a small inline bar chart.

    The active card gets a left-border accent (updated by callbacks/ui.py).
    """
    if not metrics:
        return html.Div()

    comparison_mode = datasets is not None and len(datasets) > 1

    by_dim: dict[str, list] = defaultdict(list)
    for m in metrics:
        dim = m.get("dimension") or "Other"
        by_dim[dim].append(m)

    sections = []
    for dim, dim_metrics in by_dim.items():
        cards = []
        for m in dim_metrics:
            is_active  = m["metric_id"] == active_metric_id
            card_style = _card_style(is_active)

            if comparison_mode:
                body = _comparison_card_body(m, datasets)
            else:
                body = _analysis_card_body(m)

            cards.append(
                dbc.Col(
                    html.Div(
                        dbc.Card(
                            dbc.CardBody(body, className="p-3"),
                            className="h-100",
                        ),
                        id={"type": "metric-card", "index": m["metric_id"]},
                        n_clicks=0,
                        style=card_style,
                    ),
                    xs=12, md=6, lg=4,
                    className="mb-3",
                )
            )

        dim_label = [] if dim == "Other" else [
            html.P(
                dim,
                className="text-muted fw-semibold mb-2",
                style={"fontSize": "0.75rem", "textTransform": "uppercase",
                       "letterSpacing": "0.06em"},
            )
        ]
        sections.append(html.Div(
            dim_label + [dbc.Row(cards, className="g-2")],
            className="mb-2",
        ))

    return html.Div(sections)


def _card_style(is_active: bool) -> dict:
    return {
        "cursor":     "pointer",
        "borderLeft": f"3px solid {ACCENT}" if is_active else "1px solid #dee2e6",
        "transition": "border 0.15s",
    }


def _analysis_card_body(m: dict) -> list:
    score_pct   = round(m["score"] * 100)
    badge_color = (
        "success" if score_pct >= 75 else
        "warning" if score_pct >= 40 else
        "danger"
    )
    tooltip = m.get("tooltip", "")
    description = m.get("description", "")
    tip_id = f"tip-card-{m['metric_id']}"

    return [
        dbc.Row([
            dbc.Col(
                html.Span([
                    m["name"],
                    html.Span(" ℹ", id=tip_id,
                              style={"fontSize": "0.70rem", "color": "#adb5bd",
                                     "cursor": "help", "userSelect": "none"})
                    if tooltip else html.Span(),
                ], style={"fontSize": "0.875rem", "fontWeight": "500"}),
                width=9,
            ),
            dbc.Col(
                dbc.Badge(f"{score_pct}%", color=badge_color,
                          className="float-end"),
                width=3,
                className="text-end d-flex align-items-center justify-content-end",
            ),
        ], className="g-0 mb-1"),
        html.Small(
            m.get("tooltip") or m.get("dimension", ""),
            className="text-muted",
            style={"fontSize": "0.78rem", "display": "block",
                   "whiteSpace": "nowrap", "overflow": "hidden",
                   "textOverflow": "ellipsis"},
        ),
        dbc.Tooltip(
            [html.Strong(tooltip), html.Br(),
             html.Small(description, style={"color": "#dee2e6"})],
            target=tip_id, placement="top",
            style={"maxWidth": "280px"},
        ) if tooltip else html.Span(),
    ]


def _comparison_card_body(m: dict, datasets: list[dict]) -> list:
    ds_scores = []
    for ds in datasets:
        match = next(
            (x for x in ds.get("metrics", [])
             if x["metric_id"] == m["metric_id"]),
            None,
        )
        ds_scores.append(match["score"] if match else 0.0)

    ds_labels = [ds.get("label", f"Dataset {i+1}") for i, ds in enumerate(datasets)]
    mini_fig = go.Figure()
    for i, score in enumerate(ds_scores):
        mini_fig.add_bar(
            y=[" "],          # single invisible category — no y-axis label
            x=[score],
            orientation="h",
            marker_color=COLORS[i % len(COLORS)],
            showlegend=False,
            # Show dataset name + score on hover, nothing else
            hovertemplate=f"{ds_labels[i]}: {round(score * 100)}%<extra></extra>",
            text=[f"{round(score * 100)}%"],
            textposition="outside",
            textfont=dict(size=10),
            cliponaxis=False,
            width=0.5 / len(ds_scores),
            offset=(i - len(ds_scores) / 2) * (0.5 / len(ds_scores)),
        )
    mini_fig.update_layout(
        height=44,
        margin=dict(l=0, r=28, t=0, b=0),
        plot_bgcolor="white",
        paper_bgcolor="white",
        barmode="overlay",
        xaxis=dict(range=[0, 1.3], showticklabels=False,
                   showgrid=False, zeroline=False),
        yaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
    )

    return [
        dbc.Row([
            dbc.Col(
                html.Span([
                    m["name"],
                    html.Span(" ℹ",
                              id=f"tip-ccard-{m['metric_id']}",
                              style={"fontSize": "0.70rem", "color": "#adb5bd",
                                     "cursor": "help", "userSelect": "none"})
                    if m.get("tooltip") else html.Span(),
                    dbc.Tooltip(
                        [html.Strong(m.get("tooltip", "")), html.Br(),
                         html.Small(m.get("description", ""),
                                    style={"color": "#dee2e6"})],
                        target=f"tip-ccard-{m['metric_id']}",
                        placement="top",
                        style={"maxWidth": "280px"},
                    ) if m.get("tooltip") else html.Span(),
                ], style={"fontSize": "0.875rem", "fontWeight": "500"}),
                width=12,
            ),
        ], className="g-0 mb-1"),
        html.Small(
            m.get("tooltip") or m.get("dimension", ""),
            className="text-muted",
            style={"fontSize": "0.78rem", "display": "block",
                   "whiteSpace": "nowrap", "overflow": "hidden",
                   "textOverflow": "ellipsis"},
        ),
        dcc.Graph(
            figure=mini_fig,
            config={"displayModeBar": False},
            style={"height": "48px", "marginTop": "4px"},
        ),
    ]