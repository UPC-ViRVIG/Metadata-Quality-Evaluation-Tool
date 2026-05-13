import plotly.graph_objects as go
from charts.palette import COLORS, base_layout


def hbar(
    names: list[str],
    series: list[dict],     
    title: str = "",
    height: int | None = None,
    x_range: list = None,
    x_format: str = ".0%",
    x_title: str = "",
) -> go.Figure:
    """
    Horizontal grouped bar chart.

    Parameters
    ----------
    names    : y-axis category labels
    series   : list of trace dicts with "label", "values", optional "color"
    title    : chart title (omitted if empty string)
    height   : pixel height; auto-calculated if None
    x_range  : explicit [min, max] for x-axis; defaults to [0, 1.18]
    x_format : tick format string; use "" to disable
    x_title  : x-axis label
    """
    h = height or max(220, len(names) * 36 + 60)
    xr = x_range if x_range is not None else [0, 1.18]

    fig = go.Figure()
    for i, s in enumerate(series):
        color = s.get("color", COLORS[i % len(COLORS)])
        fig.add_bar(
            name=s["label"],
            y=names,
            x=s["values"],
            orientation="h",
            marker_color=color,
            text=[
                (f"{round(v * 100)}%" if x_format == ".0%" else str(round(v)))
                if v is not None else "n/a"
                for v in s["values"]
            ],
            textposition="outside",
            **{k: v for k, v in s.items()
               if k not in ("label", "values", "color")},
        )

    fig.update_layout(base_layout(
        height=h,
        margin=dict(l=8, r=48, t=36 if title else 8, b=8),
        title=dict(text=title, font=dict(size=13)) if title else None,
        barmode="group",
        xaxis=dict(
            range=xr,
            tickformat=x_format,
            gridcolor="rgba(0,0,0,0.05)",
            title=x_title or None,
        ),
        yaxis=dict(automargin=True),
        showlegend=len(series) > 1,
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
    ))
    return fig


def vbar(
    names: list[str],
    series: list[dict],
    title: str = "",
    height: int = 260,
    y_range: list = None,
) -> go.Figure:
    """
    Vertical grouped bar chart.

    Parameters
    ----------
    names   : x-axis category labels
    series  : list of trace dicts with "label", "values", optional "color"
    title   : chart title
    height  : pixel height
    y_range : explicit [min, max] for y-axis; defaults to [0, 1.18]
    """
    yr = y_range if y_range is not None else [0, 1.18]

    fig = go.Figure()
    for i, s in enumerate(series):
        color = s.get("color", COLORS[i % len(COLORS)])
        fig.add_bar(
            name=s["label"],
            x=names,
            y=s["values"],
            marker_color=color,
            text=[f"{round(v * 100)}%" for v in s["values"]],
            textposition="outside",
        )

    fig.update_layout(base_layout(
        height=height,
        margin=dict(l=8, r=8, t=36 if title else 8, b=8),
        title=dict(text=title, font=dict(size=13)) if title else None,
        barmode="group",
        yaxis=dict(range=yr, tickformat=".0%",
                   gridcolor="rgba(0,0,0,0.05)"),
        showlegend=len(series) > 1,
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
    ))
    return fig