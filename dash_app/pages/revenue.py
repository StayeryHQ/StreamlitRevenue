# dash_app/pages/revenue.py
# Revenue hub: one nav entry, three tabbed views (Global / Pickup / Standort).
# The views live in dash_app/views/ as plain modules (layout() + their own
# callbacks, registered on import); this router just renders the active one.
# Deep-link via query param: /revenue?tab=pickup.

from __future__ import annotations

import dash
import dash_mantine_components as dmc
from dash import Input, Output, callback, html

from dash_app.views import global_report as v_global
from dash_app.views import pickup as v_pickup
from dash_app.views import standort as v_standort

dash.register_page(__name__, path="/revenue", name="Revenue", order=1,
                   title="STAYERY · Revenue")

_VIEWS = {
    "global": ("Global Report", "bi bi-bar-chart", v_global),
    "pickup": ("Pickup", "bi bi-graph-up-arrow", v_pickup),
    "standort": ("Standort", "bi bi-geo-alt", v_standort),
}


def layout(tab: str = "global", **_kwargs):
    tab = tab if tab in _VIEWS else "global"
    tabs = dmc.Tabs(
        dmc.TabsList([
            dmc.TabsTab(lbl, value=key, leftSection=html.I(className=icon))
            for key, (lbl, icon, _mod) in _VIEWS.items()
        ]),
        id="revenue-hubtabs", value=tab, variant="pills", color="dark", radius="md",
    )
    # No page-level dcc.Loading: it would overlay the whole content (incl. the
    # filter bar) on every filter change. Per-graph skeletons (chart_card) give
    # granular feedback instead, so the filter bar + navbar stay put.
    return dmc.Stack([tabs, html.Div(id="revenue-hub-content")], gap="md")


@callback(Output("revenue-hub-content", "children"), Input("revenue-hubtabs", "value"))
def _render(tab):
    _lbl, _icon, mod = _VIEWS.get(tab, _VIEWS["global"])
    return mod.layout()
