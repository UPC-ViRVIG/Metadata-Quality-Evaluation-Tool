from rdflib import Graph
from rdflib.plugins.stores.sparqlstore import SPARQLStore

from datasource.datasource_interface import DataSource
from datasource.datasource_exceptions import (
    InvalidDataSourceConfiguration,
    DataSourceLoadError
)
import graph.graph_cache as _cache


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
            try:
                store = SPARQLStore(
                    self.endpoint_url,
                    headers={
                        "User-Agent": "MetadataQualityTool/1.0",
                        "Accept": "text/turtle, application/rdf+xml"
                    }
                )

                graph = Graph(store=store)
                results = graph.query(self.query)

                if not hasattr(results, "graph"):
                    raise DataSourceLoadError(
                        "SPARQL query could not return a CONSTRUCT graph."
                    )

                loaded_graph = results.graph

            except Exception:
                # ---- FALLBACK: direct HTTP request ----
                import requests
                from rdflib import Graph

                response = requests.post(
                    self.endpoint_url,
                    data={
                        "query": self.query
                    },
                    headers={
                        "User-Agent": "MetadataQualityTool/1.0",
                        "Accept": "text/turtle",
                        "Content-Type": "application/x-www-form-urlencoded"
                    },
                    timeout=90
                )

                response.raise_for_status()

                loaded_graph = Graph()

                loaded_graph.parse(
                    data=response.text,
                    format="turtle"
                )
                # ---- END FALLBACK ----

        except DataSourceLoadError:
            raise
        except Exception as e:
            raise DataSourceLoadError(
                f"Failed to query SPARQL endpoint: {self.endpoint_url}"
            ) from e
        # FIXME: Bug - caching the wrong object.
        # 'graph' is the SPARQLStore wrapper, not the actual RDF data.
        # 'loaded_graph' contains the real results and should be cached instead.
        # This causes the second call (evaluation) to retrieve a SPARQLStore
        # object from cache instead of the RDF graph, leading to a 422 error.
        # Fix: change _cache.store(self._source_config, graph)
        #      to    _cache.store(self._source_config, loaded_graph)
        _cache.store(self._source_config, loaded_graph)


        from pathlib import Path

        folder = Path(
            r"C:\Users\victo\PycharmProjects\Metadata-Quality-Evaluation-Tool\DataToTest"
        )

        filename = f"endpoint_data.ttl"

        output_path = folder / filename
        loaded_graph.serialize(
            destination=str(output_path),
            format="turtle"
        )

        return loaded_graph