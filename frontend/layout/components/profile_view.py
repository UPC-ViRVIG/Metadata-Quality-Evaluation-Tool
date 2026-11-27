"""
Readable view of a SHACL profile: which resources each shape applies to
and which properties it requires, as described by GET /profiles.

Shown wherever a Structural Completeness score needs explaining, so the
score can be read against what was actually checked.
"""

from dash import html
import dash_bootstrap_components as dbc


def build_profile_definition(profile: dict | None) -> html.Div:
    """
    Render one profile's shapes as a list of targets and requirements.

    Parameters
    ----------
    profile : dict | None
        One entry of the GET /profiles response, or None when the
        definitions could not be loaded.

    Returns
    -------
    html.Div
        The profile's name, a note on how requirements are scored, and
        one table listing every shape's targets and requirements.
    """
    if not profile:
        return html.P(
            "Profile definitions could not be loaded from the backend.",
            className="text-muted mb-0",
            style={"fontSize": "0.85rem"},
        )

    intro = [html.Strong(profile["name"])]
    if profile.get("is_fallback"):
        intro.append(
            " — used when the data matches no known vocabulary, so its "
            "scores say little about domain-specific completeness."
        )

    if profile.get("uploaded"):
        added = (profile.get("uploaded_at") or "")[:10]
        source = profile.get("filename")
        intro.append(html.Span(
            " — added"
            + (f" on {added}" if added else "")
            + (f" from {source}" if source else ""),
            className="text-muted",
        ))

    blocks = [
        html.P(intro, className="mb-1", style={"fontSize": "0.9rem"}),
        html.P(
            "Each record scores the share of these requirements it meets. "
            "Every requirement counts equally, whatever its severity.",
            className="text-muted mb-3",
            style={"fontSize": "0.8rem"},
        ),
    ]

    # One table for the whole profile: a profile with hundreds of shapes,
    # such as a generated domain/range profile, stays readable, and each
    # shape's targets span the rows of its requirements.
    rows = []
    for shape in profile.get("shapes", []):
        requirements = shape.get("properties", [])
        for i, prop in enumerate(requirements):
            cells = []
            if i == 0:
                cells.append(html.Td(_targets_text(shape.get("targets", [])),
                                     rowSpan=len(requirements),
                                     style={"verticalAlign": "top"}))
            cells += [
                html.Td(prop.get("path") or html.Span("the resource itself",
                                                      className="text-muted")),
                html.Td(prop.get("requirement") or "—"),
                html.Td(prop.get("severity") or "—"),
                html.Td(prop.get("message") or "—"),
            ]
            rows.append(html.Tr(cells))

    blocks.append(dbc.Table(
        [html.Thead(html.Tr([html.Th("Applies to"), html.Th("Property"),
                             html.Th("Requirement"), html.Th("Severity"),
                             html.Th("Message")])),
         html.Tbody(rows)],
        bordered=True, size="sm", className="mb-0",
        style={"fontSize": "0.8rem"},
    ))

    return html.Div(blocks)


def _targets_text(targets: list[dict]) -> str:
    """
    Describe what a shape applies to in plain words.

    Parameters
    ----------
    targets : list[dict]
        Shape targets, each with kind and label.

    Returns
    -------
    str
        For example "ore:Proxy", "any resource using crm:P100" or "any
        value of crm:P100".
    """
    wording = {
        "class":       "{}",
        "subjects_of": "any resource using {}",
        "objects_of":  "any value of {}",
        "node":        "{}",
    }
    parts = [
        wording.get(target["kind"], "{}").format(target["label"])
        for target in targets
    ]
    return ", ".join(parts) or "—"
