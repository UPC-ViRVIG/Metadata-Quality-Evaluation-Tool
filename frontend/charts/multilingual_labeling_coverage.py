import plotly.graph_objects as go
from charts.palette import COLORS, base_layout

# Density interpretation region boundaries
_REGIONS = [
    (0.00, 0.01, "#e9ecef", "No presence (0%)"),
    (0.01, 0.25, "#F55B6E", "Sparse (1–25%)"),
    (0.25, 0.75, "#F5A05B", "Partial (25–75%)"),
    (0.75, 1.00, "#5B6EF5", "Dominant (75–100%)"),
]


# ════════════════════════════════════════════════════════════════════════════
# General information
# ════════════════════════════════════════════════════════════════════════════
def general_info_chart(ds_details: list[dict]) -> go.Figure:
    """
    Two grouped bar charts in a 1×2 subplot layout:
      Left:  Language tags per resource (0 tags / 1 tag / 2+ tags)
      Right: Literal tagging status (tagged vs untagged)
    """
    from plotly.subplots import make_subplots

    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=["Language tags per resource", "Literal tagging"],
        horizontal_spacing=0.12,
    )

    tag_labels = ["No tags", "Monolingual (1 tag)", "Multilingual (2+ tags)"]
    tag_keys   = ["0", "1", "2+"]

    for i, d in enumerate(ds_details):
        color   = COLORS[i % len(COLORS)]
        label   = d["label"]
        gi      = d["details"].get("general_info", {})
        dist    = gi.get("resource_language_distribution", {})
        tagged  = gi.get("tagged_literal_count", 0)
        untagged = gi.get("untagged_literal_count", 0)

        tag_counts = [dist.get(k, 0) for k in tag_keys]
        total_resources = sum(tag_counts) or 1

        fig.add_bar(
            row=1, col=1,
            name=label,
            legendgroup=label,
            x=tag_labels,
            y=tag_counts,
            marker_color=color,
            text=[f"{round(c/total_resources*100,1)}%" for c in tag_counts],
            textposition="outside",
            hovertemplate="%{x}<br>%{y:,} resources<extra></extra>",
            showlegend=(i == 0 or len(ds_details) > 1),
        )

        total_lit = tagged + untagged or 1
        fig.add_bar(
            row=1, col=2,
            name=label,
            legendgroup=label,
            x=["Tagged", "Untagged"],
            y=[tagged, untagged],
            marker_color=color,
            text=[f"{round(tagged/total_lit*100,1)}%",
                  f"{round(untagged/total_lit*100,1)}%"],
            textposition="outside",
            hovertemplate="%{x}<br>%{y:,} literals<extra></extra>",
            showlegend=False,
        )

    fig.update_layout(
        **base_layout(
            height=320,
            margin=dict(l=8, r=8, t=40, b=8),
            barmode="group",
        ),
        showlegend=len(ds_details) > 1,
        legend=dict(orientation="h", yanchor="bottom", y=1.08,
                    xanchor="right", x=1),
    )
    fig.update_yaxes(title_text="Resources", row=1, col=1,
                     gridcolor="rgba(0,0,0,0.05)")
    fig.update_yaxes(title_text="Literals", row=1, col=2,
                     gridcolor="rgba(0,0,0,0.05)")
    return fig


# ════════════════════════════════════════════════════════════════════════════
# Language distribution
# ════════════════════════════════════════════════════════════════════════════
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
        margin=dict(l=8, r=48, t=8, b=8),
        barmode="group",
        xaxis=dict(title="Resources with ≥1 literal in language",
                   gridcolor="rgba(0,0,0,0.05)"),
        yaxis=dict(
            automargin=True,
            categoryorder="array",
            categoryarray=list(reversed(all_langs)),
        ),
        showlegend=len(ds_details) > 1,
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
    ))
    return fig


# ════════════════════════════════════════════════════════════════════════════
# Class × language heatmap
# ════════════════════════════════════════════════════════════════════════════
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
    d        = ds_details[dataset_index]
    heatmap  = d["details"].get("heatmap", {})
    languages = heatmap.get("languages", [])
    classes  = heatmap.get("classes", [])

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
        textfont=dict(size=10),
        colorbar=dict(
            tickformat=".0%",
            thickness=12,
            title=dict(text="Coverage", side="right"),
        ) if show_colorbar else None,
        showscale=show_colorbar,
        xgap=2,
        ygap=2,
    ))

    fig.update_layout(base_layout(
        height=max(280, len(classes) * 36 + 80),
        margin=dict(l=8, r=80, t=8, b=8),
        xaxis=dict(side="top", tickangle=-30),
        yaxis=dict(automargin=True),
    ))
    return fig


# ════════════════════════════════════════════════════════════════════════════
# Density drilldown
# ════════════════════════════════════════════════════════════════════════════
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

    Returns None if no density data is found for the class + language.
    """
    traces = []
    for i, d in enumerate(ds_details):
        classes = d["details"].get("heatmap", {}).get("classes", [])
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

    n      = len(traces)
    fig    = go.Figure()

    for row_idx, t in enumerate(traces):
        yc = float(row_idx)

        fig.add_violin(
            x=t["densities"],
            y=[yc] * len(t["densities"]),
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
            hoverinfo="none",         # suppress kde/q1/q3 default tooltip
            showlegend=True,
        )

        bucket_size = 0.05
        n_buckets   = int(1 / bucket_size)
        bucket_counts = [0] * (n_buckets + 1)
        for v in t["densities"]:
            idx = min(int(v / bucket_size), n_buckets)
            bucket_counts[idx] += 1

        hover_x, hover_y, hover_text = [], [], []
        for b, count in enumerate(bucket_counts):
            if count == 0:
                continue
            mid = b * bucket_size + bucket_size / 2
            hover_x.append(min(mid, 1.0))
            hover_y.append(yc)
            pct_lo = f"{round(b * bucket_size * 100)}%"
            pct_hi = f"{round((b + 1) * bucket_size * 100)}%"
            hover_text.append(
                f"<b>{t['label']}</b><br>"
                f"Density range: {pct_lo}–{pct_hi}<br>"
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

    region_annotations = [
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

    fig.update_layout(base_layout(
        height=max(200, n * 100 + 80),
        margin=dict(l=8, r=8, t=48, b=48),
        violinmode="overlay",
        violingap=0,
        violingroupgap=0,
        shapes=region_shapes,
        annotations=region_annotations,
        xaxis=dict(
            range=[-0.02, 1.02],
            tickformat=".0%",
            title="Density (literals in language / all literals in resource)",
            gridcolor="rgba(0,0,0,0.05)",
        ),
        yaxis=dict(
            tickmode="array",
            tickvals=list(range(n)),
            ticktext=[t["label"] for t in traces],
            automargin=True,
            range=[-0.5, n - 0.2],
            gridcolor="rgba(0,0,0,0.04)",
        ),
        showlegend=False,   # dataset names shown on y-axis instead
    ))
    return fig