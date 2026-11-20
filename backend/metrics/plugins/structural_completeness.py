"""
metrics/plugins/structural_completeness.py
------------------------------------------
Measures whether records carry the properties their schema profile expects.

Unlike the data-driven metrics, this one validates against an external
expectation: a SHACL shape profile. The profile is detected from the data
by counting how many URIs — in subject, predicate, and object position —
belong to each known vocabulary namespace. Counting all three positions
rather than instances alone keeps detection working on a scoped subgraph
that contains no instances of a target class.

When no known vocabulary dominates, a generic core profile is used and
the result is flagged as low_confidence, since a score produced against
a profile that does not describe the data says little about its quality.

The profile can also be chosen per dataset through the profile option.
Detection still runs, so a choice that differs from what the data
suggests is reported alongside the result rather than hidden.

Score
-----
Each record scores

    1 - (missing constraints / expected constraints)

where the expected count is the number of distinct constraint messages in
the profile. Messages are deduplicated, so a property required by several
shapes is not counted more than once. The metric score is the mean of the
per-record scores.
"""

from pathlib import Path
from pyshacl import validate
from rdflib import Graph, URIRef
from rdflib.collection import Collection
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

# Known profiles. Adding one is a new shapes file plus an entry here; the
# namespaces are what detection counts in the data.
PROFILES = {
    "edm": {
        "name":       "Europeana Data Model (EDM)",
        "file":       SHAPES_DIR / "edm_profile.ttl",
        "namespaces": [
            "http://www.europeana.eu/schemas/edm/",
            "http://www.openarchives.org/ore/terms/",
        ],
    },
    "core": {
        "name":       "Generic core profile",
        "file":       SHAPES_DIR / "core_profile.ttl",
        "namespaces": [],
    },
}
FALLBACK_PROFILE = "core"
AUTO_PROFILE = "auto"


def detect_profile(graph: Graph) -> tuple[str, Path]:
    """
    Detects the appropriate SHACL shape profile by counting how many
    URIs in the graph belong to each known vocabulary namespace.

    Unlike instance-count-based detection, this approach inspects all
    URI positions — subjects, predicates, and objects — and selects
    the profile whose namespaces appear most frequently, summed per
    profile. This makes
    detection robust to scoped subgraphs that may not contain any
    instances of specific target classes but still use predicates or
    object URIs from a known vocabulary.

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
        If URI counting fails due to an unexpected graph error.
    """
    try:
        profile_counts: dict[str, int] = {
            profile_id: 0
            for profile_id, profile in PROFILES.items()
            if profile["namespaces"]
        }

        for subject, predicate, obj in graph:
            for uri_term in (subject, predicate, obj):
                if not isinstance(uri_term, URIRef):
                    continue
                uri_str = str(uri_term)
                for profile_id in profile_counts:
                    if any(uri_str.startswith(ns)
                           for ns in PROFILES[profile_id]["namespaces"]):
                        profile_counts[profile_id] += 1

        # Namespaces are summed per profile, so a vocabulary split over
        # several namespaces (EDM uses edm: and ore:) counts as one.
        active = {pid: count for pid, count in profile_counts.items() if count > 0}

        if active:
            dominant = max(active, key=lambda pid: active[pid])
            return dominant, PROFILES[dominant]["file"]

        return FALLBACK_PROFILE, PROFILES[FALLBACK_PROFILE]["file"]

    except Exception as e:
        raise ProfileDetectionError(
            f"Failed to detect schema profile from graph: {e}"
        ) from e


def describe_profiles() -> list[dict]:
    """
    Describe every known profile in a form a person can read.

    Lists, for each profile, the shapes it contains: which resources
    each shape targets and which properties it requires. A shape-level
    sh:or is reported as one requirement satisfied by any of its paths.

    Returns
    -------
    list[dict]
        One entry per profile:

            {
                "id":          str,
                "name":        str,
                "is_fallback": bool,
                "shapes": [
                    {
                        "targets":    [{"kind": str, "uri": str, "label": str}],
                        "properties": [{"path": str, "severity": str | None,
                                        "message": str | None}]
                    }
                ]
            }

    Raises
    ------
    ShapeProfileNotFoundError
        If a registered shapes file is missing.
    MetricConfigurationError
        If a registered shapes file cannot be parsed.
    """
    profiles = []
    for profile_id, profile in PROFILES.items():
        shapes_graph = load_shapes(profile["file"])

        def _label(term) -> str:
            """Return a prefixed name such as dc:title, or the URI."""
            try:
                return shapes_graph.namespace_manager.normalizeUri(term)
            except Exception:
                return str(term)

        def _severity(node) -> str | None:
            """Return Violation, Warning or Info, or None when unset."""
            value = shapes_graph.value(node, SH.severity)
            return str(value).rsplit("#", 1)[-1] if value is not None else None

        shapes = []
        for shape in sorted(shapes_graph.subjects(RDF.type, SH.NodeShape), key=str):
            targets = [
                {"kind": kind, "uri": str(uri), "label": _label(uri)}
                for kind, predicate in (("class", SH.targetClass),
                                        ("subjects_of", SH.targetSubjectsOf))
                for uri in shapes_graph.objects(shape, predicate)
            ]

            properties = []
            for prop in shapes_graph.objects(shape, SH.property):
                path = shapes_graph.value(prop, SH.path)
                message = shapes_graph.value(prop, SH.message)
                properties.append({
                    "path":     _label(path) if path is not None else "",
                    "severity": _severity(prop),
                    "message":  str(message) if message is not None else None,
                })

            for alternatives in shapes_graph.objects(shape, SH["or"]):
                paths = [
                    _label(shapes_graph.value(prop, SH.path))
                    for member in Collection(shapes_graph, alternatives)
                    for prop in shapes_graph.objects(member, SH.property)
                    if shapes_graph.value(prop, SH.path) is not None
                ]
                message = shapes_graph.value(shape, SH.message)
                properties.append({
                    "path":     " or ".join(paths),
                    "severity": _severity(shape),
                    "message":  str(message) if message is not None else None,
                })

            shapes.append({
                "targets":    targets,
                "properties": sorted(properties, key=lambda p: p["path"]),
            })

        profiles.append({
            "id":          profile_id,
            "name":        profile["name"],
            "is_fallback": profile_id == FALLBACK_PROFILE,
            "shapes":      shapes,
        })
    return profiles


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
    """
    Validates records against a detected SHACL profile and scores them
    on the proportion of expected properties they actually carry.
    """

    id = "structural_completeness"

    options = {
        "profile": {
            "label":   "SHACL profile",
            "default": AUTO_PROFILE,
            "choices": [{"id": AUTO_PROFILE, "label": "Auto (detect from the data)"}]
                       + [{"id": pid, "label": p["name"]} for pid, p in PROFILES.items()],
        },
    }

    def evaluate(self, context: DatasetContext) -> MetricResult:
        """
        Evaluates the structural completeness of a dataset using SHACL validation.

        The evaluation process includes:
        1. Detecting the appropriate schema profile, or using the one
           chosen for this dataset
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
            choice = self.resolve_options(
                context.options.get(self.id)
            )["profile"]
        except MetricConfigurationError as e:
            return self.error_result(str(e))

        try:
            detected_profile, detected_path = detect_profile(graph)
        except ProfileDetectionError as e:
            return self.error_result(str(e))

        if choice == AUTO_PROFILE:
            profile_name, shapes_path = detected_profile, detected_path
            profile_source = "detected"
        else:
            profile_name = choice
            shapes_path  = PROFILES[choice]["file"]
            profile_source = "selected"

        low_confidence = (profile_name == FALLBACK_PROFILE)

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
            if not all_records and profile_source == "selected":
                targets = sorted(
                    shapes_graph.namespace_manager.normalizeUri(t)
                    for t in shapes_graph.objects(None, SH.targetClass)
                )
                raise NoTargetRecordsError(
                    f"The selected profile, {PROFILES[profile_name]['name']}, "
                    f"found no matching records in this dataset. It checks "
                    f"resources of type {', '.join(targets) or 'any'}; "
                    f"detection suggests "
                    f"{PROFILES[detected_profile]['name']} instead."
                )
            if not all_records:
                raise NoTargetRecordsError(
                    f"No records matching the '{profile_name}' profile "
                    f"were found in dataset '{context.dataset_id}'."
                )
        except NoTargetRecordsError as e:
            return self.error_result(str(e))

        total_records  = len(all_records)
        num_properties = count_shape_properties(shapes_graph)
        violations     = extract_violations(results_graph)

        per_record_scores = compute_per_record_scores(
            all_records, violations, num_properties
        )

        score_values = list(per_record_scores.values())
        final_score  = round(statistics.mean(score_values), 4)

        details = {
            "profile":                    profile_name,
            "profile_name":               PROFILES[profile_name]["name"],
            "profile_source":             profile_source,
            "low_confidence":             low_confidence,
            "total_records":              total_records,
            "median_record_completeness": round(statistics.median(score_values), 4),
            "min_record_completeness":    round(min(score_values), 4),
            "max_record_completeness":    round(max(score_values), 4),
            "score_distribution":         compute_score_distribution(per_record_scores),
            "class_statistics":           compute_class_statistics(per_record_scores, graph),
        }

        if profile_source == "selected" and profile_name != detected_profile:
            details["detected_profile"] = detected_profile
            details["warning"] = (
                f"{PROFILES[profile_name]['name']} was selected, "
                f"but the data looks like "
                f"{PROFILES[detected_profile]['name']}. "
                f"Scores reflect the selected profile."
            )
        elif low_confidence:
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