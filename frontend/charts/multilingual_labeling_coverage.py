import plotly.graph_objects as go
from charts.palette import COLORS, base_layout

_REGIONS = [
    (0.00, 0.25, "#F55B6E", "Sparse (0–25%)"),
    (0.25, 0.75, "#F5A05B", "Partial (25–75%)"),
    (0.75, 1.00, "#5BF58E", "Dominant (75–100%)"),
]


def general_info_chart(ds_details: list[dict]) -> go.Figure:
    """
    Two 100%-stacked bar charts in a 1×2 subplot layout.

    Left:  Language tags per resource (No tags / Monolingual / Multilingual).
    Right: Literal tagging status (Tagged / Untagged).

    Both use percentage on the y-axis so datasets of very different sizes
    can be compared directly. Absolute counts appear in hover tooltips.
    One bar per dataset per category; bars are grouped so each dataset
    sits side-by-side within each category.
    """
    from plotly.subplots import make_subplots

    tag_labels = ["No tags", "Monolingual (1 tag)", "Multilingual (2+ tags)"]
    tag_keys   = ["0", "1", "2+"]
    lit_labels = ["Tagged", "Untagged"]

    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=["Language tags per resource", "Literal tagging"],
        horizontal_spacing=0.14,
    )

    for i, d in enumerate(ds_details):
        color    = COLORS[i % len(COLORS)]
        label    = d["label"]
        gi       = d["details"].get("general_info", {})
        dist     = gi.get("resource_language_distribution", {})
        tagged   = gi.get("tagged_literal_count", 0)
        untagged = gi.get("untagged_literal_count", 0)

        tag_counts      = [dist.get(k, 0) for k in tag_keys]
        total_resources = sum(tag_counts) or 1
        tag_pcts        = [round(c / total_resources * 100, 1) for c in tag_counts]

        total_lit  = tagged + untagged or 1
        lit_counts = [tagged, untagged]
        lit_pcts   = [round(c / total_lit * 100, 1) for c in lit_counts]

        fig.add_bar(
            row=1, col=1,
            name=label,
            legendgroup=label,
            x=tag_labels,
            y=tag_pcts,
            marker_color=color,
            text=[f"{p}%" for p in tag_pcts],
            textposition="auto",
            customdata=tag_counts,
            hovertemplate=(
                "<b>%{x}</b><br>"
                f"{label}<br>"
                "%{y:.1f}% of resources<br>"
                "Count: %{customdata:,}"
                "<extra></extra>"
            ),
            showlegend=(i == 0 or len(ds_details) > 1),
        )

        fig.add_bar(
            row=1, col=2,
            name=label,
            legendgroup=label,
            x=lit_labels,
            y=lit_pcts,
            marker_color=color,
            text=[f"{p}%" for p in lit_pcts],
            textposition="auto",
            customdata=lit_counts,
            hovertemplate=(
                "<b>%{x}</b><br>"
                f"{label}<br>"
                "%{y:.1f}% of literals<br>"
                "Count: %{customdata:,}"
                "<extra></extra>"
            ),
            showlegend=False,
        )

    fig.update_layout(
        **base_layout(
            height=300,
            margin=dict(l=8, r=8, t=40, b=8),
            barmode="group",
        ),
        showlegend=len(ds_details) > 1,
        legend=dict(orientation="h", yanchor="bottom", y=1.08,
                    xanchor="right", x=1),
    )
    fig.update_yaxes(title_text="% of resources", row=1, col=1,
                     range=[0, 110], ticksuffix="%",
                     gridcolor="rgba(0,0,0,0.05)")
    fig.update_yaxes(title_text="% of literals", row=1, col=2,
                     range=[0, 110], ticksuffix="%",
                     gridcolor="rgba(0,0,0,0.05)")
    return fig


def language_distribution_chart(ds_details: list[dict]) -> go.Figure:
    """
    Horizontal bar chart: one bar per language per dataset.
    x = resource count (resources with ≥1 literal in that language).
    Sorted descending by resource count of first dataset.
    Hover shows resource count and literal count.
    """
    all_langs: list[str] = []
    for d in ds_details:
        for entry in d["details"].get("language_distribution", []):
            if entry["language"] not in all_langs:
                all_langs.append(entry["language"])

    if not all_langs:
        return go.Figure()

    fig = go.Figure()
    for i, d in enumerate(ds_details):
        dist_map = {
            e["language"]: e
            for e in d["details"].get("language_distribution", [])
        }
        rc = [dist_map.get(l, {}).get("resource_count", 0) for l in all_langs]
        lc = [dist_map.get(l, {}).get("literal_count", 0) for l in all_langs]

        fig.add_bar(
            name=d["label"],
            y=all_langs,
            x=rc,
            orientation="h",
            marker_color=COLORS[i % len(COLORS)],
            customdata=list(zip(all_langs, rc, lc)),
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "Resources: %{customdata[1]:,}<br>"
                "Literals: %{customdata[2]:,}"
                "<extra></extra>"
            ),
            text=[str(c) for c in rc],
            textposition="outside",
        )

    fig.update_layout(base_layout(
        height=max(260, len(all_langs) * 32 + 80),
        margin=dict(l=60, r=48, t=8, b=8),
        barmode="group",
        xaxis=dict(title="Resources with ≥1 literal in language",
                   gridcolor="rgba(0,0,0,0.05)"),
        yaxis=dict(
            title="Language",
            automargin=True,
            categoryorder="array",
            categoryarray=list(reversed(all_langs)),
            tickmode="array",
            tickvals=all_langs,
            ticktext=all_langs,
        ),
        showlegend=len(ds_details) > 1,
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
    ))
    return fig


def heatmap_chart(
    ds_details: list[dict],
    dataset_index: int = 0,
    show_colorbar: bool = True,
) -> go.Figure:
    """
    Heatmap: rows = classes, columns = languages, values = coverage %.
    One heatmap per dataset in comparison mode — caller selects index.

    Clicking a cell fires clickData with:
        customdata = [class_uri, language]
    """
    d         = ds_details[dataset_index]
    heatmap   = d["details"].get("heatmap", {})
    languages = heatmap.get("languages", [])
    classes   = heatmap.get("classes", [])

    if not languages or not classes:
        return go.Figure()

    class_labels = [c["class_label"] for c in classes]
    z            = []
    custom       = []

    for cls in classes:
        row   = [cls["coverage"].get(lang, 0.0) for lang in languages]
        c_row = [[cls["class_uri"], lang] for lang in languages]
        z.append(row)
        custom.append(c_row)

    fig = go.Figure(go.Heatmap(
        z=z,
        x=languages,
        y=class_labels,
        zmin=0, zmax=1,
        colorscale=[
            [0.00, "#f8f9fa"],
            [0.01, "#dee7ff"],
            [0.25, "#93a8f5"],
            [0.75, "#5B6EF5"],
            [1.00, "#3a4fd4"],
        ],
        customdata=custom,
        hovertemplate=(
            "<b>%{y}</b> · <b>%{x}</b><br>"
            "Coverage: %{z:.1%}<br>"
            "<i>Click to see density distribution</i>"
            "<extra></extra>"
        ),
        text=[[f"{round(v*100)}%" for v in row] for row in z],
        texttemplate="%{text}",
        textfont=dict(size=max(7, min(10, 80 // max(len(languages), 1)))),
        colorbar=dict(
            tickformat=".0%",
            thickness=12,
            title=dict(text="Coverage", side="right"),
        ) if show_colorbar else None,
        showscale=show_colorbar,
        xgap=2,
        ygap=2,
    ))

    max_label_len = max((len(c["class_label"]) for c in classes), default=8)
    left_margin   = max(100, max_label_len * 7)
    fig.update_layout(base_layout(
        height=max(280, len(classes) * 36 + 80),
        margin=dict(l=left_margin, r=80, t=8, b=8),
        xaxis=dict(side="top", tickangle=-30),
        yaxis=dict(
            automargin=True,
            tickmode="array",
            tickvals=class_labels,
            ticktext=class_labels,
        ),
    ))
    return fig


def density_drilldown_chart(
    ds_details: list[dict],
    class_uri: str,
    language: str,
) -> go.Figure | None:
    """
    Ridgeline density plot of per-resource density values for a
    given class + language combination.

    Density = (literals in this language) / (all literals in resource).

    Each dataset gets its own KDE row (half-violin, horizontal).
    Interpretation regions are drawn as background colour bands:
      Grey   0%        no presence
      Red    1–25%     sparse
      Amber  25–75%    partial
      Blue   75–100%   dominant

    Inside each non-trivial zone (Sparse, Partial, Dominant) a text
    annotation shows the percentage of resources per dataset that fall
    in that zone, giving a plain-language reading of the distribution
    without requiring the user to interpret the KDE shape directly.

    Parameters
    ----------
    ds_details : list[dict]
        Per-dataset detail dicts from collect_ds_details.
    class_uri : str
        URI of the class to visualise.
    language : str
        BCP-47 language tag (e.g. "en", "fr").

    Returns
    -------
    go.Figure | None
        Plotly figure, or None if no density data is found for the
        given class and language combination.
    """
    traces = []
    for i, d in enumerate(ds_details):
        classes   = d["details"].get("heatmap", {}).get("classes", [])
        cls_entry = next(
            (c for c in classes if c["class_uri"] == class_uri), None
        )
        if not cls_entry:
            continue
        densities = cls_entry.get("density_data", {}).get(language, [])
        if not densities:
            continue
        traces.append({
            "label":     d["label"],
            "color":     COLORS[i % len(COLORS)],
            "densities": densities,
        })

    if not traces:
        return None

    n   = len(traces)
    fig = go.Figure()

    for row_idx, t in enumerate(traces):
        yc = float(row_idx)

        # Clamp to [0,1] so the KDE estimator has no data outside the
        # valid range and cannot extend the curve beyond the boundaries.
        clamped = [max(0.0, min(1.0, v)) for v in t["densities"]]
        fig.add_violin(
            x=clamped,
            y=[yc] * len(clamped),
            name=t["label"],
            orientation="h",
            side="positive",
            line_color=t["color"],
            fillcolor=t["color"],
            opacity=0.70,
            width=0.85,
            meanline=dict(visible=True, color="white", width=2),
            points=False,
            scalemode="width",
            hoverinfo="none",
            showlegend=True,
            span=[-0.01, 1.01],
            spanmode="hard",
        )

        # Invisible bucket markers for plain-language hover
        bucket_size   = 0.05
        n_buckets     = int(1 / bucket_size)
        bucket_counts = [0] * (n_buckets + 1)
        for v in t["densities"]:
            v = max(0.0, min(1.0, v))
            # Skip exactly-zero values — they are covered by the dedicated
            # 0% hover marker so they should not appear in the 0–5% bucket.
            if v == 0.0:
                continue
            idx = min(int(v / bucket_size), n_buckets)
            bucket_counts[idx] += 1

        hover_x, hover_y, hover_text = [], [], []
        for b, count in enumerate(bucket_counts):
            if count == 0:
                continue
            mid    = b * bucket_size + bucket_size / 2
            pct_lo   = round(b * bucket_size * 100)
            pct_hi   = min(round((b + 1) * bucket_size * 100), 100)
            range_str = f"{pct_lo}%" if pct_lo == pct_hi else f"{pct_lo}%–{pct_hi}%"
            hover_x.append(min(mid, 1.0))
            hover_y.append(yc)
            hover_text.append(
                f"<b>{t['label']}</b><br>"
                f"Density range: {range_str}<br>"
                f"Resources: {count:,}<br>"
                f"<i>(% of text in {language.upper()})</i>"
            )

        fig.add_scatter(
            x=hover_x,
            y=hover_y,
            mode="markers",
            marker=dict(size=18, opacity=0, color=t["color"]),
            hovertemplate="%{text}<extra></extra>",
            text=hover_text,
            showlegend=False,
            name=t["label"],
        )

        # Extra hover marker at exactly 0% so users can hover the left
        # edge and see how many resources have zero presence in this language
        zero_count = sum(1 for v in t["densities"] if v < 0.01)
        if zero_count > 0:
            fig.add_scatter(
                x=[0.0],
                y=[yc],
                mode="markers",
                marker=dict(size=18, opacity=0, color=t["color"]),
                hovertemplate=(
                    f"<b>{t['label']}</b><br>"
                    f"Density: 0%<br>"
                    f"Resources with no {language.upper()} content: "
                    f"{zero_count:,}<br>"
                    f"<i>(no text in {language.upper()})</i>"
                    "<extra></extra>"
                ),
                showlegend=False,
                name=t["label"],
            )

    # Background region shapes
    region_shapes = []
    for x0, x1, color, _ in _REGIONS:
        region_shapes.append(dict(
            type="rect",
            xref="x", yref="paper",
            x0=x0, x1=x1, y0=0, y1=1,
            fillcolor=color,
            opacity=0.10,
            layer="below",
            line_width=0,
        ))

    # Region name labels at the top of each band
    region_name_annotations = [
        dict(
            x=(x0 + x1) / 2,
            y=1.02,
            xref="x", yref="paper",
            text=label.split("(")[0].strip(),
            showarrow=False,
            font=dict(size=9, color="#6c757d"),
            yanchor="bottom",
        )
        for x0, x1, _, label in _REGIONS
    ]

    # Per-zone resource count annotations — always shown for the three
    # named zones even when 0, so the user sees "0 resources" rather than
    # a blank which could be misread as missing data.
    zone_summary_defs = [
        (0.00, 0.25, "Sparse"),
        (0.25, 0.75, "Partial"),
        (0.75, 1.00, "Dominant"),
    ]

    zone_annotations = []
    for z_lo, z_hi, z_name in zone_summary_defs:
        lines = []
        # Reverse traces so annotation order matches visual top-to-bottom:
        # Plotly places row_idx=0 at the bottom and row_idx=n-1 at the top,
        # so the last dataset in traces appears highest on the y-axis.
        for t in reversed(traces):
            total   = len(t["densities"]) or 1
            hi = z_hi + 0.0001   # include exactly 1.0 in the Dominant zone
            in_zone = sum(1 for v in t["densities"] if z_lo <= v < hi)
            pct     = round(in_zone / total * 100)
            prefix  = f"{t['label']}: " if len(traces) > 1 else ""
            lines.append(f"{prefix}{in_zone:,} resources (~{pct}%)")

        zone_annotations.append(dict(
            x=(z_lo + z_hi) / 2,
            y=0.97,
            xref="x", yref="paper",
            text="<br>".join(lines),
            showarrow=False,
            font=dict(size=9, color="#495057"),
            bgcolor="rgba(255,255,255,0.85)",
            borderpad=3,
            yanchor="top",
            xanchor="center",
            align="center",
        ))

    # Mask the region left of 0% with a white rectangle so the violin
    # KDE tail (which can extend slightly below 0) is clipped visually.
    # Data is already clamped to [0,1] so the KDE never extends beyond
    # the axis boundaries — no masking rectangles needed.
    mask_shapes = region_shapes

    # White clip shapes hide the KDE tails that bleed past 0 and 1.
    # x1=0.0 (not -0.001) so the left clip butts exactly against the 0% line.
    # The right clip starts at 1.0 for the same reason.
    clip_shapes = list(mask_shapes) + [
        dict(type="rect", xref="x", yref="paper",
             x0=-0.05, x1=0.0, y0=0, y1=1,
             fillcolor="white", opacity=1, layer="above", line_width=0),
        dict(type="rect", xref="x", yref="paper",
             x0=1.0, x1=1.05, y0=0, y1=1,
             fillcolor="white", opacity=1, layer="above", line_width=0),
    ]

    fig.update_layout(base_layout(
        height=max(200, n * 110 + 80),
        margin=dict(l=8, r=8, t=48, b=48),
        violinmode="overlay",
        violingap=0,
        violingroupgap=0,
        shapes=clip_shapes,
        annotations=region_name_annotations + zone_annotations,
        xaxis=dict(
            range=[-0.05, 1.05],   # slightly extended so 100% tick shows
            tickvals=[0, 0.2, 0.4, 0.6, 0.8, 1.0],
            ticktext=["0%", "20%", "40%", "60%", "80%", "100%"],
            title="Density (literals in language / all literals in resource)",
            gridcolor="rgba(0,0,0,0.05)",
            fixedrange=True,
        ),
        yaxis=dict(
            tickmode="array",
            tickvals=list(range(n)),
            ticktext=[t["label"] for t in traces],
            automargin=True,
            range=[-0.5, n - 0.2],
            gridcolor="rgba(0,0,0,0.04)",
        ),
        showlegend=False,
    ))
    return fig