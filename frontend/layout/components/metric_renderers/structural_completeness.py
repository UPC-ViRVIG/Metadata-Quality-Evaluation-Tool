from dash import html, dcc
import dash_bootstrap_components as dbc

import charts.structural_completeness as charts
from layout.components.common import panel_card, section_label
from layout.components.detail_views_helpers import (
    collect_ds_details,
    analysis_header,
    comparison_header,
)

METRIC_ID = "structural_completeness"


def render(metric: dict, datasets: list[dict]) -> html.Div:
    """
    Render the full Structural Completeness detail view.

    Parameters
    ----------
    metric : dict
        Metric metadata from the store.
    datasets : list[dict]
        Raw dataset dicts from store-results.
    """
    ds_details = collect_ds_details(datasets, METRIC_ID)
    if not ds_details:
        return html.Div()

    comparison = len(ds_details) > 1
    header = (
        comparison_header("Structural Completeness", ds_details, metric=metric)
        if comparison else
        analysis_header("Structural Completeness", ds_details[0]["score"],
                        metric=metric)
    )

    return html.Div([
        header,
        _distribution_section(ds_details),
        _summary_section(ds_details, comparison),
        _class_section(ds_details),
    ])


# ── Section builders ──────────────────────────────────────────────────────

def _summary_section(ds_details: list[dict], comparison: bool) -> html.Div:
    """
    Summary statistics table.

    Rows: total records, mean completeness, median completeness,
    min/max completeness, detected profile.
    Mean is placed first after total records as it gives the most
    immediately useful quality signal.

    Parameters
    ----------
    ds_details : list[dict]
    comparison : bool
    """
    col_headers = (
        [html.Th("")] + [html.Th(d["label"]) for d in ds_details]
        if comparison else [html.Th(""), html.Th("Value")]
    )

    rows_spec = [
        ("total_records",              "Total Records",
         lambda v: f"{v:,}"),
        ("median_record_completeness", "Median Completeness",
         lambda v: f"{round(v * 100)}%"),
        ("min_record_completeness",    "Min Completeness",
         lambda v: f"{round(v * 100)}%"),
        ("max_record_completeness",    "Max Completeness",
         lambda v: f"{round(v * 100)}%"),
        ("profile",                    "Detected Profile",
         str),
    ]

    stat_rows = []
    for key, label, fmt in rows_spec:
        vals = [
            fmt(d["details"][key])
            if d["details"].get(key) is not None else "—"
            for d in ds_details
        ]
        stat_rows.append(html.Tr(
            [html.Td(html.Strong(label,
                                 style={"fontSize": "0.82rem"}))]
            + [html.Td(v, style={"fontSize": "0.82rem"}) for v in vals]
        ))

    warnings = [
        (d["label"], d["details"]["warning"])
        for d in ds_details
        if d["details"].get("warning")
    ]

    return panel_card([
        section_label("Summary statistics"),
        dbc.Table(
            [html.Thead(html.Tr(col_headers)), html.Tbody(stat_rows)],
            bordered=True, size="sm", className="mb-2",
        ),
        html.Div([
            dbc.Alert(
                [html.Strong(f"{lbl}: "), w],
                color="warning", className="py-2 mb-2",
                style={"fontSize": "0.82rem"},
            )
            for lbl, w in warnings
        ]) if warnings else html.Div(),
    ])


def _distribution_section(ds_details: list[dict]) -> html.Div:
    """
    Record completeness distribution histogram panel.

    Parameters
    ----------
    ds_details : list[dict]
    """
    return panel_card([
        section_label("Record completeness distribution"),
        dcc.Graph(
            figure=charts.score_distribution(ds_details),
            config={"displayModeBar": False},
        ),
    ])


def _class_section(ds_details: list[dict]) -> html.Div:
    """
    Class-level completeness panel.

    Primary view: horizontal bar chart of mean completeness per class,
    sorted ascending so the most incomplete classes appear first.
    Classes are sorted by mean score so problem areas surface immediately.

    Clicking a bar opens a violin/distribution drilldown below.

    Parameters
    ----------
    ds_details : list[dict]
    """
    bar_fig = charts.class_completeness_bar(ds_details)
    if bar_fig is None:
        return html.Div()

    return panel_card([
        section_label("Mean Record Completeness by Class"),
        html.Small(
            "Click a bar to see the full score distribution for that class",
            className="text-muted d-block mb-2",
            style={"fontSize": "0.75rem"},
        ),
        dcc.Graph(
            id="sc-class-bar",
            figure=bar_fig,
            config={"displayModeBar": False},
        ),
        html.Div(id="sc-class-drilldown"),
    ])


def render_class_drilldown(
    class_label: str,
    ds_details: list[dict],
) -> html.Div:
    """
    Violin drilldown for a single class, rendered on bar click.

    Finds the class URI matching the clicked bar label, then renders
    the violin plot filtered to that class only.

    Parameters
    ----------
    class_label : str
        Short label of the clicked class (fragment or last path segment).
    ds_details : list[dict]
        Per-dataset detail dicts from collect_ds_details.
    """
    # Resolve full URI from short label
    target_uri = None
    for d in ds_details:
        for uri in d["details"].get("class_statistics", {}):
            short = uri.split("#")[-1].split("/")[-1]
            if short == class_label:
                target_uri = uri
                break
        if target_uri:
            break

    if not target_uri:
        return html.Div()

    density_fig = charts.class_density_chart(ds_details, target_uri)
    if density_fig is None:
        return html.Div()

    return html.Div([
        html.Hr(className="mt-2 mb-3"),
        html.P(
            f"Score distribution within the {class_label} class",
            className="text-muted mb-1",
            style={"fontSize": "0.78rem"},
        ),
        html.Small(
"Hover over the distribution for additional information.",
            className="text-muted d-block mb-2",
            style={"fontSize": "0.75rem"},
        ),
        dcc.Graph(figure=density_fig, config={"displayModeBar": False}),
    ])