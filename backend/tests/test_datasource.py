"""
tests/test_datasource.py
------------------------
Unit tests for the data source layer.

Covers the factory's dispatch on source type, successful loading of
local RDF files, format auto-detection, and the error paths that must
surface as DataSourceException subclasses rather than as raw parser or
network failures.

Also covers the diagnostics that replace RDFLib's message when an
endpoint query fails, since that message blames the query regardless of
what actually went wrong.

Endpoint tests use mocks, so the suite runs without network access.
"""

import io
import pytest
from pathlib import Path
from urllib.error import HTTPError, URLError
from unittest.mock import MagicMock, patch
from rdflib import Graph

import graph.graph_cache as graph_cache
from datasource.datasource_factory import DataSourceFactory
from datasource.datasource_exceptions import (
    InvalidDataSourceConfiguration,
    DataSourceLoadError,
    UnsupportedDataSourceException,
)


TEST_RESOURCES = Path(__file__).parent / "resources"


# ------------------------------------------------------------------
# SUCCESS CASES
# ------------------------------------------------------------------

def test_rdf_file_valid_turtle():
    """Valid Turtle file should load successfully."""

    source_config = {
        "type": "rdf_file",
        "file_path": str(TEST_RESOURCES / "valid.ttl"),
        "format": "turtle",
    }

    source = DataSourceFactory.create(source_config)
    graph = source.load()

    assert len(graph) > 0


def test_rdf_file_autodetect_format():
    """Valid Turtle file should load without explicitly specifying format."""

    source_config = {
        "type": "rdf_file",
        "file_path": str(TEST_RESOURCES / "valid.ttl"),
        # No format provided
    }

    source = DataSourceFactory.create(source_config)
    graph = source.load()

    assert len(graph) > 0

def test_sparql_endpoint_valid_construct():
    """Valid SPARQL endpoint query should return a graph."""

    source_config = {
        "type": "sparql_endpoint",
        "endpoint_url": "http://fake-endpoint.org/sparql",
        "query": "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }",
    }

    fake_graph = Graph()
    fake_graph.add((
        fake_graph.namespace_manager.compute_qname("rdf:type")[1],
        fake_graph.namespace_manager.compute_qname("rdf:type")[1],
        fake_graph.namespace_manager.compute_qname("rdf:type")[1],
    ))

    mock_results = MagicMock()
    mock_results.graph = fake_graph

    with patch("datasource.sources.sparql_endpoint.Graph.query", return_value=mock_results):
        source = DataSourceFactory.create(source_config)
        graph = source.load()

        assert isinstance(graph, Graph)


# ------------------------------------------------------------------
# CONFIGURATION ERRORS (constructor-level)
# ------------------------------------------------------------------

def test_rdf_file_missing_path():
    """Missing file path should raise configuration error."""

    source_config = {
        "type": "rdf_file",
        "file_path": "",
        "format": "turtle",
    }

    with pytest.raises(InvalidDataSourceConfiguration):
        DataSourceFactory.create(source_config)


def test_rdf_file_nonexistent_file():
    """Non-existent file should raise configuration error."""

    source_config = {
        "type": "rdf_file",
        "file_path": str(TEST_RESOURCES / "does_not_exist.ttl"),
        "format": "turtle",
    }

    with pytest.raises(InvalidDataSourceConfiguration):
        DataSourceFactory.create(source_config)

def test_sparql_endpoint_missing_endpoint():
    """Not including an endpoint should draise an InvalidDataSourceConfiguration error"""

    source_config = {
        "type": "sparql_endpoint",
        "endpoint_url": "",
        "query": "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }",
    }

    with pytest.raises(InvalidDataSourceConfiguration):
        DataSourceFactory.create(source_config)

def test_sparql_endpoint_missing_query():
    """Not including a query should draise an InvalidDataSourceConfiguration error"""

    source_config = {
        "type": "sparql_endpoint",
        "endpoint_url": "http://fake-endpoint.org/sparql",
        "query": "",
    }

    with pytest.raises(InvalidDataSourceConfiguration):
        DataSourceFactory.create(source_config)
        
# ------------------------------------------------------------------
# PARSING ERRORS (load-level)
# ------------------------------------------------------------------

def test_rdf_file_invalid_format_declaration():
    """Declaring an invalid RDF format should raise DataSourceLoadError."""

    source_config = {
        "type": "rdf_file",
        "file_path": str(TEST_RESOURCES / "valid.ttl"),
        "format": "invalid_format",
    }

    source = DataSourceFactory.create(source_config)

    with pytest.raises(DataSourceLoadError):
        source.load()


def test_rdf_file_invalid_syntax():
    """Malformed RDF content should raise DataSourceLoadError."""

    source_config = {
        "type": "rdf_file",
        "file_path": str(TEST_RESOURCES / "invalid.ttl"),
        "format": "turtle",
    }

    source = DataSourceFactory.create(source_config)

    with pytest.raises(DataSourceLoadError):
        source.load()


# ------------------------------------------------------------------
# FACTORY ERRORS
# ------------------------------------------------------------------

def test_unsupported_datasource_type():
    """Unknown datasource type should raise UnsupportedDataSourceException."""
    
    source_config = {
        "type": "unknown_type",
        "file_path": "whatever",
    }

    with pytest.raises(UnsupportedDataSourceException):
        DataSourceFactory.create(source_config)

# ------------------------------------------------------------------
# SPARQL FAILURE DIAGNOSTICS
# ------------------------------------------------------------------

SPARQL_CONFIG = {
    "type": "sparql_endpoint",
    "endpoint_url": "http://fake-endpoint.org/sparql",
    "query": "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }",
}


def _failing_source(cause):
    """
    Build a source whose query fails, with cause chained as RDFLib does.

    RDFLib wraps the transport failure in its own ValueError, so the
    chain is reproduced here rather than the cause being raised
    directly. Returns the error message load raises, so a test can
    assert what the user would be told.

    The graph cache is cleared first: it is a process-wide singleton
    keyed by source configuration, so a graph cached by an earlier test
    would be returned instead of the query being attempted.
    """
    graph_cache.clear()
    source = DataSourceFactory.create(SPARQL_CONFIG)

    wrapped = ValueError(
        "You did something wrong formulating either the URI or your "
        "SPARQL query"
    )
    wrapped.__cause__ = cause

    with patch("datasource.sources.sparql_endpoint.Graph.query",
               side_effect=wrapped):
        with pytest.raises(DataSourceLoadError) as raised:
            source.load()

    return str(raised.value)


def _http_error(status, body=""):
    """Build an HTTPError the way urllib delivers one."""

    return HTTPError(
        url=SPARQL_CONFIG["endpoint_url"],
        code=status,
        msg="Too Many Requests" if status == 429 else "Error",
        hdrs=None,
        fp=io.BytesIO(body.encode("utf-8")) if body else None,
    )


@pytest.mark.parametrize("status,expected", [
    (429, "rate limiting"),
    (403, "refused access"),
    (500, "internal error"),
    (503, "temporarily unavailable"),
    (414, "too long to be sent in a URL"),
    (400, "malformed"),
    (404, "No SPARQL service"),
])
def test_failure_names_the_http_status(status, expected):
    """The real status is reported instead of blaming the query."""

    message = _failing_source(_http_error(status))

    assert f"HTTP {status}" in message
    assert expected in message
    assert "You did something wrong" not in message


def test_rate_limiting_passes_through_the_endpoints_own_words():
    """
    The endpoint's explanation is the actionable part.

    This is the case that motivated the change: Wikidata answers 429
    with a description of its own outage, which RDFLib discards.
    """
    message = _failing_source(_http_error(
        429,
        "Aggressively rate-limiting to 1 req / min - this rule was created "
        "during active wdqs outage\nsecond line",
    ))

    assert "HTTP 429" in message
    assert "Aggressively rate-limiting to 1 req / min" in message
    assert "second line" not in message


def test_status_reason_is_used_when_there_is_no_body():
    """An error with no body still names what the endpoint called it."""

    assert "Too Many Requests" in _failing_source(_http_error(429))


def test_unknown_status_still_explains_itself():
    """A status with no canned explanation is still described."""

    assert "rejected the request" in _failing_source(_http_error(418))
    assert "internal error" in _failing_source(_http_error(599))


def test_unreachable_endpoint_is_reported_as_such():
    """A connection failure is not presented as a query problem."""

    message = _failing_source(URLError("no route to host"))

    assert "could not be reached" in message
    assert "no route to host" in message
    assert "You did something wrong" not in message


def test_failure_without_transport_cause_points_at_the_response():
    """
    With nothing chained, the fault was in handling the response.

    The original message is quoted here because it is the only thing
    carrying information.
    """
    message = _failing_source(None)

    assert "could not be read as a graph" in message
    assert "You did something wrong" in message


def test_diagnosis_does_not_query_the_endpoint_again():
    """
    Diagnosing must not issue a second request.

    Rate limiting is one of the failures being diagnosed, so a retry
    would be the worst possible response to it.
    """
    graph_cache.clear()
    source = DataSourceFactory.create(SPARQL_CONFIG)

    wrapped = ValueError("wrapped")
    wrapped.__cause__ = _http_error(429)

    with patch("datasource.sources.sparql_endpoint.Graph.query",
               side_effect=wrapped) as query:
        with pytest.raises(DataSourceLoadError):
            source.load()

    assert query.call_count == 1


def test_select_query_still_reports_the_construct_requirement():
    """
    The CONSTRUCT guard must not be absorbed into the diagnostics.

    A SELECT query returns bindings rather than a graph, and saying so
    is more useful than any status code.
    """
    graph_cache.clear()
    source = DataSourceFactory.create({
        **SPARQL_CONFIG,
        "query": "SELECT ?s WHERE { ?s ?p ?o }",
    })

    bindings = MagicMock(spec=[])  # no .graph attribute

    with patch("datasource.sources.sparql_endpoint.Graph.query",
               return_value=bindings):
        with pytest.raises(DataSourceLoadError, match="CONSTRUCT"):
            source.load()


def test_html_error_page_is_not_quoted_at_the_user():
    """
    An HTML body is ignored in favour of the status reason.

    Wikidata answers 429 with an HTML page, while the detail worth
    reading sits in the reason.
    """
    message = _failing_source(_http_error(
        429, "<!DOCTYPE html><html><body>Too many requests</body></html>"
    ))

    assert "<!DOCTYPE html" not in message
    assert "Too Many Requests" in message
