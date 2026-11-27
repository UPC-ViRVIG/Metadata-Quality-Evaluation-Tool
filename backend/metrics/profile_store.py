"""
metrics/profile_store.py
------------------------
Storage for SHACL profiles added by users, through the dashboard or the
CLI.

An added profile is checked before it is kept: it must parse as RDF,
declare at least one shape with a target this tool resolves, and check
at least one constraint. SHACL-SPARQL constraints and targets are
accepted when their queries only read the data being evaluated: pySHACL
runs them on the server, so a query naming other graphs (FROM) or other
servers (SERVICE) is refused, as decided by shacl_shapes.query_problem().
SHACL rules are refused, because they add triples before checking and a
score would no longer describe the data as delivered. Custom constraint
components are refused, because the score could not count them.

Accepted files are re-serialised as Turtle under backend/uploads/profiles
(gitignored), with a small JSON record beside each one, so they survive
a restart and the dashboard and the CLI see the same set. When a source
is left on Auto, an added profile that targets records in its data is
preferred over the built-in ones.
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import SH
from rdflib.util import guess_format

from metrics.shacl_shapes import (
    query_prefixes,
    query_problem,
    shape_constraints,
    shapes_with_targets,
)

UPLOAD_DIR = Path(__file__).parent.parent / "uploads" / "profiles"
MAX_PROFILE_BYTES = 5 * 1024 * 1024

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SLUG_CHARS = re.compile(r"[^a-z0-9]+")

# Features refused in added profiles, as a refusal names them.
_REFUSED_FEATURES = {
    SH.rule:      "a SHACL rule",
    SH.construct: "a SHACL rule",
    SH.validator:         "a custom constraint component",
    SH.nodeValidator:     "a custom constraint component",
    SH.propertyValidator: "a custom constraint component",
}


class ProfileError(ValueError):
    """
    Raised when a profile cannot be added or removed.

    The message is written to be shown to the user directly, because
    every case is something they can act on: a file that is not RDF, one
    without usable shapes, one using unsupported SHACL features, or an
    identifier that is taken.
    """


def uploaded_profiles() -> dict[str, dict]:
    """
    List the profiles users have added, read from disk.

    Read on every call, so a profile added by the CLI is visible to a
    running backend without a restart.

    Returns
    -------
    dict[str, dict]
        Profile ids mapped to {name, file, namespaces, uploaded,
        filename, sha256, uploaded_at}. Namespaces are always empty:
        Auto matches added profiles by the records they target instead.
    """
    if not UPLOAD_DIR.exists():
        return {}

    profiles = {}
    for record_path in sorted(UPLOAD_DIR.glob("*.json")):
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        shapes_path = record_path.with_suffix(".ttl")
        if not shapes_path.exists():
            continue
        profiles[record_path.stem] = {
            "name":        record.get("name") or record_path.stem,
            "file":        shapes_path,
            "namespaces":  [],
            "uploaded":    True,
            "filename":    record.get("filename"),
            "sha256":      record.get("sha256"),
            "uploaded_at": record.get("uploaded_at"),
        }
    return profiles


def register_profile(
    filename: str,
    content: bytes,
    name: str | None = None,
    profile_id: str | None = None,
    reserved: set[str] = frozenset(),
) -> str:
    """
    Check a SHACL file and keep it as a profile.

    Parameters
    ----------
    filename : str
        Name of the file, used to guess its RDF format and as the
        default display name.
    content : bytes
        Raw file contents.
    name : str | None
        Display name. Defaults to the file name without its extension.
    profile_id : str | None
        Identifier to store it under, as the CLI chooses one. When None,
        one is derived from the name and the file's hash, so the same
        file added twice keeps one identifier.
    reserved : set[str]
        Identifiers that may not be used, such as built-in profiles.

    Returns
    -------
    str
        The profile identifier.

    Raises
    ------
    ProfileError
        If the file is empty, too large, not RDF, has no usable shapes,
        uses SHACL-SPARQL, or the identifier is invalid or reserved.
    """
    if not content:
        raise ProfileError("The SHACL file is empty.")
    if len(content) > MAX_PROFILE_BYTES:
        raise ProfileError(
            f"The SHACL file is larger than the "
            f"{MAX_PROFILE_BYTES // (1024 * 1024)} MB limit."
        )

    shapes_graph = Graph()
    try:
        shapes_graph.parse(
            data=content.decode("utf-8"),
            format=guess_format(filename or "") or "turtle",
        )
    except Exception as exc:
        raise ProfileError(
            f"The file could not be read as RDF: {str(exc)[:200]}"
        ) from exc

    check_shapes(shapes_graph)

    stem = Path(filename or "profile").stem
    display_name = (name or stem).strip() or stem
    digest = hashlib.sha256(content).hexdigest()

    if profile_id is None:
        slug = _SLUG_CHARS.sub("-", display_name.lower()).strip("-")[:40] or "profile"
        profile_id = f"{slug}-{digest[:6]}"
    if not _ID_PATTERN.match(profile_id):
        raise ProfileError(
            f"'{profile_id}' is not a valid profile id: use lowercase "
            f"letters, digits, '-' and '_'."
        )
    if profile_id in reserved:
        raise ProfileError(
            f"'{profile_id}' is already used by a built-in profile."
        )

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    shapes_graph.serialize(destination=str(UPLOAD_DIR / f"{profile_id}.ttl"),
                           format="turtle")
    (UPLOAD_DIR / f"{profile_id}.json").write_text(json.dumps({
        "name":        display_name,
        "filename":    Path(filename or "").name or None,
        "sha256":      digest,
        "uploaded_at": datetime.now(timezone.utc)
                               .replace(microsecond=0).isoformat()
                               .replace("+00:00", "Z"),
    }, indent=2), encoding="utf-8")

    return profile_id


def remove_profile(profile_id: str) -> None:
    """
    Delete a profile users added.

    Parameters
    ----------
    profile_id : str
        Identifier of the added profile.

    Raises
    ------
    ProfileError
        If no added profile has that identifier.
    """
    if profile_id not in uploaded_profiles():
        raise ProfileError(f"There is no added profile '{profile_id}'.")
    for suffix in (".ttl", ".json"):
        (UPLOAD_DIR / f"{profile_id}{suffix}").unlink(missing_ok=True)


def check_shapes(shapes_graph: Graph) -> None:
    """
    Refuse shapes the metric cannot score, or should not run.

    Parameters
    ----------
    shapes_graph : rdflib.Graph
        The parsed SHACL file.

    Raises
    ------
    ProfileError
        If a SPARQL query in it reads anything but the data, it uses SHACL
        rules, custom constraint components or a target type other than
        a SPARQL target, declares no shape with a resolvable target, or
        checks no constraint.
    """
    # Name each shape using a refused feature, so the reason points at
    # the parts of the file to change.
    offending: dict[str, set[str]] = {}

    def flag(node, reason: str) -> None:
        holder = _owning_shape(shapes_graph, node)
        offending.setdefault(_short(shapes_graph, holder), set()).add(reason)

    for predicate, reason in _REFUSED_FEATURES.items():
        for subject in shapes_graph.subjects(predicate, None):
            flag(subject, reason)
    for predicate in (SH.select, SH.ask):
        for node, text in shapes_graph.subject_objects(predicate):
            problem = query_problem(
                f"{query_prefixes(shapes_graph, node)}\n{text}"
            )
            if problem is not None:
                flag(node, problem)
    for shape, target in shapes_graph.subject_objects(SH.target):
        if shapes_graph.value(target, SH.select) is None:
            flag(shape, "a custom target type, which this tool cannot resolve")

    if offending:
        parts = [
            f"{shape} uses {' and '.join(sorted(reasons))}"
            for shape, reasons in sorted(offending.items())
        ]
        raise ProfileError(
            f"{'; '.join(parts)}. SPARQL constraints and targets are "
            f"accepted only when their queries read nothing but the data "
            f"being evaluated, since they run on the server; SHACL rules and "
            f"custom constraint components are not accepted."
        )

    shapes = shapes_with_targets(shapes_graph)
    if not shapes:
        raise ProfileError(
            "The file declares no shape with a target (sh:targetClass, "
            "sh:targetNode, sh:targetSubjectsOf, sh:targetObjectsOf or a "
            "SPARQL target), so it would apply to no records."
        )
    if not any(shape_constraints(shapes_graph, shape) for shape in shapes):
        raise ProfileError(
            "The file's shapes declare targets but check no constraints."
        )


def _owning_shape(shapes_graph: Graph, node):
    """
    Return the named node a feature belongs to.

    A query usually sits in a blank node, so its shape is found by
    following references upwards until a named node is reached.
    """
    seen = set()
    while not isinstance(node, URIRef) and node not in seen:
        seen.add(node)
        parent = next(shapes_graph.subjects(None, node), None)
        if parent is None:
            break
        node = parent
    return node


def _short(shapes_graph: Graph, node) -> str:
    """Write a node with the file's prefixes, or as-is if it has none."""
    if isinstance(node, URIRef):
        return shapes_graph.namespace_manager.normalizeUri(node)
    return "an unnamed shape"
