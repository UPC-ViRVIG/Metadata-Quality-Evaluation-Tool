from pathlib import Path
from pyshacl import validate
from rdflib import Graph, URIRef
from rdflib.namespace import SH, RDF
import statistics

from metrics.metric_plugin import MetricPlugin
from models.dataset_context import DatasetContext
from models.metric_result import MetricResult
from metrics.metrics_exceptions import (
    MetricConfigurationError,
    MetricExecutionError,
    ShapeProfileNotFoundError,
    EmptyGraphError,
    NoTargetRecordsError,
    ProfileDetectionError
)

SHAPES_DIR = Path(__file__).parent.parent / "shapes"

TYPE_SIGNATURES = {
    "http://www.europeana.eu/schemas/edm/ProvidedCHO": ("edm", SHAPES_DIR / "edm_profile.ttl"),
    "http://www.openarchives.org/ore/terms/Proxy":     ("edm", SHAPES_DIR / "edm_profile.ttl"),
}
CORE_PROFILE = ("core", SHAPES_DIR / "core_profile.ttl")


def detect_profile(graph: Graph) -> tuple[str, Path]:
    """
    Detects the appropriate SHACL shape profile by inspecting
    rdf:type values present in the graph.
    Returns the profile whose target type appears most frequently,
    ensuring correct detection even in mixed or partially-conforming
    datasets.

    Parameters
    ----------
    graph:
        an rdflib.Graph representing the dataset

    Returns
    -------
    tuple[str, pathlib.Path]
        A tuple containing:
        - profile_name (str): Identifier of the detected profile
        - shapes_path (Path): Path to the SHACL shape file

    Raises
    ------
    ProfileDetectionError
        If type counting fails due to an unexpected graph error.
    """
    try:
        type_counts = {}
        for type_uri, profile in TYPE_SIGNATURES.items():
            count = len(set(graph.subjects(RDF.type, URIRef(type_uri))))
            if count > 0:
                type_counts[type_uri] = (count, profile)

        if type_counts:
            dominant = max(type_counts.items(), key=lambda x: x[1][0])
            return dominant[1][1]

        return CORE_PROFILE

    except Exception as e:
        raise ProfileDetectionError(
            f"Failed to detect schema profile from graph: {e}"
        ) from e


def load_shapes(shapes_path: Path) -> Graph:
    """
    Parses a SHACL shapes file into an rdflib Graph.

    Parameters
    ----------
    shapes_path
        Path to the SHACL shapes file (ttl format)

    Returns
    -------
    shapes_graph
        An rdflib Graph of the SHACL shape

    Raises
    ------
    ShapeProfileNotFoundError
        If the shapes file does not exist at the given path.
    MetricConfigurationError
        If the shapes file exists but cannot be parsed.
    """
    if not shapes_path.exists():
        raise ShapeProfileNotFoundError(
            f"Shape profile not found: {shapes_path.name}. "
            f"Expected location: {shapes_path}"
        )

    try:
        shapes_graph = Graph()
        shapes_graph.parse(str(shapes_path), format="turtle")
        return shapes_graph
    except Exception as e:
        raise MetricConfigurationError(
            f"Failed to parse shape profile '{shapes_path.name}': {e}"
        ) from e


def get_target_records(shapes_graph: Graph, data_graph: Graph) -> set[str]:
    """
    Extracts the set of target record URIs defined by a SHACL shape.
    Supports 
    - sh:targetClass (selects subjects with matching rdf:type)
    - sh:targetSubjectsOf (selects subjects having a given property)

    Parameters
    ----------
    shapes_graph
        The SHACL shapes graph.
    data_graph
        The RDF data graph being evaluated.

    Returns
    -------
    set[str]
        A set of record URIs (as strings) targeted by the shape.
        Returns an empty set if no targeting rules are defined.
    """
    target_classes = list(shapes_graph.objects(None, SH.targetClass))
    if target_classes:
        subjects = set()
        for cls in target_classes:
            subjects.update(
                str(s) for s in data_graph.subjects(RDF.type, cls)
            )
        return subjects

    target_props = list(shapes_graph.objects(None, SH.targetSubjectsOf))
    if target_props:
        subjects = set()
        for prop in target_props:
            subjects.update(
                str(s) for s in data_graph.subjects(prop, None)
            )
        return subjects

    return set()


def extract_violations(results_graph: Graph) -> dict[str, list[str]]:
    """
    Extracts validation violations from a SHACL results graph.
    Each violation is grouped by its message, mapping to the list
    of focus nodes (records) that failed the constraint.
    All severities are included, as every violation contributes
    equally to completeness scoring.

    Parameters
    ----------
    results_graph
        The SHACL validation results graph.

    Returns
    -------
    dict[str, list[str]]
        A dictionary where:
        - key: violation message (str)
        - value: list of record URIs (str) that violate the constraint
    """
    violations: dict[str, list[str]] = {}

    for node in results_graph.subjects(SH.resultSeverity, None):
        name  = results_graph.value(node, SH.resultMessage)
        focus = results_graph.value(node, SH.focusNode)
        if focus is None:
            continue
        key = str(name) if name else "unknown"
        violations.setdefault(key, []).append(str(focus))

    return violations


def compute_per_record_scores(
    all_records: set[str],
    violations: dict[str, list[str]],
    num_properties: int
) -> dict[str, float]:
    """
    Computes a completeness score for each record.
    Score = (expected properties - missing properties) / expected properties
    Records with no violations score 1.0.

    Parameters
    ----------
    all_records : set[str]
        Set of all record URIs in the dataset.
    violations : dict[str, list[str]]
        Mapping of violation messages to lists of affected record URIs.
    num_properties : int
        Total number of expected properties (constraints) per record.

    Returns
    -------
    dict[str, float]
        A dictionary mapping each record URI to its completeness score
        (range: 0.0 to 1.0).
    """
    if num_properties == 0:
        return {record: 1.0 for record in all_records}

    missing_per_record: dict[str, int] = {}
    for _, nodes in violations.items():
        for node in nodes:
            missing_per_record[node] = missing_per_record.get(node, 0) + 1

    return {
        record: round(
            1 - missing_per_record.get(record, 0) / num_properties, 4
        )
        for record in all_records
    }


def compute_score_distribution(
    per_record_scores: dict[str, float]
) -> dict[str, int]:
    """
    Computes a histogram distribution of completeness scores.
    Scores are grouped into bins of width 0.1 (e.g., 0.0, 0.1, ..., 1.0).

    Parameters
    ----------
    per_record_scores : dict[str, float]
        Mapping of record URIs to their completeness scores.

    Returns
    -------
    dict[str, int]
        A dictionary where:
        - key: score bin as string (e.g., "0.0", "0.1", ..., "1.0")
        - value: number of records in that bin
    """
    bins = {f"{round(i / 10, 1)}": 0 for i in range(11)}

    for score in per_record_scores.values():
        bucket = min(round(round(score * 10) / 10, 1), 1.0)
        bins[str(bucket)] += 1

    return bins


def compute_class_statistics(
    per_record_scores: dict[str, float],
    data_graph: Graph
) -> dict[str, dict]:
    """
    Computes summary statistics of completeness scores grouped by rdf:type.

    Each record contributes to all of its rdf:type classes.
    Records without a type are grouped under "Unknown".

    Parameters
    ----------
    per_record_scores : dict[str, float]
        Mapping of record URIs to completeness scores.
    data_graph
        The RDF data graph used to retrieve rdf:type information.

    Returns
    -------
    dict[str, dict]
        A dictionary where:
        - key: class URI (str) or "Unknown"
        - value: dict containing:
            - "count": number of records
            - "mean": average score
            - "median": median score
            - "min": minimum score
            - "max": maximum score
            - "scores": scores of items in a class
    """
    class_scores: dict[str, list[float]] = {}

    for record_uri, score in per_record_scores.items():
        types = list(data_graph.objects(URIRef(record_uri), RDF.type))
        class_labels = [str(t) for t in types] if types else ["Unknown"]

        for label in class_labels:
            class_scores.setdefault(label, []).append(score)

    return {
        cls: {
            "count":  len(scores),
            "mean":   round(statistics.mean(scores),   4),
            "median": round(statistics.median(scores), 4),
            "min":    round(min(scores), 4),
            "max":    round(max(scores), 4),
            "scores": scores,
        }
        for cls, scores in class_scores.items()
    }


def count_shape_properties(shapes_graph: Graph) -> int:
    """
    Counts the number of distinct constraints defined in a SHACL shape.

    The count includes:
    - sh:message values attached to sh:property constraints
    - sh:message values attached to sh:or constraints at node shape level

    This count represents the number of expected properties used
    to compute completeness scores.

    Parameters
    ----------
    shapes_graph
        The SHACL shapes graph.

    Returns
    -------
    int
        The number of distinct constraint messages.
        Returns 1 as a fallback to avoid division by zero.
    """
    property_messages = set()
    for prop_node in shapes_graph.objects(None, SH.property):
        msg = shapes_graph.value(prop_node, SH.message)
        if msg:
            property_messages.add(str(msg))

    or_messages = set()
    for shape in shapes_graph.subjects(RDF.type, SH.NodeShape):
        msg = shapes_graph.value(shape, SH.message)
        if msg:
            or_messages.add(str(msg))

    total = len(property_messages) + len(or_messages)
    return total if total > 0 else 1


class StructuralCompletenessMetric(MetricPlugin):

    id = "structural_completeness"

    def evaluate(self, context: DatasetContext) -> MetricResult:
        """
        Evaluates the structural completeness of a dataset using SHACL validation.

        The evaluation process includes:
        1. Detecting the appropriate schema profile
        2. Loading the corresponding SHACL shapes
        3. Running SHACL validation
        4. Identifying target records
        5. Computing per-record completeness scores
        6. Aggregating statistics into a final score and detailed report

        Parameters
        ----------
        context : DatasetContext
            Contains dataset metadata and the RDF graph to evaluate.

        Returns
        -------
        MetricResult
            The result object containing:
            - overall completeness score
            - metric metadata
            - detailed statistics and distributions

        Raises
        ------
        EmptyGraphError
            If the dataset graph is empty.

        MetricExecutionError
            If SHACL validation fails unexpectedly.
        """
        graph = context.graph

        if len(graph) == 0:
            raise EmptyGraphError(
                f"Dataset '{context.dataset_id}' contains an empty graph."
            )

        try:
            profile_name, shapes_path = detect_profile(graph)
        except ProfileDetectionError as e:
            return self.error_result(str(e))

        low_confidence = (profile_name == "core")

        try:
            shapes_graph = load_shapes(shapes_path)
        except (ShapeProfileNotFoundError, MetricConfigurationError) as e:
            return self.error_result(str(e))

        try:
            _, results_graph, _ = validate(
                graph,
                shacl_graph=shapes_graph,
                advanced=True,
                inference="none",
            )
        except Exception as e:
            raise MetricExecutionError(
                f"SHACL validation failed for dataset "
                f"'{context.dataset_id}': {e}"
            ) from e

        try:
            all_records = get_target_records(shapes_graph, graph)
            if not all_records:
                raise NoTargetRecordsError(
                    f"No records matching the '{profile_name}' profile "
                    f"were found in dataset '{context.dataset_id}'."
                )
        except NoTargetRecordsError as e:
            return self.error_result(str(e))

        total_records   = len(all_records)
        num_properties  = count_shape_properties(shapes_graph)
        violations      = extract_violations(results_graph)

        per_record_scores = compute_per_record_scores(
            all_records, violations, num_properties
        )

        score_values  = list(per_record_scores.values())
        final_score   = round(statistics.mean(score_values), 4)

        details = {
            "profile":                   profile_name,
            "low_confidence":            low_confidence,
            "total_records":             total_records,
            "median_record_completeness": round(statistics.median(score_values), 4),
            "min_record_completeness":    round(min(score_values), 4),
            "max_record_completeness":    round(max(score_values), 4),
            "score_distribution":        compute_score_distribution(per_record_scores),
            "class_statistics":          compute_class_statistics(per_record_scores, graph),
        }

        if low_confidence:
            details["warning"] = (
                "No standard schema profile was detected. "
                "Evaluation used the core fallback profile. "
                "Results may not reflect domain-specific requirements."
            )

        return MetricResult(
            metric_id=self.id,
            name=self.name,
            score=final_score,
            weight=self.weight,
            status="computed",
            details=details,
        )