"""
tests/test_profile_upload.py
----------------------------
Unit tests for adding a user's SHACL file as a Structural Completeness
profile.

Covers what is accepted and refused on upload, that an added profile
becomes a valid choice straight away and is scored with the same rule as
the built-in ones, that it survives being read back from disk, and the
upload and delete endpoints.

Every test stores profiles in a temporary folder instead of
backend/uploads, so the suite leaves nothing behind.
"""

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph

import main
from metrics import profile_store
from metrics.plugins.structural_completeness import (
    StructuralCompletenessMetric,
    all_profiles,
    describe_profiles,
    register_profile,
    remove_profile,
)
from metrics.profile_store import ProfileError
from models.dataset_context import DatasetContext


SHAPES = b"""
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ex: <http://example.org/> .

ex:PaintingShape a sh:NodeShape ;
    sh:targetClass ex:Painting ;
    sh:property [ sh:path ex:title ;   sh:minCount 1 ] ;
    sh:property [ sh:path ex:creator ; sh:minCount 1 ] .
"""

DATA = """
@prefix ex: <http://example.org/> .
ex:p1 a ex:Painting ; ex:title "A" ; ex:creator "B" .
ex:p2 a ex:Painting ; ex:title "C" .
"""


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Keep added profiles in a temporary folder for each test."""

    monkeypatch.setattr(profile_store, "UPLOAD_DIR", tmp_path / "profiles")


# ------------------------------------------------------------------
# ACCEPTED
# ------------------------------------------------------------------

def test_added_profile_becomes_a_choice():
    """Once added, the profile can be selected without a restart."""

    profile_id = register_profile("museum.ttl", SHAPES, name="Museum model")

    choices = [c["id"] for c in
               StructuralCompletenessMetric.get_options()["profile"]["choices"]]

    assert profile_id in choices
    assert all_profiles()[profile_id]["name"] == "Museum model"
    assert all_profiles()[profile_id]["uploaded"] is True


def test_added_profile_is_scored_with_the_same_rule():
    """p1 meets both requirements, p2 one of two: mean 0.75."""

    profile_id = register_profile("museum.ttl", SHAPES)
    graph = Graph()
    graph.parse(data=DATA, format="turtle")

    result = StructuralCompletenessMetric().evaluate(DatasetContext(
        "d", "d", graph,
        options={"structural_completeness": {"profile": profile_id}},
    ))

    assert result.score == 0.75
    assert result.details["profile_source"] == "selected"
    assert len(result.details["profile_sha256"]) == 64


def test_rdf_xml_is_accepted_and_kept_as_turtle():
    """The format is guessed from the name; storage is always Turtle."""

    source = Graph()
    source.parse(data=SHAPES.decode(), format="turtle")
    xml = source.serialize(format="xml").encode()

    profile_id = register_profile("model.rdf", xml)

    assert all_profiles()[profile_id]["file"].suffix == ".ttl"


def test_same_file_added_twice_keeps_one_profile():
    """The identifier comes from the content, so it is stable."""

    first = register_profile("museum.ttl", SHAPES)
    second = register_profile("museum.ttl", SHAPES)

    assert first == second
    assert sum(1 for p in all_profiles().values() if p.get("uploaded")) == 1


# ------------------------------------------------------------------
# REFUSED
# ------------------------------------------------------------------

@pytest.mark.parametrize("content,fragment", [
    (b"", "empty"),
    (b"this is not turtle {", "could not be read as RDF"),
    (b"@prefix ex: <http://example.org/> . ex:a ex:b ex:c .",
     "no shape with a target"),
    (b"""@prefix sh: <http://www.w3.org/ns/shacl#> .
         @prefix ex: <http://example.org/> .
         ex:S a sh:NodeShape ; sh:targetClass ex:Painting .""",
     "check no constraints"),
    (b"""@prefix sh: <http://www.w3.org/ns/shacl#> .
         @prefix ex: <http://example.org/> .
         ex:S a sh:NodeShape ; sh:targetClass ex:Painting ;
             sh:sparql [ sh:select "SELECT $this WHERE { SERVICE <http://x> {} }" ] .""",
     "ex:S uses a SPARQL query that contacts other servers with SERVICE"),
    (b"""@prefix sh: <http://www.w3.org/ns/shacl#> .
         @prefix ex: <http://example.org/> .
         ex:S a sh:NodeShape ; sh:targetClass ex:Painting ;
             sh:sparql [ sh:select "select $this where { service silent <http://x> { $this ?p ?o } }" ] .""",
     "SERVICE"),
    (b"""@prefix sh: <http://www.w3.org/ns/shacl#> .
         @prefix ex: <http://example.org/> .
         ex:S a sh:NodeShape ; sh:targetClass ex:Painting ;
             sh:sparql [ sh:select "SELECT $this FROM <http://x/g> WHERE { $this ?p ?o }" ] .""",
     "loads other graphs with FROM"),
    (b"""@prefix sh: <http://www.w3.org/ns/shacl#> .
         @prefix ex: <http://example.org/> .
         ex:S a sh:NodeShape ; sh:targetClass ex:Painting ;
             sh:sparql [ sh:select "SELECT $this WHERE { this is not sparql" ] .""",
     "cannot be read"),
    (b"""@prefix sh: <http://www.w3.org/ns/shacl#> .
         @prefix ex: <http://example.org/> .
         ex:S a sh:NodeShape ; sh:targetClass ex:Painting ;
             sh:property [ sh:path ex:title ; sh:minCount 1 ] ;
             sh:rule [ a sh:SPARQLRule ;
                       sh:construct "CONSTRUCT { $this ex:title 'x' } WHERE {}" ] .""",
     "a SHACL rule"),
    (b"""@prefix sh: <http://www.w3.org/ns/shacl#> .
         @prefix ex: <http://example.org/> .
         ex:S a sh:NodeShape ; sh:target [ a ex:MyTargetType ] ;
             sh:property [ sh:path ex:title ; sh:minCount 1 ] .""",
     "custom target type"),
])
def test_unusable_files_are_refused(content, fragment):
    """Each refusal says what is wrong with the file."""

    with pytest.raises(ProfileError, match=fragment):
        register_profile("bad.ttl", content)


def test_built_in_ids_are_reserved():
    """An added profile cannot replace EDM, core or Auto."""

    for reserved in ("edm", "core", "auto"):
        with pytest.raises(ProfileError, match="built-in"):
            register_profile("x.ttl", SHAPES, profile_id=reserved)


def test_built_in_profiles_cannot_be_removed():
    """Only added profiles can be deleted."""

    with pytest.raises(ProfileError, match="built-in"):
        remove_profile("edm")


# ------------------------------------------------------------------
# REMOVAL AND THE API
# ------------------------------------------------------------------

def test_removed_profile_is_no_longer_a_choice():
    """After removal, choosing it is an invalid option again."""

    profile_id = register_profile("museum.ttl", SHAPES)
    remove_profile(profile_id)

    choices = [c["id"] for c in
               StructuralCompletenessMetric.get_options()["profile"]["choices"]]
    assert profile_id not in choices


def test_upload_and_delete_endpoints():
    """Upload returns the described profile; delete removes it."""

    client = TestClient(main.app)

    response = client.post("/profiles/upload?filename=museum.ttl&name=Museum",
                           content=SHAPES)
    assert response.status_code == 200
    profile = response.json()
    assert profile["uploaded"] is True
    assert profile["name"] == "Museum"
    assert profile["shapes"][0]["targets"][0]["label"].endswith("Painting")

    listed = [p["id"] for p in client.get("/profiles").json()]
    assert profile["id"] in listed

    assert client.delete(f"/profiles/{profile['id']}").status_code == 200
    assert client.delete(f"/profiles/{profile['id']}").status_code == 404
    assert client.delete("/profiles/edm").status_code == 400


def test_upload_endpoint_reports_a_refusal_as_400():
    """A bad file is a client error with a readable reason."""

    client = TestClient(main.app)
    response = client.post("/profiles/upload?filename=bad.ttl", content=b"nope {")

    assert response.status_code == 400
    assert "could not be read as RDF" in response.json()["detail"]


# ------------------------------------------------------------------
# PROFILES WRITTEN AS DOMAIN AND RANGE CHECKS
# ------------------------------------------------------------------

RANGE_SHAPES = b"""
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ex: <http://example.org/> .

ex:died-domain a sh:NodeShape ;
    sh:targetSubjectsOf ex:died ;
    sh:class ex:Death ;
    sh:message "subject of died must be a Death" .

ex:died-range a sh:NodeShape ;
    sh:targetObjectsOf ex:died ;
    sh:class ex:Person ;
    sh:message "object of died must be a Person" .

ex:note-range a sh:NodeShape ;
    sh:targetObjectsOf ex:note ;
    sh:nodeKind sh:Literal ;
    sh:message "object of note must be a literal" .
"""


def test_view_shows_value_targets_and_rules_on_the_shape():
    """Range shapes and sh:class on the shape itself are described."""

    profile_id = register_profile("crm.ttl", RANGE_SHAPES)
    profile = next(p for p in describe_profiles() if p["id"] == profile_id)

    rows = {
        (shape["targets"][0]["kind"], prop["requirement"])
        for shape in profile["shapes"] for prop in shape["properties"]
    }
    assert ("subjects_of", "must be a ex:Death") in rows
    assert ("objects_of", "must be a ex:Person") in rows
    assert ("objects_of", "must be a literal") in rows


def test_literal_values_are_not_records():
    """Only resources are scored; a note's text is a value."""

    profile_id = register_profile("crm.ttl", RANGE_SHAPES)
    graph = Graph()
    graph.parse(data="""
        @prefix ex: <http://example.org/> .
        ex:d a ex:Death ; ex:died ex:p .
        ex:p a ex:Person ; ex:note "a note" .
    """, format="turtle")

    result = StructuralCompletenessMetric().evaluate(DatasetContext(
        "d", "d", graph,
        options={"structural_completeness": {"profile": profile_id}},
    ))

    assert result.details["total_records"] == 2


# ------------------------------------------------------------------
# AUTO PREFERS ADDED PROFILES
# ------------------------------------------------------------------

def _auto_profile(data_ttl: str) -> str:
    """Run on Auto and report the profile it used."""

    graph = Graph()
    graph.parse(data=data_ttl, format="turtle")
    return StructuralCompletenessMetric().evaluate(
        DatasetContext("d", "d", graph)
    ).details["profile"]


def test_auto_uses_an_added_profile_that_matches_the_data():
    """An added profile wins over built-in detection when it applies."""

    profile_id = register_profile("museum.ttl", SHAPES)

    assert _auto_profile(DATA) == profile_id


def test_auto_falls_back_when_no_added_profile_matches():
    """With nothing added matching, detection works as before."""

    register_profile("museum.ttl", SHAPES)

    assert _auto_profile("""
        @prefix ore: <http://www.openarchives.org/ore/terms/> .
        <http://example.org/proxy> a ore:Proxy .
    """) == "edm"


def test_auto_picks_the_added_profile_matching_most_records():
    """Between two that apply, the one covering more records is used."""

    register_profile("museum.ttl", SHAPES)
    crm_id = register_profile("crm.ttl", RANGE_SHAPES)

    # Two paintings for the museum profile; three resources for crm.
    assert _auto_profile(DATA + """
        ex:d1 a ex:Death ; ex:died ex:x1 .
        ex:d2 a ex:Death ; ex:died ex:x2 .
    """) == crm_id


# ------------------------------------------------------------------
# SHACL-SPARQL THAT ONLY READS THE DATA
# ------------------------------------------------------------------

# Modelled on the shapes that motivated this support: a SPARQL target
# selecting dates by their format, and a SPARQL check that a resource is
# not typed "unknown" beside an answer.
SPARQL_SHAPES = b"""
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ex: <http://example.org/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

ex:prefixes sh:declare [ sh:prefix "ex" ;
                         sh:namespace "http://example.org/"^^xsd:anyURI ] .

ex:DateShape a sh:NodeShape ;
    sh:target [ a sh:SPARQLTarget ;
                sh:prefixes ex:prefixes ;
                sh:select "SELECT ?this WHERE { ?this ex:format ex:EDTF }" ] ;
    sh:property [ sh:path ex:content ; sh:minCount 1 ;
                  sh:pattern "^[0-9]{4}$" ] .

ex:UnknownShape a sh:NodeShape ;
    sh:targetSubjectsOf ex:type ;
    sh:sparql [ a sh:SPARQLConstraint ;
                sh:prefixes ex:prefixes ;
                sh:message "unknown beside an answer" ;
                sh:select \"\"\"
                    # a comment mentioning service is not a SERVICE clause
                    SELECT $this WHERE {
                        $this ex:type ex:unknown .
                        $this ex:type ?other .
                        FILTER (?other != ex:unknown)
                    }\"\"\" ] .
"""


def test_read_only_sparql_is_accepted_and_scored():
    """The SPARQL target finds its records; the SPARQL check counts once."""

    profile_id = register_profile("sparql.ttl", SPARQL_SHAPES)
    graph = Graph()
    graph.parse(data="""
        @prefix ex: <http://example.org/> .
        ex:good   ex:format ex:EDTF ; ex:content "1961" .
        ex:bad    ex:format ex:EDTF ; ex:content "ca. 1880" .
        ex:clear  ex:type ex:gift .
        ex:muddle ex:type ex:unknown, ex:gift .
    """, format="turtle")

    result = StructuralCompletenessMetric().evaluate(DatasetContext(
        "d", "d", graph,
        options={"structural_completeness": {"profile": profile_id}},
    ))

    # good and clear meet their one requirement; bad and muddle fail it.
    assert result.details["total_records"] == 4
    assert result.score == 0.5


def test_view_describes_sparql_targets_and_checks():
    """The preview says a query selects the records and what it checks."""

    profile_id = register_profile("sparql.ttl", SPARQL_SHAPES)
    profile = next(p for p in describe_profiles() if p["id"] == profile_id)

    rows = {
        (shape["targets"][0]["kind"], prop["requirement"], prop["message"])
        for shape in profile["shapes"] for prop in shape["properties"]
    }
    assert ("subjects_of", "custom SPARQL check", "unknown beside an answer") in rows
    assert any(kind == "sparql" for kind, _, _ in rows)


def test_rdflib_never_loads_graphs_named_in_a_query():
    """A FROM clause cannot make the server download a graph."""

    import rdflib.plugins.sparql
    import metrics.shacl_shapes  # noqa: F401  (switches loading off)

    assert rdflib.plugins.sparql.SPARQL_LOAD_GRAPHS is False
