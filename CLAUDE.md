# ECHOES Metadata Quality Evaluation Tool

A visualization-driven metadata quality evaluation tool for digital cultural heritage Linked Data, built as part of the ECHOES European cultural heritage initiative. This is also the subject of a master's thesis: "A Visualization Tool for Metadata Quality Evaluation in Digital Cultural Heritage."

Two independently runnable applications communicate over HTTP:

- **backend/** — FastAPI, does all evaluation logic
- **frontend/** — Plotly Dash, interactive dashboard
- A **CLI** (`backend/cli/cli.py`) provides a server-free entry point into the same evaluation pipeline for scripted/reproducible workflows.

## Technology Stack

**Backend:** Python, FastAPI (API layer, Pydantic request/response validation), Uvicorn (ASGI server), RDFLib (RDF parsing/serialization/SPARQL), pySHACL (SHACL validation), SPARQLWrapper (remote SPARQL endpoints), PyYAML (CLI config files).

**Frontend:** Plotly Dash, Dash Bootstrap Components (DBC).

## Project Structure

```
backend/
    api/                     FastAPI endpoints and request handling
        evaluation_controller     the API layer implementation
    cli/                     Command-line interface (cli.py)
    config/                  Metric configuration (metrics_config.json)
    datasource/              Data source abstraction (Strategy + Factory)
    engine/                  Evaluation Engine orchestration (evaluation_engine.py)
    graph/                   Ontology extraction, graph caching, scope filtering
        graph_cache.py            thread-safe singleton graph cache
        ontology_extractor.py     class/property hierarchy extraction
    export/                  Metric-specific export infrastructure (CSV) +
                             result_archive.py (archive format, API+CLI shared)
    metrics/                 Plugin interface + metric implementations
        metric_plugin.py          shared plugin interface
        metric_registry.py        identifier -> plugin class registry
        plugins/                  one file per metric (see below)
    models/                  Request, response, and internal (Pydantic) models
    results_aggregator/      Weighted score aggregation (aggregator.py)
frontend/
    app.py                   Dash entry point + top-level layout (2-column grid)
    api_client.py            HTTP client wrapping backend endpoints
    store.py                 Shared application state (dcc.Store) definitions
    callbacks/                All reactive callback modules
        evaluation.py             run trigger + merge_results (sole store-results writer)
        results_io.py             saved-result import/export/selection
        ui.py                     visualization callbacks (store-ui driven)
    layout/                  Layout builder functions
        sidebar.py                data source + metric selection UI
        main_panel.py             build_guide() / build_analysis() / build_comparison()
        components/
            metric_renderers/         one renderer per metric (drilldown UI)
    charts/                  Pure Plotly chart functions, one file per metric,
                             no Dash/UI knowledge
```

Each module maps to a component described in the thesis's System Design chapter. **Dependency direction in the frontend is strict and one-way:** `charts/` -> `layout/components/` -> `layout/{main_panel,sidebar}.py` -> `callbacks/`. No file in a lower layer imports from a higher one. Never introduce a reverse import when adding or refactoring code.

## Backend Architecture

- **API layer** (`api/evaluation_controller`): HTTP interface only — no evaluation logic. Validates/deserializes requests, delegates to the Evaluation Engine or Ontology Extractor, serializes responses. Endpoints:
    - `GET /metrics` — implemented metrics + metadata, sourced from `config/metrics_config.json`. Metric names are **never hardcoded in the frontend**; adding a metric to config alone surfaces it in the UI.
    - `GET /dimensions` — the four quality dimensions (Intrinsic, Contextual, Representational, Accessibility), same config file.
    - `POST /ontology` — lazy class-hierarchy extraction for scope filtering; reads from graph cache if already loaded.
    - `POST /evaluate` — runs selected metrics for the given datasets. 400 if a metric identifier is unrecognized; 500 if a registered identifier has no plugin implementation (configuration inconsistency, not user error).
    - `GET /export/{dataset_id}/{metric_id}/{category}` — streams CSV of cached export rows; 404 if no matching export data exists.
    - `POST /results/export` — builds a results archive from results the client already holds; 400 if no datasets given.
    - `POST /results/import` — reads an archive back (body is an untyped `dict | list`, since legacy archives are a bare list); 400 on any unreadable archive.
- **CLI** (`cli/cli.py`): same pipeline as the API. Commands: `--config` (run a YAML evaluation config), `--inspect` (ontology/class hierarchy), `--benchmark` (cold/warm timing), `--template` (print an annotated example config), `--list-metrics`, `--help`. Config format intentionally mirrors the API's internal request models. Relative output paths resolve against the CLI directory, not the current working directory. `output.format: json` writes a **results archive** via the shared serializer, so CLI runs are importable into the dashboard; `csv` stays a lossy flat summary.
- **Evaluation Engine** (`engine/evaluation_engine.py`): orchestrator only — never implement data loading or metric computation here. Pipeline per request: Data Source loads graph (via `DataSourceFactory`) -> optional scope filter -> wrap in `DatasetContext` -> run each selected metric plugin -> pass results to `ResultAggregator` -> attach graph statistics. **Scope filtering is engine-level, not metric-level** — do not reintroduce per-metric scope logic.
- **Data Source** (`datasource/`): Strategy + Factory. `RDFFileSource` and `SPARQLEndpointSource` both implement a single `load()` interface and return `rdflib.Graph`. Format inferred from file extension if not explicit. SPARQL side uses CONSTRUCT queries (not SELECT) so results parse directly into a graph; queries must be single-line in JSON bodies (multiline breaks Wikidata/DBpedia with 502/422 errors). **RDFLib collapses every transport failure into one ValueError blaming the query**, so `sparql_endpoint.py` recovers the real cause from the exception chain (`HTTPError`/`URLError`) and names the status plus the endpoint's own reason — never by re-requesting, since rate limiting is one of the failures being diagnosed. Also note an `Accept` header cannot be set through `SPARQLStore`: its connector overwrites given headers with one derived from `returnFormat`.
- **Graph cache** (`graph/graph_cache.py`): thread-safe singleton, keyed by SHA-256 hash of the canonical source config (not dataset id/label), protected by `threading.Lock`. Scope-filtered subgraphs are **intentionally not cached** — filtering is cheap in-memory work; the expensive part (parsing/I/O) is already cached at the full-graph level.
- **Ontology Extractor** (`graph/ontology_extractor.py`): builds `ClassNode`/ `PropertyInfo` hierarchy directly from the RDF graph (rdf:type + rdf:subClassOf), no external schema. Independent of the evaluation pipeline — used only for exploration and scope configuration.
- **Metric Plugins** (`metrics/plugins/`): each implements `evaluate(context)` from `metrics/metric_plugin.py`, returns a `MetricResult` (score in [0,1], status `computed`/`failed`/`not_applicable`, metric-specific `details` dict). Registered in `metrics/metric_registry.py` (id -> class) and `config/metrics_config.json` (id -> display metadata + weight). Adding a metric = new plugin class + registry entry + config entry; no other component changes. Use `error_result()` for recoverable failures instead of raising — partial evaluation results must remain available.
    - `structural_completeness.py` — SHACL/EDM profile-based (15 deduplicated properties, score = `1 - violations/15`; structural-issues score = `max(0, 1 - violations/(len(subject_types)+violations))`)
    - `property_coverage.py` — data-driven, per-class fill rates, weighted by class size
    - `multilingual_labeling_coverage.py` — coverage ratio × language-count multiplier (`blank_class_rates` is always `{}` since BNodes have no rdf:type)
    - `foundational_format_consistency.py` — URI validity, datatype correctness, BCP 47 language tags, structural issues (blank nodes, empty literals); each sub-score exported separately via the Export cache
- **Results Aggregator** (`results_aggregator/aggregator.py`): weighted mean of successfully-computed metrics only; returns `None` (not a fabricated score) if nothing is valid. Also computes triple/entity/class counts. Keep aggregation logic isolated from metric implementations.
- **Export infrastructure** (`export/`): thread-safe in-memory cache keyed by `(dataset_id, metric_id, category)`, process-local — re-running an evaluation overwrites a dataset's entries, and a backend restart empties the cache. (`clear_dataset()` and `graph_cache.invalidate()` exist but have no callers; the README previously claimed otherwise.)
- **Result archives** (`export/result_archive.py`): the **single** serializer for the archive format, used by both the API and the CLI — never reimplement archive reading or writing in either entry point. `build_archive()` stamps schema/tool version, timestamp, per-dataset provenance (`source_config`, `scope`) and a `metrics_config` snapshot, and pulls the full export rows out of the export cache. `parse_archive()` accepts schema version 1 and legacy bare lists (version 0), **re-keys dataset ids to `imported_<digest>_<n>`** (deterministic, from the file contents) so imports can't collide with live UUIDs, and `restore_exports()` writes the rows back under those ids so `GET /export/...` serves imported datasets unchanged. Metrics with no numeric score or `status == "error"` stay in the file but are filtered out of the parse result and reported in `dropped_metrics` — the frontend escalates a failed metric to a whole-view error, and does unguarded arithmetic on scores.

## Frontend Architecture

- **Three stores**, defined centrally in `store.py`:
    - `store-sources` — list of source objects (UUID, label, source type/params, scope class URIs, selected flag). Single source of truth for the source list.
    - `store-results` — full nested evaluation results. `null` -> guide mode; one dataset -> analysis mode; multiple -> comparison mode.
    - `store-ui` — transient UI state (selected metric, active drilldown class). Kept separate from results so navigation doesn't touch evaluation data.
    - `store-computed` — datasets from the most recent run (or its error message); written only by the run callback.
    - `store-imported` — saved results keyed by their re-keyed dataset id, each with `dataset`, `archive` metadata and a `selected` flag. **Imports arrive with `selected=False`** — loading a file must never change what is on screen, because an archive is not an analysis the user has run. Re-importing an already-present dataset keeps its current selection.
    - (an ontology cache also exists client-side to avoid redundant `/ontology` calls on repeated expand/collapse)

  **`store-results` is derived state with exactly one writer — `merge_results` in `callbacks/evaluation.py`. Never add another Output to it.** It concatenates the computed run (first, so it owns `datasets[0]` and colour index 0) with the selected imported datasets, and returns `None` when nothing is selected. Because `make_results` derives the mode from `len(datasets)`, cross-run comparison needs no mode logic of its own. When a `store-imported` change leaves the visible dataset list identical (the usual case on import, since entries arrive unselected) it returns `no_update`, so the main panel is not re-rendered and the user's drilldown is preserved.
- **Export is per dataset** — `callbacks/results_io.py` renders one `{"type": "btn-export-dataset"}` button per dataset of the latest run and exports that dataset alone, so an archive written by the dashboard always holds exactly one dataset. Multi-dataset archives remain *readable* (older CLI output), and the importer splits them into independent entries.
- **Comparison never fabricates a score.** Compared datasets may cover different metric sets (a saved result vs. a run with different metrics selected). `_comparison_card_body` in `layout/components/metric_card.py` draws a bar only for datasets that actually measured the metric — **never default a missing metric to 0.0**, which renders as a score of 0% rather than an absence — and names the rest under the chart. Colours are keyed to each dataset's index in `datasets`, not to its position among the present bars, so a dataset keeps one colour across all cards. `build_comparison` hides the Overall Score chart unless every dataset covers the same metrics (the mean is over a different set otherwise) and warns when the intersection is empty. `_render_overview` in `detail_views.py` already intersects metrics for the spider chart.
- **Callbacks** (`callbacks/`) fall into three categories: configuration (sources, metric selection, lazy ontology loading), evaluation (validates >=1 source and >=1 metric, calls the API, normalizes into `store-results`), and visualization (`callbacks/ui.py` — drilldown, CSV export, active-card styling). Callbacks never talk to each other directly; only through the stores.
- **Layout**: `app.py` is the 3/9-column Bootstrap grid root. `layout/sidebar.py` builds data-source cards (`build_source_item()`) and the metric accordion. `layout/ main_panel.py` dispatches on `store-results` via `build_guide()` / `build_analysis()` / `build_comparison()`.
- **Charts** (`charts/`): pure functions, plain Python data in, Plotly `Figure` out, no Dash imports. One file per metric plus `overview.py`. Known gotcha: `fig.add_shape` creates a cartesian axis that clears background fills — use `add_scatter(mode="lines")` for background zone overlays instead.

## Design Principles (do not violate without discussion)

1. **Dual interaction model** — API and CLI share one evaluation pipeline; never fork logic between them.
2. **Layered modular monolith**, not microservices — keep module boundaries clean so it _could_ be split later, but don't add deployment-level separation now.
3. **Plugin-based metrics** — new metrics are additive (plugin + registry + config), never require touching the engine.
4. **Data source abstraction** — Strategy + Factory; new source types are new strategy classes, not branches in existing code.
5. **Evaluation Engine orchestrates only** — no business logic in the engine itself.
6. **Scope filtering is engine-level** — applied once, before metrics run; not duplicated per-metric.
7. **Centralized frontend state** — components communicate only through the three stores, never directly.

## Terminology

RDF terminology should be standardized on **"resource"** (not "entity" or "record") — flagged by a thesis reviewer as inconsistent across the tool. This is agreed direction but the sweep across the codebase has not been completed — check with me before doing a mechanical rename in files I haven't confirmed yet.

## Docstrings

Every function/module in this codebase already has a docstring in an established format. This is a hard constraint:

- **Never rewrite or reformat an existing docstring** unless the code it documents changed. Preserve exact structure/sections/wording style.
- **No backticks** around attribute or parameter names in docstrings — this project's convention writes them plain.
- For **new** functions or new code sections, match the style of the nearest existing docstring in the same file (same section headers, same level of detail, same formatting) rather than introducing a different convention.
- If you're ever unsure what the established pattern is for a given file, show me a draft before applying it broadly.

## Working Style

- **Minimal diffs.** Don't refactor unrelated code, rename things, or "clean up" while fixing something else. Ask first if a change seems to need to grow beyond the reported issue.
- **I test in the running app**, not by reading code — when something's visually wrong I'll usually describe it or share a screenshot rather than pointing at a line number. Fixes should be verifiable the same way.
- **I sometimes make local edits directly** (e.g. a color override) and will tell you to preserve them — don't silently revert local changes you didn't make.
- When a fix creates a new problem, just fix it — don't re-explain the failed approach.
- Explain significant design decisions before implementing them; small/obvious fixes don't need a preamble.
- Avoid over-engineering — prefer the simplest solution that respects the separation of concerns above.