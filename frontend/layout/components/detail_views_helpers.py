"""
Shared building blocks for metric detail views: extracting per-dataset
metric data into a chart-ready shape, and rendering analysis/comparison
header rows with score badges and description tooltips.
"""

from dash import html
import dash_bootstrap_components as dbc

from charts.palette import COLORS
from layout.components.common import score_badge


def shared_class_groups(datasets: list[dict]) -> list[list[str]]:
    """
    Find the equivalent classes that hold across all given datasets.

    Two classes count as merged only if every dataset groups them
    together. A class that differs in one dataset therefore keeps its own
    row in a comparison, and a saved result from before groups were
    recorded turns merging off for that comparison.

    Parameters
    ----------
    datasets : list[dict]
        Dataset results from store-results.

    Returns
    -------
    list[list[str]]
        One list per group of two or more classes, representative first.
    """
    if not datasets:
        return []

    shared = datasets[0].get("class_groups") or []
    for ds in datasets[1:]:
        shared = [
            common
            for group in shared
            for other in (ds.get("class_groups") or [])
            if len(common := [uri for uri in group if uri in other]) > 1
        ]
    return shared


def merged_class_count(stats: dict, groups: list[list[str]]) -> int | None:
    """
    Count classes the way the charts show them, one per merged group.

    Parameters
    ----------
    stats : dict
        Graph statistics of one dataset.
    groups : list[list[str]]
        Merged groups, as returned by shared_class_groups.

    Returns
    -------
    int | None
        The class count less the merged aliases, or None when the
        dataset recorded no count.
    """
    count = stats.get("class_count")
    if count is None:
        return None
    return count - sum(len(group) - 1 for group in groups)


def equivalent_classes_notice(datasets: list[dict]) -> html.Div:
    """
    State which classes are shown as one row in the results below.

    Merging must never be silent, so this sits with the dataset summary
    and stays visible whichever metric is open. It also says that the
    equivalence holds only for the evaluated data, rather than implying
    the classes mean the same thing in general.

    Parameters
    ----------
    datasets : list[dict]
        Dataset results from store-results.

    Returns
    -------
    html.Div
        The notice, or an empty element when no classes were merged.
    """
    groups = shared_class_groups(datasets)
    if not groups:
        return html.Div()

    def _name(uri: str) -> html.Span:
        """Show a class by its short name, with the full URI on hover."""
        return html.Span(uri.split("#")[-1].split("/")[-1], title=uri)

    def _group_item(group: list[str]) -> html.Li:
        """Render one merged group as its name and the names it absorbed."""
        merged = []
        for uri in group[1:]:
            merged += [", ", _name(uri)] if merged else [_name(uri)]
        return html.Li([html.Strong(_name(group[0])), " = "] + merged)

    return dbc.Alert(
        [
            html.Strong("Equivalent classes merged. "),
            "These classes hold exactly the same resources in this data, so "
            "each group is shown as one row. This may not hold for other "
            "data.",
            html.Ul(
                [_group_item(group) for group in groups],
                className="mb-0 mt-1",
            ),
        ],
        color="info",
        className="mb-2",
        style={"fontSize": "0.85rem"},
    )


def _without_alias_rows(value, aliases: dict[str, str]):
    """
    Copy metric details without the rows of merged aliases.

    Works on the shape of the data rather than on metric names, so a new
    metric is covered without changes here. A row is removed only when
    its representative is present alongside it, so collapsing can never
    make a class disappear, and store data is never mutated.

    Parameters
    ----------
    value : any
        A metric details value, walked recursively.
    aliases : dict[str, str]
        Alias class URIs mapped to their representative.

    Returns
    -------
    any
        A copy with alias rows removed.
    """
    if isinstance(value, dict):
        return {
            key: _without_alias_rows(item, aliases)
            for key, item in value.items()
            if key not in aliases or aliases[key] not in value
        }
    if isinstance(value, list):
        present = {_row_class(row) for row in value}
        return [
            _without_alias_rows(row, aliases)
            for row in value
            if _row_class(row) not in aliases
            or aliases[_row_class(row)] not in present
        ]
    return value


def _row_class(row) -> str | None:
    """
    Return the class a list row describes, if it describes one.

    Parameters
    ----------
    row : any
        One entry of a list inside metric details.

    Returns
    -------
    str | None
        The class URI, or None for a row that is not about a class.
    """
    if isinstance(row, dict):
        return row.get("class_uri") or row.get("class")
    return None


def collect_ds_details(
    datasets: list[dict],
    metric_id: str,
) -> list[dict]:
    """
    Extracts metric data from each dataset into a flat list ready for
    chart functions.

    Returns
    -------
    list of dicts:
        {"label": str, "color": str, "details": dict, "score": float,
         "dataset_id": str, "exports_available": list of str}
    One entry per dataset that contains the requested metric_id.

    dataset_id and exports_available are carried here rather than
    re-derived by the renderers, because datasets without the metric are
    skipped: pairing this list back against datasets by position would
    attach the wrong dataset's identity whenever the metric sets differ.

    Classes that are equivalent across all datasets appear as one row
    here. This is the single point where that happens, so charts and
    renderers need no knowledge of it.
    """
    aliases = {
        alias: group[0]
        for group in shared_class_groups(datasets)
        for alias in group[1:]
    }

    result = []
    for i, ds in enumerate(datasets):
        m = next(
            (x for x in ds.get("metrics", []) if x["metric_id"] == metric_id),
            None,
        )
        if m:
            result.append({
                "label":             ds.get("label", f"Dataset {i+1}"),
                "color":             COLORS[i % len(COLORS)],
                "details":           _without_alias_rows(
                    m.get("details", {}), aliases
                ),
                "score":             m["score"],
                "dataset_id":        ds.get("dataset_id", ""),
                "exports_available": m.get("exports_available") or [],
            })
    return result


def _description_subtitle(metric: dict) -> html.Div:
    """
    Muted description line shown below the metric name in the detail panel.
    Shows the plain-language tooltip as the subtitle if available,
    with the full technical description in a ℹ tooltip on hover.
    """
    tooltip_text = metric.get("tooltip", "")
    description  = metric.get("description", "")
    if not tooltip_text and not description:
        return html.Div()

    tip_id = f"tip-detail-{metric.get('metric_id', 'metric')}"
    return html.Div([
        html.Small([
            html.Span(tooltip_text or description,
                      className="text-muted",
                      style={"fontSize": "0.82rem"}),
            html.Span(
                " ℹ",
                id=tip_id,
                style={"fontSize": "0.70rem", "color": "#adb5bd",
                       "cursor": "help", "userSelect": "none"},
            ) if description and tooltip_text else html.Span(),
        ]),
        dbc.Tooltip(
            description,
            target=tip_id,
            placement="right",
            style={"maxWidth": "320px"},
        ) if description and tooltip_text else html.Span(),
    ], className="mb-3")


def analysis_header(name: str, score: float, metric: dict | None = None) -> html.Div:
    """Header row for single-dataset view: metric name + coloured % badge
    + description subtitle below."""
    return html.Div([
        dbc.Row([
            dbc.Col(html.H6(name, className="mb-0 fw-semibold"), width="auto"),
            dbc.Col(score_badge(score), width="auto", className="ps-0"),
        ], align="center", className="mb-1"),
        _description_subtitle(metric or {}),
    ])


def comparison_header(name: str, ds_details: list[dict],
                      metric: dict | None = None) -> html.Div:
    """Header row for comparison view: metric name + one badge per dataset
    + description subtitle below."""
    badges = [
        dbc.Badge(
            f"{d['label']}: {round(d['score'] * 100)}%",
            color="secondary",
            className="ms-2",
            style={"backgroundColor": d["color"]},
        )
        for d in ds_details
    ]
    return html.Div([
        dbc.Row(
            [dbc.Col(html.H6(name, className="mb-0 fw-semibold"), width="auto")]
            + [dbc.Col(b, width="auto") for b in badges],
            align="center",
            className="mb-1 g-1",
        ),
        _description_subtitle(metric or {}),
    ])