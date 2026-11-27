"""
metrics/shacl_shapes.py
-----------------------
Reading a SHACL shapes graph: which resources each shape applies to, and
which constraints it checks.

Structural Completeness scores each record only against the shapes that
target it. That needs two things a SHACL validator does not report on
its own: the set of constraints each record is expected to meet, and,
from the validation results, the set it failed. Both are computed here,
from the shapes graph alone, so they hold for any shapes file and not
only for the profiles shipped with the tool.

A constraint is counted once however many values break it. A record
with three wrongly typed dates fails one constraint, not three.

Only resources are records. A literal can be the focus of a shape, for
instance one requiring the values of a property to be literals, but it
is a value rather than something described, so it is never counted.

SHACL-SPARQL is supported where its queries only read the data being
evaluated: SPARQL constraints (sh:sparql) and SPARQL targets. A query
that names other graphs with FROM, or other servers with SERVICE, is
never run; query_problem() is the single check, used on upload and
again before this module runs a target query itself.
"""

import rdflib.plugins.sparql
from pyparsing import ParseResults
from rdflib import Graph, Literal, RDF, RDFS, URIRef
from rdflib.namespace import SH
from rdflib.plugins.sparql.algebra import translateQuery
from rdflib.plugins.sparql.parser import parseQuery
from rdflib.plugins.sparql.parserutils import CompValue

# rdflib downloads the graphs a query names with FROM unless this is off.
# Nothing in this tool relies on that, and shapes files must never make
# the server fetch data, so it is off for the whole process.
rdflib.plugins.sparql.SPARQL_LOAD_GRAPHS = False

# Target declarations this module resolves. A shape using none of them
# applies to no records. sh:target is resolved only when it is a SPARQL
# target, a node holding an sh:select query.
TARGET_PREDICATES = (
    SH.targetClass,
    SH.targetNode,
    SH.targetSubjectsOf,
    SH.targetObjectsOf,
    SH.target,
)

# Constraint components that can sit directly on a node shape. A node
# shape carrying any of them is one constraint of its own, alongside its
# property shapes. Several sh:sparql queries on one shape are one
# constraint, as validation reports them all against the shape.
NODE_CONSTRAINTS = (
    SH["or"], SH["and"], SH["not"], SH.xone, SH.node, SH["class"],
    SH.datatype, SH.nodeKind, SH.closed, SH["in"], SH.hasValue,
    SH.pattern, SH.minLength, SH.maxLength,
    SH.minInclusive, SH.maxInclusive, SH.minExclusive, SH.maxExclusive,
    SH.sparql,
)


def query_prefixes(shapes_graph: Graph, node) -> str:
    """
    Return the PREFIX lines a SHACL-SPARQL query is given.

    SHACL declares a query's prefixes through sh:prefixes, pointing at
    nodes whose sh:declare entries pair an sh:prefix with an
    sh:namespace. Validation prepends the same declarations.

    Parameters
    ----------
    shapes_graph : rdflib.Graph
        The SHACL shapes graph.
    node : rdflib term
        The node holding the query, such as a SPARQL target.

    Returns
    -------
    str
        PREFIX declarations, one per line; empty if there are none.
    """
    lines = []
    for holder in shapes_graph.objects(node, SH.prefixes):
        for declaration in shapes_graph.objects(holder, SH.declare):
            prefix    = shapes_graph.value(declaration, SH.prefix)
            namespace = shapes_graph.value(declaration, SH.namespace)
            if prefix is not None and namespace is not None:
                lines.append(f"PREFIX {prefix}: <{namespace}>")
    return "\n".join(lines)


def query_problem(query_text: str) -> str | None:
    """
    Say why a SHACL-SPARQL query may not run, or return None if it may.

    A query may run when it parses, is a SELECT or ASK query, and reads
    only the data being evaluated: no FROM or FROM NAMED, which make
    rdflib load other graphs, and no SERVICE, which makes it contact
    other servers. The query is parsed rather than searched for words,
    so "service" in a comment or a string value is not mistaken for one.

    Parameters
    ----------
    query_text : str
        The query, with its PREFIX declarations.

    Returns
    -------
    str | None
        The reason, worded to follow "uses", or None.
    """
    # $PATH stands for a property path in SHACL-SPARQL validators and
    # is substituted before running; it is not SPARQL on its own.
    text = query_text.replace("$PATH", "<urn:shacl:path>")
    try:
        parsed = parseQuery(text)
        translateQuery(parsed)
    except Exception as exc:
        return f"a SPARQL query that cannot be read ({str(exc)[:120]})"

    query = parsed[1]
    if query.name not in ("SelectQuery", "AskQuery"):
        return "a SPARQL query that is not SELECT or ASK"
    # Tested by key: CompValue.get returns the key's name when it is absent.
    if "datasetClause" in query:
        return "a SPARQL query that loads other graphs with FROM"
    if _contains(parsed, "ServiceGraphPattern"):
        return "a SPARQL query that contacts other servers with SERVICE"
    return None


def _contains(node, name: str) -> bool:
    """Whether a parsed query contains a part with this name."""
    if isinstance(node, CompValue):
        return node.name == name or any(
            _contains(value, name) for value in node.values()
        )
    if isinstance(node, (list, tuple, ParseResults)):
        return any(_contains(value, name) for value in node)
    return False


def shapes_with_targets(shapes_graph: Graph) -> list:
    """
    Return every shape that declares at least one target.

    A shape that is also an rdfs:Class targets its own instances
    implicitly, as SHACL defines.

    Parameters
    ----------
    shapes_graph : rdflib.Graph
        The SHACL shapes graph.

    Returns
    -------
    list
        Shape nodes, sorted for a stable order.
    """
    shapes = set()
    for predicate in TARGET_PREDICATES:
        shapes.update(shapes_graph.subjects(predicate, None))
    for shape in shapes_graph.subjects(RDF.type, RDFS.Class):
        if ((shape, RDF.type, SH.NodeShape) in shapes_graph
                or (shape, RDF.type, SH.PropertyShape) in shapes_graph):
            shapes.add(shape)
    return sorted(shapes, key=str)


def shape_constraints(shapes_graph: Graph, shape) -> set:
    """
    Return the constraints a shape checks, as the nodes that hold them.

    Each property shape is one constraint. A node shape with constraint
    components of its own, such as an sh:or, is one more. A top-level
    property shape with its own target is itself the constraint.

    Parameters
    ----------
    shapes_graph : rdflib.Graph
        The SHACL shapes graph.
    shape : rdflib term
        A shape declaring a target.

    Returns
    -------
    set
        Constraint nodes; these match sh:sourceShape in validation
        results.
    """
    constraints = set(shapes_graph.objects(shape, SH.property))
    if shapes_graph.value(shape, SH.path) is not None:
        constraints.add(shape)
    elif any(shapes_graph.value(shape, p) is not None for p in NODE_CONSTRAINTS):
        constraints.add(shape)
    return constraints


def shape_targets(shapes_graph: Graph, data_graph: Graph, shape) -> set[str]:
    """
    Return the records a shape applies to in the data.

    A class target includes instances of its subclasses, as SHACL
    requires, using rdfs:subClassOf statements found in the data. A
    SPARQL target is resolved by running its query on the data, only if
    query_problem() allows it.

    Parameters
    ----------
    shapes_graph : rdflib.Graph
        The SHACL shapes graph.
    data_graph : rdflib.Graph
        The data being evaluated.
    shape : rdflib term
        A shape declaring a target.

    Returns
    -------
    set[str]
        Record identifiers, as strings. Literals are left out: they are
        values, not records.
    """
    classes = set(shapes_graph.objects(shape, SH.targetClass))
    if (shape, RDF.type, RDFS.Class) in shapes_graph:
        classes.add(shape)

    records = set()
    for cls in classes:
        for sub in data_graph.transitive_subjects(RDFS.subClassOf, cls):
            records.update(str(s) for s in data_graph.subjects(RDF.type, sub))
    for node in shapes_graph.objects(shape, SH.targetNode):
        if not isinstance(node, Literal):
            records.add(str(node))
    for prop in shapes_graph.objects(shape, SH.targetSubjectsOf):
        records.update(str(s) for s in data_graph.subjects(prop, None))
    for prop in shapes_graph.objects(shape, SH.targetObjectsOf):
        records.update(
            str(o) for o in data_graph.objects(None, prop)
            if not isinstance(o, Literal)
        )
    for target in shapes_graph.objects(shape, SH.target):
        select = shapes_graph.value(target, SH.select)
        if select is None:
            continue
        query = f"{query_prefixes(shapes_graph, target)}\n{select}"
        if query_problem(query) is not None:
            continue
        for row in data_graph.query(query):
            node = getattr(row, "this", None)
            if node is not None and not isinstance(node, Literal):
                records.add(str(node))
    return records


def record_constraints(shapes_graph: Graph, data_graph: Graph) -> dict[str, set]:
    """
    Map each targeted record to the constraints it is expected to meet.

    A record targeted by several shapes is expected to meet all of their
    constraints. Shapes that check nothing are ignored, so they do not
    turn up records with nothing to score.

    Parameters
    ----------
    shapes_graph : rdflib.Graph
        The SHACL shapes graph.
    data_graph : rdflib.Graph
        The data being evaluated.

    Returns
    -------
    dict[str, set]
        Record identifiers mapped to their constraint nodes.
    """
    expected: dict[str, set] = {}
    for shape in shapes_with_targets(shapes_graph):
        constraints = shape_constraints(shapes_graph, shape)
        if not constraints:
            continue
        for record in shape_targets(shapes_graph, data_graph, shape):
            expected.setdefault(record, set()).update(constraints)
    return expected


def failed_constraints(results_graph: Graph) -> dict[str, set]:
    """
    Map each record to the constraints it failed, from validation results.

    Results are read by their sh:sourceShape, so a constraint broken by
    several values of one record is counted once. All severities are
    included: a Warning counts as much as a Violation.

    Parameters
    ----------
    results_graph : rdflib.Graph
        The SHACL validation results graph.

    Returns
    -------
    dict[str, set]
        Record identifiers mapped to the constraint nodes they failed.
    """
    failed: dict[str, set] = {}
    for result in results_graph.subjects(SH.resultSeverity, None):
        focus  = results_graph.value(result, SH.focusNode)
        source = results_graph.value(result, SH.sourceShape)
        if focus is None or source is None:
            continue
        failed.setdefault(str(focus), set()).add(source)
    return failed
