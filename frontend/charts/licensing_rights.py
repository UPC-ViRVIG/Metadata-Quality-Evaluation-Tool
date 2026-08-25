"""
Charts for the licensing_rights metric.

Three views: a per-class rights-coverage bar (mirrors
property_coverage's class chart), a summary bar comparing machine
readability and vocabulary conformance, and a grouped bar of the
unscored rights category distribution (public domain / open /
restricted / unevaluated).
"""

from collections import defaultdict

import plotly.graph_objects as go
from charts.palette import COLORS, base_layout


def _short(uri: str) -> str:
    """Last fragment of a URI (after # or last /)."""
    return uri.split("#")[-1].split("/")[-1]


_CATEGORY_LABELS = {
    "public_domain":    "Public domain",
    "open_permissive":  "Open / permissive",
    "restricted":       "Restricted (in copyright)",
    "unevaluated":      "Unevaluated",
    "other_recognized": "Other recognized",
}


def coverage_by_class(ds_details: list[dict]) -> go.Figure | None:
    """
    Horizontal bar chart of rights coverage (fill rate) per class.

    One trace per dataset in comparison mode; classes ordered by mean
    fill rate ascending (worst first), the same convention as
    property_coverage's drilldown charts.

    Parameters
    ----------
    ds_details : list[dict]
        Per-dataset detail dicts from collect_ds_details.

    Returns
    -------
    go.Figure | None
        None if no dataset has any class fill-rate data.
    """
    all_classes: list[str] = []
    for d in ds_details:
        for cls in d["details"].get("rights_coverage", {}).get("class_fill_rates", {}):
            if cls not in all_classes:
                all_classes.append(cls)

    if not all_classes:
        return None

    def _mean_rate(cls: str) -> float:
        rates = [
            d["details"].get("rights_coverage", {})
            .get("class_fill_rates", {}).get(cls)
            for d in ds_details
        ]
        valid = [r for r in rates if r is not None]
        return sum(valid) / len(valid) if valid else 0.0

    all_classes.sort(key=_mean_rate, reverse=True)
    labels = [_short(c) for c in all_classes]

    comparison = len(ds_details) > 1
    fig = go.Figure()
    for i, d in enumerate(ds_details):
        rates = d["details"].get("rights_coverage", {}).get("class_fill_rates", {})
        vals  = [rates.get(c, 0.0) for c in all_classes]
        fig.add_bar(
            name=d["label"],
            y=labels,
            x=vals,
            orientation="h",
            marker_color=COLORS[i % len(COLORS)] if comparison else "#5B6EF5",
            customdata=all_classes,
            hovertemplate="<b>%{customdata}</b><br>Coverage: %{x:.1%}<extra></extra>",
            text=[f"{round(v * 100, 1)}%" for v in vals],
            textposition="outside",
            showlegend=comparison,
        )

    fig.update_layout(base_layout(
        height=max(220, len(labels) * (40 if comparison else 32) + 80),
        margin=dict(l=8, r=48, t=8, b=8),
        barmode="group",
        xaxis=dict(range=[0, 1.15], tickformat=".0%",
                   gridcolor="rgba(0,0,0,0.05)", title="Rights coverage"),
        yaxis=dict(
            automargin=True,
            categoryorder="array",
            categoryarray=list(reversed(labels)),
        ),
        showlegend=comparison,
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
    ))
    return fig


def signal_quality_bar(ds_details: list[dict]) -> go.Figure:
    """
    Grouped bar comparing machine readability and vocabulary
    conformance scores across datasets.

    Parameters
    ----------
    ds_details : list[dict]
        Per-dataset detail dicts from collect_ds_details.

    Returns
    -------
    go.Figure
    """
    categories = ["Machine readability", "Vocabulary conformance"]
    comparison = len(ds_details) > 1

    fig = go.Figure()
    for i, d in enumerate(ds_details):
        scores = d["details"].get("scores", {})
        vals = [
            scores.get("machine_readability", 0.0),
            scores.get("vocabulary_conformance", 0.0),
        ]
        fig.add_bar(
            name=d["label"],
            x=categories,
            y=vals,
            marker_color=COLORS[i % len(COLORS)] if comparison else "#5B6EF5",
            text=[f"{round(v * 100, 1)}%" for v in vals],
            textposition="outside",
            hovertemplate="<b>%{x}</b><br>Score: %{y:.1%}<extra></extra>",
            showlegend=comparison,
        )

    fig.update_layout(base_layout(
        height=280,
        margin=dict(l=8, r=8, t=8, b=8),
        barmode="group",
        yaxis=dict(range=[0, 1.15], tickformat=".0%",
                   gridcolor="rgba(0,0,0,0.05)"),
        showlegend=comparison,
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
    ))
    return fig


def rights_category_bar(ds_details: list[dict]) -> go.Figure | None:
    """
    Grouped bar chart of the unscored rights category distribution
    (public domain / open / restricted / unevaluated) for recognized
    rights statements.

    One trace per dataset, grouped by category — the same
    dataset-colored grouped-bar convention as coverage_by_class and
    signal_quality_bar. Categories are ordered by total count across
    datasets, descending.

    Parameters
    ----------
    ds_details : list[dict]
        Per-dataset detail dicts from collect_ds_details.

    Returns
    -------
    go.Figure | None
        None if no dataset has any recognized rights statements.
    """
    category_totals: dict[str, int] = defaultdict(int)
    for d in ds_details:
        for e in d["details"].get("rights_category_distribution", []):
            category_totals[e["category"]] += e["count"]

    if not category_totals:
        return None

    categories = sorted(category_totals, key=lambda c: category_totals[c], reverse=True)
    labels = [_CATEGORY_LABELS.get(c, c) for c in categories]

    comparison = len(ds_details) > 1
    fig = go.Figure()
    for i, d in enumerate(ds_details):
        counts = {
            e["category"]: e["count"]
            for e in d["details"].get("rights_category_distribution", [])
        }
        vals = [counts.get(c, 0) for c in categories]
        fig.add_bar(
            name=d["label"],
            x=labels,
            y=vals,
            marker_color=COLORS[i % len(COLORS)] if comparison else "#5B6EF5",
            text=[str(v) if v > 0 else "" for v in vals],
            textposition="outside",
            hovertemplate="<b>%{x}</b><br>Count: %{y:,}<extra></extra>",
            showlegend=comparison,
        )

    fig.update_layout(base_layout(
        height=300,
        margin=dict(l=8, r=8, t=8, b=8),
        barmode="group",
        xaxis=dict(automargin=True),
        yaxis=dict(title="Count", gridcolor="rgba(0,0,0,0.05)"),
        showlegend=comparison,
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
    ))
    return fig
