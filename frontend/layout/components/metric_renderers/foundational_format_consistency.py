from dash import html, dcc
import dash_bootstrap_components as dbc

import charts.foundational_format_consistency as charts
from layout.components.common import panel_card, section_label, score_badge
from layout.components.detail_views_helpers import (
    collect_ds_details,
    analysis_header,
    comparison_header,
)

METRIC_ID = "foundational_format_consistency"

# Tooltip text for each sub-score card
_SUB_SCORE_TOOLTIPS = {
    "uri_validity": (
        "Checks that every URI in the dataset has a valid scheme, "
        "contains no illegal characters, and has no empty fragments. "
        "A score of 100% means all URIs are well-formed."
    ),
    "datatype_correctness": (
        "Checks that literal values are compatible with their declared "
        "XSD datatype — for example, that a date field actually contains "
        "a valid date, not free text. "
        "A score of 100% means no mismatched literals were found."
    ),
    "language_tag_format": (
        "Checks that language tags on text literals conform to BCP 47 "
        "— the international standard for language codes. "
        "'en' and 'fr-BE' are valid; 'english' and 'ENG' are not."
    ),
    "structural_issues": (
        "Checks for blank node subjects (resources without a URI), "
        "empty "
        "string literals. Lower counts mean fewer structural problems."
    ),
}

_SUB_SCORE_LABELS = {
    "uri_validity":         "URI Validity",
    "datatype_correctness": "Datatype Correctness",
    "language_tag_format":  "Language Tag Format",
    "structural_issues":    "Structural Issues",
}


def render(metric: dict, datasets: list[dict]) -> html.Div:
    ds_details = collect_ds_details(datasets, METRIC_ID)
    if not ds_details:
        return html.Div()

    # Enrich ds_details with dataset_id, label, and exports_available
    # so _export_section can build the correct download requests
    for i, (ds, detail) in enumerate(zip(datasets, ds_details)):
        detail["dataset_id"]       = ds.get("dataset_id", "")
        detail["label"]            = ds.get("label", f"Dataset {i+1}")
        # exports_available lives on the metric result, not in details
        m = next(
            (x for x in ds.get("metrics", []) if x["metric_id"] == METRIC_ID),
            {},
        )
        detail["exports_available"] = m.get("exports_available") or []

    comparison = len(ds_details) > 1
    header = (
        comparison_header("Foundational & Format Consistency", ds_details,
                          metric=metric)
        if comparison else
        analysis_header("Foundational & Format Consistency",
                        ds_details[0]["score"], metric=metric)
    )

    return html.Div([
        header,
        _sub_scores_section(ds_details),
        # Detail sections rendered on demand when the user clicks a bar
        html.Div(id="ffc-drilldown-panel"),
        _export_section(ds_details),
    ])


# ── Section builders ──────────────────────────────────────────────────────

def _inv_count_for(details: dict, key: str) -> int:
    """Return the total violation count for a given concern area."""
    area = details.get(key, {})
    if key == "structural_issues":
        return (
            area.get("blank_node_subjects", {}).get("count", 0)
            + area.get("empty_literals", {}).get("count", 0)
        )
    return area.get("invalid_count", 0)


_INV_LABELS = {
    "uri_validity":         "invalid URIs",
    "datatype_correctness": "datatype violations",
    "language_tag_format":  "malformed tags",
    "structural_issues":    "structural violations",
}

_TOTAL_FIELDS = {
    "uri_validity":         "total_uri_count",
    "datatype_correctness": "total_typed_literals",
    "language_tag_format":  "total_lang_literals",
}


def _sub_scores_section(ds_details: list[dict]) -> html.Div:
    """
    Overview section showing:
    - Violation count cards per concern area with ℹ tooltips
    - Horizontal bar chart of violation counts, clickable to open drilldown
    """
    keys = [
        "uri_validity",
        "datatype_correctness",
        "language_tag_format",
        "structural_issues",
    ]

    # ── Violation count cards ─────────────────────────────────────────────
    cards = []
    for k in keys:
        tip_id = f"tip-ffc-{k}"
        # Violation counts only — "No issues detected" when count is zero
        items = []
        for d in ds_details:
            det        = d["details"]
            count      = _inv_count_for(det, k)
            prefix_txt = f"{d['label']} " if len(ds_details) > 1 else ""
            if count == 0:
                value_text = "No issues detected"
                value_color = "#2ECC71"
            else:
                value_text  = f"{count:,} {_INV_LABELS[k]}"
                value_color = "#343a40"
            items.append(html.Div([
                html.Span(prefix_txt,
                          style={"fontSize": "0.72rem", "color": "#6c757d",
                                 "whiteSpace": "nowrap"}),
                html.Span(
                    value_text,
                    style={"fontSize": "0.78rem", "color": value_color,
                           "whiteSpace": "nowrap"},
                ),
            ], style={"display": "flex", "alignItems": "center",
                      "gap": "4px", "marginBottom": "2px",
                      "whiteSpace": "nowrap"}))

        cards.append(dbc.Col([
            html.Div([
                html.Span(
                    _SUB_SCORE_LABELS[k],
                    style={"fontSize": "0.78rem", "fontWeight": "600",
                           "marginRight": "3px", "whiteSpace": "nowrap"},
                ),
                html.Span(
                    "ℹ",
                    id=tip_id,
                    style={"fontSize": "0.68rem", "color": "#adb5bd",
                           "cursor": "help", "userSelect": "none"},
                ),
                dbc.Tooltip(
                    _SUB_SCORE_TOOLTIPS[k],
                    target=tip_id,
                    placement="top",
                    style={"maxWidth": "280px"},
                ),
            ], style={"display": "flex", "alignItems": "center",
                      "marginBottom": "4px"}),
            *items,
        ], style={"flex": "1 1 0", "minWidth": "0",
                  "paddingRight": "12px"}, className="mb-2"))

    fig, use_log = charts.sub_scores_chart(ds_details)

    return panel_card([
        section_label(
            "Overview of common Foundational & Format Consistency issues"
        ),
        # Violation count cards above the chart — one per category, single row
        html.Div(
            dbc.Row(cards, className="g-0 flex-nowrap"),
            style={"overflowX": "auto"},
            className="mb-2",
        ),
        html.Small(
            "Click a bar to explore the detailed breakdown · "
            "categories with no issues are hidden",
            className="text-muted d-block mb-1",
            style={"fontSize": "0.75rem"},
        ),
        html.Small(
            "⚠ Log scale applied — violation counts differ greatly "
            "between datasets. Hover for exact values.",
            className="text-warning d-block mb-1",
            style={"fontSize": "0.75rem"},
        ) if use_log else html.Span(),
        dcc.Graph(
            id="ffc-overview-bar",
            figure=fig,
            config={"displayModeBar": False},
        ),
    ])


def _uri_validity_section(
    ds_details: list[dict],
    comparison: bool,
) -> html.Div:
    """
    URI validity drilldown: summary counts, failure reason bar chart,
    position bar chart, and a sample violations table.

    Reason and position charts use invalid_by_reason and
    invalid_by_position — both computed over the full graph in the
    backend. The sample table shows up to 10 example broken URIs.
    """
    summaries = []
    for d in ds_details:
        uv     = d["details"].get("uri_validity", {})
        total  = uv.get("total_uri_count", 0)
        inv    = uv.get("invalid_count", 0)
        prefix = f"{d['label']}: " if comparison else ""
        summaries.append(html.Span(
            f"{prefix}{inv:,} invalid / {total:,} total URIs",
            className="text-muted me-4",
            style={"fontSize": "0.82rem"},
        ))

    fig_reason   = charts.uri_reason_chart(ds_details)
    fig_position = charts.uri_position_chart(ds_details)

    content = [
        section_label("URI validity — failure causes and positions"),
        html.Div(summaries, className="mb-2"),
    ]

    if fig_reason is not None:
        content += [
            html.P("Failure reasons",
                   className="text-muted mb-1",
                   style={"fontSize": "0.78rem"}),
            dcc.Graph(figure=fig_reason, config={"displayModeBar": False}),
        ]
    if fig_position is not None:
        content += [
            html.P("Where invalid URIs occur",
                   className="text-muted mb-1 mt-2",
                   style={"fontSize": "0.78rem"}),
            dcc.Graph(figure=fig_position, config={"displayModeBar": False}),
        ]
    if fig_reason is None and fig_position is None:
        content.append(html.P("No URI violation details available.",
                              className="text-muted",
                              style={"fontSize": "0.85rem"}))

    # Sample violations table — one per dataset, columns: value, position, reason
    for d in ds_details:
        samples = (d["details"]
                   .get("uri_validity", {})
                   .get("samples", []))
        if not samples:
            continue
        prefix = f"{d['label']} — " if comparison else ""
        content += [
            html.P(f"{prefix}Sample broken URIs (showing up to 10)",
                   className="text-muted mt-2 mb-1",
                   style={"fontSize": "0.78rem"}),
            _samples_table(
                samples[:10],
                ["value", "position", "reason"],
            ),
        ]

    return panel_card(content)


def _datatype_section(
    ds_details: list[dict],
    comparison: bool,
) -> html.Div:
    """
    Datatype correctness drilldown: summary counts, two parallel bar charts
    (by datatype and by property), and a sample violations table.
    """
    summaries = []
    for d in ds_details:
        dt     = d["details"].get("datatype_correctness", {})
        total  = dt.get("total_typed_literals", 0)
        inv    = dt.get("invalid_count", 0)
        prefix = f"{d['label']}: " if comparison else ""
        summaries.append(html.Span(
            f"{prefix}{inv:,} invalid / {total:,} typed literals",
            className="text-muted me-4",
            style={"fontSize": "0.82rem"},
        ))
        # Most affected for first dataset
        if d == ds_details[0]:
            dt_list = dt.get("invalid_by_datatype", [])
            if dt_list:
                most_affected_dt = dt_list[0].get("label") or dt_list[0].get("datatype", "")
            prop_list = dt.get("invalid_by_property", [])
            if prop_list:
                most_affected_prop = prop_list[0].get("label") or prop_list[0].get("property", "")

    fig_dt, fig_prop, use_log = charts.datatype_parallel_charts(ds_details)

    content = [
        section_label("Datatype correctness"),
        html.Div(summaries, className="mb-2"),
    ]

    if use_log:
        content.append(html.Small(
            "⚠ Log scale applied — violation counts differ greatly "
            "between datasets. Hover for exact values.",
            className="text-warning d-block mb-2",
            style={"fontSize": "0.75rem"},
        ))

    if fig_dt is None and fig_prop is None:
        content.append(html.P("No datatype violations found. ✓",
                              className="text-success mb-0",
                              style={"fontSize": "0.85rem"}))
    else:
        if fig_dt is not None:
            content += [
                html.P("Invalid literals by datatype",
                       className="text-muted mb-1",
                       style={"fontSize": "0.78rem"}),
                dcc.Graph(figure=fig_dt, config={"displayModeBar": False}),
            ]
        if fig_prop is not None:
            content += [
                html.P("Invalid literals by property",
                       className="text-muted mb-1 mt-2",
                       style={"fontSize": "0.78rem"}),
                dcc.Graph(figure=fig_prop, config={"displayModeBar": False}),
            ]

    # Sample violations table — one per dataset
    for d in ds_details:
        samples = (d["details"]
                   .get("datatype_correctness", {})
                   .get("samples", []))
        if not samples:
            continue
        prefix = f"{d['label']} — " if comparison else ""
        content += [
            html.P(f"{prefix}Sample violations (showing up to 10)",
                   className="text-muted mt-2 mb-1",
                   style={"fontSize": "0.78rem"}),
            _samples_table(samples[:10], ["subject", "property", "value", "datatype"]),
        ]

    return panel_card(content)


def _language_tag_section(
    ds_details: list[dict],
    comparison: bool,
) -> html.Div:
    """Language tag validity: donut chart and list of invalid tags."""
    fig = charts.language_tag_donut(ds_details)

    summaries = []
    invalid_tag_rows = []

    for d in ds_details:
        lt     = d["details"].get("language_tag_format", {})
        total  = lt.get("total_lang_literals", 0)
        inv    = lt.get("invalid_count", 0)
        prefix = f"{d['label']}: " if comparison else ""
        summaries.append(html.Span(
            f"{prefix}{inv:,} invalid / {total:,} language-tagged literals",
            className="text-muted me-4",
            style={"fontSize": "0.82rem"},
        ))
        for tag_entry in lt.get("invalid_tags", []):
            invalid_tag_rows.append(
                html.Li(
                    f"'{tag_entry['tag']}' — {tag_entry['count']:,} occurrences"
                    + (f" ({prefix.rstrip(': ')})" if comparison else ""),
                    style={"fontSize": "0.82rem"},
                )
            )

    content = [
        section_label("Language tag format (BCP 47)"),
        html.Div(summaries, className="mb-2"),
        dcc.Graph(figure=fig, config={"displayModeBar": False}),
    ]

    if invalid_tag_rows:
        content += [
            html.P("Invalid language tags found:",
                   className="text-muted mt-2 mb-1",
                   style={"fontSize": "0.78rem"}),
            html.Ul(invalid_tag_rows, className="mb-0 ps-3"),
        ]
    else:
        content.append(html.P("All language tags are valid BCP 47. ✓",
                              className="text-success mb-0 mt-1",
                              style={"fontSize": "0.85rem"}))

    return panel_card(content)


def _structural_section(
    ds_details: list[dict],
    comparison: bool,
) -> html.Div:
    """Structural issues: blank node subjects and empty literals counts + samples."""
    fig_counts = charts.structural_issues_bar(ds_details)

    content = [
        section_label("Structural issues"),
        html.Div([
            _term_tooltip(
                "blank-node",
                "Blank node",
                "A blank node is an RDF resource without a stable URI — it has "
                "no address that other datasets can link to. Overuse makes the "
                "dataset harder to integrate and reference.",
            ),
            html.Span(" · ", style={"color": "#dee2e6", "margin": "0 4px"}),
            _term_tooltip(
                "empty-literal",
                "Empty literal",
                "An empty literal is a string property whose value is empty or "
                "contains only whitespace. These typically indicate missing data "
                "that was not properly validated before ingestion.",
            ),
        ], className="mb-2"),
        dcc.Graph(figure=fig_counts, config={"displayModeBar": False}),
    ]

    # Blank node samples
    bn_samples = (ds_details[0]["details"]
                  .get("structural_issues", {})
                  .get("blank_node_subjects", {})
                  .get("samples", []))
    if bn_samples:
        content += [
            html.P("Sample blank node subjects",
                   className="text-muted mt-2 mb-1",
                   style={"fontSize": "0.78rem"}),
            _samples_table(bn_samples[:10], ["predicate", "object"]),
        ]

    return panel_card(content)


# Human-readable labels for each export category
_EXPORT_LABELS = {
    "uri_validity":         "URI Validity violations",
    "datatype_correctness": "Datatype Correctness violations",
    "language_tag_format":  "Language Tag violations",
    "structural_issues":    "Structural Issues violations",
}


def _export_section(ds_details: list[dict]) -> html.Div:
    """
    Export section with one download button per dataset per category.

    In comparison mode each dataset gets its own labelled row of buttons
    so the user can download violations for any specific dataset and
    category independently.

    Uses exports_available from the metric result when the backend export
    cache is populated (new backend). Falls back to the legacy flat export
    list embedded in details if exports_available is not present.

    Button ids encode both dataset_id and category as
    {"type": "btn-ffc-export", "index": "<dataset_id>|<category>"}
    so the callback can route each click to the correct endpoint.
    """
    has_any = any(
        d.get("exports_available") or d["details"].get("export")
        for d in ds_details
    )
    if not has_any:
        return html.Div()

    content = [
        section_label("Export violations"),
        html.P(
            "Download violation records as CSV. "
            "One file per dataset and category.",
            className="text-muted mb-2",
            style={"fontSize": "0.82rem"},
        ),
    ]

    for d in ds_details:
        dataset_id        = d.get("dataset_id", "")
        label             = d.get("label", dataset_id)
        exports_available = d.get("exports_available") or []
        legacy_rows       = d["details"].get("export", [])

        row_content = []

        if exports_available:
            for cat in exports_available:
                btn_label = _EXPORT_LABELS.get(
                    cat, cat.replace("_", " ").title()
                )
                # Encode both dataset_id and category in the button index
                btn_index = f"{dataset_id}|{cat}"
                row_content.append(dbc.Button(
                    btn_label,
                    id={"type": "btn-ffc-export", "index": btn_index},
                    color="outline-secondary",
                    size="sm",
                    className="me-2 mb-1",
                ))
        elif legacy_rows:
            row_content.append(dbc.Button(
                f"All violations ({len(legacy_rows):,} records)",
                id={"type": "btn-ffc-export",
                    "index": f"{dataset_id}|legacy"},
                color="outline-secondary",
                size="sm",
                className="me-2 mb-1",
            ))

        if row_content:
            content.append(html.Div([
                html.Span(
                    label,
                    className="text-muted fw-semibold me-2",
                    style={"fontSize": "0.78rem"},
                ),
                html.Div(row_content,
                         style={"display": "inline-flex",
                                "flexWrap": "wrap",
                                "alignItems": "center"}),
            ], className="mb-2"))

    content.append(dcc.Download(id="download-ffc-csv"))
    return panel_card(content)


# ── Helpers ───────────────────────────────────────────────────────────────


def _term_tooltip(tip_id: str, term: str, explanation: str) -> html.Span:
    """
    Underlined term with a dbc.Tooltip explaining what it means.

    Parameters
    ----------
    tip_id : str
        Unique id for the tooltip target element.
    term : str
        Display text of the term.
    explanation : str
        Plain-language explanation shown on hover.
    """
    return html.Span([
        html.Span(
            term,
            id=tip_id,
            style={"textDecoration": "underline dotted", "cursor": "help",
                   "fontSize": "0.80rem", "color": "#6c757d"},
        ),
        dbc.Tooltip(
            explanation,
            target=tip_id,
            placement="top",
            style={"maxWidth": "280px"},
        ),
    ])


def _class_violation_table(
    ds_details: list[dict],
    area: str,
) -> html.Div:
    """
    Compact table of per-class violation rates for a given concern area.

    Green badge when rate = 0, amber/red otherwise. More intuitive than
    a heatmap for non-technical users.

    Parameters
    ----------
    ds_details : list[dict]
        Per-dataset detail dicts from collect_ds_details.
    area : str
        One of uri_validity, datatype_correctness,
        language_tag_format, structural_issues.
    """
    all_classes: list[str] = []
    for d in ds_details:
        for cls in d["details"].get(area, {}).get("class_violation_rates", {}):
            if cls not in all_classes:
                all_classes.append(cls)

    if not all_classes:
        return html.P("No class-level data available.",
                      className="text-muted", style={"fontSize": "0.85rem"})

    header_cells = [html.Th("Class", style={"fontSize": "0.75rem"})]
    for d in ds_details:
        header_cells.append(
            html.Th(d["label"] if len(ds_details) > 1 else "Violation rate",
                    style={"fontSize": "0.75rem"})
        )

    rows = []
    for cls in all_classes:
        label = cls.split("#")[-1].split("/")[-1]
        cells = [html.Td(label, style={"fontSize": "0.78rem",
                                       "fontFamily": "monospace"})]
        for d in ds_details:
            rate = d["details"].get(area, {}).get(
                "class_violation_rates", {}
            ).get(cls, 0.0)
            if rate == 0:
                badge_color, badge_text = "success", "0"
            elif rate < 0.5:
                badge_color, badge_text = "warning", f"{rate:.2f}"
            else:
                badge_color, badge_text = "danger", f"{rate:.2f}"
            cells.append(html.Td(
                dbc.Badge(badge_text, color=badge_color),
                style={"textAlign": "center"},
            ))
        rows.append(html.Tr(cells))

    return dbc.Table(
        [html.Thead(html.Tr(header_cells)), html.Tbody(rows)],
        bordered=True, hover=True, size="sm",
        className="mb-0",
        style={"fontSize": "0.78rem"},
    )


def _samples_table(samples: list[dict], columns: list[str]) -> dbc.Table:
    """
    Render a compact table of sample violation records.

    Parameters
    ----------
    samples : list[dict]
        List of violation dicts to display.
    columns : list[str]
        Keys to show as columns, in order.
    """
    def _cell(v: str) -> html.Td:
        s = str(v)
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
        html.Tr([_cell(row.get(c, "")) for c in columns])
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