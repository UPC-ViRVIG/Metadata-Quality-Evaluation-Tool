"""
Detail view renderer for the connectivity metric: reachable/unreachable
donut, failure-reason bar chart, a sample violations table, and the
CSV export button for the full unreachable-URI list.
"""

from dash import html, dcc
import dash_bootstrap_components as dbc

import charts.connectivity as charts
from layout.components.common import panel_card, section_label
from layout.components.detail_views_helpers import (
    collect_ds_details,
    analysis_header,
    comparison_header,
)

METRIC_ID = "connectivity"


def render(metric: dict, datasets: list[dict]) -> html.Div:
    """
    Render the full Connectivity detail view.

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
        comparison_header("Connectivity", ds_details, metric=metric)
        if comparison else
        analysis_header("Connectivity", ds_details[0]["score"], metric=metric)
    )

    return html.Div([
        header,
        _summary_section(ds_details, comparison),
        _export_section(ds_details),
    ])


# ── Section builders ──────────────────────────────────────────────────────

def _summary_section(ds_details: list[dict], comparison: bool) -> html.Div:
    """
    Overview section: not-applicable/sampled context line, reachability
    donut, failure-reason bar chart, and a sample violations table.
    """
    content = [section_label("URI dereferenceability")]

    # Per-dataset summary lines. A dataset with no checkable URIs at all
    # (details["not_applicable"]) gets a plain informational note rather
    # than being folded silently into a 100% score.
    summaries = []
    for d in ds_details:
        det   = d["details"]
        total = det.get("total_checked", 0)
        inv   = det.get("unreachable_count", 0)
        prefix = f"{d['label']}: " if comparison else ""
        if det.get("not_applicable"):
            text = f"{prefix}No URIs found in this dataset to check."
        else:
            text = f"{prefix}{inv:,} unreachable / {total:,} distinct URIs checked"
        summaries.append(html.Span(
            text, className="text-muted me-4", style={"fontSize": "0.82rem"},
        ))
    content.append(html.Div(summaries, className="mb-2"))

    for d in ds_details:
        warning = d["details"].get("ambiguity_warning")
        if not warning:
            continue
        prefix = f"{d['label']}: " if comparison else ""
        content.append(html.Small(
            f"⚠ {prefix}{warning}",
            className="text-warning d-block mb-2",
            style={"fontSize": "0.78rem"},
        ))

    if all(d["details"].get("not_applicable") for d in ds_details):
        return panel_card(content)

    content.append(dcc.Graph(
        figure=charts.reachability_donut(ds_details),
        config={"displayModeBar": False},
    ))

    fig_reason = charts.failure_reason_chart(ds_details)
    if fig_reason is not None:
        content += [
            html.P("Unreachable URIs by reason",
                   className="text-muted mb-1 mt-2",
                   style={"fontSize": "0.78rem"}),
            dcc.Graph(figure=fig_reason, config={"displayModeBar": False}),
        ]
    else:
        content.append(html.P(
            "All checked URIs are reachable. ✓",
            className="text-success mb-0 mt-2",
            style={"fontSize": "0.85rem"},
        ))

    for d in ds_details:
        samples = d["details"].get("samples", [])
        if not samples:
            continue
        prefix = f"{d['label']} — " if comparison else ""
        content += [
            html.P(f"{prefix}Sample unreachable URIs (showing up to 10)",
                   className="text-muted mt-2 mb-1",
                   style={"fontSize": "0.78rem"}),
            _samples_table(samples[:10]),
        ]

    return panel_card(content)


def _export_section(ds_details: list[dict]) -> html.Div:
    """
    Export section with one download button per dataset for the full
    unreachable-URI list.

    Button ids encode both dataset_id and category as
    {"type": "btn-connectivity-export", "index": "<dataset_id>|<category>"}
    so the callback can route each click to the correct endpoint.
    """
    has_any = any(d.get("exports_available") for d in ds_details)
    if not has_any:
        return html.Div()

    content = [
        section_label("Export"),
        html.P(
            "Download the complete list of unreachable URIs as CSV.",
            className="text-muted mb-2",
            style={"fontSize": "0.82rem"},
        ),
    ]

    for d in ds_details:
        dataset_id        = d.get("dataset_id", "")
        label             = d.get("label", dataset_id)
        exports_available = d.get("exports_available") or []
        if not exports_available:
            continue

        row_content = [
            dbc.Button(
                "Unreachable URIs",
                id={"type": "btn-connectivity-export",
                    "index": f"{dataset_id}|{cat}"},
                color="outline-secondary",
                size="sm",
                className="me-2 mb-1",
            )
            for cat in exports_available
        ]

        content.append(html.Div([
            html.Span(
                label,
                className="text-muted fw-semibold me-2",
                style={"fontSize": "0.78rem"},
            ),
            html.Div(row_content,
                     style={"display": "inline-flex", "flexWrap": "wrap",
                            "alignItems": "center"}),
        ], className="mb-2"))

    content.append(dcc.Download(id="download-connectivity-csv"))
    return panel_card(content)


# ── Helpers ───────────────────────────────────────────────────────────────

def _samples_table(samples: list[dict]) -> dbc.Table:
    """
    Render a compact table of sample unreachable URIs.

    Parameters
    ----------
    samples : list[dict]
        Each dict has keys: uri, classification, status_code.
    """
    columns = ["uri", "classification", "status_code"]

    def _cell(v) -> html.Td:
        """Render one table cell, truncating long values."""
        s = str(v) if v is not None else "—"
        if len(s) > 60:
            s = s[:57] + "…"
        return html.Td(
            s,
            style={"fontSize": "0.75rem", "wordBreak": "break-all",
                   "maxWidth": "320px"},
        )

    header = html.Thead(html.Tr([
        html.Th(c.replace("_", " ").title(),
                style={"fontSize": "0.75rem", "whiteSpace": "nowrap"})
        for c in columns
    ]))
    body = html.Tbody([
        html.Tr([_cell(row.get(c)) for c in columns])
        for row in samples
    ])
    return dbc.Table(
        [header, body],
        bordered=True,
        hover=True,
        size="sm",
        className="mb-0",
        style={"tableLayout": "fixed"},
    )
