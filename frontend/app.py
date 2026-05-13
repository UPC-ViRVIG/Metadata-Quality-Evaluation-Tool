"""
Main Dash application entry point.

This module initializes the frontend application, defines the global
layout structure, registers shared client-side state stores, and loads
all callback modules.

Main Layout Structure
---------------------
Top Bar
    Application title/header.
Sidebar
    Dataset management, metric selection, ontology browsing.
Main Panel
    Dynamic metric visualizations and evaluation results.
Modal Layer
    Source/dataset configuration dialogs.

Shared State Stores
-------------------
store-sources
    User-configured dataset sources.
store-results
    Evaluation results returned from the backend.
store-ontology
    Cached ontology/class hierarchy data.
store-ui
    Transient UI interaction state.
store-metric-dims
    Metric-to-dimension mapping metadata.
store-dimensions
    Quality dimension descriptions and tooltips.
"""
import dash
from dash import html, dcc
import dash_bootstrap_components as dbc

from layout.sidebar import build_sidebar, build_add_source_modal

# ============================================================================
# Dash application initialization
# ============================================================================
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,
)

server = app.server

# ============================================================================
# Global application layout
# ============================================================================
app.layout = dbc.Container(
    fluid=True,
    children=[

        # ── Stores ────────────────────────────────────────────────────────
        dcc.Store(id="store-sources", data=[]),
        dcc.Store(id="store-results",  data=None),
        dcc.Store(id="store-ontology", data={}),
        dcc.Store(id="store-ui", data={
            "active_metric": None,
            "active_class":  None
        }),

        dcc.Store(id="store-metric-dims",  data={}),

        dcc.Store(id="store-dimensions",  data={}),

        # ── Modal ─────────────────────────────────────────────────────────
        build_add_source_modal(),

        # ── Top bar ───────────────────────────────────────────────────────
        dbc.Row(
            dbc.Col(
                html.H4(
                    "Metadata Quality Evaluator",
                    className="my-3 text-muted fw-light",
                )
            )
        ),

        # ── Main area ─────────────────────────────────────────────────────
        dbc.Row([
            dbc.Col(build_sidebar(), width=3),
            dbc.Col(id="main-panel", width=9, children=[]),
        ]),
    ]
)


import callbacks.sources      # noqa: F401, E402
import callbacks.evaluation   # noqa: F401, E402
import callbacks.main_panel   # noqa: F401, E402
import callbacks.ui            # noqa: F401, E402

if __name__ == "__main__":
    app.run(debug=True, port=8050)