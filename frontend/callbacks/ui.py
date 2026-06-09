from dash import Input, Output, State, ALL, callback, ctx, no_update, html

from layout.components.detail_views import render_detail_panel as _render_detail_panel
from layout.components.metric_renderers.property_coverage import (
    build_analysis_drilldown,
    build_comparison_drilldown,
)
from layout.components.metric_renderers.foundational_format_consistency import (
    _export_section as _ffc_export,
)
from layout.components.metric_renderers.multilingual_labeling_coverage import (
    build_density_drilldown,
)


# ── 1. Update active_metric on card click ─────────────────────────────────

@callback(
    Output("store-ui", "data", allow_duplicate=True),
    Input({"type": "metric-card", "index": ALL}, "n_clicks"),
    State("store-ui", "data"),
    prevent_initial_call=True,
)
def update_active_metric(n_clicks_list, ui_state):
    if not any(n for n in (n_clicks_list or []) if n):
        return no_update
    triggered_id = ctx.triggered_id
    if not isinstance(triggered_id, dict):
        return no_update
    clicked = triggered_id["index"]
    current = (ui_state or {}).get("active_metric")
    return {
        **(ui_state or {}),
        "active_metric": None if clicked == current else clicked,
        "active_class":  None,
    }


# ── 2. Update card border accents ─────────────────────────────────────────
#
# Only re-renders when active_metric changes. Changes to active_class or
# prop_view must NOT trigger this — they would recreate the detail panel
# and wipe the drilldown.

@callback(
    Output({"type": "metric-card", "index": ALL}, "style"),
    Input("store-ui", "data"),
    State({"type": "metric-card", "index": ALL}, "id"),
    State({"type": "metric-card", "index": ALL}, "style"),
    prevent_initial_call=True,
)
def update_card_styles(ui_state, card_ids, current_styles):
    active = (ui_state or {}).get("active_metric")
    new_styles, changed = [], False
    for i, cid in enumerate(card_ids or []):
        is_active = cid["index"] == active
        new_style = {
            "cursor":     "pointer",
            "borderLeft": "3px solid #5B6EF5" if is_active else "1px solid #dee2e6",
            "transition": "border 0.15s",
        }
        new_styles.append(new_style)
        old = (current_styles or [])[i] if i < len(current_styles or []) else {}
        if old.get("borderLeft") != new_style["borderLeft"]:
            changed = True
    return new_styles if changed else [no_update] * len(card_ids or [])


# ── 3. Render the detail panel ────────────────────────────────────────────
#
# Only fires when active_metric changes, NOT on active_class / prop_view.
# Those are handled by render_property_drilldown (callback 6) which writes
# to a nested div, not the full panel.

@callback(
    Output("detail-panel", "children"),
    Input("store-ui",      "data"),
    Input("store-results", "data"),
    State("store-ui",      "data"),   # previous value via triggered check
    prevent_initial_call=True,
)
def render_detail_panel_callback(ui_state, results, _ui_state_prev):
    if not results or results.get("status") == "error":
        return no_update

    # Only re-render the full detail panel when active_metric triggered this.
    # If store-ui changed due to active_class or prop_view, skip — those are
    # handled by the drilldown callback below.
    triggered = ctx.triggered_id
    if triggered == "store-ui":
        # Check if active_metric actually changed vs previous render
        # We can't get the previous value easily, so instead we check:
        # if active_class or prop_view is set, the metric panel is already
        # rendered and we should not wipe it.
        active_class = (ui_state or {}).get("active_class")
        # Only skip if we're in property_coverage and class is selected
        # or a non-default prop_view — otherwise always re-render
        active_metric = (ui_state or {}).get("active_metric")
        if (active_metric == "property_coverage"
                and active_class is not None):
            return no_update
        # Allow re-render when multilingual heatmap is clicked
        # (multilingual_click changed but active_metric didn't)
        if active_metric == "multilingual_labeling_coverage":
            pass   # always re-render to update drilldown

    active_metric_id = (ui_state or {}).get("active_metric")
    return _render_detail_panel(active_metric_id, results, ui_state=ui_state)


# ── 4. Update active_class on chart click ─────────────────────────────────

@callback(
    Output("store-ui", "data", allow_duplicate=True),
    Input("property-class-chart", "clickData"),
    State("store-ui", "data"),
    prevent_initial_call=True,
)
def update_active_class(click_data, ui_state):
    if not click_data:
        return no_update
    try:
        raw = click_data["points"][0]["customdata"]
        class_uri = raw[0] if isinstance(raw, (list, tuple)) else raw
    except (KeyError, IndexError, TypeError):
        return no_update
    current = (ui_state or {}).get("active_class")
    return {
        **(ui_state or {}),
        "active_class": None if class_uri == current else class_uri,
    }


# ── 5. Render property drilldown ──────────────────────────────────────────

@callback(
    Output("property-drilldown-panel", "children"),
    Input("store-ui",      "data"),
    Input("store-results", "data"),
    prevent_initial_call=True,
)
def render_property_drilldown(ui_state, results):
    if (ui_state or {}).get("active_metric") != "property_coverage":
        return no_update
    active_class = (ui_state or {}).get("active_class")
    comparison   = (results or {}).get("mode") == "comparison"

    if comparison:
        return build_comparison_drilldown(active_class, results or {})
    else:
        return build_analysis_drilldown(active_class, results or {})


# ── 7. Multilingual heatmap click → store in store-ui ─────────────────────
#
# We store the click in store-ui rather than writing directly to
# multilingual-drilldown-panel, because that div is dynamic (only exists
# after a multilingual metric is selected) and Dash suppresses Outputs
# targeting non-existent elements at startup.
# render_detail_panel_callback picks up the store-ui change and re-renders
# the full detail panel including the drilldown.

@callback(
    Output("store-ui", "data", allow_duplicate=True),
    Input({"type": "multilingual-heatmap", "index": ALL}, "clickData"),
    State("store-ui", "data"),
    prevent_initial_call=True,
)
def update_multilingual_click(click_multi, ui_state):
    click_data = next(
        (cd for cd in (click_multi or []) if cd is not None),
        None,
    )
    if not click_data:
        return no_update
    return {**(ui_state or {}), "multilingual_click": click_data}


# ── 8. Foundational Format Consistency — CSV export ────────────────────────

@callback(
    Output("download-ffc-csv", "data"),
    Input({"type": "btn-ffc-export", "index": ALL}, "n_clicks"),
    State("store-results", "data"),
    prevent_initial_call=True,
)
def download_ffc_csv(n_clicks_list, results):
    """
    Handles CSV export for the foundational_format_consistency metric.

    Two modes depending on which button fired:

    Per-category mode (new backend):
        Calls GET /export/{dataset_id}/{metric_id}/{category} and
        streams the CSV directly from the backend export cache.

    Legacy mode (old backend without export cache):
        Builds the CSV client-side from the details.export list
        embedded in the evaluation results.
    """
    if not results or not any(n for n in (n_clicks_list or []) if n):
        return no_update

    # Identify which button fired and its category index
    triggered = ctx.triggered_id
    if not triggered or not isinstance(triggered, dict):
        return no_update

    category = triggered.get("index", "legacy")

    from layout.components.detail_views_helpers import collect_ds_details
    from api_client import get_export_csv, APIError

    datasets   = results.get("datasets", [])
    ds_details = collect_ds_details(datasets, "foundational_format_consistency")
    if not ds_details:
        return no_update

    # Button index is "<dataset_id>|<category>" or "<dataset_id>|legacy"
    if "|" not in category:
        return no_update

    dataset_id, cat = category.split("|", 1)

    if cat == "legacy":
        # Old backend — build CSV client-side from embedded export list.
        # Find the matching dataset by dataset_id.
        target_ds = next(
            (ds for ds in datasets if ds.get("dataset_id") == dataset_id),
            None,
        )
        if not target_ds:
            return no_update
        target_detail = next(
            (x for x in target_ds.get("metrics", [])
             if x["metric_id"] == "foundational_format_consistency"),
            {},
        )
        export_rows = target_detail.get("details", {}).get("export", [])
        if not export_rows:
            return no_update
        import io, csv as _csv
        buf = io.StringIO()
        writer = _csv.DictWriter(
            buf,
            fieldnames=["subject", "property", "value", "issue_type", "detail"],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(export_rows)
        label = target_ds.get("label", dataset_id)
        return dict(
            content  = buf.getvalue(),
            filename = f"ffc_{label}_violations_all.csv",
            type     = "text/csv",
        )

    # New backend — fetch from export cache endpoint
    if not dataset_id:
        return no_update

    # Find dataset label for filename
    label = next(
        (ds.get("label", dataset_id)
         for ds in datasets if ds.get("dataset_id") == dataset_id),
        dataset_id,
    )

    try:
        csv_bytes = get_export_csv(
            dataset_id,
            "foundational_format_consistency",
            cat,
        )
    except APIError:
        return no_update

    return dict(
        content  = csv_bytes.decode("utf-8"),
        filename = f"ffc_{label}_{cat}_violations.csv",
        type     = "text/csv",
    )


# ── 9. FFC overview bar click → drilldown section ──────────────────────────

@callback(
    Output("ffc-drilldown-panel", "children"),
    Input("ffc-overview-bar",     "clickData"),
    State("store-results",        "data"),
    prevent_initial_call=True,
)
def render_ffc_drilldown(click_data, results):
    """
    Fires when the user clicks a bar in the FFC overview chart.
    Maps the clicked y-label to the corresponding detail section and
    renders it inside ffc-drilldown-panel.
    """
    if not click_data or not results:
        return no_update

    try:
        label = click_data["points"][0]["y"]
    except (KeyError, IndexError, TypeError):
        return no_update

    from layout.components.detail_views_helpers import collect_ds_details
    from layout.components.metric_renderers.foundational_format_consistency import (
        _uri_validity_section,
        _datatype_section,
        _language_tag_section,
        _structural_section,
    )

    datasets   = results.get("datasets", [])
    ds_details = collect_ds_details(datasets, "foundational_format_consistency")
    if not ds_details:
        return no_update

    # Enrich with dataset_id and label (needed by export section)
    for i, (ds, detail) in enumerate(zip(datasets, ds_details)):
        detail["dataset_id"] = ds.get("dataset_id", "")
        detail["label"]      = ds.get("label", f"Dataset {i+1}")

    comparison = len(ds_details) > 1

    label_to_section = {
        "URI Validity":         lambda: _uri_validity_section(ds_details, comparison),
        "Datatype Correctness": lambda: _datatype_section(ds_details, comparison),
        "Language Tag Format":  lambda: _language_tag_section(ds_details, comparison),
        "Structural Issues":    lambda: _structural_section(ds_details, comparison),
    }

    builder = label_to_section.get(label)
    if builder is None:
        return no_update

    return html.Div([
        html.Hr(className="mt-2 mb-3"),
        builder(),
    ])


# ── Structural Completeness — class bar click → violin drilldown ────────────

@callback(
    Output("sc-class-drilldown", "children"),
    Input("sc-class-bar",        "clickData"),
    State("store-results",       "data"),
    prevent_initial_call=True,
)
def render_sc_class_drilldown(click_data, results):
    """
    Fires when the user clicks a bar in the class completeness bar chart.
    Renders a violin distribution for the clicked class below the bar chart.
    """
    if not click_data or not results:
        return no_update

    try:
        class_label = click_data["points"][0]["y"]
    except (KeyError, IndexError, TypeError):
        return no_update

    from layout.components.detail_views_helpers import collect_ds_details
    from layout.components.metric_renderers.structural_completeness import (
        render_class_drilldown,
    )

    datasets   = results.get("datasets", [])
    ds_details = collect_ds_details(datasets, "structural_completeness")
    if not ds_details:
        return no_update

    return render_class_drilldown(class_label, ds_details)