# dash_app/app.py
# Dash application factory for the Stayery revenue tool.
#
# Run locally:   uv run python -m dash_app.app
# WSGI (prod):   gunicorn dash_app.app:server

from __future__ import annotations

import os

import dash
import dash_mantine_components as dmc
from dash import Dash, _dash_renderer, dcc, html, page_container

# dash-mantine-components 2.x targets React 18; pin 18.2.0 explicitly so dmc
# renders deterministically. Must run BEFORE the Dash() instance is created.
_dash_renderer._set_react_version("18.2.0")

from dash_app.theme import DMC_THEME, EXTERNAL_STYLESHEETS

app = Dash(
    __name__,
    use_pages=True,
    external_stylesheets=EXTERNAL_STYLESHEETS,
    suppress_callback_exceptions=True,  # callbacks target page-scoped layouts
    title="STAYERY · Revenue Analytics",
)
# WSGI server object (gunicorn dash_app.app:server).
server = app.server


def _navbar() -> html.Header:
    """Top navigation shell. Links render via the callback below (reads
    dcc.Location); the current route gets the `.active` class."""
    brand = html.A(
        html.Div([
            html.Span(className="stayery-accent"),
            html.Span("STAYERY", className="stayery-wordmark"),
            html.Span("Revenue Analytics", className="stayery-subbrand"),
        ], className="stayery-brand-inner"),
        href="/", className="stayery-brand")
    return html.Header(
        html.Div([brand, html.Nav(id="stayery-nav", className="stayery-nav")],
                 className="stayery-header-inner"),
        className="stayery-header")


@dash.callback(dash.Output("stayery-nav", "children"), dash.Input("app-url", "pathname"))
def _nav_links(pathname):
    """Re-render nav links on every route change; the current page gets `.active`."""
    pages = sorted(dash.page_registry.values(), key=lambda p: p.get("order", 99))
    return [
        dcc.Link(p["name"], href=p["relative_path"],
                 className="stayery-navlink"
                 + (" active" if pathname == p["relative_path"] else ""))
        for p in pages
    ]


app.layout = dmc.MantineProvider(
    html.Div(
        [dcc.Location(id="app-url"), _navbar(), page_container],
        style={"maxWidth": "1500px", "margin": "0 auto", "padding": "0 12px"}),
    theme=DMC_THEME,
    forceColorScheme="light",
)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 8050)))
