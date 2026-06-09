import plotly.graph_objects as go
from charts.palette import COLORS, base_layout

_BUCKETS = ["0.0","0.1","0.2","0.3","0.4","0.5",
            "0.6","0.7","0.8","0.9","1.0"]


def _bucket_label(b: str) -> str:
    if b == "1.0":
        return "100%"
    v = int(float(b) * 100)
    return f"{v}–{v+9}%"


def _short_uri(uri: str) -> str:
    return uri.split("#")[-1].split("/")[-1]


def score_distribution(
    ds_details: list[dict],
) -> go.Figure:
    """
    Grouped bar chart of per-record completeness score distribution.

    X-axis : completeness buckets (0–9%, 10–19%, … 100%)
    Y-axis : number of records (raw count, not percentage)

    Using raw counts makes the y-axis unambiguous — "200 records" is clearer
    than "24% of records" especially when comparing datasets of different sizes.
    In comparison mode the grouped bars let the user see both absolute counts
    and relative shapes side by side.
    """
    fig = go.Figure()
    labels = [_bucket_label(b) for b in _BUCKETS]

    for d in ds_details:
        raw    = d["details"].get("score_distribution", {})
        counts = [raw.get(b, 0) for b in _BUCKETS]

        fig.add_bar(
            name=d["label"],
            x=labels,
            y=counts,
            marker_color=d["color"],
            text=[str(c) if c > 0 else "" for c in counts],
            textposition="outside",
            hovertemplate="%{x}<br>%{y} records<extra></extra>",
        )

    fig.update_layout(base_layout(
        height=300,
        margin=dict(l=8, r=8, t=8, b=8),
        barmode="group",
        yaxis=dict(
            title="Number of records",
            gridcolor="rgba(0,0,0,0.05)",
        ),
        xaxis=dict(title="Record completeness score"),
        showlegend=len(ds_details) > 1,
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
    ))
    return fig


def class_completeness(
    ds_details: list[dict],
) -> go.Figure | None:
    """
    Range-box chart: one box per dataset per class.

    Each box spans min → max as a thin semi-transparent filled rectangle,
    with a solid vertical line at the mean inside it.
    When min == max == mean (all records identical) a dot is shown instead.

    Multiple datasets sharing a class are stacked vertically within the
    row using fractional y offsets. The y-axis is numeric with class names
    as tick labels so sub-row positioning works cleanly.

    Returns None if no class_statistics are present.
    """
    all_classes: list[str] = []
    for d in ds_details:
        for uri in d["details"].get("class_statistics", {}):
            if uri not in all_classes:
                all_classes.append(uri)

    if not all_classes:
        return None

    n_ds         = len(ds_details)
    n_classes    = len(all_classes)
    class_labels = [_short_uri(c) for c in all_classes]
    uri_to_row   = {uri: i for i, uri in enumerate(all_classes)}

    # Half-height of each box in y-axis units — narrower with more datasets
    box_half = 0.28 / n_ds

    # Vertical centre of each dataset within its row
    if n_ds == 1:
        centres = [0.0]
    else:
        span    = 0.55
        step    = span / (n_ds - 1)
        centres = [-span / 2 + i * step for i in range(n_ds)]

    def _hex_rgba(hex_color: str, alpha: float) -> str:
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r},{g},{b},{alpha})"

    fig = go.Figure()

    for ds_idx, d in enumerate(ds_details):
        stats  = d["details"].get("class_statistics", {})
        color  = d["color"]
        label  = d["label"]
        centre = centres[ds_idx]

        box_x, box_y   = [], []
        mean_x, mean_y = [], []
        dot_x, dot_y   = [], []
        hover_x, hover_y, hover_custom = [], [], []

        for uri in all_classes:
            if uri not in stats:
                continue
            s             = stats[uri]
            mn, mean, mx  = s["min"], s["mean"], s["max"]
            row           = uri_to_row[uri]
            yc            = row + centre
            ylo, yhi      = yc - box_half, yc + box_half

            if abs(mx - mn) < 1e-9:
                # Point value — dot only, no box
                dot_x.append(mean)
                dot_y.append(yc)
            else:
                # Filled rectangle path (clockwise, closed)
                box_x += [mn, mx, mx, mn, mn, None]
                box_y += [ylo, ylo, yhi, yhi, ylo, None]

            # Vertical mean line inside the box
            mean_x += [mean, mean, None]
            mean_y += [ylo, yhi, None]

            # Invisible wide marker for hover
            hover_x.append(mean)
            hover_y.append(yc)
            hover_custom.append((_short_uri(uri), mn, mean, mx))

        fill_color = _hex_rgba(color, 0.20)

        # Filled box
        if box_x:
            fig.add_scatter(
                x=box_x, y=box_y,
                mode="lines", fill="toself",
                fillcolor=fill_color,
                line=dict(color=color, width=1.5),
                showlegend=False, hoverinfo="none",
            )

        # Mean line
        if mean_x:
            fig.add_scatter(
                x=mean_x, y=mean_y,
                mode="lines",
                line=dict(color=color, width=2.5),
                showlegend=False, hoverinfo="none",
            )

        # Point-value dot
        if dot_x:
            fig.add_scatter(
                x=dot_x, y=dot_y,
                mode="markers",
                marker=dict(color=color, size=8, symbol="circle",
                            line=dict(color="white", width=1.5)),
                showlegend=False, hoverinfo="none",
            )

        # Legend entry + hover (invisible wide markers)
        if hover_x:
            fig.add_scatter(
                x=hover_x, y=hover_y,
                mode="markers",
                marker=dict(color=color, size=16, opacity=0),
                name=label,
                customdata=hover_custom,
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    f"{label}<br>"
                    "Mean: %{customdata[2]:.1%}<br>"
                    "Min: %{customdata[1]:.1%} · Max: %{customdata[3]:.1%}"
                    "<extra></extra>"
                ),
            )

    row_height = 60 + (n_ds - 1) * 24
    fig.update_layout(base_layout(
        height=max(180, n_classes * row_height + 80),
        margin=dict(l=8, r=48, t=8, b=8),
        xaxis=dict(range=[0, 1.05], tickformat=".0%",
                   gridcolor="rgba(0,0,0,0.05)",
                   title="Completeness"),
        yaxis=dict(
            tickmode="array",
            tickvals=list(range(n_classes)),
            ticktext=class_labels,
            automargin=True,
            range=[-0.5, n_classes - 0.5],
            gridcolor="rgba(0,0,0,0.04)",
        ),
        showlegend=n_ds > 1,
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
    ))
    return fig






def class_completeness_bar(
    ds_details: list[dict],
) -> go.Figure | None:
    """
    Horizontal bar chart of mean completeness score per class.

    Each bar represents the mean completeness of all records belonging
    to that class. In comparison mode each dataset gets its own bar
    within each class row (grouped). Classes are sorted by mean score
    ascending so the most incomplete classes appear at the top.

    This is the primary class-level view. Clicking a class in the
    dashboard opens the violin drilldown for detailed distribution.

    Parameters
    ----------
    ds_details : list[dict]
        Per-dataset detail dicts from collect_ds_details.

    Returns
    -------
    go.Figure | None
        None if no class statistics are available.
    """
    all_classes: list[str] = []
    for d in ds_details:
        for uri in d["details"].get("class_statistics", {}):
            if uri not in all_classes:
                all_classes.append(uri)

    if not all_classes:
        return None

    import statistics as _st

    comparison = len(ds_details) > 1

    # Compute mean per class per dataset
    means: dict[str, list[float | None]] = {}
    for uri in all_classes:
        row = []
        for d in ds_details:
            stats  = d["details"].get("class_statistics", {}).get(uri)
            scores = stats.get("scores", []) if stats else []
            row.append(round(_st.mean(scores) * 100, 1) if scores else None)
        means[uri] = row

    # Sort classes by max mean score ascending so worst are at top
    all_classes.sort(
        key=lambda u: max((v for v in means[u] if v is not None), default=0),
    )
    class_labels = [_short_uri(c) for c in all_classes]

    fig = go.Figure()
    for i, d in enumerate(ds_details):
        vals    = [means[uri][i] for uri in all_classes]
        display = [f"{v:.1f}%" if v is not None else "" for v in vals]
        x_vals  = [v if v is not None else 0 for v in vals]

        fig.add_bar(
            name=d["label"],
            x=x_vals,
            y=class_labels,
            orientation="h",
            marker_color=COLORS[i % len(COLORS)] if comparison else "#5B6EF5",
            hovertemplate=(
                "<b>%{y}</b><br>"
                f"{d['label']}: %{{x:.1f}}% mean completeness"
                "<extra></extra>"
            ),
            showlegend=comparison,
        )

    # Compute needed left margin from longest class label
    max_label_len = max((len(l) for l in class_labels), default=8)
    left_margin   = max(120, max_label_len * 7)

    # Place legend to the right so it never overlaps bars
    fig.update_layout(base_layout(
        height=max(200, len(all_classes) * 44 + (80 if not comparison else 80)),
        margin=dict(l=left_margin, r=24, t=8, b=8),
        barmode="group",
        xaxis=dict(
            range=[0, 105],
            tickformat=".0f",
            ticksuffix="%",
            title="Mean completeness",
            gridcolor="rgba(0,0,0,0.05)",
        ),
        yaxis=dict(
            automargin=True,
            tickmode="array",
            tickvals=class_labels,
            ticktext=class_labels,
        ),
        showlegend=comparison,
        legend=dict(
            orientation="v",
            yanchor="middle", y=0.5,
            xanchor="left",   x=1.02,
        ),
    ))
    return fig


def class_density_chart(
    ds_details: list[dict],
    class_uri: str,
) -> go.Figure | None:
    """
    Ridgeline KDE density chart of per-record completeness scores for
    a single class.

    Mirrors the multilingual density drilldown style:
    - One half-violin (KDE) row per dataset
    - Three coloured background zones: Low / Partial / High
    - Zone legend via dummy scatter traces (coloured squares), same
      pattern as the multilingual chart
    - 5% bucket invisible scatter markers for hover across the full
      distribution
    - Dedicated edge markers at 0% and 100%
    - When all scores converge at a single value, a vertical line is
      drawn instead of a near-invisible dot cluster
    - Per-zone resource counts shown as white-background annotations
    - spanmode="hard" + clamping keep the KDE within [0, 1]
    - White clip shapes hide any KDE bleed beyond 0% and 100%

    Parameters
    ----------
    ds_details : list[dict]
        Per-dataset detail dicts from collect_ds_details.
    class_uri : str
        Full URI of the class to show.

    Returns
    -------
    go.Figure | None
        None if no score data exists for the class.
    """
    import statistics as _st

    _ZONES = [
        (0.00, 0.40, "#F55B6E", "rgba(245,91,110,0.10)",  "Low (0–40%)"),
        (0.40, 0.80, "#F5A05B", "rgba(245,160,91,0.10)",  "Partial (40–80%)"),
        (0.80, 1.00, "#2ECC71", "rgba(46,204,113,0.10)",  "High (80–100%)"),
    ]

    PALETTE = ["#5B6EF5", "#F5A05B", "#5BF5A0", "#F55B6E"]
    BUCKET  = 0.05

    traces_data = []
    for ds_idx, d in enumerate(ds_details):
        stats  = d["details"].get("class_statistics", {}).get(class_uri)
        scores = stats.get("scores", []) if stats else []
        if not scores:
            continue
        traces_data.append({
            "label":  d["label"],
            "color":  PALETTE[ds_idx % len(PALETTE)],
            "scores": scores,
        })

    if not traces_data:
        return None

    fig = go.Figure()

    for row_idx, t in enumerate(traces_data):
        yc     = float(row_idx)
        scores = t["scores"]
        n      = len(scores)
        color  = t["color"]
        label  = t["label"]

        clamped = [max(0.0, min(1.0, v)) for v in scores]
        unique  = set(round(v, 4) for v in clamped)

        if len(unique) == 1:
            # All records at same value — draw a vertical line instead of
            # a near-invisible KDE spike
            val = list(unique)[0]
            # Use a scatter line trace instead of add_shape — add_shape
            # with any yref triggers Plotly to register a cartesian axis
            # which clears the background zone fill shapes.
            # Draw vertical line as a lines trace but register legend
            # entry via a separate invisible marker trace so the legend
            # icon shows a square (marker) not a line.
            fig.add_scatter(
                x=[val, val],
                y=[yc - 0.4, yc + 0.4],
                mode="lines",
                line=dict(color=color, width=3),
                name=label,
                legendgroup=label,
                showlegend=False,
                hoverinfo="none",
            )
            # Legend entry: invisible marker with square symbol
            fig.add_scatter(
                x=[val], y=[yc],
                mode="markers",
                marker=dict(color=color, size=10, symbol="square",
                            opacity=1),
                name=label,
                legendgroup=label,
                showlegend=True,
                hovertemplate=(
                    f"<b>{label}</b><br>"
                    f"All {n:,} records score: {round(val*100)}%"
                    "<extra></extra>"
                ),
            )
        else:
            fig.add_violin(
                x=clamped,
                y=[yc] * n,
                name=label,
                orientation="h",
                side="positive",
                line_color=color,
                fillcolor=color,
                opacity=0.65,
                width=0.85,
                meanline=dict(visible=True, color="white", width=2),
                points=False,
                scalemode="width",
                span=[-0.01, 1.01],
                spanmode="hard",
                hoverinfo="none",
                showlegend=True,
                legendgroup=label,
            )

            # Bucketed hover markers — 5% buckets, excluding exact edges
            n_buckets     = int(1 / BUCKET)
            bucket_counts = [0] * n_buckets
            for v in clamped:
                if v <= 0.0 or v >= 1.0:
                    continue
                idx = min(int(v / BUCKET), n_buckets - 1)
                bucket_counts[idx] += 1

            hover_x, hover_y, hover_text = [], [], []
            for b, count in enumerate(bucket_counts):
                if count == 0:
                    continue
                mid = b * BUCKET + BUCKET / 2
                lo  = round(b * BUCKET * 100)
                hi  = round((b + 1) * BUCKET * 100)
                hover_x.append(mid)
                hover_y.append(yc)
                hover_text.append(
                    f"<b>{label}</b><br>"
                    f"Completeness: {lo}%–{hi}%<br>"
                    f"Records: {count:,} ({round(count/n*100,1)}% of class)"
                )
            if hover_x:
                fig.add_scatter(
                    x=hover_x, y=hover_y,
                    mode="markers",
                    marker=dict(size=20, opacity=0, color=color),
                    hovertemplate="%{text}<extra></extra>",
                    text=hover_text,
                    showlegend=False,
                    legendgroup=label,
                    name=label,
                )

            # Edge: 0%
            zero_count = sum(1 for v in clamped if v <= 0.0)
            if zero_count > 0:
                fig.add_scatter(
                    x=[0.0], y=[yc],
                    mode="markers",
                    marker=dict(size=20, opacity=0, color=color),
                    hovertemplate=(
                        f"<b>{label}</b><br>"
                        f"Completeness: 0%<br>"
                        f"Records: {zero_count:,} ({round(zero_count/n*100,1)}%)"
                        "<extra></extra>"
                    ),
                    showlegend=False, legendgroup=label, name=label,
                )

            # Edge: 100%
            full_count = sum(1 for v in clamped if v >= 1.0)
            if full_count > 0:
                fig.add_scatter(
                    x=[1.0], y=[yc],
                    mode="markers",
                    marker=dict(size=20, opacity=0, color=color),
                    hovertemplate=(
                        f"<b>{label}</b><br>"
                        f"Completeness: 100%<br>"
                        f"Records: {full_count:,} ({round(full_count/n*100,1)}%)"
                        "<extra></extra>"
                    ),
                    showlegend=False, legendgroup=label, name=label,
                )

    # ── Background zone shapes ────────────────────────────────────────────
    shapes = [
        dict(type="rect", xref="x", yref="paper",
             x0=lo, x1=hi, y0=0, y1=1,
             fillcolor=fill, line_width=0, layer="below")
        for lo, hi, _, fill, _ in _ZONES
    ]
    # spanmode='hard' keeps KDE within [0,1]; no clip shapes needed

    # ── Zone name labels — shown above the chart via annotations ───────
    top_annotations = [
        dict(
            x=(lo + hi) / 2, y=1.04,
            xref="x", yref="paper",
            text=zone_label.split(" ")[0],
            showarrow=False,
            font=dict(size=10, color="#6c757d"),
            xanchor="center", yanchor="bottom",
        )
        for lo, hi, _, _, zone_label in _ZONES
    ]

    # ── Per-zone resource count annotations ──────────────────────────────
    # Placed at the bottom of the chart area (yref="paper", y=0.02)
    # so they never overlap the violin shapes above them.
    zone_count_annotations = []
    for lo, hi, _, _, zone_label in _ZONES:
        lines = []
        for t in traces_data:
            n_t       = len(t["scores"])
            clamped_t = [max(0.0, min(1.0, v)) for v in t["scores"]]
            in_zone   = sum(
                1 for v in clamped_t
                if (lo <= v < hi) or (hi == 1.0 and v >= 1.0)
            )
            pct    = round(in_zone / n_t * 100)
            prefix = f"{t['label']}: " if len(traces_data) > 1 else ""
            lines.append(f"{prefix}{in_zone:,} items ({pct}% of class items)")
        zone_count_annotations.append(dict(
            x=(lo + hi) / 2, y=0.02,
            xref="x", yref="paper",
            text="<br>".join(lines),
            showarrow=False,
            font=dict(size=9, color="#495057"),
            bgcolor="rgba(255,255,255,0.85)",
            borderpad=3,
            yanchor="bottom", xanchor="center", align="center",
        ))

    n_rows = len(traces_data)
    fig.update_layout(
        base_layout(
            height=max(200, n_rows * 100 + 80),
            margin=dict(l=8, r=180, t=32, b=40),
        ),
        shapes=shapes,
        annotations=top_annotations + zone_count_annotations,
        violinmode="overlay",
        violingap=0,
        xaxis=dict(
            range=[-0.05, 1.05],
            tickvals=[0, 0.2, 0.4, 0.6, 0.8, 1.0],
            ticktext=["0%", "20%", "40%", "60%", "80%", "100%"],
            title="Completeness score",
            gridcolor="rgba(0,0,0,0.05)",
        ),
        yaxis=dict(
            tickmode="array",
            tickvals=list(range(n_rows)),
            ticktext=[t["label"] for t in traces_data],
            automargin=True,
            range=[-0.55, n_rows - 0.45],
            zeroline=False,
        ),
        showlegend=True,
        # legend = dataset entries, bottom-right outside plot
        legend=dict(orientation="v", yanchor="bottom", y=0,
                    xanchor="left", x=1.02),
    )
    return fig


def class_completeness_violin(
    ds_details: list[dict],
    restrict_to: str | None = None,
) -> go.Figure | None:
    """
    Violin plot of per-record completeness scores grouped by class.

    Layout strategy:
    - Each class occupies one row on the y-axis (integer position).
    - When multiple datasets share a class, each dataset gets its own
      sub-row by offsetting the y-position by a small amount, and each
      violin is given a fixed bandwidth so the shapes are readable.
    - Single unique value → dot instead of violin.
    - Mean line shown inside each violin.
    """
    all_classes: list[str] = []
    for d in ds_details:
        for uri in d["details"].get("class_statistics", {}):
            if uri not in all_classes:
                all_classes.append(uri)

    if not all_classes:
        return None

    if restrict_to is not None:
        all_classes = [c for c in all_classes if c == restrict_to]
        if not all_classes:
            return None

    has_scores = any(
        d["details"].get("class_statistics", {}).get(uri, {}).get("scores")
        for d in ds_details for uri in all_classes
    )
    if not has_scores:
        return None

    n_ds         = len(ds_details)
    n_classes    = len(all_classes)
    class_labels = [_short_uri(c) for c in all_classes]
    uri_to_row   = {uri: i for i, uri in enumerate(all_classes)}
    PALETTE      = ["#5B6EF5", "#F5A05B", "#5BF5A0", "#F55B6E"]

    # Vertical offsets so datasets don't overlap within a row.
    # Each violin is drawn at row + offset, then the y-axis tick is placed
    # at the integer row centre.
    if n_ds == 1:
        offsets = [0.0]
    else:
        span    = 0.6 * (n_ds - 1) / n_ds
        offsets = [-span/2 + i * span/(n_ds-1) for i in range(n_ds)]

    # Violin half-bandwidth in y-axis units — shrinks with more datasets
    bandwidth = 0.28 / n_ds

    fig = go.Figure()

    for ds_idx, d in enumerate(ds_details):
        stats  = d["details"].get("class_statistics", {})
        color  = PALETTE[ds_idx % len(PALETTE)]
        label  = d["label"]
        offset = offsets[ds_idx]

        for cls_idx, uri in enumerate(all_classes):
            cls_data = stats.get(uri)
            if not cls_data:
                continue
            scores = cls_data.get("scores", [])
            if not scores:
                continue

            row = uri_to_row[uri]
            yc  = row + offset

            unique = set(round(s, 3) for s in scores)

            if len(unique) == 1:
                # Point value — dot
                fig.add_scatter(
                    x=[scores[0]],
                    y=[yc],
                    mode="markers",
                    name=label,
                    legendgroup=label,
                    showlegend=(cls_idx == 0),
                    marker=dict(color=color, size=9, symbol="circle",
                                line=dict(color="white", width=1.5)),
                    hovertemplate=(
                        f"<b>{_short_uri(uri)}</b><br>"
                        f"Dataset: {label}<br>"
                        f"Records in class: {len(scores):,}<br>"
                        f"All records score: {round(scores[0]*100)}%"
                        "<extra></extra>"
                    ),
                )
            else:
                # Build a KDE violin manually using y as the numeric position.
                # We pass y as a constant array (all = yc) so Plotly centres
                # the violin on that position.
                import statistics as _st
                n      = len(scores)
                mean   = round(_st.mean(scores) * 100, 1)
                median = round(_st.median(scores) * 100, 1)
                mn     = round(min(scores) * 100, 1)
                mx     = round(max(scores) * 100, 1)

                # Violin hovertemplate cannot suppress the default stats box,
                # so we use a transparent scatter on top as the hover target
                # and disable hover on the violin itself.
                fig.add_violin(
                    x=scores,
                    y=[yc] * len(scores),
                    name=label,
                    legendgroup=label,
                    showlegend=(cls_idx == 0),
                    orientation="h",
                    line_color=color,
                    fillcolor=color,
                    opacity=0.65,
                    width=bandwidth * 2,
                    meanline=dict(visible=True, color="white", width=2),
                    points=False,
                    scalemode="width",
                    hoverinfo="none",   # suppress default kde/q1/q3 tooltip
                )

                # Invisible wide scatter sitting on top — provides clean hover
                fig.add_scatter(
                    x=[mean / 100],   # hover target at the mean
                    y=[yc],
                    mode="markers",
                    marker=dict(size=18, opacity=0, color=color),
                    name=label,
                    legendgroup=label,
                    showlegend=False,
                    hovertemplate=(
                        f"<b>{_short_uri(uri)}</b><br>"
                        f"Dataset: {label}<br>"
                        f"Records in class: {n:,}<br>"
                        f"Mean completeness: {mean}%<br>"
                        f"Median completeness: {median}%<br>"
                        f"Best record: {mx}%<br>"
                        f"Worst record: {mn}%"
                        "<extra></extra>"
                    ),
                )

    row_height = 70 + (n_ds - 1) * 30

    fig.update_layout(base_layout(
        height=max(220, n_classes * row_height + 100),
        margin=dict(l=8, r=48, t=8, b=8),
        violinmode="overlay",
        violingap=0,
        violingroupgap=0,
        xaxis=dict(
            range=[-0.05, 1.05],
            tickformat=".0%",
            gridcolor="rgba(0,0,0,0.05)",
            title="Completeness score",
        ),
        yaxis=dict(
            tickmode="array",
            tickvals=list(range(n_classes)),
            ticktext=class_labels,
            automargin=True,
            range=[-0.55, n_classes - 0.45],
            gridcolor="rgba(0,0,0,0.04)",
            zeroline=False,
        ),
        showlegend=n_ds > 1,
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
    ))
    return fig