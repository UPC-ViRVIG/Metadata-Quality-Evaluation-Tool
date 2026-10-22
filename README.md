# Metadata Quality Evaluation Tool

A visualization-driven tool for evaluating and comparing metadata quality in semantic (RDF / Linked Data) collections, with a focus on Digital Cultural Heritage. It supports query-based and file-based selection of collections, restriction of an evaluation to specific RDF classes, and interactive visualization of results both *within* a single collection and *across* several of them.

Built as part of the **ECHOES** European cultural heritage initiative, and as the practical component of the master's thesis *"A Visualization Tool for Metadata Quality Evaluation in Digital Cultural Heritage."*

---

## Table of Contents

- [Overview](#overview)
- [Quality Model](#quality-model)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Installation](#installation)
- [Running the Application](#running-the-application)
- [Using the Dashboard](#using-the-dashboard)
- [Data Sources](#data-sources)
- [Command-Line Interface](#command-line-interface)
- [REST API Reference](#rest-api-reference)
- [Project Structure](#project-structure)
- [Extending the Tool](#extending-the-tool)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)

---

## Overview

The tool answers a practical question for metadata custodians: *given an RDF collection, where is its metadata weak, and how does it compare to another collection?*

It does this in three steps:

1. **Load** — an RDF collection is read either from a local file or from a remote SPARQL endpoint via a `CONSTRUCT` query.
2. **Evaluate** — a set of selected quality metrics is executed over the resulting graph, each producing a normalized score in `[0, 1]` plus metric-specific diagnostic detail.
3. **Visualize** — results are rendered as interactive charts. A single collection opens in *analysis* mode; two or more open in *comparison* mode.

Two entry points share the exact same evaluation pipeline:

- an interactive **web dashboard** (Dash frontend + FastAPI backend), and
- a server-free **CLI** for scripted, reproducible batch runs.

Key capabilities:

- **Scope filtering** — restrict an evaluation to instances of chosen RDF classes, discovered automatically from the data itself (no external schema required).
- **Drill-down** — click a metric card to inspect per-class and per-property breakdowns.
- **CSV export** — download the complete, uncapped violation lists behind any chart.
- **Save & re-import results** — archive any evaluated dataset to a JSON file and load it back later, including comparing a fresh evaluation against an archived one.
- **Graph caching** — a parsed graph is reused across repeated evaluations of the same source, so only the metric computation is paid for on the second run.

---

## Quality Model

Metrics are grouped into four quality dimensions. Dimensions and metrics are both defined in [`backend/config/metrics_config.json`](backend/config/metrics_config.json) — the frontend never hardcodes metric names, so the configuration file is the single source of truth.

| Dimension | Question it answers |
| --- | --- |
| **Intrinsic** | Is the metadata correct and trustworthy on its own? |
| **Contextual** | Is the metadata complete and relevant for how it will be used? |
| **Representational** | Is the metadata easy to read and consistently formatted? |
| **Accessibility** | Can the metadata be found, shared, and reused by others? |

### Implemented Metrics

| Metric ID | Name | Dimension | What it measures |
| --- | --- | --- | --- |
| `structural_completeness` | Structural Completeness | Contextual | Proportion of records containing all required fields, validated with SHACL against a detected schema profile (EDM or a generic core profile). |
| `property_coverage` | Property Coverage | Contextual | How consistently properties are used across all instances of each class — data-driven per-class fill rates, weighted by class size. |
| `multilingual_labeling_coverage` | Multilingual Labeling Coverage | Contextual | Presence and distribution of language-tagged literals: how many resources carry multilingual metadata and how evenly languages are represented. |
| `foundational_format_consistency` | Foundational and Format Consistency | Representational | URI validity, datatype correctness, BCP 47 language-tag format, and structural issues (blank nodes, empty literals). Each sub-score is exportable separately. |
| `connectivity` | Connectivity | Accessibility | Whether every distinct URI referenced by the dataset — as a subject, predicate, or object — is dereferenceable over HTTP. Every URI is checked, with no sampling; concurrency (not a cap) is what keeps this tractable.

An **overall score** per dataset is the weighted mean of the metrics that computed successfully. Metrics that failed or were not applicable are excluded rather than counted as zero; if nothing computed, the overall score is `null` rather than a fabricated number.

SHACL shape profiles used by `structural_completeness` live in [`backend/metrics/shapes/`](backend/metrics/shapes/) (`edm_profile.ttl`, `core_profile.ttl`).

---

## Architecture

The application is split into two independently runnable services plus a CLI, all sharing one evaluation pipeline.

```
┌──────────────────────────┐          ┌──────────────────────────────────────┐
│  Dash Frontend  :8050    │          │  FastAPI Backend  :8000              │
│                          │  HTTP    │                                      │
│  sidebar / main panel    │ ───────▶ │  API layer                           │
│  charts / callbacks      │ ◀─────── │      ↓                               │
│  dcc.Store state         │   JSON   │  Evaluation Engine (orchestrator)    │
└──────────────────────────┘          │      ↓          ↓          ↓         │
                                      │  Data Source  Scope     Metric       │
┌──────────────────────────┐          │  (Strategy)   Filter    Plugins      │
│  CLI (backend/cli)       │ ───────▶ │      ↓                    ↓          │
│  YAML config in,         │  direct  │  Graph Cache        Result           │
│  JSON / CSV out          │  import  │                     Aggregator       │
└──────────────────────────┘          └──────────────────────────────────────┘
```

### Frontend

Implemented with **Dash**, **Plotly**, and **Dash Bootstrap Components**.

Responsibilities: dataset configuration, metric selection, ontology browsing and scope filtering, interactive visualization, and the analysis / comparison views.

State is centralized in `dcc.Store` components — components never talk to each other directly, only through the stores:

| Store | Contents |
| --- | --- |
| `store-sources` | Configured sources (id, label, source config, scope, selection flag). |
| `store-computed` | Datasets returned by the most recent evaluation run, or the error that stopped it. |
| `store-imported` | Results loaded from saved archive files, keyed by dataset id. Entries start unselected, so an import never alters the current view on its own. |
| `store-results` | Full nested evaluation results, **derived** from the computed run plus the selected saved results. `null` → guide mode, one dataset → analysis mode, several → comparison mode. Written by exactly one callback, `merge_results`. |
| `store-ontology` | Client-side cache of extracted class hierarchies, to avoid redundant `/ontology` calls. |
| `store-ui` | Transient interaction state (active metric, active drill-down class). |
| `store-metric-dims` / `store-dimensions` | Metric and dimension metadata fetched from the backend at startup. |

Dependency direction is strict and one-way: `charts/` → `layout/components/` → `layout/` → `callbacks/`.

### Backend

Implemented with **FastAPI**, **RDFLib**, **pySHACL**, and **Pydantic**.

Responsibilities: data source handling (RDF parsing, SPARQL querying), metric execution, ontology extraction, result aggregation, and CSV export.

Design points worth knowing:

- **The API layer contains no evaluation logic.** It validates requests, delegates, and serializes responses.
- **The Evaluation Engine orchestrates only.** Per request it loads the graph, applies the scope filter, wraps everything in a `DatasetContext`, runs each metric plugin, aggregates, and attaches graph statistics.
- **Scope filtering happens once, at engine level** — never inside individual metrics.
- **Data sources use Strategy + Factory.** `RDFFileSource` and `SPARQLEndpointSource` both implement a single `load()` interface returning an `rdflib.Graph`. New source types are new strategy classes, not new branches.
- **Metrics are plugins.** Each implements `evaluate(context) -> MetricResult`. Adding a metric means a plugin class, a registry entry, and a config entry — nothing else changes.
- **The graph cache is a thread-safe singleton** keyed by a SHA-256 hash of the canonical source configuration (not by dataset id or label), so two differently-named sources pointing at the same data share one parsed graph. Scope-filtered subgraphs are deliberately *not* cached: filtering is cheap in-memory work, while the expensive parsing is already cached at the full-graph level.
- **Recoverable metric failures return an error result rather than raising**, so a single broken metric never discards the results of the others.

---

## Requirements

- **Python 3.11+** (3.12 recommended)
- `pip`
- `venv` / `virtualenv`

The backend and the frontend have separate dependency sets and are intended to run in **two separate virtual environments**.

---

## Installation

**1. Clone the repository**

```bash
git clone <repository-url>
cd "Metadata Quality Evaluation Tool"
```

**2. Set up the backend**

Windows (PowerShell):

```powershell
cd backend
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Linux / macOS:

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

> **Note:** the CLI additionally requires PyYAML. If `python cli/cli.py --help` fails with `ModuleNotFoundError: No module named 'yaml'`, install it into the backend environment with `pip install PyYAML`.

**3. Set up the frontend**

Open a *second* terminal, at the repository root.

Windows (PowerShell):

```powershell
cd frontend
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Linux / macOS:

```bash
cd frontend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Running the Application

Both services must be running for the dashboard to work. The frontend talks to the backend at `http://127.0.0.1:8000`, configured as `BACKEND_URL` in [`frontend/api_client.py`](frontend/api_client.py).

**Terminal 1 — backend** (from `backend/`, with its venv active):

```bash
uvicorn main:app --reload
```

The API is served at `http://127.0.0.1:8000`, with interactive OpenAPI docs at `http://127.0.0.1:8000/docs`.

**Terminal 2 — frontend** (from `frontend/`, with its venv active):

```bash
python app.py
```

The dashboard is served at `http://127.0.0.1:8050`.

---

## Using the Dashboard

**1. Add a data source.** Use *Add source* in the sidebar and choose either a local RDF file or a SPARQL endpoint. Give it a label — this is what appears in the charts and legends.

For a local file you can drag and drop it onto the modal, or select it with a file picker, instead of typing a path. The file is uploaded to the backend, which stores it and fills in the path and the serialisation format for you. The format is guessed from the file name, so check the dropdown if the extension is unusual. Typing a path that already exists on the server still works and is the better option for large files.

**2. (Optional) Narrow the scope.** Expand a source card to browse the class hierarchy extracted from the data itself. Selecting one or more classes restricts the evaluation to triples whose subject is an instance of those classes. Leaving the selection empty evaluates the whole graph. The hierarchy is fetched lazily on first expand and cached client-side.

**3. Select metrics.** Metrics are grouped by quality dimension in the accordion. Each carries a tooltip explaining what it measures.

**4. Run the evaluation.** At least one source and one metric must be selected.

**5. Read the results.**

- One selected source → **analysis mode**: an overview chart plus one card per metric.
- Two or more → **comparison mode**: the same metrics rendered side by side across datasets.

**6. Drill down.** Clicking a metric card opens its detail view — per-class breakdowns, per-property fill rates, violation samples, and language distributions, depending on the metric.

**7. Export violations.** Where a metric supports it, the detail view offers per-category CSV downloads — currently *Foundational and Format Consistency* and *Connectivity*. The on-screen samples are capped for readability, but the exported CSV contains the complete, uncapped set of rows.

**8. Save a result.** After a run, a *Save Results* list appears under the Run button with one button per evaluated dataset. **Each export is a single dataset**, never a whole comparison, so saved results stay independent and can be recombined freely later. The archive holds that dataset's scores, all metric detail, the provenance of the run (source configuration, scope, timestamp, metric configuration snapshot), and the complete export rows behind the CSV downloads.

**9. Load a saved result.** *Import Results* in the **Saved Results** section reads an archive back. Each dataset in the file becomes a card with its own checkbox.

**An import arrives unselected and does not change what is on screen** — a loaded file is not an analysis you have run. Tick a saved result to bring it into the view:

- One saved result ticked → analysis mode, with every chart, drill-down and CSV download intact.
- Two or more ticked → comparison mode between saved results.
- One ticked alongside a completed run → comparison mode. This is how a collection is compared against its own earlier state. When both carry the same label, the saved one is shown as *label (imported)*.

Archives written by the CLI can be imported the same way, and result files from older CLI runs still load as the legacy format. A CLI run that evaluated several datasets produces one archive containing all of them; importing it yields one independently selectable card per dataset.

**Comparing results that measured different metrics.** A saved result and a new run need not cover the same metrics, and the comparison only ever claims what is actually comparable:

- A metric measured by only some of the compared results shows bars for those results alone, with *Not measured in: …* naming the rest. It is never drawn at 0%, which would read as a score rather than an absence.
- The **Overall Score** chart is shown only when all compared results cover the same metrics. An overall score is a weighted mean over whichever metrics ran, so otherwise it is replaced by a note saying the scores are not comparable.
- When the results have **no metric in common** at all, a warning explains that there is nothing to compare directly, and each metric is shown with the one result that measured it.

---

## Data Sources

### Local RDF file

```json
{
  "type": "rdf_file",
  "file_path": "tests/resources/valid.ttl",
  "format": "turtle"
}
```

- `format` is optional — RDFLib attempts auto-detection from the file extension when it is omitted.
- Supported formats include `turtle`, `xml`, `n3`, `nt`, and `json-ld`.
- Relative paths resolve against the process working directory, i.e. `backend/` when the server or the CLI is started from there.
- A file uploaded through the dashboard becomes an ordinary `rdf_file` source: the backend stores it under `backend/uploads/` (gitignored) and returns the path to put here. Stored names carry a short random prefix, so re-uploading the same file is never served from the previous file's cache entry. Nothing removes old uploads — clear the directory when it grows.

### SPARQL endpoint

```json
{
  "type": "sparql_endpoint",
  "endpoint_url": "https://dbpedia.org/sparql",
  "query": "CONSTRUCT { ?s ?p ?o } WHERE { { SELECT DISTINCT ?s WHERE { ?s a <http://dbpedia.org/ontology/Artwork> . } LIMIT 10 } ?s ?p ?o . }"
}
```

Two constraints matter here:

- **Use `CONSTRUCT`, not `SELECT`.** Results are materialized directly into an `rdflib.Graph`; a `SELECT` query has no graph to return and the load fails.
- **Keep the query on a single line inside JSON bodies.** Embedded newlines break several public endpoints (Wikidata and DBpedia respond with 502 / 422). In YAML config files this is not an issue — the folded block scalar (`>`) collapses the query for you, which is why the example configs can span multiple lines.

Bounding the query with `LIMIT` is strongly recommended when exploring a large public endpoint.

---

## Command-Line Interface

The CLI runs the same pipeline as the API without starting a server, which makes it the right tool for reproducible and scripted evaluations. Run it from the `backend/` directory with the backend virtual environment active.

```bash
python cli/cli.py --help
```

| Command | Description |
| --- | --- |
| `--config FILE`, `-c` | Run a full evaluation from a YAML config file. |
| `--inspect FILE`, `-i` | Print the class hierarchy for every dataset in the config, without running any metrics. Use it to discover class URIs before writing a scoped config. |
| `--benchmark FILE`, `-b` | Run the evaluation twice — cold cache, then warm — and report the parsing cost eliminated by the graph cache, plus per-metric runtimes. |
| `--template`, `-t` | Print an annotated example config to stdout. |
| `--list-metrics`, `-l` | List available metric IDs and their descriptions. |
| `--help`, `-h` | Show all commands. |

### Typical workflow

```bash
# 1. Create a config from the annotated template
python cli/cli.py --template > cli/configs/my_evaluation.yaml

# 2. Discover which classes exist in the data
python cli/cli.py --inspect cli/configs/my_evaluation.yaml

# 3. Run the evaluation
python cli/cli.py --config cli/configs/my_evaluation.yaml
```

### Configuration format

The YAML format intentionally mirrors the API's internal request models.

```yaml
datasets:
  - id: europeana_local
    label: "Europeana EDM Export"
    source_config:
      type: rdf_file
      file_path: tests/resources/valid.ttl
      format: turtle
    scope: null            # null = full graph, or a list of class URIs

  - id: wikidata_paintings
    label: "Wikidata Paintings"
    source_config:
      type: sparql_endpoint
      endpoint_url: https://query.wikidata.org/sparql
      query: >
        CONSTRUCT { ?s ?p ?o }
        WHERE {
          ?s <http://www.wikidata.org/prop/direct/P31>
             <http://www.wikidata.org/entity/Q3305213> .
          ?s ?p ?o .
        }
        LIMIT 100
    scope: null

metrics:
  - structural_completeness
  - property_coverage
  - multilingual_labeling_coverage
  - foundational_format_consistency

output:
  path: results/evaluation_output.json
  format: json           # json | csv
```

Notes:

- **Relative output paths resolve against the `cli/` directory**, not the current working directory, so results always land in a predictable place. Absolute paths are used as-is.
- Omitting the `output` section prints results to stdout; progress and summaries always go to stderr, so `python cli/cli.py -c config.yaml > results.json` yields clean output.
- `json` produces a **results archive** — the full nested result plus provenance and the complete export rows — which can be imported straight into the dashboard. Because the export rows travel with it, an archive is considerably larger than the old output. `csv` produces one row per (dataset, metric) with score and status, and is a summary only: it cannot be imported back.
- Result files from earlier CLI versions (a bare JSON list with no envelope) still import as the legacy format, so the samples in `cli/results/` remain usable.
- A metric ID that is unknown to the configuration or registry is skipped with a warning rather than aborting the run.

Ready-made configs are in [`backend/cli/configs/`](backend/cli/configs/), with sample outputs in [`backend/cli/results/`](backend/cli/results/).

---

## REST API Reference

Interactive documentation is available at `http://127.0.0.1:8000/docs` while the backend is running.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/metrics` | Implemented metrics with display metadata, from `metrics_config.json`. |
| `GET` | `/dimensions` | The four quality dimensions with descriptions and tooltips. |
| `POST` | `/ontology` | Extract the class hierarchy of a dataset for scope configuration. |
| `POST` | `/evaluate` | Run the selected metrics over the given datasets. |
| `GET` | `/export/{dataset_id}/{metric_id}/{category}` | Stream the full export rows for a metric category as CSV. |
| `POST` | `/results/export` | Serialize evaluation results into a portable results archive. |
| `POST` | `/results/import` | Read a results archive back and restore its export rows. |
| `POST` | `/sources/upload` | Store an RDF file uploaded from the dashboard as a local source. |

### `POST /evaluate`

Request:

```json
{
  "datasets": [
    {
      "dataset_id": "local_file_test",
      "label": "Local Turtle Test",
      "source_config": {
        "type": "rdf_file",
        "file_path": "tests/resources/valid.ttl",
        "format": "turtle"
      },
      "scope": null
    },
    {
      "dataset_id": "dbpedia_artworks",
      "label": "DBpedia Artworks",
      "source_config": {
        "type": "sparql_endpoint",
        "endpoint_url": "https://dbpedia.org/sparql",
        "query": "CONSTRUCT { ?s ?p ?o } WHERE { { SELECT DISTINCT ?s WHERE { ?s a <http://dbpedia.org/ontology/Artwork> . } LIMIT 10 } ?s ?p ?o . }"
      }
    }
  ],
  "metrics": [
    { "metric_id": "structural_completeness" },
    { "metric_id": "property_coverage" }
  ]
}
```

Response (abbreviated):

```json
{
  "datasets": [
    {
      "dataset_id": "local_file_test",
      "label": "Local Turtle Test",
      "overall_score": 0.5759,
      "stats": {
        "triple_count": 74125,
        "entity_count": 5835,
        "class_count": 15
      },
      "metrics": [
        {
          "metric_id": "structural_completeness",
          "name": "Structural Completeness",
          "score": 0.9556,
          "weight": 1.0,
          "status": "computed",
          "details": { "profile": "edm", "total_records": 4750, "…": "…" },
          "exports_available": null
        }
      ]
    }
  ]
}
```

### `POST /results/export`

Request body — dataset results as received from `/evaluate`, optionally with the provenance of each run:

```json
{
  "datasets": [
    {
      "dataset_id": "3f1c…",
      "label": "Europeana EDM export",
      "overall_score": 0.68,
      "stats": { "triple_count": 74210, "entity_count": 5835, "class_count": 15 },
      "metrics": [ "… as returned by /evaluate …" ],
      "source_config": { "type": "rdf_file", "file_path": "…", "format": "turtle" },
      "scope": null
    }
  ]
}
```

The endpoint accepts any number of datasets, but the dashboard sends exactly one per archive so that saved results stay independent. CLI runs over several datasets write them into a single archive, which the importer then splits.

The response is the archive itself, as indented JSON with a `Content-Disposition` filename. Its shape:

| Field | Type | Notes |
| --- | --- | --- |
| `schema_version` | int | `1`. A bare top-level list is read as legacy version `0`. |
| `tool` / `tool_version` | str | Which tool and version wrote the file. |
| `created_at` | str | UTC ISO 8601, e.g. `2026-09-25T14:03:11Z`. |
| `created_by` | str | `api` or `cli`. |
| `metrics_config` | object | Snapshot of the configuration entries for the metrics present — names, dimensions and weights as they were at the time of the run. |
| `datasets[]` | array | Per dataset: `dataset_id`, `label`, `overall_score`, `stats`, `source_config`, `scope`, `metrics[]`, and `exports`. |
| `datasets[].exports` | object | `{metric_id: {category: [rows]}}` — the complete uncapped export rows read out of the export cache. |

### `POST /results/import`

The body is an archive, sent as-is; a legacy bare list is also accepted. The response carries the archive's provenance plus its datasets in exactly the `/evaluate` response shape, so no separate rendering path is needed:

```json
{
  "schema_version": 1,
  "created_at": "2026-09-25T14:03:11Z",
  "tool_version": "1.0.0",
  "dropped_metrics": [],
  "datasets": [ "… same shape as POST /evaluate …" ]
}
```

Two things happen on import:

- **Dataset IDs are re-keyed** to `imported_<archive digest>_<n>`, so an archive can never collide with a live run's UUID in a merged comparison. The digest is derived from the file contents, so re-importing the same archive is idempotent.
- **Export rows are written back into the export cache** under those new IDs, which is what lets `GET /export/…` serve an imported dataset exactly as it serves a freshly evaluated one.

Metrics that failed or carry no numeric score are kept in the archive file but omitted from the response and named in `dropped_metrics`, because the dashboard treats a failed metric as a whole-view error.

### `POST /sources/upload`

The file is sent as the raw request body, with its name as the `filename` query parameter — no multipart form, and therefore no extra backend dependency:

```
POST /sources/upload?filename=my_dataset.ttl
Content-Type: application/octet-stream

<raw file bytes>
```

```json
{
  "file_path": "…/backend/uploads/2f38ab23_my_dataset.ttl",
  "filename": "my_dataset.ttl",
  "format": "turtle",
  "size_bytes": 3419
}
```

`file_path` is what belongs in an `rdf_file` source configuration, and `format` is guessed from the extension (`null` when it is not recognised). Only the final component of the supplied name is used and unsafe characters are replaced, so a client cannot decide where the file is written. The limit is 200 MB.

### Status codes

| Code | Meaning |
| --- | --- |
| `400` | A requested metric ID is not defined in the configuration (user error). |
| `422` | A dataset could not be loaded, or evaluation failed. |
| `500` | A configured metric ID has no registered plugin — a configuration inconsistency, not user error. |
| `404` | *(export only)* No export data exists for the requested combination; run `/evaluate` first. |
| `400` | *(results import/export only)* The payload is not a readable archive, carries no datasets, or declares a schema version this tool does not support. |
| `400` | *(upload only)* The file is empty or its name has nothing usable in it. |
| `413` | *(upload only)* The file exceeds the 200 MB upload limit. |

### Export categories

`exports_available` on each metric result lists the categories that can be downloaded, or `null` when the metric does not support export. Currently `foundational_format_consistency` is the only metric that exports; it exposes four categories:

| Category | Contents |
| --- | --- |
| `uri_validity` | Malformed or non-dereferenceable URIs. |
| `datatype_correctness` | Literals whose value does not match their declared datatype. |
| `language_tag_format` | Language tags that are not valid BCP 47. |
| `structural_issues` | Blank nodes and empty literals. |

Export rows are cached in memory during `/evaluate`, keyed by `(dataset_id, metric_id, category)`, and re-running an evaluation overwrites the entries for that dataset. The cache is process-local: it is emptied when the backend restarts, which is what a results archive protects against — importing one writes its rows back into the cache.

---

## Project Structure

```
backend/
    api/                     FastAPI endpoints and request handling
        evaluation_controller.py  the API layer implementation
    cli/                     Command-line interface
        cli.py                    argument parsing and command dispatch
        configs/                  ready-made YAML evaluation configs
        results/                  sample CLI output
    config/                  Metric and dimension configuration
        metrics_config.json       single source of truth for metric metadata
        config_loader.py          config access helpers
    datasource/              Data source abstraction (Strategy + Factory)
        datasource_interface.py   the load() strategy interface
        datasource_factory.py     source-type dispatch
        sources/                  RDFFileSource, SPARQLEndpointSource
        upload_store.py           storage for files uploaded from the dashboard
    engine/
        evaluation_engine.py      pipeline orchestration
    export/                  Export and archive serialisation infrastructure
        export_cache.py           thread-safe in-memory export cache
        csv_writer.py             row serialisation
        result_archive.py         results archive format, shared by API and CLI
    graph/
        graph_cache.py            thread-safe singleton graph cache
        ontology_extractor.py     class/property hierarchy extraction
        scope_filter.py           class-based subgraph filtering, graph stats
    metrics/
        metric_plugin.py          shared plugin interface
        metric_registry.py        identifier -> plugin class registry
        plugins/                  one file per metric
        shapes/                   SHACL profiles (EDM, core)
    models/                  Request, response, and internal models
    results_aggregator/
        result_aggregator.py      weighted score aggregation
    tests/                   Unit tests and RDF test fixtures
    main.py                  FastAPI application entry point

frontend/
    app.py                   Dash entry point + top-level layout
    api_client.py            HTTP client wrapping the backend endpoints
    store.py                 Shared application state (dcc.Store) definitions
    callbacks/               Reactive callback modules
        sources.py                source configuration and ontology loading
        evaluation.py             evaluation triggering, and the merge that
                                  derives store-results
        results_io.py             saved result import, export, and selection
        main_panel.py             view-mode dispatch
        ui.py                     drill-down, export, active-card styling
    layout/
        sidebar.py                data source + metric selection UI
        main_panel.py             guide / analysis / comparison views
        metric_details.py         detail panel composition
        components/
            metric_card.py            metric summary cards
            detail_views*.py          shared detail-view building blocks
            metric_renderers/         one renderer per metric
    charts/                  Pure Plotly chart functions, one file per metric
        palette.py                shared colour definitions
        primitives.py             reusable chart building blocks
```

---

## Extending the Tool

### Adding a metric

Three additive steps — no other component changes:

1. **Create the plugin** in `backend/metrics/plugins/`, subclassing `MetricPlugin`:

   ```python
   from metrics.metric_plugin import MetricPlugin
   from models.metric_result import MetricResult

   class MyMetric(MetricPlugin):
       id = "my_metric"

       def evaluate(self, context):
           try:
               score = ...  # compute over context.graph
               return MetricResult(
                   metric_id=self.id,
                   name=self.name,
                   score=score,
                   weight=self.weight,
                   details={...},
               )
           except Exception as exc:
               return self.error_result(str(exc))
   ```

   Use `self.error_result(...)` for recoverable failures instead of raising — partial evaluation results must stay available to the user.

2. **Register it** in `backend/metrics/metric_registry.py`:

   ```python
   METRIC_REGISTRY = {
       ...,
       "my_metric": MyMetric,
   }
   ```

3. **Describe it** in `backend/config/metrics_config.json`:

   ```json
   "my_metric": {
     "name": "My Metric",
     "description": "…",
     "tooltip": "…",
     "dimension": "Intrinsic",
     "weight": 1.0
   }
   ```

The metric now appears in the sidebar automatically. To visualize it beyond the default score card, add a chart module in `frontend/charts/` and a renderer in `frontend/layout/components/metric_renderers/`.

### Adding a data source type

1. Implement the `DataSource` interface in `backend/datasource/sources/`, returning an `rdflib.Graph` from `load()` and consulting the graph cache as the existing sources do.
2. Add a `case` for the new `type` value in `DataSourceFactory.create()`.

No engine or API change is required.

---

## Testing

Unit tests live in `backend/tests/`, with RDF fixtures under `backend/tests/resources/` and per-metric evaluation fixtures under `backend/tests/evaluation/`. Three suites exist: the data source layer; the results archive round trip (`test_result_archive.py`), which also checks every result file shipped in `backend/cli/results/` still imports; and the upload store (`test_upload_store.py`), which covers format guessing and the handling of client-supplied file names.

From `backend/`, with the virtual environment active:

```bash
python -m pytest
```

The evaluation fixtures are small, hand-written Turtle files, each isolating one condition — perfect coverage, invalid BCP 47 tags, multi-typed records, unknown classes, and so on — so that metric behaviour can be checked against a known expected outcome.

---

## Troubleshooting

**"Cannot reach the backend. Make sure the FastAPI server is running."**
The Dash app is up but `uvicorn` is not, or it is bound to a different port. The frontend expects `http://127.0.0.1:8000`.

**`ModuleNotFoundError: No module named 'yaml'` when running the CLI.**
PyYAML is required by the CLI. Install it into the backend environment: `pip install PyYAML`.

**A SPARQL endpoint returns 502 or 422.**
Most often the query spans multiple lines inside a JSON body. Collapse it to a single line. If the query still fails, it may be too large or slow for the public endpoint — add or lower a `LIMIT`.

**`DataSourceLoadError: SPARQL query could not return a CONSTRUCT graph.`**
The query is a `SELECT`. Rewrite it as a `CONSTRUCT` so the results can be materialized into a graph.

**Structural Completeness produces uninformative scores on non-EDM data.**
The metric validates against a detected schema profile. On data with no matching profile (DBpedia, for instance) it falls back to a generic core profile, and the result is of limited value. Prefer the other metrics for such collections, or scope the evaluation to the classes the profile actually targets.

**Results look stale after changing a source file on disk.**
The graph cache is keyed by source configuration, not by file modification time. Restart the backend to clear it.

**A CSV download from an imported result does nothing.**
The export cache is process-local, so a backend restart empties it. Import the archive again — that writes its export rows back into the cache.

**Importing a large archive is slow.**
Dash sends an uploaded file through a callback as a base64 data URL, which adds about a third to its size. Archives carrying the full export rows for a large collection can be several megabytes.

---

## Acknowledgements

Developed within the **ECHOES** European cultural heritage initiative, and as the practical component of the master's thesis *"A Visualization Tool for Metadata Quality Evaluation in Digital Cultural Heritage."*
