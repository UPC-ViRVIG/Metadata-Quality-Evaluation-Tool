"""
metrics/plugins/licensing_rights.py
------------------------------------
Measures whether the dataset documents rights and licensing information
that a downstream consumer could actually act on.

This metric evaluates three distinct concern areas, independent of any
particular ontology or schema profile:

1. Rights Coverage
   Checks whether each resource carries at least one rights-related
   statement, detected purely from the data (see "Detection" below) —
   not from a fixed list of expected properties.

2. Machine Readability
   Of the rights statements found, checks what proportion are expressed
   as a URI (machine-actionable) rather than a free-text literal
   (human-readable only).

3. Vocabulary Conformance
   Of the URI-valued statements, checks what proportion resolve into a
   recognized, standardized rights vocabulary (RightsStatements.org,
   Creative Commons) rather than an arbitrary, unverifiable URI.

Detection
---------
Cultural heritage metadata is pooled from many institutions with
different practices, so this metric does not assume any specific
predicate (edm:rights, dc:rights, dcterms:license, ...) is the "right"
one to check — that would make it just another schema/SHACL presence
check, which structural_completeness already covers for datasets that
declare an EDM profile. Instead a triple is treated as a rights signal
if either of the following holds, regardless of which ontology it is
drawn from:

    - its predicate's local name contains a rights-related keyword
      (right, licen[sc]e, usageterms) — catches edm:rights, dc:rights,
      dcterms:license, dcterms:rightsHolder, schema:license, cc:license,
      and equally an institution's own ex:copyrightStatement
    - its object is a URI matching a recognized rights vocabulary
      namespace, regardless of what the predicate is called

Score
-----
The overall score is the unweighted mean of the three area scores.
Coverage is computed at the resource level, grouped by rdf:type and
size-weighted, the same way property_coverage.py measures completeness.
Machine readability and vocabulary conformance are computed only over
the rights signals that were actually found — a dataset with no rights
information at all scores 1.0 on both (coverage already penalizes the
absence; these two areas would otherwise penalize the same gap twice).

Rights category distribution (not scored)
------------------------------------------
Recognized rights statements are additionally bucketed into an
illustrative openness category (public_domain / open_permissive /
restricted / unevaluated / other_recognized) purely for display. This
is deliberately NOT part of the score: the metric evaluates whether
rights are documented accurately and verifiably, not how permissive
those rights are. An institution that correctly and machine-readably
states "In Copyright" is exactly as well-documented as one that states
CC0, and should score the same.

Export
------
This metric stores the complete (uncapped) violation lists in the
export cache during evaluate(). The frontend receives only capped
samples (MAX_SAMPLES per area) for display. Full lists are available
via GET /export/{dataset_id}/licensing_rights/{category} where category
is one of: missing_rights, non_machine_readable, unrecognized_vocabulary.

Each export row includes dataset_label as the first column so exported
files are self-identifying without exposing the internal session UUID.
"""

import statistics
from collections import defaultdict

from rdflib import Graph, URIRef, BNode
from rdflib.namespace import RDF

from metrics.metric_plugin import MetricPlugin
from models.dataset_context import DatasetContext
from models.metric_result import MetricResult
from metrics.metrics_exceptions import EmptyGraphError, NoTargetRecordsError
from export import export_cache

# Maximum number of sample violations sent to the frontend per area.
# The full lists are stored in the export cache separately.
MAX_SAMPLES = 50

METRIC_ID = "licensing_rights"

EXPORT_CATEGORIES = [
    "missing_rights",
    "non_machine_readable",
    "unrecognized_vocabulary",
]

# Substrings matched case-insensitively against a predicate's local
# name. Deliberately ontology-agnostic: catches edm:rights, dc:rights,
# dcterms:license, dcterms:rightsHolder, dcterms:accessRights,
# schema:license, cc:license, and any institution-specific predicate
# whose name signals the same intent (e.g. ex:copyrightStatement).
_RIGHTS_KEYWORDS = ("right", "licen", "usageterms")

# Namespace prefixes recognized as standardized, verifiable rights
# vocabularies. Extensible — add new prefixes here (e.g. SPDX, Open
# Data Commons) without touching any detection or scoring logic.
#
# RightsStatements.org publishes each statement under two paths —
# /vocab/ (the machine-readable RDF resource) and /page/ (a
# human-readable HTML page) — and real-world metadata (e.g. Hispana,
# Europeana aggregations) commonly uses the /page/ form as the
# dc:rights value, so both are accepted here. The legacy Europeana
# Licensing Framework namespace (europeana.eu/portal/rights/) is also
# one of the three vocabularies EDM's edm:rights guidelines accept,
# alongside RightsStatements.org and Creative Commons.
_RECOGNIZED_VOCAB_PREFIXES = (
    "http://rightsstatements.org/vocab/",
    "https://rightsstatements.org/vocab/",
    "http://rightsstatements.org/page/",
    "https://rightsstatements.org/page/",
    "http://creativecommons.org/licenses/",
    "https://creativecommons.org/licenses/",
    "http://creativecommons.org/publicdomain/",
    "https://creativecommons.org/publicdomain/",
    "http://www.europeana.eu/portal/rights/",
    "https://www.europeana.eu/portal/rights/",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _local_name(uri: str) -> str:
    """Return the fragment or last path segment of a URI."""
    if "#" in uri:
        return uri.rsplit("#", 1)[-1]
    return uri.rsplit("/", 1)[-1] or uri


def _is_rights_predicate(predicate: str) -> bool:
    """
    Check whether a predicate's local name suggests a rights/licensing
    statement, independent of which ontology it belongs to.

    Parameters
    ----------
    predicate : str
        Full predicate URI.

    Returns
    -------
    bool
    """
    name = _local_name(predicate).lower()
    return any(keyword in name for keyword in _RIGHTS_KEYWORDS)


def _is_recognized_vocabulary(uri: str) -> bool:
    """
    Check whether a URI belongs to a recognized, standardized rights
    vocabulary (RightsStatements.org, Creative Commons).

    Parameters
    ----------
    uri : str
        Full URI of the object value.

    Returns
    -------
    bool
    """
    return uri.startswith(_RECOGNIZED_VOCAB_PREFIXES)


def _rights_category(uri: str) -> str:
    """
    Bucket a recognized rights statement URI into an illustrative
    openness category, for display only — never used in scoring.

    Parameters
    ----------
    uri : str
        A URI already known to match _is_recognized_vocabulary.

    Returns
    -------
    str
        One of: public_domain, open_permissive, restricted,
        unevaluated, other_recognized.
    """
    u = uri.rstrip("/").lower()
    # RightsStatements.org codes appear under both /vocab/ (machine-readable)
    # and /page/ (human-readable) paths; categorize by code regardless of
    # which one was used.
    is_rightsstatements = "rightsstatements.org/vocab/" in u or "rightsstatements.org/page/" in u

    if "/publicdomain/zero" in u or "/publicdomain/mark" in u or (is_rightsstatements and "/nkc" in u):
        return "public_domain"
    if (is_rightsstatements and "/noc" in u) or "/licenses/by" in u:
        return "open_permissive"
    if is_rightsstatements and "/inc" in u:
        return "restricted"
    if is_rightsstatements and ("/cne" in u or "/und" in u):
        return "unevaluated"
    return "other_recognized"


def _group_by_class(graph: Graph) -> dict[str, set[str]]:
    """
    Group named RDF resources by rdf:type, the same way
    property_coverage.py's get_records_by_class does.

    Resources without a non-blank rdf:type are grouped under the
    synthetic class label "Unknown" so they are still accounted for
    in the coverage denominator.

    Parameters
    ----------
    graph : rdflib.Graph
        RDF graph to analyse.

    Returns
    -------
    dict[str, set[str]]
        Mapping of class URI (or "Unknown") to the set of resource URIs
        belonging to it.
    """
    class_records: dict[str, set[str]] = defaultdict(set)

    for subject in graph.subjects():
        if isinstance(subject, BNode):
            continue
        types = [
            str(t) for t in graph.objects(subject, RDF.type)
            if not isinstance(t, BNode)
        ]
        if types:
            for t in types:
                class_records[t].add(str(subject))
        else:
            class_records["Unknown"].add(str(subject))

    return dict(class_records)


# ---------------------------------------------------------------------------
# Export row builders
# ---------------------------------------------------------------------------

def _missing_rights_export_rows(
    missing: list[tuple[str, str]],
    dataset_label: str,
) -> list[dict]:
    """
    Build export rows for the missing_rights category.

    Parameters
    ----------
    missing : list of (subject_uri, class_uri) tuples
        Full list from _compute_rights_coverage().
    dataset_label : str
        Human-readable dataset label included as the first column of
        every row so the exported file is self-identifying.

    Returns
    -------
    list of dict
        Each dict has keys: dataset_label, subject, class.
    """
    return [
        {"dataset_label": dataset_label, "subject": subject, "class": cls}
        for subject, cls in missing
    ]


def _signal_export_rows(
    signals: list[dict],
    dataset_label: str,
) -> list[dict]:
    """
    Build export rows for a list of rights-signal violation dicts,
    shared by the non_machine_readable and unrecognized_vocabulary
    categories.

    Parameters
    ----------
    signals : list of dict
        Full list of signal dicts from _collect().
    dataset_label : str
        Human-readable dataset label included as the first column of
        every row so the exported file is self-identifying.

    Returns
    -------
    list of dict
        Each dict has keys: dataset_label, subject, property, value.
    """
    return [
        {
            "dataset_label": dataset_label,
            "subject":       s["subject"],
            "property":      s["predicate"],
            "value":         s["value"],
        }
        for s in signals
    ]


# ---------------------------------------------------------------------------
# Data collection — single pass
# ---------------------------------------------------------------------------

def _collect(graph: Graph) -> dict:
    """
    Single pass over the graph collecting every rights signal triple.

    A triple is a rights signal if its predicate's local name matches a
    rights-related keyword, or its object is a URI matching a
    recognized rights vocabulary — see the module docstring's
    "Detection" section.

    Parameters
    ----------
    graph : rdflib.Graph
        The RDF graph to analyse.

    Returns
    -------
    dict with keys:
        rights_subjects — set of subject URIs with at least one rights
                           signal
        signals         — complete list of rights signal dicts, each
                           with keys: subject, predicate, value, is_uri,
                           recognized
    """
    rights_subjects: set[str] = set()
    signals: list[dict] = []

    for subject, predicate, obj in graph:
        if not isinstance(subject, URIRef):
            continue

        predicate_str = str(predicate)
        is_uri_object = isinstance(obj, URIRef)
        value_str     = str(obj)

        recognized = is_uri_object and _is_recognized_vocabulary(value_str)
        if not (_is_rights_predicate(predicate_str) or recognized):
            continue

        subject_str = str(subject)
        rights_subjects.add(subject_str)
        signals.append({
            "subject":    subject_str,
            "predicate":  predicate_str,
            "value":      value_str[:200],
            "is_uri":     is_uri_object,
            "recognized": recognized,
        })

    return {"rights_subjects": rights_subjects, "signals": signals}


# ---------------------------------------------------------------------------
# Per-area computation
# ---------------------------------------------------------------------------

def _compute_rights_coverage(
    class_records: dict[str, set[str]],
    rights_subjects: set[str],
) -> tuple[float, dict, list[tuple[str, str]]]:
    """
    Compute rights coverage score and details.

    Within a class, the fill rate is the proportion of that class's
    resources carrying at least one rights signal. The overall score is
    the mean of the class fill rates, weighted by class size — the same
    aggregation as property_coverage.py's compute_overall_score.

    Parameters
    ----------
    class_records : dict[str, set[str]]
        Resources grouped by class, from _group_by_class().
    rights_subjects : set[str]
        Subject URIs with at least one rights signal, from _collect().

    Returns
    -------
    tuple[float, dict, list[tuple[str, str]]]
        Score, details dict (with class fill rates sorted ascending,
        worst first), and the complete list of (subject, class) pairs
        missing rights information, for export.
    """
    class_fill_rates: dict[str, float] = {}
    class_counts: dict[str, int] = {}
    missing: list[tuple[str, str]] = []

    for cls, records in class_records.items():
        total = len(records)
        present = sum(1 for r in records if r in rights_subjects)
        class_fill_rates[cls] = round(present / total, 4) if total else 1.0
        class_counts[cls] = total
        for r in records:
            if r not in rights_subjects:
                missing.append((r, cls))

    total_weighted = sum(class_fill_rates[c] * class_counts[c] for c in class_fill_rates)
    total_weight   = sum(class_counts.values())
    score = round(total_weighted / total_weight, 4) if total_weight else 1.0

    sorted_fill_rates = dict(sorted(class_fill_rates.items(), key=lambda x: x[1]))

    return score, {
        "total_resources":       total_weight,
        "resources_with_rights": len(rights_subjects),
        "class_fill_rates":      sorted_fill_rates,
        "classes_found":         class_counts,
        "samples": [
            {"subject": s, "class": c} for s, c in missing[:MAX_SAMPLES]
        ],
    }, missing


def _compute_machine_readability(signals: list[dict]) -> tuple[float, dict, list[dict]]:
    """
    Compute machine readability score and details.

    Proportion of rights signals expressed as a URI rather than a
    literal (or blank node). Defaults to 1.0 when no rights signals
    exist at all, so the absence of rights information is only
    penalised once, by the coverage score.

    Parameters
    ----------
    signals : list of dict
        Rights signal dicts from _collect().

    Returns
    -------
    tuple[float, dict, list[dict]]
        Score, details dict, and the complete list of non-URI-valued
        signal dicts, for export.
    """
    total = len(signals)
    literal_signals = [s for s in signals if not s["is_uri"]]
    invalid_count = len(literal_signals)
    score = round(1 - invalid_count / total, 4) if total else 1.0

    by_property: dict[str, int] = defaultdict(int)
    for s in literal_signals:
        by_property[s["predicate"]] += 1

    return score, {
        "total_signals": total,
        "literal_count": invalid_count,
        "invalid_by_property": [
            {"property": p, "label": _local_name(p), "count": c}
            for p, c in sorted(by_property.items(), key=lambda x: x[1], reverse=True)
        ],
        "samples": literal_signals[:MAX_SAMPLES],
    }, literal_signals


def _compute_vocabulary_conformance(signals: list[dict]) -> tuple[float, dict, list[dict]]:
    """
    Compute vocabulary conformance score and details.

    Proportion of URI-valued rights signals matching a recognized
    rights vocabulary. Defaults to 1.0 when no URI-valued signals
    exist, for the same reason as machine readability.

    Parameters
    ----------
    signals : list of dict
        Rights signal dicts from _collect().

    Returns
    -------
    tuple[float, dict, list[dict]]
        Score, details dict, and the complete list of unrecognized
        URI-valued signal dicts, for export.
    """
    uri_signals = [s for s in signals if s["is_uri"]]
    total = len(uri_signals)
    unrecognized = [s for s in uri_signals if not s["recognized"]]
    invalid_count = len(unrecognized)
    score = round(1 - invalid_count / total, 4) if total else 1.0

    return score, {
        "total_uri_signals":  total,
        "unrecognized_count": invalid_count,
        "samples": unrecognized[:MAX_SAMPLES],
    }, unrecognized


def _rights_category_distribution(signals: list[dict]) -> list[dict]:
    """
    Bucket recognized rights signals into an illustrative openness
    category, for display only. Not used in scoring — see the module
    docstring's "Rights category distribution" section.

    Parameters
    ----------
    signals : list of dict
        Rights signal dicts from _collect().

    Returns
    -------
    list of dict
        Each dict has keys: category, count, sorted by count descending.
    """
    counts: dict[str, int] = defaultdict(int)
    for s in signals:
        if s["recognized"]:
            counts[_rights_category(s["value"])] += 1

    return [
        {"category": cat, "count": n}
        for cat, n in sorted(counts.items(), key=lambda x: x[1], reverse=True)
    ]


# ---------------------------------------------------------------------------
# Metric plugin
# ---------------------------------------------------------------------------

class LicensingRightsMetric(MetricPlugin):
    """
    Scores rights coverage, machine readability, and vocabulary
    conformance of rights/licensing statements, and exports the full
    violation lists for each.
    """

    id = METRIC_ID

    def evaluate(self, context: DatasetContext) -> MetricResult:
        """
        Evaluate rights and licensing documentation quality.

        Detects rights-related triples data-agnostically (see the
        module docstring's "Detection" section), then computes scores
        and details for coverage, machine readability, and vocabulary
        conformance independently.

        After computing results, stores the complete (uncapped)
        violation lists in the export cache keyed by dataset_id and
        category. The frontend receives only capped samples in the
        response.

        Parameters
        ----------
        context : DatasetContext
            Contains the RDF graph to evaluate and optional scope.

        Returns
        -------
        MetricResult
            Score: unweighted mean of the three area scores.
            Details: structured data for each concern area with capped
            samples for frontend display, plus an unscored rights
            category distribution.
            exports_available: list of category names available for CSV
            download via GET /export/{dataset_id}/{metric_id}/{category}.

        Raises
        ------
        EmptyGraphError
            If the dataset graph contains no triples.
        NoTargetRecordsError
            If the graph contains triples but no named (non-blank)
            resources to evaluate coverage over.
        """
        graph         = context.graph
        dataset_id    = context.dataset_id
        dataset_label = context.label or context.dataset_id

        if len(graph) == 0:
            raise EmptyGraphError(
                f"Dataset '{dataset_id}' contains an empty graph."
            )

        class_records = _group_by_class(graph)
        if not class_records:
            raise NoTargetRecordsError(
                f"No named (non-blank) resources found in dataset "
                f"'{dataset_id}'."
            )

        raw = _collect(graph)

        coverage_score, coverage_details, missing = _compute_rights_coverage(
            class_records, raw["rights_subjects"]
        )
        mr_score, mr_details, literal_signals = _compute_machine_readability(
            raw["signals"]
        )
        vc_score, vc_details, unrecognized = _compute_vocabulary_conformance(
            raw["signals"]
        )

        overall_score = round(
            statistics.mean([coverage_score, mr_score, vc_score]), 4
        )

        export_cache.store(
            dataset_id, METRIC_ID, "missing_rights",
            _missing_rights_export_rows(missing, dataset_label),
        )
        export_cache.store(
            dataset_id, METRIC_ID, "non_machine_readable",
            _signal_export_rows(literal_signals, dataset_label),
        )
        export_cache.store(
            dataset_id, METRIC_ID, "unrecognized_vocabulary",
            _signal_export_rows(unrecognized, dataset_label),
        )

        details = {
            "scores": {
                "rights_coverage":        coverage_score,
                "machine_readability":    mr_score,
                "vocabulary_conformance": vc_score,
            },
            "rights_coverage":              coverage_details,
            "machine_readability":          mr_details,
            "vocabulary_conformance":       vc_details,
            "rights_category_distribution": _rights_category_distribution(raw["signals"]),
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
