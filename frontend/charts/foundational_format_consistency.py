import plotly.graph_objects as go
from charts.palette import COLORS, base_layout


def _short(uri: str) -> str:
    """Return the fragment or last path segment of a URI."""
    return uri.split("#")[-1].split("/")[-1]


def _class_label(uri: str) -> str:
    """Return a short display label for a class URI."""
    return _short(uri)


def sub_scores_chart(ds_details: list[dict]) -> go.Figure:
    """
    Horizontal bar chart of violation counts for each concern area.

    x = number of invalid items, y = concern area label (fixed order).
    Bars are colour-coded green / amber / red by score threshold.
    Hover shows affected resources out of total and the score.

    Parameters
    ----------
    ds_details : list[dict]
        Per-dataset detail dicts from collect_ds_details.

    Returns
    -------
    go.Figure
    """
    labels = [
        "URI Validity",
        "Datatype Correctness",
        "Language Tag Format",
        "Structural Issues",
    ]
    keys = [
        "uri_validity",
        "datatype_correctness",
        "language_tag_format",
        "structural_issues",
    ]

    # Violation count accessors per area
    def _inv_count(details: dict, key: str) -> int:
        area = details.get(key, {})
        if key == "structural_issues":
            return (
                area.get("blank_node_subjects", {}).get("count", 0)
                + area.get("empty_literals", {}).get("count", 0)
            )
        return area.get("invalid_count", 0)

    def _total(details: dict, key: str) -> int:
        area = details.get(key, {})
        mapping = {
            "uri_validity":         "total_uri_count",
            "datatype_correctness": "total_typed_literals",
            "language_tag_format":  "total_lang_literals",
            "structural_issues":    None,
        }
        field = mapping.get(key)
        return area.get(field, 0) if field else 0

    comparison = len(ds_details) > 1

    # Detect large scale difference: use log scale when max/min ratio > 50
    # and there are at least two datasets with non-zero active counts
    all_active_counts = []
    for d in ds_details:
        det = d["details"]
        for k in keys:
            c = _inv_count(det, k)
            if c > 0:
                all_active_counts.append(c)
    use_log = (
        comparison
        and len(all_active_counts) >= 2
        and max(all_active_counts) / min(all_active_counts) > 50
    )

    fig = go.Figure()
    for i, d in enumerate(ds_details):
        det    = d["details"]
        scores = det.get("scores", {})
        counts = [_inv_count(det, k) for k in keys]
        totals = [_total(det, k) for k in keys]

        hover = []
        for k, count, total in zip(keys, counts, totals):
            score_pct = round(scores.get(k, 0) * 100)
            if total > 0:
                tip = (
                    f"{count:,} violations out of {total:,} items<br>"
                    f"Score: {score_pct}%"
                )
            else:
                tip = f"{count:,} violations · Score: {score_pct}%"
            hover.append(tip)

        # Analysis: single blue bar. Comparison: per-dataset colour.
        bar_color = "#5B6EF5" if not comparison else COLORS[i % len(COLORS)]

        fig.add_bar(
            name=d["label"],
            x=counts,
            y=labels,
            orientation="h",
            marker_color=bar_color,
            customdata=hover,
            hovertemplate="<b>%{y}</b><br>%{customdata}<extra></extra>",
            showlegend=comparison,
        )

    # Filter to only categories that have violations in at least one dataset
    active_indices = [
        j for j, k in enumerate(keys)
        if any(_inv_count(d["details"], k) > 0 for d in ds_details)
    ]
    active_labels = [labels[j] for j in active_indices]

    # Reverse so Plotly renders top-to-bottom in the declared order
    active_labels_reversed = list(reversed(active_labels))

    xaxis_cfg = dict(
        title="Number of violations (log scale)" if use_log
              else "Number of violations",
        gridcolor="rgba(0,0,0,0.05)",
        type="log" if use_log else "linear",
    )

    fig.update_layout(base_layout(
        height=max(120, len(active_labels) * 48 + 60),
        margin=dict(l=160, r=16, t=48, b=8),
        barmode="group",
        xaxis=xaxis_cfg,
        yaxis=dict(
            automargin=True,
            categoryorder="array",
            categoryarray=active_labels_reversed,
            tickmode="array",
            tickvals=active_labels,
            ticktext=active_labels,
        ),
        showlegend=comparison,
        legend=dict(
            orientation="h",
            yanchor="bottom", y=1.02,
            xanchor="right", x=1,
        ),
    ))

    # Remove zero-count traces by filtering each bar's data
    for trace in fig.data:
        new_x, new_y, new_cd = [], [], []
        for x_val, y_val, cd_val in zip(trace.x, trace.y, trace.customdata):
            if y_val in active_labels:
                new_x.append(x_val)
                new_y.append(y_val)
                new_cd.append(cd_val)
        trace.x = new_x
        trace.y = new_y
        trace.customdata = new_cd

    return fig, use_log


def uri_reason_chart(ds_details: list[dict]) -> go.Figure | None:
    """
    Horizontal bar chart of invalid URI counts by failure reason.

    Uses invalid_by_reason from the backend, which is computed over
    the full graph (not just samples).

    Parameters
    ----------
    ds_details : list[dict]
        Per-dataset detail dicts from collect_ds_details.

    Returns
    -------
    go.Figure | None
        None if no URI violations exist.
    """
    all_reasons: list[str] = []
    reason_data: list[dict] = []

    for d in ds_details:
        by_reason = {
            e["reason"]: e["count"]
            for e in d["details"].get("uri_validity", {}).get(
                "invalid_by_reason", []
            )
        }
        reason_data.append(by_reason)
        for r in by_reason:
            if r not in all_reasons:
                all_reasons.append(r)

    if not all_reasons:
        return None

    # Sort reasons by total count descending
    all_reasons.sort(
        key=lambda r: sum(rd.get(r, 0) for rd in reason_data),
        reverse=True,
    )

    comparison = len(ds_details) > 1
    fig = go.Figure()
    for i, (d, by_reason) in enumerate(zip(ds_details, reason_data)):
        vals = [by_reason.get(r, 0) for r in all_reasons]
        fig.add_bar(
            name=d["label"],
            y=all_reasons,
            x=vals,
            orientation="h",
            marker_color=COLORS[i % len(COLORS)] if comparison else "#5B6EF5",
            text=[str(v) if v > 0 else "" for v in vals],
            textposition="outside",
            hovertemplate="<b>%{y}</b><br>Count: %{x:,}<extra></extra>",
            showlegend=comparison,
        )

    fig.update_layout(base_layout(
        height=max(160, len(all_reasons) * 40 + 80),
        margin=dict(l=200, r=48, t=8, b=8),
        barmode="group",
        xaxis=dict(title="Invalid URI count",
                   gridcolor="rgba(0,0,0,0.05)"),
        yaxis=dict(
            automargin=True,
            tickmode="array",
            tickvals=all_reasons,
            ticktext=all_reasons,
        ),
        showlegend=comparison,
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
    ))
    return fig


def uri_position_chart(ds_details: list[dict]) -> go.Figure | None:
    """
    Horizontal bar chart showing where invalid URIs occur:
    subject, predicate, or object position.

    Uses invalid_by_position from the backend, which is computed over
    the full graph (not just samples).

    Parameters
    ----------
    ds_details : list[dict]
        Per-dataset detail dicts from collect_ds_details.

    Returns
    -------
    go.Figure | None
        None if no URI violations exist.
    """
    position_order = ["Subject URIs", "Predicate URIs", "Object URIs"]
    pos_key_map    = {
        "subject":   "Subject URIs",
        "predicate": "Predicate URIs",
        "object":    "Object URIs",
    }

    has_data  = False
    comparison = len(ds_details) > 1
    fig = go.Figure()

    for i, d in enumerate(ds_details):
        by_pos = {
            pos_key_map.get(e["position"], e["position"]): e["count"]
            for e in d["details"].get("uri_validity", {}).get(
                "invalid_by_position", []
            )
        }
        vals = [by_pos.get(p, 0) for p in position_order]
        if any(vals):
            has_data = True
        fig.add_bar(
            name=d["label"],
            y=position_order,
            x=vals,
            orientation="h",
            marker_color=COLORS[i % len(COLORS)] if comparison else "#5B6EF5",
            text=[str(v) if v > 0 else "" for v in vals],
            textposition="outside",
            hovertemplate="<b>%{y}</b><br>Count: %{x:,}<extra></extra>",
            showlegend=comparison,
        )

    if not has_data:
        return None

    fig.update_layout(base_layout(
        height=180,
        margin=dict(l=120, r=48, t=8, b=8),
        barmode="group",
        xaxis=dict(title="Invalid URI count",
                   gridcolor="rgba(0,0,0,0.05)"),
        yaxis=dict(
            automargin=True,
            tickmode="array",
            tickvals=position_order,
            ticktext=position_order,
        ),
        showlegend=comparison,
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
    ))
    return fig


def datatype_parallel_charts(
    ds_details: list[dict],
) -> tuple[go.Figure | None, go.Figure | None, bool]:
    """
    Two horizontal bar charts for the datatype correctness section:
    one by datatype label and one by property label.

    In comparison mode bars are stacked (one per dataset) rather than
    grouped side-by-side. This avoids width constraints — each category
    row is a single stacked bar whose segments are coloured by dataset.
    Hover shows the per-dataset count for each segment. No text labels
    on bars; all values are in hover.

    In analysis mode a single bar per category is shown in blue.

    Log scale is applied on both charts when the max/min violation count
    ratio across datasets exceeds 10.

    Parameters
    ----------
    ds_details : list[dict]
        Per-dataset detail dicts from collect_ds_details.

    Returns
    -------
    tuple[go.Figure | None, go.Figure | None, bool]
        (fig_by_datatype, fig_by_property, use_log).
    """
    comparison = len(ds_details) > 1

    # Collect all non-zero counts to detect large scale differences
    all_counts = []
    for d in ds_details:
        for area_key in ("invalid_by_datatype", "invalid_by_property"):
            for e in d["details"].get("datatype_correctness", {}).get(area_key, []):
                if e["count"] > 0:
                    all_counts.append(e["count"])

    # Lower threshold (10x) — even modest differences hide small bars
    use_log = (
        comparison
        and len(all_counts) >= 2
        and max(all_counts) / min(all_counts) > 10
    )
    xtype  = "log" if use_log else "linear"
    xtitle = "Invalid literal count (log scale)" if use_log else "Invalid literal count"

    # Stack mode in comparison, overlay single bar in analysis

    # ── By datatype ───────────────────────────────────────────────────────
    all_dt: list[str] = []
    for d in ds_details:
        for e in d["details"].get("datatype_correctness", {}).get(
            "invalid_by_datatype", []
        ):
            lbl = e.get("label") or _short(e["datatype"])
            if lbl not in all_dt:
                all_dt.append(lbl)

    fig_dt = None
    if all_dt:
        fig_dt = go.Figure()
        for i, d in enumerate(ds_details):
            by_dt = {
                (e.get("label") or _short(e["datatype"])): e["count"]
                for e in d["details"].get("datatype_correctness", {}).get(
                    "invalid_by_datatype", []
                )
            }
            counts = [by_dt.get(lbl, 0) for lbl in all_dt]
            fig_dt.add_bar(
                name=d["label"],
                y=all_dt,
                x=counts,
                orientation="h",
                marker_color=COLORS[i % len(COLORS)] if comparison else "#5B6EF5",
                text=[f"{c:,}" if c > 0 else "" for c in counts],
                textposition="outside",
                hovertemplate="<b>%{y}</b><br>Invalid literals: %{x:,}<extra></extra>",
                showlegend=comparison,
            )
        fig_dt.update_layout(base_layout(
            height=max(160, len(all_dt) * 40 + 80),
            margin=dict(l=100, r=80, t=48, b=8),
            barmode="group",
            xaxis=dict(title=xtitle, gridcolor="rgba(0,0,0,0.05)",
                       type=xtype),
            yaxis=dict(
                automargin=True,
                tickmode="array",
                tickvals=all_dt,
                ticktext=all_dt,
            ),
            showlegend=comparison,
            legend=dict(orientation="v", yanchor="middle", y=0.5,
                        xanchor="left", x=1.02),
        ))

    # ── By property ───────────────────────────────────────────────────────
    all_prop: list[str] = []
    for d in ds_details:
        for e in d["details"].get("datatype_correctness", {}).get(
            "invalid_by_property", []
        ):
            lbl = e.get("label") or _short(e["property"])
            if lbl not in all_prop:
                all_prop.append(lbl)

    fig_prop = None
    if all_prop:
        fig_prop = go.Figure()
        for i, d in enumerate(ds_details):
            by_prop = {
                (e.get("label") or _short(e["property"])): e["count"]
                for e in d["details"].get("datatype_correctness", {}).get(
                    "invalid_by_property", []
                )
            }
            counts = [by_prop.get(lbl, 0) for lbl in all_prop]
            fig_prop.add_bar(
                name=d["label"],
                y=all_prop,
                x=counts,
                orientation="h",
                marker_color=COLORS[i % len(COLORS)] if comparison else "#5B6EF5",
                text=[f"{c:,}" if c > 0 else "" for c in counts],
                textposition="outside",
                hovertemplate="<b>%{y}</b><br>Invalid literals: %{x:,}<extra></extra>",
                showlegend=False,
            )
        fig_prop.update_layout(base_layout(
            height=max(160, len(all_prop) * 40 + 80),
            margin=dict(l=120, r=80, t=8, b=8),
            barmode="group",
            xaxis=dict(title=xtitle, gridcolor="rgba(0,0,0,0.05)",
                       type=xtype),
            yaxis=dict(
                automargin=True,
                tickmode="array",
                tickvals=all_prop,
                ticktext=all_prop,
            ),
            showlegend=False,
        ))

    return fig_dt, fig_prop, use_log


def class_violation_heatmap(
    ds_details: list[dict],
    area: str,
) -> go.Figure | None:
    """
    Heatmap matrix of per-class violation rates for a concern area.

    Rows    = RDF classes, sorted by maximum violation rate descending
              so anomalies appear at the top.
    Columns = one per dataset.
    Colour  = white (0) to red (high rate). Any deviation from white
              signals a problem instantly.

    Parameters
    ----------
    ds_details : list[dict]
        Per-dataset detail dicts from collect_ds_details.
    area : str
        One of uri_validity, datatype_correctness,
        language_tag_format, structural_issues.

    Returns
    -------
    go.Figure | None
        None if no class violation data is available for any dataset.
    """
    all_classes: list[str] = []
    for d in ds_details:
        for cls in d["details"].get(area, {}).get("class_violation_rates", {}):
            if cls not in all_classes:
                all_classes.append(cls)

    if not all_classes:
        return None

    ds_labels = [d["label"] for d in ds_details]

    rates: dict[str, list[float]] = {}
    for cls in all_classes:
        row = []
        for d in ds_details:
            r = d["details"].get(area, {}).get(
                "class_violation_rates", {}
            ).get(cls, 0.0)
            row.append(r)
        rates[cls] = row

    # Sort rows by max violation rate descending so anomalies appear first
    all_classes = sorted(
        all_classes,
        key=lambda c: max(rates[c]),
        reverse=True,
    )

    class_labels = [_class_label(c) for c in all_classes]
    z            = [rates[c] for c in all_classes]
    # Cap at 1.0 for colour scale — rates can exceed 1.0 (duplicate counts)
    z_capped     = [[min(v, 1.0) for v in row] for row in z]

    hover = []
    for cls, row in zip(all_classes, z):
        hover_row = []
        for d, rate in zip(ds_details, row):
            if rate == 0:
                tip = "No violations detected"
            elif rate > 1.0:
                tip = (
                    f"Rate: {rate:.4f} (>{100:.0f}%)<br>"
                    "Rate exceeds 100% — this class has more violations<br>"
                    "than instances, indicating repeated violations<br>"
                    "on the same resource."
                )
            else:
                tip = (
                    f"Violation rate: {rate:.4f}<br>"
                    f"{rate * 100:.2f}% of instances in this class"
                )
            hover_row.append(
                f"<b>{_class_label(cls)}</b><br>"
                f"Dataset: {d['label']}<br>"
                f"{tip}"
            )
        hover.append(hover_row)

    colorscale = [
        [0.000, "#2ECC71"],
        [0.250, "#A8E6A3"],
        [0.500, "#F5A05B"],
        [0.750, "#F58B5B"],
        [1.000, "#F55B6E"],
    ]

    fig = go.Figure(go.Heatmap(
        z=z_capped,
        x=ds_labels,
        y=class_labels,
        zmin=0,
        zmax=1,
        colorscale=colorscale,
        hovertext=hover,
        hovertemplate="%{hovertext}<extra></extra>",
        text=[
            [
                f"{rates[cls][j] * 100:.1f}%" if rates[cls][j] > 0 else ""
                for j in range(len(ds_details))
            ]
            for cls in all_classes
        ],
        texttemplate="%{text}",
        textfont=dict(size=10, color="black"),
        colorbar=dict(
            tickformat=".0%",
            thickness=14,
            title=dict(text="Rate", side="right"),
            tickvals=[0, 0.25, 0.5, 0.75, 1.0],
            ticktext=["0%", "25%", "50%", "75%", ">=100%"],
        ),
        xgap=3,
        ygap=3,
    ))

    fig.update_layout(base_layout(
        height=max(260, len(all_classes) * 30 + 100),
        margin=dict(l=8, r=90, t=24, b=8),
        xaxis=dict(side="top", tickangle=0),
        yaxis=dict(automargin=True),
    ))
    return fig


def datatype_bar(ds_details: list[dict]) -> go.Figure | None:
    """
    Horizontal bar chart of invalid counts by datatype.

    Analysis mode: single horizontal bar per datatype.
    Comparison mode: grouped bars.

    Parameters
    ----------
    ds_details : list[dict]
        Per-dataset detail dicts from collect_ds_details.

    Returns
    -------
    go.Figure | None
        None if no invalid datatype entries exist.
    """
    all_datatypes: list[str] = []
    for d in ds_details:
        for entry in d["details"].get("datatype_correctness", {}).get(
            "invalid_by_datatype", []
        ):
            lbl = entry.get("label") or _short(entry["datatype"])
            if lbl not in all_datatypes:
                all_datatypes.append(lbl)

    if not all_datatypes:
        return None

    fig = go.Figure()
    for i, d in enumerate(ds_details):
        by_dt = {
            (e.get("label") or _short(e["datatype"])): e["count"]
            for e in d["details"].get("datatype_correctness", {}).get(
                "invalid_by_datatype", []
            )
        }
        counts = [by_dt.get(lbl, 0) for lbl in all_datatypes]
        fig.add_bar(
            name=d["label"],
            y=all_datatypes,
            x=counts,
            orientation="h",
            marker_color=COLORS[i % len(COLORS)],
            text=[str(c) if c > 0 else "" for c in counts],
            textposition="outside",
            hovertemplate="<b>%{y}</b><br>Invalid literals: %{x:,}<extra></extra>",
        )

    fig.update_layout(base_layout(
        height=max(180, len(all_datatypes) * 36 + 80),
        margin=dict(l=8, r=48, t=8, b=8),
        barmode="group",
        xaxis=dict(
            title="Invalid literal count",
            gridcolor="rgba(0,0,0,0.05)",
        ),
        yaxis=dict(automargin=True),
        showlegend=len(ds_details) > 1,
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
    ))
    return fig


def language_tag_donut(ds_details: list[dict]) -> go.Figure:
    """
    Donut chart showing valid vs invalid language-tagged literals.

    One donut per dataset, arranged in a row using subplots.
    One add_pie call per dataset with all slices bundled together —
    this is the only correct way to build a donut with make_subplots.

    Both "Valid tags" and "Invalid tags" always appear in the legend.
    When a category has zero count its slice is omitted from the donut
    (to avoid a "0%" label) but a dummy scatter trace registers it in
    the legend so both entries are always visible.

    Parameters
    ----------
    ds_details : list[dict]
        Per-dataset detail dicts from collect_ds_details.

    Returns
    -------
    go.Figure
    """
    from plotly.subplots import make_subplots

    n          = len(ds_details)
    top_margin = 56 if n > 1 else 16
    fig = make_subplots(
        rows=1, cols=n,
        specs=[[{"type": "pie"}] * n],
        subplot_titles=[d["label"] for d in ds_details] if n > 1 else [],
    )

    all_labels = ["Valid tags", "Invalid tags"]
    all_colors = {"Valid tags": "#2ECC71", "Invalid tags": "#F55B6E"}

    for i, d in enumerate(ds_details):
        lt    = d["details"].get("language_tag_format", {})
        total = lt.get("total_lang_literals", 0)
        inv   = lt.get("invalid_count", 0)
        valid = max(0, total - inv)

        if total == 0:
            values  = [1]
            labels  = ["No data"]
            colors  = ["#dee2e6"]
        else:
            # Only include non-zero slices to avoid "0%" labels
            values, labels, colors = [], [], []
            if valid > 0:
                values.append(valid)
                labels.append("Valid tags")
                colors.append(all_colors["Valid tags"])
            if inv > 0:
                values.append(inv)
                labels.append("Invalid tags")
                colors.append(all_colors["Invalid tags"])

        fig.add_pie(
            row=1, col=i + 1,
            values=values,
            labels=labels,
            marker_colors=colors,
            hole=0.55,
            textinfo="percent",
            hovertemplate=(
                "<b>%{label}</b><br>"
                "Count: %{value:,}<br>"
                "Share: %{percent}<extra></extra>"
            ),
            showlegend=False,   # legend handled by dummy traces below
        )

    # Dummy scatter traces — one per legend category — so both "Valid tags"
    # and "Invalid tags" always appear in the legend. Axes are hidden via
    # update_xaxes/update_yaxes after layout is applied.
    for label in all_labels:
        fig.add_scatter(
            x=[None], y=[None],
            mode="markers",
            marker=dict(color=all_colors[label], size=10, symbol="square"),
            name=label,
            showlegend=True,
        )

    # Hide all axes — make_subplots generates numbered xaxis2, xaxis3 etc.
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)

    fig.update_layout(base_layout(
        height=260,
        margin=dict(l=8, r=100, t=top_margin, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=-0.15,
                    xanchor="center", x=0.5),
    ))
    return fig


def structural_issues_bar(ds_details: list[dict]) -> go.Figure:
    """
    Grouped horizontal bar chart showing structural issue counts.

    Two categories: blank node subjects and empty literals.
    Hover for blank nodes includes total URI count as a proxy for
    total named resources, giving context like "6,368 out of 57,100".

    Parameters
    ----------
    ds_details : list[dict]
        Per-dataset detail dicts from collect_ds_details.

    Returns
    -------
    go.Figure
    """
    categories = ["Blank node subjects", "Empty literals"]
    keys       = ["blank_node_subjects", "empty_literals"]
    comparison = len(ds_details) > 1

    fig = go.Figure()
    for i, d in enumerate(ds_details):
        si     = d["details"].get("structural_issues", {})
        counts = [si.get(k, {}).get("count", 0) for k in keys]
        # Use total_uri_count as a proxy for total graph resources
        total_uris = d["details"].get("uri_validity", {}).get("total_uri_count", 0)

        hover = []
        for k, cat, count in zip(keys, categories, counts):
            if k == "blank_node_subjects" and total_uris > 0:
                tip = (
                    f"<b>{cat}</b><br>"
                    f"{count:,} out of {total_uris:,} URI positions<br>"
                    f"({round(count / total_uris * 100, 1)}% of all URI positions)"
                )
            else:
                tip = f"<b>{cat}</b><br>Count: {count:,}"
            hover.append(tip)

        fig.add_bar(
            name=d["label"],
            y=categories,
            x=counts,
            orientation="h",
            marker_color=COLORS[i % len(COLORS)] if comparison else "#5B6EF5",
            text=[f"{c:,}" if c > 0 else "0" for c in counts],
            textposition="outside",
            customdata=hover,
            hovertemplate="%{customdata}<extra></extra>",
        )

    fig.update_layout(base_layout(
        height=max(140, len(categories) * 48 + 60),
        margin=dict(l=160, r=80, t=48, b=8),
        barmode="group",
        xaxis=dict(
            title="Issue count",
            gridcolor="rgba(0,0,0,0.05)",
        ),
        yaxis=dict(
            automargin=True,
            tickmode="array",
            tickvals=categories,
            ticktext=categories,
        ),
        showlegend=comparison,
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="left", x=0),
    ))
    return fig


def duplicate_property_bar(ds_details: list[dict]) -> go.Figure | None:
    """
    Horizontal bar chart of duplicate counts by property, top 10.

    Parameters
    ----------
    ds_details : list[dict]
        Per-dataset detail dicts from collect_ds_details.

    Returns
    -------
    go.Figure | None
        None if no duplicate entries exist across any dataset.
    """
    all_props: list[str] = []
    for d in ds_details:
        for entry in (
            d["details"]
            .get("structural_issues", {})
            .get("duplicate_values", {})
            .get("by_property", [])[:10]
        ):
            lbl = entry.get("label") or _short(entry["property"])
            if lbl not in all_props:
                all_props.append(lbl)

    if not all_props:
        return None

    fig = go.Figure()
    for i, d in enumerate(ds_details):
        by_prop = {
            (e.get("label") or _short(e["property"])): e["count"]
            for e in d["details"]
            .get("structural_issues", {})
            .get("duplicate_values", {})
            .get("by_property", [])
        }
        counts = [by_prop.get(lbl, 0) for lbl in all_props]
        fig.add_bar(
            name=d["label"],
            y=all_props,
            x=counts,
            orientation="h",
            marker_color=COLORS[i % len(COLORS)],
            text=[f"{c:,}" if c > 0 else "" for c in counts],
            textposition="outside",
            hovertemplate="<b>%{y}</b><br>Duplicates: %{x:,}<extra></extra>",
        )

    fig.update_layout(base_layout(
        height=max(200, len(all_props) * 32 + 80),
        margin=dict(l=8, r=64, t=8, b=8),
        barmode="group",
        xaxis=dict(
            title="Duplicate value count",
            gridcolor="rgba(0,0,0,0.05)",
        ),
        yaxis=dict(
            automargin=True,
            categoryorder="array",
            categoryarray=list(reversed(all_props)),
        ),
        showlegend=len(ds_details) > 1,
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
    ))
    return fig