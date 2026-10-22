"""
datasource/sources/sparql_endpoint.py
-------------------------------------
DataSource strategy for remote SPARQL endpoints.

Executes a CONSTRUCT query through RDFLib's SPARQLStore and materialises
the result into an rdflib.Graph. CONSTRUCT is required rather than
optional: a SELECT query returns bindings, not a graph, and is rejected
as a load error.

Queries sent in JSON request bodies must be on a single line — embedded
newlines cause several public endpoints, Wikidata and DBpedia among
them, to answer with 502 or 422. YAML configuration files avoid this
because the folded block scalar collapses the query automatically.

As with local files, the retrieved graph is stored in the shared cache
so repeated evaluations do not re-query the endpoint.

RDFLib reports every transport problem as the same ValueError, which
blames the query even when the endpoint was rate limiting or down. It
does however chain the underlying HTTP error, so the real cause is
recovered from the exception chain and named in the message. A message
about the query would otherwise send the user off rewriting something
that was never wrong.

The cause is read rather than re-requested on purpose: rate limiting is
one of the common failures, and a second request would be the worst
possible response to it.

Note that an Accept header cannot be set through SPARQLStore: its
connector overwrites the headers it is given with one derived from
returnFormat. Content negotiation is left at RDFLib's default, which
both DBpedia and Wikidata answer.
"""

from urllib.error import HTTPError, URLError

from rdflib import Graph
from rdflib.plugins.stores.sparqlstore import SPARQLStore

from datasource.datasource_interface import DataSource
from datasource.datasource_exceptions import (
    InvalidDataSourceConfiguration,
    DataSourceLoadError
)
import graph.graph_cache as _cache

_STATUS_EXPLANATIONS = {
    400: "It considered the query malformed, so the query itself is worth "
         "checking.",
    401: "It requires authentication.",
    403: "It refused access. Public endpoints often answer this way when a "
         "client is querying too often.",
    404: "No SPARQL service was found at that URL.",
    405: "It does not accept requests of this kind at that URL.",
    414: "The query was too long to be sent in a URL. Shorten it, for "
         "example by removing comments and extra whitespace.",
    429: "It is rate limiting the request. Wait a moment and try again.",
    500: "The endpoint reported an internal error. The query may be too "
         "heavy for it, or it may dislike the requested response format.",
    502: "The endpoint is behind a gateway that did not answer.",
    503: "The endpoint is temporarily unavailable, usually because it is "
         "overloaded.",
    504: "The endpoint timed out while answering. Try a smaller result set.",
}


class SPARQLEndpointSource(DataSource):
    """
    DataSource strategy that retrieves RDF data from a SPARQL endpoint
    using a CONSTRUCT query and materializes it into an rdflib.Graph.
    """

    def __init__(self, endpoint_url: str, query: str):
        """
        Parameters
        ----------
        endpoint_url : str
            Public SPARQL endpoint URL.
        query : str
            SPARQL CONSTRUCT query.

        Raises
        ------
        InvalidDataSourceConfiguration
            If the endpoint or query is missing.
        """
        if not endpoint_url:
            raise InvalidDataSourceConfiguration("Endpoint is missing.")
        if not query:
            raise InvalidDataSourceConfiguration("Query is missing.")

        self.endpoint_url = endpoint_url
        self.query = query
        self._source_config = {
            "type": "sparql_endpoint",
            "endpoint_url": endpoint_url,
            "query": query,
        }

    def load(self) -> Graph:
        """
        Returns the queried RDF graph, fetching from the endpoint on
        first call and from cache on subsequent calls.

        Returns
        -------
        rdflib.Graph

        Raises
        ------
        DataSourceLoadError
            If the endpoint cannot be reached or the query fails.
        """
        cached = _cache.get(self._source_config)
        if cached is not None:
            return cached

        try:
            store = SPARQLStore(
                self.endpoint_url,
                headers={"User-Agent": "MetadataQualityTool/1.0"},
            )
            graph = Graph(store=store)
            results = graph.query(self.query)

            if not hasattr(results, "graph"):
                raise DataSourceLoadError(
                    "SPARQL query could not return a CONSTRUCT graph."
                )

            loaded_graph = results.graph

        except DataSourceLoadError:
            raise
        except Exception as e:
            raise DataSourceLoadError(
                _describe_failure(self.endpoint_url, self.query, e)
            ) from e

        _cache.store(self._source_config, loaded_graph)
        return loaded_graph

def _describe_failure(endpoint_url: str, query: str, error: Exception) -> str:
    """
    Explain why a SPARQL query failed.

    RDFLib raises the same ValueError whether the endpoint returned 500,
    rate limited the request, or was never reachable, but it chains the
    original error, so the status code and the endpoint's own reason can
    be recovered from there without issuing another request.

    Parameters
    ----------
    endpoint_url : str
        The endpoint that was queried.
    query : str
        The query that failed. Unused in the message, kept so callers
        read naturally alongside the endpoint.
    error : Exception
        The failure raised by RDFLib, whose chain carries the cause.

    Returns
    -------
    str
        A message naming the real cause where one could be determined.
    """
    cause = _http_cause(error)

    if isinstance(cause, HTTPError):
        status = cause.code
        explanation = _STATUS_EXPLANATIONS.get(status)
        if explanation is None:
            explanation = (
                "The endpoint rejected the request."
                if status < 500 else
                "The endpoint reported an internal error."
            )

        message = (
            f"The endpoint {endpoint_url} returned HTTP {status}. "
            f"{explanation}"
        )

        reason = _http_reason(cause)
        if reason:
            message += f" It reported: {reason}"
        return message

    if isinstance(cause, URLError):
        return (
            f"The endpoint {endpoint_url} could not be reached: "
            f"{cause.reason}. Check the URL and the network connection."
        )

    return (
        f"The endpoint {endpoint_url} answered, but the response could not "
        f"be read as a graph: {error}"
    )


def _http_cause(error: Exception) -> Exception | None:
    """
    Find the HTTP or network error underlying a failure.

    Parameters
    ----------
    error : Exception
        The exception raised by RDFLib.

    Returns
    -------
    Exception | None
        The first HTTPError or URLError in the chain, or None when the
        failure did not come from the transport.
    """
    seen: set[int] = set()
    current: BaseException | None = error

    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (HTTPError, URLError)):
            return current
        current = current.__cause__ or current.__context__

    return None


def _http_reason(cause: HTTPError) -> str:
    """
    Read the endpoint's own explanation out of an HTTP error.

    A plain text body is preferred, because engines such as Virtuoso
    put their real complaint there while the status reason stays
    generic. A markup body is ignored instead: an HTML error page
    contributes nothing to a one line message, and in that case the
    status reason carries the detail, as with Wikidata's description of
    its own rate limiting.

    Parameters
    ----------
    cause : HTTPError
        The chained HTTP error.

    Returns
    -------
    str
        The first useful line available, trimmed to stay readable in a
        single message. Empty when there is nothing to report.
    """
    body = _http_body(cause).strip()
    if body.startswith("<"):
        body = ""

    for candidate in (body, getattr(cause, "reason", "")):
        text = str(candidate or "").strip()
        if text:
            return text.splitlines()[0][:200]
    return ""


def _http_body(cause: HTTPError) -> str:
    """
    Read an HTTP error's body without letting that reading fail.

    The body of an HTTPError is a stream that may already be consumed or
    closed, and a failure to read it must not replace the diagnosis.

    Parameters
    ----------
    cause : HTTPError
        The chained HTTP error.

    Returns
    -------
    str
        The decoded body, or an empty string.
    """
    try:
        return cause.read().decode("utf-8", "replace")
    except Exception:
        return ""
