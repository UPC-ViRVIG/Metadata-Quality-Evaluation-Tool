import plotly.graph_objects as go
from charts.palette import COLORS, base_layout


def _short(uri: str) -> str:
    """Last fragment of a URI (after # or last /)."""
    return uri.split("#")[-1].split("/")[-1]


def _make_labels(uris: list[str]) -> list[str]:
    """
    Convert a list of URIs to display labels, disambiguating collisions.

    When two URIs share the same fragment (e.g. dc:type and edm:type both
    become "type"), we prepend a short namespace prefix so they are distinct.
    This prevents Plotly from stacking bars that share a y-category name.

    Strategy: detect duplicates AFTER shortening, then for each duplicate
    group extract a short namespace prefix from the URI and prepend it.
    """
    raw = [_short(u) for u in uris]

    # Find which short names appear more than once
    from collections import Counter
    counts = Counter(raw)
    duplicates = {name for name, n in counts.items() if n > 1}

    if not duplicates:
        return raw

    def _ns_prefix(uri: str) -> str:
        """Extract a short namespace prefix, e.g. 'dc', 'edm', 'skos'."""
        # Try common prefixes embedded in the URI path
        known = {
            "purl.org/dc/elements": "dc",
            "purl.org/dc/terms": "dcterms",
            "europeana.eu/schemas/edm": "edm",
            "openarchives.org/ore": "ore",
            "w3.org/2004/02/skos": "skos",
            "w3.org/2002/07/owl": "owl",
            "w3.org/2000/01/rdf-schema": "rdfs",
            "w3.org/1999/02/22-rdf-syntax": "rdf",
            "schema.org": "schema",
            "xmlns.com/foaf": "foaf",
            "rdvocab.info": "rdvocab",
            "ebu.ch/metadata": "ebu",
        }
        for fragment, prefix in known.items():
            if fragment in uri:
                return prefix
        # Fallback: use second-to-last path segment
        parts = uri.replace("#", "/").rstrip("/").split("/")
        return parts[-2] if len(parts) >= 2 else "?"

    labels = []
    for uri, name in zip(uris, raw):
        if name in duplicates:
            labels.append(f"{_ns_prefix(uri)}:{name}")
        else:
            labels.append(name)

    return labels


# ════════════════════════════════════════════════════════════════════════════
# Shared bubble chart (analysis and comparison)
# ════════════════════════════════════════════════════════════════════════════

def _bubble_figure(ds_details: list[dict]) -> tuple:
    """
    Core bubble chart used by both analysis and comparison.

    Returns (figure, has_scores: bool).
    Bubble: x=score, y=class (disambiguated label), size=instance count.
    Classes ordered by total count descending across all datasets.
    """
    class_totals: dict[str, int] = {}
    for d in ds_details:
        for uri, count in d["details"].get("classes_found", {}).items():
            class_totals[uri] = class_totals.get(uri, 0) + count

    all_class_uris = sorted(class_totals, key=lambda u: class_totals[u], reverse=True)
    if not all_class_uris:
        return None, False

    any_scores = any(d["details"].get("class_scores") for d in ds_details)
    if not any_scores:
        return None, False

    max_count = max(class_totals.values()) or 1
    y_labels  = _make_labels(all_class_uris)
    # Map uri → disambiguated label for lookups
    uri_to_label = dict(zip(all_class_uris, y_labels))

    fig = go.Figure()
    for d in ds_details:
        scores = d["details"].get("class_scores", {})
        counts = d["details"].get("classes_found", {})
        total  = d["details"].get("total_records", 1) or 1
        color  = d["color"]

        x_vals, y_vals, sizes, custom = [], [], [], []
        for uri in all_class_uris:
            if uri not in scores:
                continue
            count = counts.get(uri, 0)
            x_vals.append(scores[uri])
            y_vals.append(uri_to_label[uri])
            sizes.append(8 + 32 * (count / max_count))
            custom.append((
                uri, count,
                f"{round(count / total * 100, 1)}%",
                scores[uri],
            ))

        # Small vertical offset per dataset so bubbles sharing a class
        # row don't sit on top of each other in comparison mode.
        # We use numeric y (row index + offset) instead of category strings
        # so Plotly renders offset positions. Tick labels are set explicitly.
        n_ds   = len(ds_details)
        ds_idx = list(ds_details).index(d)
        if n_ds > 1:
            span   = 0.28
            offset = -span / 2 + ds_idx * span / (n_ds - 1)
        else:
            offset = 0.0

        # Map each class label to its row index (0 = bottom in reversed order)
        # y_labels is already ordered top-to-bottom; row 0 = last item displayed
        label_to_row = {lbl: i for i, lbl in enumerate(reversed(y_labels))}
        y_numeric = [label_to_row[lbl] + offset for lbl in y_vals]

        fig.add_trace(go.Scatter(
            x=x_vals,
            y=y_numeric if n_ds > 1 else y_vals,
            mode="markers",
            name=d["label"],
            marker=dict(
                color=color, size=sizes, opacity=0.75,
                line=dict(color="white", width=1),
            ),
            customdata=custom,
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                f"<b>{d['label']}</b><br>"
                "Score: %{customdata[3]:.1%}<br>"
                "Instances: %{customdata[1]:,} (%{customdata[2]} of dataset)<br>"
                "<i>Click to explore properties</i>"
                "<extra></extra>"
            ),
        ))

    n = len(all_class_uris)
    fig.update_layout(base_layout(
        height=max(300, n * 40 + 100),
        margin=dict(l=160, r=8, t=48, b=8),
        xaxis=dict(range=[-0.05, 1.1], tickformat=".0%",
                   title="Property coverage score",
                   gridcolor="rgba(0,0,0,0.05)"),
        yaxis=dict(
            automargin=True,
            tickmode="array",
            # row 0 = bottom label = last item in y_labels (top of list)
            tickvals=list(range(len(y_labels))),
            ticktext=list(reversed(y_labels)),
        ) if len(ds_details) > 1 else dict(
            automargin=True,
            categoryorder="array",
            categoryarray=list(reversed(y_labels)),
            tickmode="array",
            tickvals=y_labels,
            ticktext=y_labels,
        ),
        showlegend=len(ds_details) > 1,
        legend=dict(orientation="h", yanchor="bottom", y=1.04,
                    xanchor="right", x=1),
        annotations=[dict(
            text="Bubble size = instance count",
            xref="paper", yref="paper",
            x=0, y=1.07, showarrow=False,
            font=dict(size=11, color="#6c757d"),
        )],
    ))
    return fig, True


# ════════════════════════════════════════════════════════════════════════════
# Analysis
# ════════════════════════════════════════════════════════════════════════════

def analysis_bubble(ds_details: list[dict]) -> tuple:
    """Bubble chart for single-dataset analysis. Returns (fig, has_scores)."""
    return _bubble_figure(ds_details)


def analysis_property_drilldown(
    ds_details: list[dict],
    class_uri: str,
) -> go.Figure | None:
    """
    Stacked horizontal bar: present (blue) + missing (red) record counts.
    Sorted by missing count descending so worst properties appear first.

    Fill rate % is shown as a text label at the end of each full bar
    so the user gets both the absolute count and the relative rate at once,
    without needing a toggle.

    Duplicate short property names within a class are disambiguated using
    namespace prefixes.
    """
    d          = ds_details[0]
    fill_rates = (
        d["details"]
        .get("class_property_fill_rates", {})
        .get(class_uri, {})
    )
    if not fill_rates:
        return None

    props = list(fill_rates.keys())
    props.sort(key=lambda p: fill_rates[p].get("missing", 0), reverse=True)

    labels       = _make_labels(props)
    present_vals = [fill_rates[p].get("present", 0) for p in props]
    missing_vals = [fill_rates[p].get("missing", 0) for p in props]
    fill_pcts    = [
        f"{round(fill_rates[p].get('fill_rate', 0) * 100, 1)}%"
        for p in props
    ]
    custom = [(p, fill_rates[p].get("present", 0),
               fill_rates[p].get("missing", 0),
               fill_rates[p].get("fill_rate", 0)) for p in props]

    fig = go.Figure()

    # Present bars — no text, hover only
    fig.add_bar(
        name="Present",
        x=present_vals, y=labels,
        orientation="h",
        marker_color="#5B6EF5",
        customdata=custom,
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "Present: %{customdata[1]:,}<br>"
            "Missing: %{customdata[2]:,}<br>"
            "Fill rate: %{customdata[3]:.1%}"
            "<extra></extra>"
        ),
    )

    # Missing bars — show fill rate % text at the end of the full stacked bar
    fig.add_bar(
        name="Missing",
        x=missing_vals, y=labels,
        orientation="h",
        marker_color="#F55B6E",
        customdata=custom,
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "Present: %{customdata[1]:,}<br>"
            "Missing: %{customdata[2]:,}<br>"
            "Fill rate: %{customdata[3]:.1%}"
            "<extra></extra>"
        ),
        text=fill_pcts,
        textposition="outside",
        textfont=dict(size=10, color="#495057"),
        cliponaxis=False,
    )

    fig.update_layout(base_layout(
        height=max(300, len(props) * 28 + 80),
        margin=dict(l=8, r=48, t=8, b=8),
        barmode="stack",
        xaxis=dict(title="Record count", gridcolor="rgba(0,0,0,0.05)"),
        yaxis=dict(
            automargin=True,
            categoryorder="array",
            categoryarray=list(reversed(labels)),  # missing desc = worst at top
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
    ))
    return fig


# ════════════════════════════════════════════════════════════════════════════
# Comparison
# ════════════════════════════════════════════════════════════════════════════

def comparison_bubble(ds_details: list[dict]) -> tuple:
    """Bubble chart for comparison mode. Returns (fig, has_scores)."""
    return _bubble_figure(ds_details)


def comparison_property_drilldown(
    ds_details: list[dict],
    class_uri: str,
) -> go.Figure | None:
    """
    Grouped horizontal bar of fill rates per property for one class.
    One trace per dataset; sorted by mean fill rate ascending (worst first).
    Duplicate short property names disambiguated with namespace prefixes.
    """
    all_props: list[str] = []
    for d in ds_details:
        for p in (d["details"]
                  .get("class_property_fill_rates", {})
                  .get(class_uri, {})):
            if p not in all_props:
                all_props.append(p)

    if not all_props:
        return None

    def _mean_rate(prop: str) -> float:
        rates = [
            d["details"]
            .get("class_property_fill_rates", {})
            .get(class_uri, {})
            .get(prop, {})
            .get("fill_rate", None)
            for d in ds_details
        ]
        valid = [r for r in rates if r is not None]
        return sum(valid) / len(valid) if valid else 0.0

    all_props.sort(key=_mean_rate)
    labels = _make_labels(all_props)

    fig = go.Figure()
    for d in ds_details:
        fr_map = (d["details"]
                  .get("class_property_fill_rates", {})
                  .get(class_uri, {}))

        rates  = [fr_map.get(p, {}).get("fill_rate", None) for p in all_props]
        custom = [
            f"{p}\n"
            + (f"present: {fr_map[p].get('present',0):,} | "
               f"missing: {fr_map[p].get('missing',0):,}"
               if p in fr_map else "(not in this dataset)")
            for p in all_props
        ]

        fig.add_bar(
            name=d["label"],
            y=labels,
            x=[r if r is not None else 0 for r in rates],
            orientation="h",
            marker_color=d["color"],
            opacity=0.9,
            customdata=custom,
            hovertemplate="%{customdata}<br>Fill rate: %{x:.1%}<extra></extra>",
            text=[f"{round(r*100, 1)}%" if r is not None else "—" for r in rates],
            textposition="outside",
        )

    fig.update_layout(base_layout(
        height=max(300, len(all_props) * (44 if len(ds_details) > 1 else 28) + 80),
        margin=dict(l=8, r=48, t=8, b=8),
        barmode="group",
        xaxis=dict(range=[0, 1.18], tickformat=".0%",
                   gridcolor="rgba(0,0,0,0.05)", title="Fill rate"),
        yaxis=dict(
            automargin=True,
            categoryorder="array",
            categoryarray=list(reversed(labels)),
        ),
        showlegend=len(ds_details) > 1,
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
    ))
    return fig