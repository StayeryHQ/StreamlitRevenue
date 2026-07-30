# dash_app/pages/sales.py
# Sales hub: one nav entry, three tabbed views (B2B / Code-Deepdive / Promo).
# The views live in dash_app/views/ as plain modules (layout() + their own
# callbacks, registered on import); this router just renders the active one.
# Deep-link via query param: /sales?tab=promo, or /sales?tab=code&code=XYZ to
# land on the Code tab with the code prefilled (used by the B2B/Promo drilldown
# "Im Code-Deepdive öffnen" links). Mirrors dash_app/pages/revenue.py.

from __future__ import annotations

import dash
import dash_mantine_components as dmc
from dash import Input, Output, State, callback, dcc, html

from dash_app.views import b2b as v_b2b
from dash_app.views import code_deepdive as v_code
from dash_app.views import promo as v_promo

dash.register_page(__name__, path="/sales", name="Sales", order=2,
                   title="STAYERY · Sales")

_VIEWS = {
    "b2b": ("B2B", "bi bi-building", v_b2b),
    "code": ("Code-Deepdive", "bi bi-upc-scan", v_code),
    "promo": ("Promo-Codes", "bi bi-tag", v_promo),
}


def layout(tab: str = "b2b", code=None, **_kwargs):
    # A code query param is a deep-link into the Code-Deepdive -> force that tab
    # and carry the code through a store so the content callback can prefill it.
    if code:
        tab = "code"
    tab = tab if tab in _VIEWS else "b2b"
    tabs = dmc.Tabs(
        dmc.TabsList([
            dmc.TabsTab(lbl, value=key, leftSection=html.I(className=icon))
            for key, (lbl, icon, _mod) in _VIEWS.items()
        ]),
        id="sales-hubtabs", value=tab, variant="pills", color="dark", radius="md",
    )
    # No page-level dcc.Loading (see revenue.py) - keeps the filter bar stable
    # on filter changes; per-graph skeletons handle loading feedback.
    return dmc.Stack([
        dcc.Store(id="sales-hub-code", data=code),
        tabs,
        html.Div(id="sales-hub-content"),
    ], gap="md")


@callback(Output("sales-hub-content", "children"), Input("sales-hubtabs", "value"),
          State("sales-hub-code", "data"))
def _render(tab, code):
    _lbl, _icon, mod = _VIEWS.get(tab, _VIEWS["b2b"])
    if tab == "code":
        return mod.layout(code=code)
    return mod.layout()
