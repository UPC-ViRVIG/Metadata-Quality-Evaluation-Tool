"""
metrics/plugins/property_coverage.py
------------------------------------
Measures how consistently properties are used within each class.

This metric is entirely data-driven: it imposes no external schema and
derives its expectation from the data itself. If most instances of a
class carry a property, an instance missing that property is treated as
a gap. That makes the metric applicable to collections for which no
shape profile exists.

Resources are grouped by rdf:type, and those without a usable type fall
into a synthetic "Unknown" class so that they are still accounted for.
rdf:type itself is excluded from coverage, since every typed resource
carries it by construction.

Score
-----
Within a class, the fill rate of a property is the proportion of that
class's resources using it at least once. A class score is the mean of
its property fill rates, and the metric score is the mean of the class
scores weighted by class size — so a class with thousands of resources
influences the result more than one with a handful.
"""

from collections import defaultdict
from rdflib import Graph, URIRef, BNode
from rdflib.namespace import RDF
import statistics

from metrics.metric_plugin import MetricPlugin
from models.dataset_context import DatasetContext
from models.metric_result import MetricResult
from metrics.metrics_exceptions import EmptyGraphError, NoTargetRecordsError


EXCLUDED_PROPERTIES = {
    str(RDF.type),
}


def get_records_by_class(graph: Graph) -> dict[str, set[str]]:
    """
    Group named RDF resources by rdf:type.

    Each resource is associated with every RDF class declared via
    rdf:type. Resources without a non-blank rdf:type are grouped
    under the synthetic class label "Unknown".

    Scope is not applied here. The engine has already restricted the
    graph to the selected resources, and those resources keep all their
    types, so this metric reports the same classes as every other.

    Parameters
    ----------
    graph : rdflib.Graph
        RDF graph to analyse.

    Returns
    -------
    dict
        Structure:

            {
                class_uri: str
                    RDF class URI or the synthetic label "Unknown".
                    {
                        resource_uri: str
                            URI of a named RDF subject/resource.
                        ...
                    }
            } 
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


def compute_class_property_fill_rates(
    graph: Graph,
    class_records: dict[str, set[str]]
) -> dict[str, dict[str, dict]]:
    """
    Compute per-property completeness statistics for each RDF class.

    For every class:
        - determine which properties appear among its records
        - count how many records contain each property
        - compute property fill rates

    Fill rate is defined as:
        (# records containing property) / (total records in class)

    Parameters
    ----------
    graph : rdflib.Graph
        RDF graph being analysed.
    class_records : dict[str, set[str]]
        Mapping produced by get_records_by_class().
        Structure:
            {
                class_uri: {
                    resource_uri,
                    ...
                }
            }

    Returns
    -------
    dict
        Nested structure:
            {
                class_uri: {
                    property_uri: {
                        "present": int,
                            Number of class records containing at least one value
                            for the property.
                        "missing": int,
                            Number of class records not containing the property.
                        "fill_rate": float
                            Fraction of records containing the property.
                    }
                }
            }    
    """
    result = {}

    for class_uri, records in class_records.items():
        class_total = len(records)
        prop_counts: dict[str, set[str]] = defaultdict(set)

        for record_uri in records:
            for _, prop, _ in graph.triples(
                (URIRef(record_uri), None, None)
            ):
                prop_str = str(prop)
                if prop_str not in EXCLUDED_PROPERTIES:
                    prop_counts[prop_str].add(record_uri)

        class_fill_rates = {
            prop: {
                "present":   len(record_set),
                "missing":   class_total - len(record_set),
                "fill_rate": round(len(record_set) / class_total, 4)
            }
            for prop, record_set in prop_counts.items()
        }

        result[class_uri] = dict(
            sorted(
                class_fill_rates.items(),
                key=lambda x: x[1]["fill_rate"]
            )
        )

    return result


def compute_class_scores(
    class_property_fill_rates: dict[str, dict[str, dict]]
) -> dict[str, float]:
    """
    Compute a completeness score for each RDF class.

    For a class C with properties P: score(C) = Σ fill_rate(p) / |P|                   

    Parameters
    ----------
    class_property_fill_rates : dict
        Per-property completeness statistics produced by
        compute_class_property_fill_rates().

    Returns
    -------
    dict:
        Structure:
        {
             class_uri: class_score
                Mean property fill rate for the class.
        }
    """
    return {
        class_uri: round(
            statistics.mean(
                prop["fill_rate"]
                for prop in props.values()
            ),
            4
        )
        for class_uri, props in class_property_fill_rates.items()
        if props
    }


def compute_overall_score(
    class_scores: dict[str, float],
    class_records: dict[str, set[str]]
) -> float:
    """
    Compute the overall dataset completeness score.

    overall_score = Σ(score(C) × records(C)) / Σ(records(C))

    Parameters
    ----------
    class_scores : dict[str, float]
        Per-class completeness scores.
    class_records : dict[str, set[str]]
        Mapping of classes to their associated records.

    Returns
    -------
    float
        Overall dataset completeness score.
    """
    total_weighted = sum(
        class_scores[cls] * len(class_records[cls])
        for cls in class_scores
        if cls in class_records
    )
    total_weight = sum(
        len(class_records[cls])
        for cls in class_scores
        if cls in class_records
    )

    return round(total_weighted / total_weight, 4) if total_weight > 0 else 1.0


class PropertyCoverageMetric(MetricPlugin):
    """
    Measures metadata completeness across RDF classes.
    """

    id          = "property_coverage"

    def evaluate(self, context: DatasetContext) -> MetricResult:
        """
        Evaluates how consistently properties are used across classes.

        Groups resources by rdf:type, computes the per-class property
        fill rates, reduces those to one score per class, and combines
        the class scores into a size-weighted overall score.

        Parameters
        ----------
        context : DatasetContext
            Contains the RDF graph to evaluate and the optional scope.

        Returns
        -------
        MetricResult
            Score: the mean of the class scores, weighted by the number
            of resources in each class.
            Details: total record count, resources per class, per-class
            scores, and per-class property fill rates.

        Raises
        ------
        EmptyGraphError
            If the dataset graph contains no triples.
        NoTargetRecordsError
            If the graph contains triples but no typed records.
        """
        graph = context.graph

        if len(graph) == 0:
            raise EmptyGraphError(
                f"Dataset '{context.dataset_id}' contains an empty graph."
            )

        class_records = get_records_by_class(graph)

        if not class_records:
            raise NoTargetRecordsError(
                f"No typed records found in dataset "
                f"'{context.dataset_id}'."
            )

        class_property_fill_rates = compute_class_property_fill_rates(
            graph, class_records
        )

        class_scores = compute_class_scores(class_property_fill_rates)

        final_score = compute_overall_score(class_scores, class_records)

        details = {
            "total_records": sum(
                len(records) for records in class_records.values()
            ),
            "classes_found": {
                cls: len(records)
                for cls, records in class_records.items()
            },
            "class_scores":              class_scores,
            "class_property_fill_rates": class_property_fill_rates,
        }

        return MetricResult(
            metric_id=self.id,
            name=self.name,
            score=final_score,
            weight=self.weight,
            status="computed",
            details=details,
        )