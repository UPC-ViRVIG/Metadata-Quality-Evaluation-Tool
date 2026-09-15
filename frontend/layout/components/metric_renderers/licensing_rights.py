"""
Detail view renderer for the licensing_rights metric: per-class rights
coverage, a machine-readability/vocabulary-conformance summary, the
unscored rights category distribution, sample violation tables, and
CSV export buttons for all three exportable categories.
"""

from dash import html, dcc
import dash_bootstrap_components as dbc

import charts.licensing_rights as charts
from layout.components.common import panel_card, section_label
from layout.components.detail_views_helpers import (
    collect_ds_details,
    analysis_header,
    comparison_header,
)

METRIC_ID = "licensing_rights"


def render(metric: dict, datasets: list[dict]) -> html.Div:
    """
    Render the full Licensing (Rights) detail view.

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

    # Enrich ds_details with dataset_id, label, and exports_available so
    # _export_section can build the correct download requests.
    for i, (ds, detail) in enumerate(zip(datasets, ds_details)):
        detail["dataset_id"] = ds.get("dataset_id", "")
        detail["label"]      = ds.get("label", f"Dataset {i+1}")
        m = next(
            (x for x in ds.get("metrics", []) if x["metric_id"] == METRIC_ID),
            {},
        )
        detail["exports_available"] = m.get("exports_available") or []

    comparison = len(ds_details) > 1
    header = (
        comparison_header("Licensing (Rights)", ds_details, metric=metric)
        if comparison else
        analysis_header("Licensing (Rights)", ds_details[0]["score"], metric=metric)
    )

    return html.Div([
        header,
        _coverage_section(ds_details, comparison),
        _signal_quality_section(ds_details, comparison),
        _category_section(ds_details),
        _export_section(ds_details),
    ])


# ── Section builders ──────────────────────────────────────────────────────

def _coverage_section(ds_details: list[dict], comparison: bool) -> html.Div:
    """Per-class rights coverage: summary line, bar chart, sample table."""
    content = [section_label("Rights coverage")]

    for d in ds_details:
        cov = d["details"].get("rights_coverage", {})
        total = cov.get("total_resources", 0)
        present = cov.get("resources_with_rights", 0)
        prefix = f"{d['label']}: " if comparison else ""
        content.append(html.Span(
            f"{prefix}{present:,} / {total:,} resources carry rights information",
            className="text-muted me-4 d-block mb-1",
            style={"fontSize": "0.82rem"},
        ))

    fig = charts.coverage_by_class(ds_details)
    if fig is not None:
        content.append(dcc.Graph(figure=fig, config={"displayModeBar": False}))

    for d in ds_details:
        samples = d["details"].get("rights_coverage", {}).get("samples", [])
        if not samples:
            continue
        prefix = f"{d['label']} — " if comparison else ""
        content += [
            html.P(f"{prefix}Sample resources missing rights info (showing up to 10)",
                   className="text-muted mt-2 mb-1",
                   style={"fontSize": "0.78rem"}),
            _samples_table(samples[:10], ["subject", "class"]),
        ]

    return panel_card(content)


def _signal_quality_section(ds_details: list[dict], comparison: bool) -> html.Div:
    """
    Machine-readability and vocabulary-conformance scores, plus sample
    violation tables for literal-valued and unrecognized-URI statements.
    """
    content = [
        section_label("Statement quality"),
        html.P(
            "Of the rights statements found, how many are expressed as a "
            "machine-actionable URI, and how many of those resolve to a "
            "recognized vocabulary (RightsStatements.org, Creative Commons)?",
            className="text-muted mb-2",
            style={"fontSize": "0.82rem"},
        ),
        dcc.Graph(
            figure=charts.signal_quality_bar(ds_details),
            config={"displayModeBar": False},
        ),
    ]

    for d in ds_details:
        mr_samples = d["details"].get("machine_readability", {}).get("samples", [])
        if not mr_samples:
            continue
        prefix = f"{d['label']} — " if comparison else ""
        content += [
            html.P(f"{prefix}Sample free-text (non-machine-readable) statements",
                   className="text-muted mt-2 mb-1",
                   style={"fontSize": "0.78rem"}),
            _samples_table(mr_samples[:10], ["subject", "predicate", "value"]),
        ]

    for d in ds_details:
        vc_samples = d["details"].get("vocabulary_conformance", {}).get("samples", [])
        if not vc_samples:
            continue
        prefix = f"{d['label']} — " if comparison else ""
        content += [
            html.P(f"{prefix}Sample unrecognized rights URIs",
                   className="text-muted mt-2 mb-1",
                   style={"fontSize": "0.78rem"}),
            _samples_table(vc_samples[:10], ["subject", "predicate", "value"]),
        ]

    return panel_card(content)


def _category_section(ds_details: list[dict]) -> html.Div:
    """
    Unscored rights category distribution (public domain / open /
    restricted / unevaluated), shown for context only.
    """
    fig = charts.rights_category_bar(ds_details)
    if fig is None:
        return html.Div()

    return panel_card([
        section_label("Rights category distribution"),
        html.P(
            "Informational only — not part of the score. A dataset that "
            "accurately and machine-readably documents an in-copyright "
            "statement is scored the same as one documenting an open "
            "license; this chart just shows what those statements say.",
            className="text-muted mb-2",
            style={"fontSize": "0.78rem", "fontStyle": "italic"},
        ),
        dcc.Graph(figure=fig, config={"displayModeBar": False}),
    ])


def _export_section(ds_details: list[dict]) -> html.Div:
    """
    Export section with one download button per category per dataset.

    Button ids encode dataset_id and category as
    {"type": "btn-licensing-export", "index": "<dataset_id>|<category>"}
    so the callback can route each click to the correct endpoint.
    """
    has_any = any(d.get("exports_available") for d in ds_details)
    if not has_any:
        return html.Div()

    _labels = {
        "missing_rights":          "Missing rights",
        "non_machine_readable":    "Non-machine-readable statements",
        "unrecognized_vocabulary": "Unrecognized vocabulary",
    }

    content = [
        section_label("Export"),
        html.P(
            "Download the complete violation lists as CSV.",
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
                _labels.get(cat, cat),
                id={"type": "btn-licensing-export",
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

    content.append(dcc.Download(id="download-licensing-csv"))
    return panel_card(content)


# ── Helpers ───────────────────────────────────────────────────────────────

def _samples_table(samples: list[dict], columns: list[str]) -> dbc.Table:
    """
    Render a compact table of sample rows for the given columns.

    Parameters
    ----------
    samples : list[dict]
    columns : list[str]
        Keys to display, in order.
    """
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
