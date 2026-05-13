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


def get_records_by_class(graph: Graph, scope: list[str] | None = None) -> dict[str, set[str]]:
    """
    Group named RDF resources by rdf:type.

    Each resource is associated with every RDF class declared via
    rdf:type. Resources without a non-blank rdf:type are grouped
    under the synthetic class label "Unknown".

    Parameters
    ----------
    graph : rdflib.Graph
        RDF graph to analyse.
    scope : list[str] | None, optional
        Optional whitelist of class URIs.

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
    scope_set = set(scope) if scope else None
    print(f"[DEBUG] scope_set = {scope_set}") 
    class_records: dict[str, set[str]] = defaultdict(set)

    for subject in graph.subjects():
        if isinstance(subject, BNode):
            continue

        types = [
            str(t) for t in graph.objects(subject, RDF.type)
            if not isinstance(t, BNode)
        ]

        if scope_set:
            types = [t for t in types if t in scope_set]

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
        graph = context.graph

        if len(graph) == 0:
            raise EmptyGraphError(
                f"Dataset '{context.dataset_id}' contains an empty graph."
            )

        class_records = get_records_by_class(graph, context.scope)

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