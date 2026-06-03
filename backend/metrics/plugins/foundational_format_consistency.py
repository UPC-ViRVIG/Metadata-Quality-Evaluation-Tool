"""
metrics/plugins/foundational_format_consistency.py
---------------------------------------------------
Measures the foundational and format consistency of an RDF dataset.

This metric evaluates four distinct concern areas that together
determine whether metadata is structurally sound and correctly
formatted, independent of any schema or vocabulary:

1. URI Validity
   Checks whether all URIs appearing as subjects, predicates, or
   objects in the graph are well-formed according to RFC 3986.

2. Datatype Correctness
   Checks whether typed literals carry values compatible with their
   declared XSD datatype.

3. Language Tag Format
   Checks whether language tags on literals conform to BCP 47.

4. Structural Issues
   Checks for blank node subjects, duplicate property values, and
   empty string literals.

Score
-----
The overall score is the unweighted mean of the four area scores.

URI validity, datatype correctness, and language tag format scores
are computed at the triple level:

    1 - (invalid_count / total_applicable_count)

Class violation rates are computed at the resource level — the
proportion of resources in each class that have at least one violation
of that type.

Export
------
This metric stores the complete (uncapped) violation lists in the
export cache during evaluate(). The frontend receives only capped
samples (MAX_SAMPLES per area) for display. Full lists are available
via GET /export/{dataset_id}/foundational_format_consistency/{category}
where category is one of: uri_validity, datatype_correctness,
language_tag_format, structural_issues.

Each export row includes dataset_label as the first column so exported
files are self-identifying without exposing the internal session UUID.
"""

import re
import statistics
from collections import defaultdict
from urllib.parse import urlparse

from rdflib import Graph, URIRef, Literal, BNode
from rdflib.namespace import RDF, XSD

from metrics.metric_plugin import MetricPlugin
from models.dataset_context import DatasetContext
from models.metric_result import MetricResult
from metrics.metrics_exceptions import EmptyGraphError
from export import export_cache

# Maximum number of sample violations sent to the frontend per area.
# The full lists are stored in the export cache separately.
MAX_SAMPLES = 50

_BCP47_PATTERN = re.compile(
    r"^[a-zA-Z]{2,8}"
    r"(-[a-zA-Z0-9]{1,8})*$"
)

_XSD_VALIDATORS = {
    str(XSD.integer):            re.compile(r"^[+-]?\d+$"),
    str(XSD.decimal):            re.compile(r"^[+-]?\d+(\.\d+)?$"),
    str(XSD.float):              re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$|^[+-]?INF$|^NaN$"),
    str(XSD.double):             re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$|^[+-]?INF$|^NaN$"),
    str(XSD.boolean):            re.compile(r"^(true|false|1|0)$"),
    str(XSD.date):               re.compile(r"^\d{4}-\d{2}-\d{2}(Z|[+-]\d{2}:\d{2})?$"),
    str(XSD.dateTime):           re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$"),
    str(XSD.gYear):              re.compile(r"^[+-]?\d{4,}(Z|[+-]\d{2}:\d{2})?$"),
    str(XSD.gYearMonth):         re.compile(r"^\d{4}-\d{2}(Z|[+-]\d{2}:\d{2})?$"),
    str(XSD.hexBinary):          re.compile(r"^([0-9a-fA-F]{2})*$"),
    str(XSD.base64Binary):       re.compile(r"^[A-Za-z0-9+/]*={0,2}$"),
    str(XSD.anyURI):             re.compile(r"^\S+$"),
    str(XSD.nonNegativeInteger): re.compile(r"^\+?\d+$"),
    str(XSD.positiveInteger):    re.compile(r"^\+?[1-9]\d*$"),
}

METRIC_ID = "foundational_format_consistency"

EXPORT_CATEGORIES = [
    "uri_validity",
    "datatype_correctness",
    "language_tag_format",
    "structural_issues",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _local_name(uri: str) -> str:
    """Return the fragment or last path segment of a URI."""
    if "#" in uri:
        return uri.rsplit("#", 1)[-1]
    return uri.rsplit("/", 1)[-1] or uri


def _is_valid_uri(uri: str) -> tuple[bool, str]:
    """
    Check whether a URI string is well-formed per RFC 3986.

    Parameters
    ----------
    uri : str
        The URI string to validate.

    Returns
    -------
    tuple[bool, str]
        A tuple of (is_valid, reason). reason is an empty string when
        valid, or a human-readable explanation when invalid.
    """
    if not uri or not uri.strip():
        return False, "Empty URI"
    try:
        parsed = urlparse(uri)
        if not parsed.scheme:
            return False, "Missing URI scheme"
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+\-.]*$", parsed.scheme):
            return False, f"Invalid URI scheme: '{parsed.scheme}'"
        if " " in uri:
            return False, "URI contains spaces"
        if parsed.fragment == "" and uri.endswith("#"):
            return False, "Empty URI fragment"
        return True, ""
    except Exception as e:
        return False, f"URI parse error: {e}"


def _is_valid_lang_tag(tag: str) -> bool:
    """
    Check whether a language tag conforms to BCP 47.

    Parameters
    ----------
    tag : str
        The language tag to validate.

    Returns
    -------
    bool
    """
    return bool(_BCP47_PATTERN.match(tag))


def _is_valid_datatype_value(value: str, datatype: str) -> bool:
    """
    Check whether a literal value is compatible with its XSD datatype.

    Only datatypes listed in _XSD_VALIDATORS are checked. Unknown
    datatypes are considered valid by convention — the metric does not
    penalise the use of custom or external datatypes.

    Parameters
    ----------
    value : str
        The string lexical form of the literal.
    datatype : str
        The full URI of the XSD datatype.

    Returns
    -------
    bool
    """
    validator = _XSD_VALIDATORS.get(datatype)
    if validator is None:
        return True
    return bool(validator.match(value.strip()))


def _build_class_violation_rates(
    violating_subjects: set[str],
    types: dict[str, set],
) -> dict[str, float]:
    """
    Compute the proportion of resources in each class that have at least
    one violation.

    This is a resource-level measure — a resource with five violations
    counts the same as one with a single violation. This prevents classes
    whose resources carry many violations from having rates above 1.0.

    Parameters
    ----------
    violating_subjects : set[str]
        URIs of subjects that have at least one violation of this type.
    types : dict[str, set]
        Mapping of subject URI to the set of class URIs it belongs to,
        as collected by _collect().

    Returns
    -------
    dict[str, float]
        Mapping of class URI to violation rate (0.0 to 1.0).
    """
    class_totals: dict[str, int] = defaultdict(int)
    class_violations: dict[str, int] = defaultdict(int)

    for subject_uri, classes in types.items():
        for cls in classes:
            class_totals[cls] += 1
            if subject_uri in violating_subjects:
                class_violations[cls] += 1

    return {
        cls: round(class_violations[cls] / class_totals[cls], 4)
        for cls in class_totals
        if class_totals[cls] > 0
    }


# ---------------------------------------------------------------------------
# Export row builders
# ---------------------------------------------------------------------------

def _uri_export_rows(
    issues: list[dict],
    dataset_label: str,
) -> list[dict]:
    """
    Build export rows for the uri_validity category.

    Parameters
    ----------
    issues : list of dict
        Full list of URI violation dicts from _collect().
    dataset_label : str
        Human-readable dataset label included as the first column of
        every row so the exported file is self-identifying.

    Returns
    -------
    list of dict
        Each dict has keys: dataset_label, subject, property, value,
        position, reason.
    """
    return [
        {
            "dataset_label": dataset_label,
            "subject":       s["subject"],
            "property":      s["predicate"],
            "value":         s["value"],
            "position":      s["position"],
            "reason":        s["reason"],
        }
        for s in issues
    ]


def _datatype_export_rows(
    issues: list[dict],
    dataset_label: str,
) -> list[dict]:
    """
    Build export rows for the datatype_correctness category.

    Parameters
    ----------
    issues : list of dict
        Full list of datatype violation dicts from _collect().
    dataset_label : str
        Human-readable dataset label included as the first column of
        every row so the exported file is self-identifying.

    Returns
    -------
    list of dict
        Each dict has keys: dataset_label, subject, property, value,
        datatype.
    """
    return [
        {
            "dataset_label": dataset_label,
            "subject":       s["subject"],
            "property":      s["property"],
            "value":         s["value"],
            "datatype":      _local_name(s["datatype"]),
        }
        for s in issues
    ]


def _lang_export_rows(
    issues: list[dict],
    dataset_label: str,
) -> list[dict]:
    """
    Build export rows for the language_tag_format category.

    Parameters
    ----------
    issues : list of dict
        Full list of language tag violation dicts from _collect().
    dataset_label : str
        Human-readable dataset label included as the first column of
        every row so the exported file is self-identifying.

    Returns
    -------
    list of dict
        Each dict has keys: dataset_label, subject, property, value,
        invalid_tag.
    """
    return [
        {
            "dataset_label": dataset_label,
            "subject":       s["subject"],
            "property":      s["property"],
            "value":         s["value"],
            "invalid_tag":   s["tag"],
        }
        for s in issues
    ]


def _structural_export_rows(
    empty_list: list[dict],
    blank_list: list[dict],
    dataset_label: str,
) -> list[dict]:
    """
    Build export rows for the structural_issues category.

    Combines blank node subjects and empty literals into a single flat
    list with an issue_type column to distinguish them.

    Parameters
    ----------
    empty_list : list of dict
    blank_list : list of dict
    dataset_label : str
        Human-readable dataset label included as the first column of
        every row so the exported file is self-identifying.

    Returns
    -------
    list of dict
        Each dict has keys: dataset_label, subject, property,
        issue_type, detail.
    """
    rows = []

    for e in empty_list:
        rows.append({
            "dataset_label": dataset_label,
            "subject":       e["subject"],
            "property":      e["property"],
            "issue_type":    "empty_literal",
            "detail":        "Empty or whitespace-only literal value",
        })

    for b in blank_list:
        rows.append({
            "dataset_label": dataset_label,
            "subject":       "_blank_node",
            "property":      b["predicate"],
            "issue_type":    "blank_node_subject",
            "detail":        f"Object: {b['object']}",
        })

    return rows


# ---------------------------------------------------------------------------
# Data collection — single pass
# ---------------------------------------------------------------------------

def _collect(graph: Graph) -> dict:
    """
    Single pass over the graph collecting all data needed by the four
    concern areas.

    Parameters
    ----------
    graph : rdflib.Graph
        The RDF graph to analyse.

    Returns
    -------
    dict with keys:
        subject_types   — {subject_uri: set of class URIs}
        uri_issues      — complete list of URI violation dicts
        datatype_issues — complete list of datatype violation dicts
        lang_issues     — complete list of language tag violation dicts
        blank_subjects  — complete list of blank node subject dicts
        empty_literals  — complete list of empty literal dicts
        all_uris        — total count of URI positions checked
        all_typed       — total count of typed literals seen
        all_lang        — total count of language-tagged literals seen
    """
    subject_types: dict[str, set] = defaultdict(set)
    uri_issues: list[dict] = []
    datatype_issues: list[dict] = []
    lang_issues: list[dict] = []
    blank_subjects: list[dict] = []
    empty_literals: list[dict] = []

    all_uris = 0
    all_typed = 0
    all_lang = 0

    for subject, predicate, obj in graph:

        subject_str   = str(subject)
        predicate_str = str(predicate)

        if predicate == RDF.type and isinstance(obj, URIRef):
            subject_types[subject_str].add(str(obj))

        if isinstance(subject, BNode):
            blank_subjects.append({
                "predicate": predicate_str,
                "object":    str(obj),
            })

        if isinstance(subject, URIRef):
            all_uris += 1
            valid, reason = _is_valid_uri(subject_str)
            if not valid:
                uri_issues.append({
                    "subject":   subject_str,
                    "predicate": predicate_str,
                    "value":     subject_str,
                    "position":  "subject",
                    "reason":    reason,
                })

        all_uris += 1
        valid, reason = _is_valid_uri(predicate_str)
        if not valid:
            uri_issues.append({
                "subject":   subject_str,
                "predicate": predicate_str,
                "value":     predicate_str,
                "position":  "predicate",
                "reason":    reason,
            })

        if isinstance(obj, URIRef):
            all_uris += 1
            valid, reason = _is_valid_uri(str(obj))
            if not valid:
                uri_issues.append({
                    "subject":   subject_str,
                    "predicate": predicate_str,
                    "value":     str(obj),
                    "position":  "object",
                    "reason":    reason,
                })

        if isinstance(obj, Literal):
            value_str = str(obj)

            if obj.datatype:
                all_typed += 1
                if not _is_valid_datatype_value(value_str, str(obj.datatype)):
                    datatype_issues.append({
                        "subject":  subject_str,
                        "property": predicate_str,
                        "value":    value_str[:200],
                        "datatype": str(obj.datatype),
                    })

            if obj.language:
                all_lang += 1
                if not _is_valid_lang_tag(obj.language):
                    lang_issues.append({
                        "subject":  subject_str,
                        "property": predicate_str,
                        "value":    value_str[:200],
                        "tag":      obj.language,
                    })

            if value_str.strip() == "":
                empty_literals.append({
                    "subject":  subject_str,
                    "property": predicate_str,
                })

    return {
        "subject_types":   dict(subject_types),
        "uri_issues":      uri_issues,
        "datatype_issues": datatype_issues,
        "lang_issues":     lang_issues,
        "blank_subjects":  blank_subjects,
        "empty_literals":  empty_literals,
        "all_uris":        all_uris,
        "all_typed":       all_typed,
        "all_lang":        all_lang,
    }


# ---------------------------------------------------------------------------
# Per-area computation
# ---------------------------------------------------------------------------

def _compute_uri_validity(raw: dict) -> tuple[float, dict]:
    """
    Compute URI validity score and details.

    Overall score is computed at the triple level:
        1 - (invalid_uri_count / total_uri_positions_checked)

    Class violation rates are computed at the resource level — the
    proportion of resources in each class that have at least one
    malformed URI, regardless of how many bad URIs they have.

    Parameters
    ----------
    raw : dict
        Raw collected data from _collect().

    Returns
    -------
    tuple[float, dict]
        Score and details dict for the uri_validity section.
        Details contains capped samples for frontend display.
        Also includes invalid_by_reason and invalid_by_position as
        aggregated counts over the full violation list, not just samples.
    """
    issues = raw["uri_issues"]
    total  = raw["all_uris"]
    types  = raw["subject_types"]

    invalid_count = len(issues)
    score = round(1 - invalid_count / total, 4) if total else 1.0

    by_property: dict[str, int] = defaultdict(int)
    by_reason:   dict[str, int] = defaultdict(int)
    by_position: dict[str, int] = defaultdict(int)

    for issue in issues:
        by_property[issue["predicate"]] += 1
        by_reason[issue["reason"]]      += 1
        by_position[issue["position"]]  += 1

    violating_subjects: set[str] = {issue["subject"] for issue in issues}
    class_violation_rates = _build_class_violation_rates(violating_subjects, types)

    return score, {
        "total_uri_count": total,
        "invalid_count":   invalid_count,
        "invalid_by_property": [
            {"property": p, "label": _local_name(p), "count": c}
            for p, c in sorted(by_property.items(), key=lambda x: x[1], reverse=True)
        ],
        "invalid_by_reason": [
            {"reason": r, "count": c}
            for r, c in sorted(by_reason.items(), key=lambda x: x[1], reverse=True)
        ],
        "invalid_by_position": [
            {"position": p, "count": c}
            for p, c in sorted(by_position.items(), key=lambda x: x[1], reverse=True)
        ],
        "class_violation_rates": class_violation_rates,
        "samples": issues[:MAX_SAMPLES],
    }


def _compute_datatype_correctness(raw: dict) -> tuple[float, dict]:
    """
    Compute datatype correctness score and details.

    Overall score is computed at the triple level:
        1 - (invalid_typed_literal_count / total_typed_literal_count)

    Class violation rates are computed at the resource level — the
    proportion of resources in each class that have at least one
    datatype violation, regardless of how many they have.

    Parameters
    ----------
    raw : dict
        Raw collected data from _collect().

    Returns
    -------
    tuple[float, dict]
        Score and details dict for the datatype_correctness section.
        Details contains capped samples for frontend display.
    """
    issues = raw["datatype_issues"]
    total  = raw["all_typed"]
    types  = raw["subject_types"]

    invalid_count = len(issues)
    score = round(1 - invalid_count / total, 4) if total else 1.0

    by_datatype: dict[str, int] = defaultdict(int)
    by_property: dict[str, int] = defaultdict(int)

    for issue in issues:
        by_datatype[issue["datatype"]] += 1
        by_property[issue["property"]] += 1

    violating_subjects: set[str] = {issue["subject"] for issue in issues}
    class_violation_rates = _build_class_violation_rates(violating_subjects, types)

    return score, {
        "total_typed_literals": total,
        "invalid_count":        invalid_count,
        "invalid_by_datatype": [
            {"datatype": d, "label": _local_name(d), "count": c}
            for d, c in sorted(by_datatype.items(), key=lambda x: x[1], reverse=True)
        ],
        "invalid_by_property": [
            {"property": p, "label": _local_name(p), "count": c}
            for p, c in sorted(by_property.items(), key=lambda x: x[1], reverse=True)
        ],
        "class_violation_rates": class_violation_rates,
        "samples": issues[:MAX_SAMPLES],
    }


def _compute_language_tag_format(raw: dict) -> tuple[float, dict]:
    """
    Compute language tag format score and details.

    Overall score is computed at the triple level:
        1 - (invalid_tag_count / total_lang_literal_count)

    Class violation rates are computed at the resource level — the
    proportion of resources in each class that have at least one
    invalid language tag, regardless of how many they have.

    Parameters
    ----------
    raw : dict
        Raw collected data from _collect().

    Returns
    -------
    tuple[float, dict]
        Score and details dict for the language_tag_format section.
        Details contains capped samples for frontend display.
    """
    issues = raw["lang_issues"]
    total  = raw["all_lang"]
    types  = raw["subject_types"]

    invalid_count = len(issues)
    score = round(1 - invalid_count / total, 4) if total else 1.0

    tag_counts: dict[str, int] = defaultdict(int)
    by_property: dict[str, int] = defaultdict(int)

    for issue in issues:
        tag_counts[issue["tag"]] += 1
        by_property[issue["property"]] += 1

    violating_subjects: set[str] = {issue["subject"] for issue in issues}
    class_violation_rates = _build_class_violation_rates(violating_subjects, types)

    return score, {
        "total_lang_literals": total,
        "invalid_count":       invalid_count,
        "invalid_tags": [
            {"tag": tag, "count": cnt}
            for tag, cnt in sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
        ],
        "invalid_by_property": [
            {"property": p, "label": _local_name(p), "count": c}
            for p, c in sorted(by_property.items(), key=lambda x: x[1], reverse=True)
        ],
        "class_violation_rates": class_violation_rates,
        "samples": issues[:MAX_SAMPLES],
    }


def _compute_structural_issues(
    raw: dict,
    dataset_label: str,
) -> tuple[float, dict, list[dict]]:
    """
    Compute structural issues score and details.

    Covers three sub-concerns:

    - Blank node subjects: subjects that are blank nodes rather than URIs.
    - Empty literals: string literals whose value is empty or whitespace.

    Score = 1 - (total_structural_violations / (total_triples +
    total_violations)), clamped to 0.0.

    Class violation rates are computed at the resource level.

    Parameters
    ----------
    raw : dict
        Raw collected data from _collect().
    dataset_label : str
        Passed to the export row builder so every export row is
        self-identifying.

    Returns
    -------
    tuple[float, dict, list[dict]]
        Score, details dict for frontend display, and the complete flat
        list of structural violation rows for export.
    """
    types      = raw["subject_types"]
    blank_list = raw["blank_subjects"]
    empty_list = raw["empty_literals"]

    blank_count = len(blank_list)
    empty_count = len(empty_list)

    total_items      = len(types) or 1
    total_violations = blank_count + empty_count
    score = round(
        max(0.0, 1 - total_violations / (total_items + total_violations)), 4
    )

    empty_by_property: dict[str, int] = defaultdict(int)
    for e in empty_list:
        empty_by_property[e["property"]] += 1

    empty_violating  = {e["subject"] for e in empty_list}
    combined_class_rates = _build_class_violation_rates(empty_violating, types)
    blank_class_rates: dict[str, float] = {}
    empty_class_rates    = _build_class_violation_rates(empty_violating, types)

    details = {
        "blank_node_subjects": {
            "count": blank_count,
            "class_violation_rates": blank_class_rates,
            "samples": blank_list[:MAX_SAMPLES],
        },
        "empty_literals": {
            "count": empty_count,
            "by_property": [
                {"property": p, "label": _local_name(p), "count": c}
                for p, c in sorted(empty_by_property.items(), key=lambda x: x[1], reverse=True)
            ],
            "class_violation_rates": empty_class_rates,
            "samples": empty_list[:MAX_SAMPLES],
        },
        "class_violation_rates": combined_class_rates,
    }

    export_rows = _structural_export_rows(
        empty_list, blank_list, dataset_label,
    )

    return score, details, export_rows


# ---------------------------------------------------------------------------
# Metric plugin
# ---------------------------------------------------------------------------

class FoundationalFormatConsistencyMetric(MetricPlugin):

    id = METRIC_ID

    def evaluate(self, context: DatasetContext) -> MetricResult:
        """
        Evaluate foundational and format consistency of the dataset.

        Performs a single pass over the graph to collect all violation
        data, then computes scores and details for each of the four
        concern areas independently.

        After computing results, stores the complete (uncapped) violation
        lists in the export cache keyed by dataset_id and category. Each
        export row includes dataset_label as the first column. The
        frontend receives only capped samples in the response.

        Parameters
        ----------
        context : DatasetContext
            Contains the RDF graph to evaluate and optional scope.

        Returns
        -------
        MetricResult
            Score: unweighted mean of the four area scores.
            Details: structured data for each concern area with capped
            samples for frontend display.
            exports_available: list of category names available for CSV
            download via GET /export/{dataset_id}/{metric_id}/{category}.

        Raises
        ------
        EmptyGraphError
            If the dataset graph contains no triples.
        """
        graph         = context.graph
        dataset_id    = context.dataset_id
        dataset_label = context.label or context.dataset_id

        if len(graph) == 0:
            raise EmptyGraphError(
                f"Dataset '{dataset_id}' contains an empty graph."
            )

        raw = _collect(graph)

        uri_score,    uri_details    = _compute_uri_validity(raw)
        dtype_score,  dtype_details  = _compute_datatype_correctness(raw)
        lang_score,   lang_details   = _compute_language_tag_format(raw)
        struct_score, struct_details, struct_export = _compute_structural_issues(
            raw, dataset_label
        )

        overall_score = round(
            statistics.mean([uri_score, dtype_score, lang_score, struct_score]), 4
        )

        export_cache.store(
            dataset_id, METRIC_ID, "uri_validity",
            _uri_export_rows(raw["uri_issues"], dataset_label),
        )
        export_cache.store(
            dataset_id, METRIC_ID, "datatype_correctness",
            _datatype_export_rows(raw["datatype_issues"], dataset_label),
        )
        export_cache.store(
            dataset_id, METRIC_ID, "language_tag_format",
            _lang_export_rows(raw["lang_issues"], dataset_label),
        )
        export_cache.store(
            dataset_id, METRIC_ID, "structural_issues",
            struct_export,
        )

        details = {
            "scores": {
                "uri_validity":         uri_score,
                "datatype_correctness": dtype_score,
                "language_tag_format":  lang_score,
                "structural_issues":    struct_score,
            },
            "uri_validity":         uri_details,
            "datatype_correctness": dtype_details,
            "language_tag_format":  lang_details,
            "structural_issues":    struct_details,
        }

        return MetricResult(
            metric_id=self.id,
            name=self.name,
            score=overall_score,
            weight=self.weight,
            status="computed",
            details=details,
            exports_available=EXPORT_CATEGORIES,
        )