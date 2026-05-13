from dash import html
import dash_bootstrap_components as dbc

from layout.components.common import panel_card, section_label


def render_details_table(details: dict) -> html.Div:
    """
    Converts a metric details dict into a structured block of Dash components.

    Handles four value shapes:
      - nested dict  {str: {str: scalar}}  → progress-bar table per sub-key
      - list of dicts [{col: val}]         → scrollable tabular view (max 200 rows)
      - plain list   [scalar]              → bullet list (max 200 items)
      - scalar       float | int | str     → key/value row
    """
    if not details:
        return html.Div(
            html.P("No additional details available.",
                   className="text-muted", style={"fontSize": "0.85rem"}),
        )

    blocks = []
    for key, val in details.items():

        if isinstance(val, dict):
            rows = []
            for sub_key, sub_val in val.items():
                if isinstance(sub_val, float):
                    pct   = round(sub_val * 100)
                    color = ("success" if pct >= 75
                             else "warning" if pct >= 40 else "danger")
                    rows.append(html.Tr([
                        html.Td(sub_key,
                                style={"fontSize": "0.85rem",
                                       "wordBreak": "break-all"}),
                        html.Td(
                            dbc.Progress(value=pct, color=color,
                                         style={"height": "8px"},
                                         className="my-1"),
                            style={"width": "55%"},
                        ),
                        html.Td(dbc.Badge(f"{pct}%", color=color),
                                className="text-end"),
                    ]))
                else:
                    rows.append(html.Tr([
                        html.Td(sub_key, style={"fontSize": "0.85rem"}),
                        html.Td(str(sub_val), colSpan=2,
                                style={"fontSize": "0.85rem"}),
                    ]))
            blocks.append(panel_card([
                section_label(key),
                dbc.Table([html.Tbody(rows)],
                          bordered=False, size="sm", className="mb-0",
                          style={"tableLayout": "fixed"}),
            ]))

        elif isinstance(val, list) and val and isinstance(val[0], dict):
            cols  = list(val[0].keys())
            thead = html.Thead(html.Tr([html.Th(c) for c in cols]))
            tbody = html.Tbody([
                html.Tr([
                    html.Td(
                        f"{round(row.get(c, 0) * 100)}%"
                        if isinstance(row.get(c), float)
                        else str(row.get(c, "")),
                        style={"fontSize": "0.82rem", "wordBreak": "break-all"},
                    )
                    for c in cols
                ])
                for row in val[:200]
            ])
            caption = (
                html.Caption(
                    f"Showing first 200 of {len(val)} entries.",
                    style={"fontSize": "0.75rem", "captionSide": "bottom"},
                ) if len(val) > 200 else None
            )
            blocks.append(panel_card([
                section_label(key),
                html.Div(
                    dbc.Table(
                        [thead, tbody] + ([caption] if caption else []),
                        bordered=True, size="sm", className="mb-0",
                    ),
                    style={"overflowX": "auto", "overflowY": "auto",
                           "maxHeight": "340px"},
                ),
            ]))

        elif isinstance(val, list):
            blocks.append(panel_card([
                section_label(key),
                html.Ul(
                    [html.Li(str(v), style={"fontSize": "0.85rem"})
                     for v in val[:200]],
                    className="mb-0 ps-3",
                ),
            ]))

        else:
            display = f"{round(val * 100)}%" if isinstance(val, float) else str(val)
            blocks.append(
                dbc.Row([
                    dbc.Col(html.Span(key, className="text-muted",
                                     style={"fontSize": "0.82rem"}), width=4),
                    dbc.Col(html.Span(display,
                                     style={"fontSize": "0.85rem",
                                            "fontWeight": "500"}), width=8),
                ], className="mb-1 g-0"),
            )

    return html.Div(blocks)