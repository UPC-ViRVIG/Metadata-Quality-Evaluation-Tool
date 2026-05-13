from collections import defaultdict

from rdflib import Graph, URIRef, Literal, BNode
from rdflib.namespace import RDF

from metrics.metric_plugin import MetricPlugin
from models.dataset_context import DatasetContext
from models.metric_result import MetricResult
from metrics.metrics_exceptions import EmptyGraphError

# Maximum number of distinct language columns before collapsing into "other"
MAX_LANGUAGES = 10


def _collect_resource_data(graph: Graph) -> dict:
    """
    Single pass over the graph collecting per-resource literal stats.

    Parameters
    ----------
    graph: rdf.Graph:
        RDF graph to be evaluated

    Returns
    -------
    dict keyed by subject URI string:
        {
            "types": set[str],
            "tagged_count": int
                Number of literals with any language tag
            "untagged_count": int   
                Number of plain string literals (no lang tag)
            "lang_literal_counts": {lang: int}  
                Number of literals of each language
        }
    """
    resources: dict[str, dict] = {}

    for subject, predicate, obj in graph:
        if not isinstance(subject, URIRef):
            continue
        if predicate == RDF.type:
            # Collect type information
            uri = str(subject)
            if uri not in resources:
                resources[uri] = {
                    "types": set(),
                    "tagged_count": 0,
                    "untagged_count": 0,
                    "lang_literal_counts": defaultdict(int),
                }
            if isinstance(obj, URIRef):
                resources[uri]["types"].add(str(obj))
            continue

        if not isinstance(obj, Literal):
            continue

        uri = str(subject)
        if uri not in resources:
            resources[uri] = {
                "types": set(),
                "tagged_count": 0,
                "untagged_count": 0,
                "lang_literal_counts": defaultdict(int),
            }

        lang = obj.language 
        if lang:
            resources[uri]["tagged_count"] += 1
            resources[uri]["lang_literal_counts"][lang.lower()] += 1
        else:
            resources[uri]["untagged_count"] += 1

    return resources


def _compute_general_info(resources: dict) -> dict:
    """
    Computes dataset-level multilingual statistics.

    Parameters
    ----------
    resources : dict
        Resource statistics produced by _collect_resource_data().

    Returns
    -------
    dict:
        {
            resource_language_distribution: dict[str, int]
                How many resources have 0, 1, or 2+ distinct language tags.
            tagged/untagged literal counts: int
                Totals across all resources.
            dominant_language: str
                The language tag appearing in the most resources
            dominant_language_ratio: int
                Fraction of all resources have at least one literal in the
                dominant language
        }
    """
    dist = {"0": 0, "1": 0, "2+": 0}
    total_tagged = 0
    total_untagged = 0
    lang_resource_count: dict[str, int] = defaultdict(int)

    for data in resources.values():
        n_langs = len(data["lang_literal_counts"])
        if n_langs == 0:
            dist["0"] += 1
        elif n_langs == 1:
            dist["1"] += 1
        else:
            dist["2+"] += 1

        total_tagged += data["tagged_count"]
        total_untagged += data["untagged_count"]

        for lang in data["lang_literal_counts"]:
            lang_resource_count[lang] += 1

    n_resources = len(resources)

    if lang_resource_count:
        dominant = max(lang_resource_count, key=lambda l: lang_resource_count[l])
        dominant_ratio = round(
            lang_resource_count[dominant] / n_resources, 4
        ) if n_resources else 0.0
    else:
        dominant = None
        dominant_ratio = 0.0

    return {
        "resource_language_distribution": dist,
        "tagged_literal_count":   total_tagged,
        "untagged_literal_count": total_untagged,
        "dominant_language":      dominant,
        "dominant_language_ratio": dominant_ratio,
    }


def _compute_language_distribution(resources: dict) -> list[dict]:
    """
    Per-language stats sorted descending by resource count.

    Parameters
    ----------
    resources : dict
        Resource statistics produced by _collect_resource_data().

    Returns
    -------
    Each entry: {language, resource_count, literal_count}
    """
    lang_resource_count: dict[str, int] = defaultdict(int)
    lang_literal_count: dict[str, int] = defaultdict(int)

    for data in resources.values():
        for lang, count in data["lang_literal_counts"].items():
            lang_resource_count[lang] += 1
            lang_literal_count[lang] += count

    return sorted(
        [
            {
                "language":       lang,
                "resource_count": lang_resource_count[lang],
                "literal_count":  lang_literal_count[lang],
            }
            for lang in lang_resource_count
        ],
        key=lambda x: x["resource_count"],
        reverse=True,
    )


def _select_top_languages(
    language_distribution: list[dict],
    max_languages: int,
) -> tuple[list[str], bool]:
    """
    Returns the top-N language tags and whether an "other" column
    is needed.
    """
    all_langs = [e["language"] for e in language_distribution]
    if len(all_langs) <= max_languages:
        return all_langs, False
    return all_langs[:max_languages], True


def _compute_class_heatmap(
    resources: dict,
    top_languages: list[str],
    has_other: bool,
) -> list[dict]:
    """
    Builds the class-level heatmap data.
    """
    top_lang_set = set(top_languages)

    class_data: dict[str, dict] = defaultdict(lambda: {
        "instances": set(),
        "lang_resource_sets": defaultdict(set),   
        "other_resource_set": set(),
        "lang_densities": defaultdict(list),      
        "other_densities": [],
    })

    for uri, data in resources.items():
        total_literals = data["tagged_count"] + data["untagged_count"]

        for class_uri in (data["types"] or {"Unknown"}):
            cd = class_data[class_uri]
            cd["instances"].add(uri)

            for lang, count in data["lang_literal_counts"].items():
                ratio = round(count / total_literals, 4) if total_literals else 0.0

                if lang in top_lang_set:
                    cd["lang_resource_sets"][lang].add(uri)
                    cd["lang_densities"][lang].append(ratio)
                else:
                    cd["other_resource_set"].add(uri)
            
            if has_other:
                other_count = sum(
                    count for lang, count in data["lang_literal_counts"].items()
                    if lang not in top_lang_set
                )
                other_ratio = round(
                    other_count / total_literals, 4
                ) if total_literals else 0.0
                cd["other_densities"].append(other_ratio)

    result = []

    for class_uri, cd in class_data.items():
        n = len(cd["instances"])
        if n == 0:
            continue

        coverage = {}
        density_data = {}

        for lang in top_languages:
            resource_set = cd["lang_resource_sets"].get(lang, set())
            coverage[lang] = round(len(resource_set) / n, 4)
            density_data[lang] = cd["lang_densities"].get(lang, [])

        if has_other:
            coverage["other"] = round(len(cd["other_resource_set"]) / n, 4)
            density_data["other"] = cd["other_densities"]

        label = class_uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]

        result.append({
            "class_uri":   class_uri,
            "class_label": label,
            "total":       n,
            "coverage":    coverage,
            "density_data": density_data,
        })

    # Sort by instance count descending
    result.sort(key=lambda x: x["total"], reverse=True)
    return result


def _compute_score(resources: dict) -> float:
    """
    Overall multilingual coverage score.

    Defined as the proportion of resources that have at least one
    language-tagged literal AND at least two distinct languages.
    Resources with only one language tag are partially credited (0.5).

    This rewards genuine multilinguality over monolingual tagging.
    """
    if not resources:
        return 0.0

    total = len(resources)
    score_sum = 0.0

    for data in resources.values():
        n_langs = len(data["lang_literal_counts"])
        if n_langs >= 2:
            score_sum += 1.0
        elif n_langs == 1:
            score_sum += 0.5

    return round(score_sum / total, 4)


class MultilingualLabelingCoverageMetric(MetricPlugin):

    id          = "multilingual_labeling_coverage"

    def evaluate(self, context: DatasetContext) -> MetricResult:
        """
        Evaluates multilingual literal coverage across the dataset.

        Parameters
        ----------
        context : DatasetContext

        Returns
        -------
        MetricResult
            Score: proportion of resources with multilingual content,
            with partial credit for monolingual-tagged resources.
        """
        graph = context.graph

        if len(graph) == 0:
            raise EmptyGraphError(
                f"Dataset '{context.dataset_id}' contains an empty graph."
            )

        resources = _collect_resource_data(graph)

        if not resources:
            return self.error_result(
                f"No named resources found in dataset '{context.dataset_id}'."
            )

        general_info = _compute_general_info(resources)
        language_distribution = _compute_language_distribution(resources)
        top_languages, has_other = _select_top_languages(
            language_distribution, MAX_LANGUAGES
        )
        class_heatmap = _compute_class_heatmap(
            resources, top_languages, has_other
        )

        score = _compute_score(resources)

        details = {
            "total_resources":      len(resources),
            "general_info":         general_info,
            "language_distribution": language_distribution,
            "heatmap": {
                "languages": top_languages + (["other"] if has_other else []),
                "classes":   class_heatmap,
            },
        }

        return MetricResult(
            metric_id=self.id,
            name=self.name,
            score=score,
            weight=self.weight,
            status="computed",
            details=details,
        )