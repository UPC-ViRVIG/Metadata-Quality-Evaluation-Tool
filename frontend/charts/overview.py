import plotly.graph_objects as go
from charts.palette import ACCENT, GREY, COLORS, hex_to_rgba, base_layout


def donut(value: float, height: int = 170) -> go.Figure:
    """
    Single-value donut chart showing a 0–1 score as a percentage.

    Parameters
    ----------
    value  : float 0–1
    height : pixel height of the figure
    """
    pct = round(value * 100)
    fig = go.Figure(go.Pie(
        values=[pct, 100 - pct],
        hole=0.68,
        textinfo="none",
        hoverinfo="skip",
        showlegend=False,
        marker=dict(colors=[ACCENT, GREY]),
    ))
    fig.update_layout(base_layout(
        height=height,
        margin=dict(l=0, r=0, t=0, b=0),
        annotations=[dict(
            text=f"<b>{pct}%</b>",
            x=0.5, y=0.5,
            font=dict(size=20),
            showarrow=False,
        )],
    ))
    return fig


def spider(
    metric_names: list[str],
    datasets: list[dict],    # [{"label": str, "values": [float 0-1]}]
    height: int = 380,
) -> go.Figure:
    """
    Radar / spider chart — one filled polygon per dataset.
    Used in the overview panel when 2+ datasets are present.
    """
    fig = go.Figure()
    for i, ds in enumerate(datasets):
        color = COLORS[i % len(COLORS)]
        fig.add_trace(go.Scatterpolar(
            r=ds["values"] + [ds["values"][0]],
            theta=metric_names + [metric_names[0]],
            fill="toself",
            name=ds["label"],
            line=dict(color=color),
            fillcolor=hex_to_rgba(color, 0.15),
        ))
    fig.update_layout(base_layout(
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


def metric_score_bar(
    metric_names: list[str],
    scores: list[float],
    height: int | None = None,
) -> go.Figure:
    """
    Vertical bar chart of metric scores for a single dataset, sorted
    highest to lowest.
    Used in the overview panel (analysis mode).
    """
    paired = sorted(zip(scores, metric_names), reverse=True)
    sorted_scores = [p[0] for p in paired]
    sorted_names  = [p[1] for p in paired]

    h = height or max(280, len(sorted_names) * 60)
    fig = go.Figure(go.Bar(
        x=sorted_names,
        y=sorted_scores,
        marker_color=ACCENT,
        text=[f"{round(v * 100)}%" for v in sorted_scores],
        textposition="outside",
        hoverinfo="none",
    ))
    fig.update_layout(base_layout(
        height=h,
        margin=dict(l=8, r=8, t=8, b=80),
        yaxis=dict(range=[0, 1.18], tickformat=".0%",
                   gridcolor="rgba(0,0,0,0.05)"),
        xaxis=dict(automargin=True),
    ))
    return fig


def grouped_metric_bar(
    metric_names: list[str],
    datasets: list[dict],    
    height: int | None = None,
) -> go.Figure:
    """
    Grouped vertical bar chart for comparison overview when there are too
    few metrics to render a meaningful spider chart (<2 metrics).
    """
    h = height or max(280, len(metric_names) * 60)
    fig = go.Figure()
    for i, ds in enumerate(datasets):
        fig.add_bar(
            name=ds["label"],
            x=metric_names,
            y=ds["values"],
            marker_color=COLORS[i % len(COLORS)],
            text=[f"{round(v * 100)}%" for v in ds["values"]],
            textposition="outside",
            hoverinfo="none",
        )
    fig.update_layout(base_layout(
        height=h,
        margin=dict(l=8, r=8, t=8, b=80),
        barmode="group",
        yaxis=dict(range=[0, 1.18], tickformat=".0%",
                   gridcolor="rgba(0,0,0,0.05)"),
        xaxis=dict(automargin=True),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
    ))
    return fig