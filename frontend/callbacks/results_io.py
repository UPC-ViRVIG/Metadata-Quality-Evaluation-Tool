"""
Saved results callbacks: exporting a run to an archive file, importing
one back, and managing which saved results take part in the view.

Archives are built and read by the backend, so this module only moves
bytes: it hands the uploaded file over as-is and offers the returned
archive as a download. Each dataset is exported on its own, so a saved
result is always one dataset and can be recombined freely later.

Imported datasets land in store-imported unselected, so an import never
changes what is on screen by itself: the user decides what takes part in
the view by ticking it, exactly as a data source only takes part in an
evaluation once ticked.

Unlike the CSV download callbacks, failures here are always reported to
the user, because an import acts on a file the user just chose and a
silent no-op would look like nothing happened.
"""

import base64

from dash import ALL, Input, Output, State, callback, ctx, html, no_update

from api_client import export_results, import_results, APIError
from layout.sidebar import build_export_item, build_saved_result_item
from store import make_imported


@callback(
    Output("store-imported",          "data",     allow_duplicate=True),
    Output("saved-results-feedback",  "children"),
    Output("upload-saved-results",    "contents", allow_duplicate=True),
    Input("upload-saved-results",     "contents"),
    State("upload-saved-results",     "filename"),
    State("store-imported",           "data"),
    prevent_initial_call=True,
)
def import_archive(contents, filename, imported):
    """
    Load a results archive file into store-imported.

    Outputs
    -------
    store-imported.data
        Saved results, keyed by the dataset id the backend assigned.
    saved-results-feedback.children
        What was imported, or why it could not be.
    upload-saved-results.contents
        Cleared so that re-selecting the same file triggers again.

    Parameters
    ----------
    contents : str | None
        Base64 data URL delivered by the upload component.
    filename : str | None
        Name of the uploaded file.
    imported : dict | None
        Saved results already loaded.

    Returns
    -------
    tuple
        Structure:

            (
                imported_store,
                feedback_message,
                upload_contents
            )

    """
    if not contents:
        return no_update, no_update, None

    try:
        archive_bytes = base64.b64decode(contents.split(",", 1)[-1])
    except (ValueError, TypeError):
        return no_update, "Could not read the uploaded file.", None

    try:
        result = import_results(archive_bytes)
    except APIError as exc:
        return no_update, exc.message, None

    updated = dict(imported or {})
    for dataset in result.get("datasets", []):
        dataset_id = dataset["dataset_id"]
        # Re-importing the same file must not silently drop the result
        # out of the view, so an existing selection is kept.
        was_selected = updated.get(dataset_id, {}).get("selected", False)
        updated[dataset_id] = make_imported(
            dataset=dataset,
            filename=filename or "archive.json",
            created_at=result.get("created_at"),
            schema_version=result.get("schema_version", 0),
            selected=was_selected,
        )

    count = len(result.get("datasets", []))
    message = (
        f"Imported {count} dataset(s) from {filename or 'archive.json'}. "
        f"Select to view."
    )

    dropped = result.get("dropped_metrics") or []
    if dropped:
        message += (
            f" {len(dropped)} metric(s) omitted — they did not complete in "
            f"the saved run."
        )

    return updated, message, None


@callback(
    Output("download-results-archive", "data"),
    Output("export-feedback",          "children"),
    Input({"type": "btn-export-dataset", "index": ALL}, "n_clicks"),
    State("store-computed",            "data"),
    State("store-sources",             "data"),
    prevent_initial_call=True,
)
def export_archive(n_clicks_list, computed, sources):
    """
    Offer one evaluated dataset as a downloadable archive.

    Only datasets from the computed run can be exported. A saved result
    re-exported would carry no fresh provenance, and the file it came
    from already exists.

    Outputs
    -------
    download-results-archive.data
        The archive file handed to the browser.
    export-feedback.children
        Why nothing could be exported, when that is the case.

    Parameters
    ----------
    n_clicks_list : list[int | None]
        Pattern-matching export button click states.
    computed : dict | None
        Latest run state.
    sources : list[dict]
        Source configurations, used to record provenance.

    Returns
    -------
    tuple
        Structure:

            (
                download_payload,
                feedback_message
            )

    """
    if not any(n for n in (n_clicks_list or []) if n):
        return no_update, no_update

    dataset_id = ctx.triggered_id["index"]
    dataset = next(
        (d for d in ((computed or {}).get("datasets") or [])
         if d.get("dataset_id") == dataset_id),
        None,
    )
    if dataset is None:
        return no_update, "That result is no longer available to export."

    try:
        filename, content = export_results([dataset], sources or [])
    except APIError as exc:
        return no_update, exc.message

    return (
        dict(
            content=content.decode("utf-8"),
            filename=filename,
            type="application/json",
        ),
        "",
    )


@callback(
    Output("export-results-list", "children"),
    Input("store-computed",       "data"),
)
def render_export_list(computed):
    """
    Render one export button per dataset in the most recent run.

    Parameters
    ----------
    computed : dict | None
        Latest run state.

    Returns
    -------
    list
        A heading and one button per dataset, empty when nothing has
        been evaluated yet.
    """
    datasets = (computed or {}).get("datasets") or []
    if not datasets:
        return []

    return [
        html.P(
            "Save Results",
            className="text-muted text-uppercase fw-semibold mt-3 mb-2",
            style={"fontSize": "0.7rem", "letterSpacing": "0.08em"},
        ),
    ] + [
        build_export_item(
            dataset.get("dataset_id", ""),
            dataset.get("label") or dataset.get("dataset_id", "Dataset"),
        )
        for dataset in datasets
    ]


@callback(
    Output("saved-results-list", "children"),
    Input("store-imported",      "data"),
)
def render_saved_results_list(imported):
    """
    Render one card per saved result.

    Parameters
    ----------
    imported : dict | None
        Saved results keyed by dataset id.

    Returns
    -------
    list
        Saved result cards, empty when nothing has been imported.
    """
    return [
        build_saved_result_item(dataset_id, entry)
        for dataset_id, entry in (imported or {}).items()
    ]


@callback(
    Output("store-imported", "data", allow_duplicate=True),
    Input({"type": "saved-result-checkbox", "index": ALL}, "value"),
    State("store-imported", "data"),
    prevent_initial_call=True,
)
def toggle_saved_result(checkbox_values, imported):
    """
    Synchronize saved result checkboxes with store-imported state.
    """
    if not imported:
        return no_update

    checked_map = {
        item["id"]["index"]: item["value"]
        for item in ctx.inputs_list[0]
    }

    updated = {}
    for dataset_id, entry in imported.items():
        e = dict(entry)
        if dataset_id in checked_map:
            e["selected"] = bool(checked_map[dataset_id])
        updated[dataset_id] = e

    return updated


@callback(
    Output("store-imported", "data", allow_duplicate=True),
    Input({"type": "btn-delete-saved", "index": ALL}, "n_clicks"),
    State("store-imported", "data"),
    prevent_initial_call=True,
)
def delete_saved_result(n_clicks_list, imported):
    """
    Remove a saved result from frontend state.

    The backend keeps the archive's export rows cached, which is
    harmless: nothing references them once the entry is gone.

    Parameters
    ----------
    n_clicks_list : list[int | None]
        Pattern-matching delete button click states.
    imported : dict | None
        Saved results keyed by dataset id.

    Returns
    -------
    dict
        Updated saved results with the selected entry removed.
    """
    if not any(n for n in (n_clicks_list or []) if n):
        return no_update

    dataset_id = ctx.triggered_id["index"]
    return {
        key: entry
        for key, entry in (imported or {}).items()
        if key != dataset_id
    }
