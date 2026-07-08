import argparse
import json
import sys
import textwrap
import time
from pathlib import Path
import yaml

CLI_DIR = Path(__file__).resolve().parent
BACKEND_DIR = CLI_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))


TEMPLATE = textwrap.dedent("""\
# Metadata Quality Evaluation — configuration file
# ─────────────────────────────────────────────────
# Run:      python cli.py --config this_file.yaml
# Inspect:  python cli.py --inspect this_file.yaml
# Benchmark: python cli.py --benchmark this_file.yaml
# Template: python cli.py --template > this_file.yaml

# ── Datasets ──────────────────────────────────────────────────────────────
# Add one or more datasets. Each needs a unique id and a source_config
# block. Supported source types: rdf_file, sparql_endpoint.
#
# scope restricts evaluation to specific RDF class URIs.
# Set to null (or omit) to evaluate the full graph.
# Use --inspect to discover which class URIs are available.

datasets:

  - id: local_europeana
    label: "Europeana EDM export"
    source_config:
      type: rdf_file
      file_path: tests/resources/valid.ttl
      format: turtle          # turtle | xml | n3 | nt | json-ld
    scope: null               # null = full graph
                              # or a list of class URIs, e.g.:
                              # scope:
                              #   - http://www.europeana.eu/schemas/edm/ProvidedCHO
                              #   - http://www.openarchives.org/ore/terms/Proxy

  - id: wikidata_paintings
    label: "Wikidata Paintings sample"
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

# ── Metrics ───────────────────────────────────────────────────────────────
# List the metric IDs to run.
# See all available metrics with: python cli.py --list-metrics

metrics:
  - property_completeness
  - structural_completeness
  - multilingual_labeling_coverage

# ── Output ────────────────────────────────────────────────────────────────
# Where to write results. Omit this section to print to stdout.
# Formats:
#   json — full nested result including per-metric details
#   csv  — one row per (dataset, metric) with score and status

output:
  path: results/evaluation_output.json
  format: json                # json | csv
""")


def load_config(path: str) -> dict:
    """
    Load and validate a YAML evaluation configuration file.

    The configuration must define at least one dataset under datasets
    and at least one metric ID under metrics. The optional output
    section controls where results are written.

    Parameters
    ----------
    path : str
        Path to the YAML configuration file.

    Returns
    -------
    dict
        Parsed configuration with the following top-level keys:

        datasets (list of dict): Dataset descriptors, each containing
        id, label, source_config, and optionally scope.

        metrics (list of str): Metric IDs to evaluate.

        output (dict, optional): Output settings with path and
        format (json or csv).

    Raises
    ------
    ValueError
        If datasets or metrics is missing or empty.
    FileNotFoundError
        If the file at path does not exist.
    yaml.YAMLError
        If the file cannot be parsed as valid YAML.
    """
    with open(path) as f:
        config = yaml.safe_load(f)

    if not config.get("datasets"):
        raise ValueError("Config must contain at least one dataset under 'datasets'.")
    if not config.get("metrics"):
        raise ValueError("Config must contain at least one metric under 'metrics'.")

    return config


def load_config_for_inspect(path: str) -> dict:
    """
    Load a YAML configuration file for ontology inspection only.

    Unlike load_config, this does not require a metrics section since
    inspection does not run any metrics. The output section is also
    ignored. Only the datasets section is required and validated.

    Parameters
    ----------
    path : str
        Path to the YAML configuration file.

    Returns
    -------
    dict
        Parsed configuration. Only the datasets key is guaranteed to
        be present and non-empty.

    Raises
    ------
    ValueError
        If datasets is missing or empty.
    FileNotFoundError
        If the file at path does not exist.
    yaml.YAMLError
        If the file cannot be parsed as valid YAML.
    """
    with open(path) as f:
        config = yaml.safe_load(f)

    if not config.get("datasets"):
        raise ValueError("Config must contain at least one dataset under 'datasets'.")

    return config


def _build_source_config(raw: dict) -> dict:
    """
    Normalise a raw source_config dict from YAML into the shape
    expected by the evaluation engine and data source factory.

    Parameters
    ----------
    raw : dict
        Source configuration block from the YAML file. Must contain
        a type key. Supported types:

        rdf_file: requires file_path and optionally format.

        sparql_endpoint: requires endpoint_url and query.

    Returns
    -------
    dict
        Normalised source configuration dict compatible with
        DataSourceFactory.create().

    Raises
    ------
    ValueError
        If type is missing or not one of the supported values.
    """
    source_type = raw.get("type")
    if source_type == "rdf_file":
        return {
            "type":      "rdf_file",
            "file_path": raw.get("file_path"),
            "format":    raw.get("format"),
        }
    elif source_type == "sparql_endpoint":
        return {
            "type":         "sparql_endpoint",
            "endpoint_url": raw.get("endpoint_url"),
            "query":        raw.get("query"),
        }
    else:
        raise ValueError(f"Unsupported source type: '{source_type}'")


def _to_json(results: list) -> str:
    """
    Serialise evaluation results to a formatted JSON string.

    Parameters
    ----------
    results : list of dict
        Evaluation results as plain dicts, one entry per dataset.

    Returns
    -------
    str
        Pretty-printed JSON string with 2-space indentation.
    """
    return json.dumps(results, indent=2, ensure_ascii=False)


def _to_csv(results: list) -> str:
    """
    Serialise evaluation results to a CSV string.

    Produces one row per (dataset, metric) combination. Columns are
    dataset_id, dataset_label, metric_id, metric_name, score, status.

    Scores are formatted to 4 decimal places. Metrics that did not
    produce a numeric score (status error or not_applicable) are
    represented as N/A.

    Parameters
    ----------
    results : list of dict
        Evaluation results as plain dicts, one entry per dataset.

    Returns
    -------
    str
        CSV content including a header row.
    """
    lines = ["dataset_id,dataset_label,metric_id,metric_name,score,status"]
    for dataset in results:
        for metric in dataset.get("metrics", []):
            score = metric.get("score")
            score_str = f"{score:.4f}" if score is not None else "N/A"
            lines.append(",".join([
                dataset.get("dataset_id", ""),
                f'"{dataset.get("label", "")}"',
                metric.get("metric_id", ""),
                f'"{metric.get("name", "")}"',
                score_str,
                metric.get("status", ""),
            ]))
    return "\n".join(lines)


def list_metrics() -> None:
    """
    Print all available metric IDs and their descriptions to stdout.

    Reads from the metrics configuration file via load_metrics_config.
    Each metric is printed with its ID on one line and its description
    indented on the next.

    Returns
    -------
    None
    """
    from config.config_loader import load_metrics_config
    config = load_metrics_config()
    print("\nAvailable metrics:\n")
    for metric_id, meta in config.items():
        print(f"  {metric_id}")
        print(f"      {meta.get('description', '')}")
        print()


def _render_tree(nodes: list, prefix: str = "", is_last_list: list = None) -> None:
    """
    Recursively print a class hierarchy tree to stdout.

    Each node is printed with its label, full URI, and instance count.
    Properties used by the class are listed beneath it, showing the
    local name and the number of instances that use each property.
    Child classes are indented and connected with box-drawing characters.

    Parameters
    ----------
    nodes : list of ClassNode
        Class nodes to render at the current level of the hierarchy.
    prefix : str
        The indentation prefix accumulated from parent levels.
    is_last_list : list of bool or None
        Tracks whether each ancestor node was the last sibling at its
        level, used to draw vertical continuation lines correctly.

    Returns
    -------
    None
    """
    if is_last_list is None:
        is_last_list = []

    for i, node in enumerate(nodes):
        is_last = (i == len(nodes) - 1)

        if prefix:
            connector = "└── " if is_last else "├── "
        else:
            connector = ""

        print(f"{prefix}{connector}{node.label}  ({node.instance_count} instances)")
        print(f"{prefix}{'    ' if is_last else '│   '}  {node.uri}")

        if node.properties:
            child_prefix = prefix + ("    " if is_last else "│   ") + "  "
            top_props = node.properties[:5]
            prop_line = ", ".join(
                f"{p.label} ({p.count})" for p in top_props
            )
            if len(node.properties) > 5:
                prop_line += f", ... +{len(node.properties) - 5} more"
            print(f"{child_prefix}properties: {prop_line}")

        if node.children:
            child_prefix = prefix + ("    " if is_last else "│   ")
            _render_tree(node.children, prefix=child_prefix)

        if not is_last:
            print(f"{prefix}│")


def inspect(config: dict) -> None:
    """
    Extract and display the class hierarchy for all datasets in a config.

    For each dataset, loads the graph via the data source layer (which
    uses the shared cache internally), runs the ontology extractor, and
    prints the resulting class tree to stdout. The metrics and output
    sections of the config are ignored.

    Parameters
    ----------
    config : dict
        Parsed configuration as returned by load_config_for_inspect.
        Only the datasets key is used.

    Returns
    -------
    None

    Raises
    ------
    DataSourceLoadError
        If a dataset cannot be loaded from its source.
    """
    from datasource.datasource_factory import DataSourceFactory
    from graph.graph_cache import get_or_load
    from graph.ontology_extractor import extract

    for ds in config["datasets"]:
        label = ds.get("label", ds["id"])
        print(f"\n{'─' * 60}")
        print(f"  {label}")
        print(f"  id: {ds['id']}")
        print(f"{'─' * 60}\n")

        source_config = _build_source_config(ds["source_config"])

        try:
            def _load(sc=source_config):
                datasource = DataSourceFactory.create(sc)
                return datasource.load()

            graph = get_or_load(source_config, _load)
        except Exception as e:
            print(f"  ERROR: Could not load dataset — {e}\n", file=sys.stderr)
            continue

        nodes = extract(graph)

        if not nodes:
            print("  No typed classes found in this dataset.\n")
            continue

        total_instances = sum(n.instance_count for n in nodes)
        print(f"  {len(nodes)} class(es) — {total_instances} total instances\n")

        _render_tree(nodes)
        print()


def run(config: dict) -> list:
    """
    Execute the evaluation pipeline for all datasets and metrics in
    the configuration.

    Resolves metric plugins from the registry, builds dataset descriptors,
    and delegates to the EvaluationEngine. Metrics not found in the config
    or registry are skipped with a warning printed to stderr. A summary
    of scores is printed to stderr after evaluation completes.

    Parameters
    ----------
    config : dict
        Parsed configuration as returned by load_config. All three
        top-level keys (datasets, metrics, output) may be present,
        but only datasets and metrics are used by this function.

    Returns
    -------
    list of dict
        Serialised evaluation results, one dict per dataset. Each dict
        contains:

        dataset_id (str): The dataset identifier from the config.

        label (str): The human-readable dataset label.

        overall_score (float or None): Weighted mean score across all
        computed metrics.

        stats (dict or None): Graph statistics with keys triple_count,
        entity_count, and class_count.

        metrics (list of dict): Per-metric results, each containing
        metric_id, name, score, weight, status, and details.

    Raises
    ------
    SystemExit
        If no valid metrics could be resolved from the registry.
        Exit code is 1.
    """
    from engine.evaluation_engine import EvaluationEngine
    from config.config_loader import load_metrics_config
    from metrics.metric_registry import METRIC_REGISTRY

    metric_config = load_metrics_config()
    engine = EvaluationEngine()

    metrics = []
    for metric_id in config["metrics"]:
        if metric_id not in metric_config:
            print(f"WARNING: metric '{metric_id}' not in config — skipping.", file=sys.stderr)
            continue
        metric_class = METRIC_REGISTRY.get(metric_id)
        if not metric_class:
            print(f"WARNING: no plugin for '{metric_id}' — skipping.", file=sys.stderr)
            continue
        metrics.append(metric_class())

    if not metrics:
        print("ERROR: No valid metrics to run.", file=sys.stderr)
        sys.exit(1)

    datasets = []
    for ds in config["datasets"]:
        source_config = _build_source_config(ds["source_config"])
        scope = ds.get("scope") or None
        datasets.append({
            "dataset_id":    ds["id"],
            "label":         ds.get("label", ds["id"]),
            "source_config": source_config,
            "scope":         scope,
        })

    print(
        f"\nRunning {len(metrics)} metric(s) on {len(datasets)} dataset(s)...\n",
        file=sys.stderr,
    )

    results_domain = engine.evaluate(datasets=datasets, metrics=metrics)

    results = []
    for dr in results_domain:
        results.append({
            "dataset_id":    dr.dataset_id,
            "label":         dr.label,
            "overall_score": dr.overall_score,
            "stats":         dr.stats,
            "metrics": [
                {
                    "metric_id":       m.metric_id,
                    "name":            m.name,
                    "score":           m.score,
                    "weight":          m.weight,
                    "status":          m.status,
                    "details":         m.details,
                    "runtime_seconds": m.runtime_seconds,   # add this
                }
                for m in dr.metrics
            ],
        })

    print("Summary:", file=sys.stderr)
    for dr in results:
        score_str = (
            f"{dr['overall_score']:.4f}"
            if dr["overall_score"] is not None else "N/A"
        )
        print(f"  [{score_str}]  {dr['label']}", file=sys.stderr)
        for m in dr["metrics"]:
            m_score = f"{m['score']:.4f}" if m["score"] is not None else "N/A"
            print(f"           {m['name']}: {m_score}  ({m['status']})", file=sys.stderr)
    print("", file=sys.stderr)

    return results

def benchmark(config: dict) -> None:
    """
    Measure and compare cold-cache versus warm-cache evaluation time.

    Runs the evaluation twice using the same configuration:

    Cold run: the graph cache is cleared before running so the dataset
    must be loaded from disk or fetched from the network. This measures
    the full cost including file I/O, RDF parsing, and metric computation.

    Warm run: the cache is populated from the cold run so the dataset
    is served from memory. This measures only metric computation cost,
    with no I/O or parsing overhead.

    The difference between the two times represents the parsing cost
    eliminated by the cache on subsequent evaluations of the same dataset.
    This is the primary performance benefit of the shared graph cache.

    A summary table is printed to stderr with cold time, warm time,
    time saved, and speedup factor per dataset. Results from the warm
    run are written to the configured output path if one is set.

    Parameters
    ----------
    config : dict
        Parsed configuration as returned by load_config.

    Returns
    -------
    None
    """
    from graph.graph_cache import clear as clear_cache

    print("\nClearing cache — cold run starting...\n", file=sys.stderr)
    clear_cache()

    t0 = time.perf_counter()
    results = run(config)
    cold_time = time.perf_counter() - t0

    print("Warm run starting (cache populated)...\n", file=sys.stderr)

    t1 = time.perf_counter()
    results = run(config)
    warm_time = time.perf_counter() - t1

    dataset_stats = {
        dr["dataset_id"]: dr.get("stats") or {}
        for dr in results
    }

    speedup = cold_time / warm_time if warm_time > 0 else float("inf")
    saved   = cold_time - warm_time

    print("", file=sys.stderr)
    print("─" * 60, file=sys.stderr)
    print("  Benchmark results", file=sys.stderr)
    print("─" * 60, file=sys.stderr)
    print(f"  Cold run (parse + evaluate):  {cold_time:.3f}s", file=sys.stderr)
    print(f"  Warm run (evaluate only):     {warm_time:.3f}s", file=sys.stderr)
    print(f"  Parsing cost eliminated:      {saved:.3f}s", file=sys.stderr)
    print(f"  Speedup factor:               {speedup:.1f}x", file=sys.stderr)
    print("", file=sys.stderr)

    # Per-dataset breakdown
    print("  Per-dataset breakdown:", file=sys.stderr)
    for dr in results:
        stats       = dataset_stats.get(dr["dataset_id"], {})
        triple_count = stats.get("triple_count", "N/A")
        print(
            f"    {dr['label']}: {triple_count} triples",
            file=sys.stderr,
        )
    print("─" * 60, file=sys.stderr)
    print("", file=sys.stderr)

    print("  Per-metric runtime (warm run):", file=sys.stderr)
    for dr in results:
        print(f"    {dr['label']}:", file=sys.stderr)
        for m in dr["metrics"]:
            rt = m.get("runtime_seconds")
            rt_str = f"{rt:.3f}s" if rt is not None else "N/A"
            print(f"      {m['name']:<45} {rt_str}", file=sys.stderr)
    print("─" * 60, file=sys.stderr)
    print("", file=sys.stderr)

    return results


def write_output(results: list, output_config: dict | None) -> None:
    """
    Write evaluation results to a file or stdout.

    Relative paths in output_config path are resolved relative to the
    cli/ directory so that results always land in a predictable location
    regardless of the working directory when the CLI is invoked. Absolute
    paths are used as-is.

    Parameters
    ----------
    results : list of dict
        Serialised evaluation results as returned by run.
    output_config : dict or None
        Output configuration from the YAML file. Expected keys:

        path (str, optional): Destination file path. If omitted,
        results are printed to stdout.

        format (str, optional): json (default) or csv.

    Returns
    -------
    None

    Raises
    ------
    OSError
        If the output directory cannot be created or the file cannot
        be written.
    """
    fmt  = (output_config or {}).get("format", "json").lower()
    path = (output_config or {}).get("path")

    content = _to_csv(results) if fmt == "csv" else _to_json(results)

    if path:
        out_path = (
            CLI_DIR / path if not Path(path).is_absolute() else Path(path)
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
        print(f"Results written to: {out_path}", file=sys.stderr)
    else:
        print(content)


def main() -> None:
    """
    Parse command-line arguments and dispatch to the appropriate handler.

    Available commands
    ------------------
    --config FILE
        Run a full evaluation using the specified YAML config file.

    --inspect FILE
        Display the class hierarchy for all datasets in the config file
        without running any metrics. Useful for exploring a dataset
        before writing a scoped evaluation config.

    --benchmark FILE
        Run the evaluation twice — cold cache then warm cache — and
        report the time difference. Demonstrates the parsing cost
        eliminated by the shared graph cache on repeated evaluations.

    --template
        Print a filled example config to stdout and exit. Redirect to
        a file to create a new config:
        python cli/cli.py --template > cli/configs/my_evaluation.yaml

    --list-metrics
        Print all available metric IDs and descriptions, then exit.

    --help
        Show all available commands with their descriptions and exit.

    Returns
    -------
    None

    Raises
    ------
    SystemExit
        On argument errors, missing config file, config validation
        failure, or evaluation errors. Exit code is 0 on success and
        1 on any error.
    """
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Metadata quality evaluation CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python cli/cli.py --config cli/configs/my_evaluation.yaml
              python cli/cli.py --inspect cli/configs/my_evaluation.yaml
              python cli/cli.py --benchmark cli/configs/my_evaluation.yaml
              python cli/cli.py --template > cli/configs/my_evaluation.yaml
              python cli/cli.py --list-metrics
        """),
    )
    parser.add_argument(
        "--config", "-c", metavar="FILE",
        help="Run a full evaluation from a YAML config file.",
    )
    parser.add_argument(
        "--inspect", "-i", metavar="FILE",
        help="Display the class hierarchy for all datasets in a config file.",
    )
    parser.add_argument(
        "--benchmark", "-b", metavar="FILE",
        help="Run cold then warm evaluation and report cache speedup.",
    )
    parser.add_argument(
        "--template", "-t", action="store_true",
        help="Print a filled example config to stdout and exit.",
    )
    parser.add_argument(
        "--list-metrics", "-l", action="store_true",
        help="List available metric IDs and exit.",
    )

    args = parser.parse_args()

    if args.template:
        print(TEMPLATE)
        sys.exit(0)

    if args.list_metrics:
        list_metrics()
        sys.exit(0)

    if args.inspect:
        if not Path(args.inspect).exists():
            print(f"ERROR: Config file not found: {args.inspect}", file=sys.stderr)
            sys.exit(1)
        try:
            config = load_config_for_inspect(args.inspect)
        except Exception as e:
            print(f"ERROR loading config: {e}", file=sys.stderr)
            sys.exit(1)
        try:
            inspect(config)
        except Exception as e:
            print(f"ERROR during inspection: {e}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    if args.benchmark:
        if not Path(args.benchmark).exists():
            print(f"ERROR: Config file not found: {args.benchmark}", file=sys.stderr)
            sys.exit(1)
        try:
            config = load_config(args.benchmark)
        except Exception as e:
            print(f"ERROR loading config: {e}", file=sys.stderr)
            sys.exit(1)
        try:
            results = benchmark(config)
        except Exception as e:
            print(f"ERROR during benchmark: {e}", file=sys.stderr)
            sys.exit(1)
        write_output(results, config.get("output"))
        sys.exit(0)

    if args.config:
        if not Path(args.config).exists():
            print(f"ERROR: Config file not found: {args.config}", file=sys.stderr)
            sys.exit(1)
        try:
            config = load_config(args.config)
        except Exception as e:
            print(f"ERROR loading config: {e}", file=sys.stderr)
            sys.exit(1)
        try:
            results = run(config)
        except Exception as e:
            print(f"ERROR during evaluation: {e}", file=sys.stderr)
            sys.exit(1)
        write_output(results, config.get("output"))
        sys.exit(0)

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()