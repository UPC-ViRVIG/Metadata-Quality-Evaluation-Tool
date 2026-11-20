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
        one table per shape.
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

    blocks = [
        html.P(intro, className="mb-1", style={"fontSize": "0.9rem"}),
        html.P(
            "Each record scores the share of these requirements it meets. "
            "Every requirement counts equally, whatever its severity.",
            className="text-muted mb-3",
            style={"fontSize": "0.8rem"},
        ),
    ]

    for shape in profile.get("shapes", []):
        blocks.append(html.P(
            [html.Span("Applies to: ", className="text-muted"),
             html.Strong(_targets_text(shape.get("targets", [])))],
            className="mb-1",
            style={"fontSize": "0.82rem"},
        ))
        blocks.append(dbc.Table(
            [html.Thead(html.Tr([html.Th("Property"), html.Th("Severity"),
                                 html.Th("Message")])),
             html.Tbody([
                 html.Tr([
                     html.Td(prop["path"]),
                     html.Td(prop.get("severity") or "—"),
                     html.Td(prop.get("message") or "—"),
                 ])
                 for prop in shape.get("properties", [])
             ])],
            bordered=True, size="sm", className="mb-3",
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
        For example "ore:Proxy" or "any resource using rdf:type".
    """
    parts = [
        target["label"] if target["kind"] == "class"
        else f"any resource using {target['label']}"
        for target in targets
    ]
    return ", ".join(parts) or "—"
