from dash import html
import dash_bootstrap_components as dbc

from charts.palette import ACCENT


def card(children, className: str = "h-100", **kwargs) -> dbc.Card:
    """Standard card wrapper used in stat rows and chart panels."""
    return dbc.Card(
        dbc.CardBody(children, className="p-3"),
        className=className,
        **kwargs,
    )


# Plain-language explanations for the three RDF dataset statistics.
_STAT_TOOLTIPS = {
    "Triples":   "The total number of individual facts in the dataset. "
                 "Each triple is a subject–predicate–object statement, "
                 "e.g. 'Painting X has creator Y'.",
    "Entities":  "The number of distinct real-world things described in "
                 "the dataset, each identified by a unique URI and classified "
                 "with rdf:type.",
    "Classes":   "The number of distinct categories (rdf:type values) used "
                 "to classify entities, e.g. Artwork, Place, Agent.",
}


def stat_card(label: str, value) -> dbc.Col:
    """
    A single stat display column (Triples / Entities / Classes).
    Renders '—' when value is None.
    Includes a ℹ tooltip with a plain-language explanation.
    """
    tip_id  = f"tip-stat-{label.lower()}"
    tooltip = _STAT_TOOLTIPS.get(label)

    label_content = html.Span([
        html.Span(
            label,
            className="text-muted",
            style={"fontSize": "0.75rem", "textTransform": "uppercase",
                   "letterSpacing": "0.06em"},
        ),
        html.Span(
            " ℹ",
            id=tip_id,
            style={"fontSize": "0.70rem", "color": "#adb5bd",
                   "cursor": "help", "userSelect": "none"},
        ) if tooltip else html.Span(),
    ])

    return dbc.Col(
        card([
            html.P(label_content, className="mb-1"),
            html.H4(
                str(value) if value is not None else "—",
                className="mb-0 fw-semibold",
            ),
            dbc.Tooltip(tooltip, target=tip_id,
                        placement="bottom",
                        style={"maxWidth": "240px"}) if tooltip else html.Span(),
        ]),
        xs=6, md=3,
        className="mb-3",
    )


def panel_card(children) -> dbc.Card:
    """Card used inside the detail panel sections."""
    return dbc.Card(
        dbc.CardBody(children, className="p-3"),
        className="mb-3",
    )


def section_label(text: str) -> html.P:
    """Small uppercase muted section heading."""
    return html.P(
        text,
        className="text-muted fw-semibold mb-2",
        style={"fontSize": "0.75rem", "textTransform": "uppercase",
               "letterSpacing": "0.06em"},
    )


def score_badge(score: float) -> dbc.Badge:
    """Coloured % badge — green ≥75%, amber ≥40%, red <40%."""
    pct   = round(score * 100)
    color = "success" if pct >= 75 else "warning" if pct >= 40 else "danger"
    return dbc.Badge(f"{pct}%", color=color, className="ms-2 fs-6")