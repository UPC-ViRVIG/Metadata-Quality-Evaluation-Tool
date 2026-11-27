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
suggests is reported alongside the result rather than hidden. Besides the
built-in profiles, users can add their own SHACL files, kept by
metrics/profile_store.py. Auto prefers an added profile: if any added
profile targets records in the data, the one targeting the most is used,
and only otherwise does detection fall back to the built-in vocabularies.

Score
-----
Each record scores

    1 - (constraints failed / constraints expected)

counting only the constraints of the shapes that target that record. A
WebResource is scored out of what a WebResource must have, not out of
everything the profile asks of every class. Each constraint is counted
once, however many values break it, and every severity counts equally.
The metric score is the mean of the per-record scores.

This replaced an earlier rule that divided by every constraint in the
profile. Requirements of other classes, which a record can never fail,
then counted as met, which inflated scores most for small classes in
large profiles. Results carry scoring_version so the two can be told
apart.
"""

import hashlib
from pathlib import Path
from pyshacl import validate
from rdflib import Graph, URIRef
from rdflib.collection import Collection
from rdflib.namespace import SH, RDF, RDFS
import statistics

from metrics.metric_plugin import MetricPlugin
from metrics.shacl_shapes import (
    failed_constraints,
    record_constraints,
    shape_constraints,
    shapes_with_targets,
)
from metrics import profile_store
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


def all_profiles() -> dict[str, dict]:
    """
    Return the built-in profiles and those users have added.

    Returns
    -------
    dict[str, dict]
        Profile ids mapped to their entries. Built-in entries come first
        and are marked uploaded False.
    """
    builtin = {pid: {**p, "uploaded": False} for pid, p in PROFILES.items()}
    return {**builtin, **profile_store.uploaded_profiles()}


def register_profile(
    filename: str,
    content: bytes,
    name: str | None = None,
    profile_id: str | None = None,
) -> str:
    """
    Add a user's SHACL file as a profile, keeping built-in ids reserved.

    Parameters
    ----------
    filename : str
        Name of the file.
    content : bytes
        Raw file contents.
    name : str | None
        Display name.
    profile_id : str | None
        Identifier to use, or None to derive one.

    Returns
    -------
    str
        The new profile's identifier.

    Raises
    ------
    profile_store.ProfileError
        If the file is not acceptable or the identifier is taken.
    """
    return profile_store.register_profile(
        filename, content, name=name, profile_id=profile_id,
        reserved=set(PROFILES) | {AUTO_PROFILE},
    )


def remove_profile(profile_id: str) -> None:
    """
    Remove a profile a user added. Built-in profiles cannot be removed.

    Parameters
    ----------
    profile_id : str

    Raises
    ------
    profile_store.ProfileError
        If the profile is built-in or does not exist.
    """
    if profile_id in PROFILES:
        raise profile_store.ProfileError(
            f"'{profile_id}' is a built-in profile and cannot be removed."
        )
    profile_store.remove_profile(profile_id)


SCORING_VERSION = 2
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


def choose_profile(graph: Graph) -> tuple[str, Path]:
    """
    Pick the profile Auto uses, preferring profiles users have added.

    An added profile is a deliberate statement of what the data should
    meet, so it wins whenever it applies at all: the added profile whose
    shapes target the most records in graph is used. Only when no added
    profile targets anything does detection fall back to the built-in
    vocabularies, as detect_profile describes.

    Parameters
    ----------
    graph : rdflib.Graph
        The data being evaluated.

    Returns
    -------
    tuple[str, pathlib.Path]
        The chosen profile id and its shapes file.

    Raises
    ------
    ProfileDetectionError
        If built-in detection fails.
    """
    best = None
    for profile_id, profile in profile_store.uploaded_profiles().items():
        try:
            shapes_graph = load_shapes(profile["file"])
        except (ShapeProfileNotFoundError, MetricConfigurationError):
            continue
        matched = len(record_constraints(shapes_graph, graph))
        if matched and (best is None or matched > best[0]):
            best = (matched, profile_id, profile["file"])

    if best is not None:
        return best[1], best[2]
    return detect_profile(graph)


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
    for profile_id, profile in all_profiles().items():
        try:
            shapes_graph = load_shapes(profile["file"])
        except (ShapeProfileNotFoundError, MetricConfigurationError):
            # An added file damaged on disk must not hide every other
            # profile. Built-in files are part of the tool and still fail.
            if profile.get("uploaded"):
                continue
            raise

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

        def _requirement(node) -> str:
            """Describe in words what a constraint asks for."""
            parts = []
            value = shapes_graph.value
            if value(node, SH.minCount) is not None:
                parts.append(f"at least {value(node, SH.minCount)}")
            if value(node, SH.maxCount) is not None:
                parts.append(f"at most {value(node, SH.maxCount)}")
            if value(node, SH["class"]) is not None:
                parts.append(f"must be a {_label(value(node, SH['class']))}")
            if value(node, SH.datatype) is not None:
                parts.append(f"typed {_label(value(node, SH.datatype))}")
            if value(node, SH.nodeKind) is not None:
                kind = str(value(node, SH.nodeKind)).rsplit("#", 1)[-1]
                parts.append({"Literal": "must be a literal",
                              "IRI": "must be an IRI",
                              "BlankNode": "must be a blank node"}
                             .get(kind, f"node kind {kind}"))
            if value(node, SH.minLength) is not None:
                parts.append(f"at least {value(node, SH.minLength)} characters")
            if value(node, SH.maxLength) is not None:
                parts.append(f"at most {value(node, SH.maxLength)} characters")
            if value(node, SH.pattern) is not None:
                parts.append(f"matches {value(node, SH.pattern)}")
            if value(node, SH.languageIn) is not None:
                languages = Collection(shapes_graph, value(node, SH.languageIn))
                parts.append("language " + " or ".join(str(l) for l in languages))
            if value(node, SH.disjoint) is not None:
                parts.append(f"no value shared with {_label(value(node, SH.disjoint))}")
            if value(node, SH["in"]) is not None:
                parts.append("one of a listed set of values")
            if value(node, SH.hasValue) is not None:
                parts.append(f"has value {_label(value(node, SH.hasValue))}")
            if value(node, SH["or"]) is not None:
                parts.append("at least one of these present")
            if value(node, SH.node) is not None:
                parts.append(f"conforms to {_label(value(node, SH.node))}")
            for negated in shapes_graph.objects(node, SH["not"]):
                if value(negated, SH["class"]) is not None:
                    parts.append(f"must not be a {_label(value(negated, SH['class']))}")
                else:
                    parts.append("must not match a given shape")
            if value(node, SH.sparql) is not None:
                parts.append("custom SPARQL check")
            return "; ".join(parts) or "—"

        def _or_paths(shape) -> str:
            """Join the paths an sh:or accepts, for its row."""
            return " or ".join(
                _label(shapes_graph.value(prop, SH.path))
                for alternatives in shapes_graph.objects(shape, SH["or"])
                for member in Collection(shapes_graph, alternatives)
                for prop in shapes_graph.objects(member, SH.property)
                if shapes_graph.value(prop, SH.path) is not None
            )

        # Exactly the shapes and constraints the scoring counts, so what
        # is shown is what a record is measured against.
        shapes = []
        for shape in shapes_with_targets(shapes_graph):
            constraints = shape_constraints(shapes_graph, shape)
            if not constraints:
                continue

            targets = [
                {"kind": kind, "uri": str(uri), "label": _label(uri)}
                for kind, predicate in (("class", SH.targetClass),
                                        ("subjects_of", SH.targetSubjectsOf),
                                        ("objects_of", SH.targetObjectsOf),
                                        ("node", SH.targetNode))
                for uri in shapes_graph.objects(shape, predicate)
            ]
            if (shape, RDF.type, RDFS.Class) in shapes_graph:
                targets.append({"kind": "class", "uri": str(shape),
                                "label": _label(shape)})
            if shapes_graph.value(shape, SH.target) is not None:
                targets.append({"kind": "sparql", "uri": "",
                                "label": "resources selected by a SPARQL query"})

            properties = []
            for constraint in constraints:
                path = shapes_graph.value(constraint, SH.path)
                if path is not None:
                    path_text = _label(path)
                elif shapes_graph.value(constraint, SH["or"]) is not None:
                    path_text = _or_paths(constraint)
                else:
                    path_text = ""
                message = shapes_graph.value(constraint, SH.message)
                if message is None:
                    # A SPARQL check usually carries its message itself.
                    check = shapes_graph.value(constraint, SH.sparql)
                    if check is not None:
                        message = shapes_graph.value(check, SH.message)
                properties.append({
                    "path":        path_text,
                    "requirement": _requirement(constraint),
                    "severity":    _severity(constraint),
                    "message":     str(message) if message is not None else None,
                })

            shapes.append({
                "targets":    targets,
                "properties": sorted(properties, key=lambda p: p["path"]),
            })

        profiles.append({
            "id":          profile_id,
            "name":        profile["name"],
            "is_fallback": profile_id == FALLBACK_PROFILE,
            "uploaded":    profile.get("uploaded", False),
            "filename":    profile.get("filename"),
            "uploaded_at": profile.get("uploaded_at"),
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


def compute_per_record_scores(
    expected: dict[str, set],
    failed: dict[str, set],
) -> dict[str, float]:
    """
    Computes a completeness score for each record.

    Score = 1 - (constraints failed / constraints expected), where both
    counts are limited to the constraints of the shapes targeting the
    record.

    Parameters
    ----------
    expected : dict[str, set]
        Record URIs mapped to the constraints they are expected to meet.
    failed : dict[str, set]
        Record URIs mapped to the constraints they failed.

    Returns
    -------
    dict[str, float]
        A dictionary mapping each record URI to its completeness score
        (range: 0.0 to 1.0).
    """
    return {
        record: round(
            1 - len(failed.get(record, set()) & constraints) / len(constraints), 4
        )
        for record, constraints in expected.items()
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


class StructuralCompletenessMetric(MetricPlugin):
    """
    Validates records against a detected SHACL profile and scores them
    on the proportion of expected properties they actually carry.
    """

    id = "structural_completeness"

    @classmethod
    def get_options(cls) -> dict:
        """
        Return the profile option, with every current profile a choice.

        Computed on each call rather than fixed, so a profile a user has
        just added can be chosen straight away.

        Returns
        -------
        dict
            The profile option: label, default and choices.
        """
        return {
            "profile": {
                "label":   "SHACL profile",
                "default": AUTO_PROFILE,
                "choices": [{"id": AUTO_PROFILE, "label": "Auto (detect from the data)"}]
                           + [{"id": pid, "label": p["name"]}
                              for pid, p in all_profiles().items()],
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
            detected_profile, detected_path = choose_profile(graph)
        except ProfileDetectionError as e:
            return self.error_result(str(e))

        profiles = all_profiles()

        if choice == AUTO_PROFILE:
            profile_name, shapes_path = detected_profile, detected_path
            profile_source = "detected"
        else:
            profile_name = choice
            shapes_path  = profiles[choice]["file"]
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
            expected    = record_constraints(shapes_graph, graph)
            all_records = set(expected)
            if not all_records and profile_source == "selected":
                # The user chose this profile and confirmed it before the
                # run, so it is reported as not applying rather than
                # replaced: there is no fallback from a choice.
                targets = sorted(
                    shapes_graph.namespace_manager.normalizeUri(t)
                    for t in shapes_graph.objects(None, SH.targetClass)
                )
                result = self.error_result(
                    f"Not applicable: the selected profile, "
                    f"{profiles[profile_name]['name']}, found no matching "
                    f"records in this dataset, so there is nothing to score. "
                    f"It checks resources of type {', '.join(targets) or 'any'}; "
                    f"detection suggests "
                    f"{profiles[detected_profile]['name']} instead."
                )
                result.details["not_applicable"] = True
                result.details["profile"] = profile_name
                return result
            if not all_records:
                raise NoTargetRecordsError(
                    f"No records matching the '{profile_name}' profile "
                    f"were found in dataset '{context.dataset_id}'."
                )
        except NoTargetRecordsError as e:
            return self.error_result(str(e))

        total_records = len(all_records)

        per_record_scores = compute_per_record_scores(
            expected, failed_constraints(results_graph)
        )

        score_values = list(per_record_scores.values())
        final_score  = round(statistics.mean(score_values), 4)

        details = {
            "profile":                    profile_name,
            "profile_name":               profiles[profile_name]["name"],
            "profile_sha256":             hashlib.sha256(
                Path(shapes_path).read_bytes()
            ).hexdigest(),
            "profile_source":             profile_source,
            "low_confidence":             low_confidence,
            "scoring_version":            SCORING_VERSION,
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
                f"{profiles[profile_name]['name']} was selected, "
                f"but the data looks like "
                f"{profiles[detected_profile]['name']}. "
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

    def check_before_run(self, context: DatasetContext) -> list[dict]:
        """
        Ask for confirmation when a chosen profile does not fit the data.

        Only a profile the user chose is checked; Auto picks a profile
        that fits by definition. A choice is reported when it targets no
        records here, when Auto would pick a different profile for this
        data, or when it leaves typed resources unchecked. The warning
        states how many records the choice covers, so a partial fit is
        visible before the run. The choice is never replaced: the user
        either confirms it or changes it.

        Parameters
        ----------
        context : DatasetContext
            Contains dataset metadata and the RDF graph that would be
            evaluated.

        Returns
        -------
        list[dict]
            At most one warning, as MetricPlugin.check_before_run
            describes; empty when the choice fits or is Auto.
        """
        try:
            choice = self.resolve_options(context.options.get(self.id))["profile"]
        except MetricConfigurationError:
            return []   # evaluate reports an invalid choice itself
        if choice == AUTO_PROFILE:
            return []

        graph = context.graph
        profiles = all_profiles()
        try:
            detected, _ = choose_profile(graph)
            shapes_graph = load_shapes(profiles[choice]["file"])
        except (ProfileDetectionError, ShapeProfileNotFoundError,
                MetricConfigurationError):
            return []   # evaluate reports these as failures

        records   = set(record_constraints(shapes_graph, graph))
        matched   = len(records)
        typed     = {str(s) for s in graph.subjects(RDF.type, None)}
        unchecked = len(typed - records)
        if matched and detected == choice and not unchecked:
            return []

        name  = profiles[choice]["name"]
        lines = [
            f"{name} applies to {matched:,} resource(s) here; "
            f"{unchecked:,} of the {len(typed):,} typed resource(s) are not "
            f"checked by it."
        ]
        if not matched:
            lines.append(
                "With nothing to score, Structural Completeness will be "
                "reported as not applicable for this source."
            )
        if detected != choice:
            lines.append(
                f"Auto would choose {profiles[detected]['name']} for this data."
            )
        mismatch = not matched or detected != choice
        return [{
            "message": f"The chosen profile, {name}, does not match this "
                       f"source's data." if mismatch else
                       f"The chosen profile, {name}, covers only part of this "
                       f"source's data.",
            "lines":   lines,
            "action":  "Choose another profile",
        }]