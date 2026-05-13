from rdflib import Graph

from datasource.datasource_interface import DataSource
from datasource.datasource_exceptions import (
    InvalidDataSourceConfiguration,
    DataSourceLoadError
)
import graph.graph_cache as _cache


class RDFFileSource(DataSource):
    """
    DataSource strategy that loads RDF data from a local file.
    """

    def __init__(self, file_path: str, rdf_format: str = None):
        """
        Parameters
        ----------
        file_path : str
            Path to the local RDF file.
        rdf_format : str | None
            RDF serialisation format (e.g. 'turtle', 'xml', 'n3').
            If None, rdflib will attempt auto-detection.

        Raises
        ------
        InvalidDataSourceConfiguration
            If file_path is missing.
        """
        if not file_path:
            raise InvalidDataSourceConfiguration("File path is missing.")

        self.file_path = file_path
        self.rdf_format = rdf_format
        self._source_config = {
            "type": "rdf_file",
            "file_path": file_path,
            "format": rdf_format,
        }

    def load(self) -> Graph:
        """
        Returns the parsed RDF graph, loading from disk on first call
        and from cache on subsequent calls.

        Returns
        -------
        rdflib.Graph

        Raises
        ------
        DataSourceLoadError
            If the file cannot be found or parsed.
        """
        cached = _cache.get(self._source_config)
        if cached is not None:
            return cached

        try:
            graph = Graph()
            graph.parse(self.file_path, format=self.rdf_format)
        except FileNotFoundError:
            raise DataSourceLoadError(
                f"RDF file not found: {self.file_path}"
            )
        except Exception as e:
            raise DataSourceLoadError(
                f"Failed to parse RDF file '{self.file_path}': {e}"
            ) from e

        _cache.store(self._source_config, graph)
        return graph