# dash_app/components/ui.py
# Reusable dash-mantine-components building blocks shared across all pages -
# same primitives as the overbooking tool (kpi_card, chart_card, info_icon,
# job_loader) plus the revenue-specific section header, alert cards, AG-Grid
# and freshness badge.

from __future__ import annotations

import dash_mantine_components as dmc
import pandas as pd
from dash import Input, Output, callback, dcc, html

import dash_ag_grid as dag
from dash_app import theme


# ---------------------------------------------------------------------------
# Info icon: a small (i) that reveals an explanation on hover. Every metric and
# chart gets one - no unexplained numbers.
# ---------------------------------------------------------------------------
def info_icon(text: str):
    return dmc.Tooltip(
        html.I(className="bi bi-info-circle",
               style={"cursor": "help", "color": "#9AA0A6", "fontSize": "0.85rem"}),
        label=text, multiline=True, w=290, withArrow=True, position="top",
        transitionProps={"transition": "fade", "duration": 150},
    )


# ---------------------------------------------------------------------------
# KPI metric card. `accent=True` adds the brand-yellow left bar. `delta` renders
# a small green/red change line under the value (sign decides the colour).
# ---------------------------------------------------------------------------
def kpi_card(label: str, value: str, sub: str | None = None,
             accent: bool = False, tooltip: str | None = None,
             delta: str | None = None, delta_good: bool | None = None):
    head = dmc.Group(
        [dmc.Text(label, size="xs", c="dimmed", tt="uppercase", fw=600),
         info_icon(tooltip) if tooltip else None],
        gap=4, wrap="nowrap",
    )
    body = [head,
            dmc.Text(value, fw=700, style={"fontSize": "1.7rem", "lineHeight": 1.15})]
    if delta is not None:
        color = theme.GREEN if delta_good else theme.RED
        if delta_good is None:
            color = theme.GREY
        body.append(dmc.Text(delta, size="sm", fw=600, style={"color": color}))
    if sub:
        body.append(dmc.Text(sub, size="xs", c="dimmed"))
    style = {"borderLeft": f"4px solid {theme.YELLOW}"} if accent else {}
    return dmc.Paper(body, p="md", radius="lg", withBorder=True, style=style)


def kpi_strip(cards: list, cols: int = 4):
    """Responsive row of KPI cards (wraps on narrow viewports)."""
    return dmc.SimpleGrid(cards, cols={"base": 1, "xs": 2, "md": cols}, spacing="md")


# ---------------------------------------------------------------------------
# Chart card: titled surface with an optional info tooltip and header control,
# wrapping a Graph in a skeleton loader.
# ---------------------------------------------------------------------------
def chart_card(title: str, graph_id: str, *, info: str | None = None,
               height: int | None = 340, subtitle: str | None = None,
               header_extra=None):
    graph_style = {"height": f"{height}px"} if height else {"width": "100%"}
    skeleton_h = height or 380
    header = dmc.Group(
        [dmc.Group([dmc.Text(title, fw=600, size="sm"),
                    info_icon(info) if info else None], gap=6, wrap="nowrap"),
         header_extra if header_extra is not None else html.Span()],
        justify="space-between", align="center", wrap="nowrap",
    )
    children = [header]
    if subtitle:
        children.append(dmc.Text(subtitle, size="xs", c="dimmed", mt=2, mb=2))
    children.append(
        dcc.Loading(
            dcc.Graph(id=graph_id, config={"displayModeBar": False}, style=graph_style),
            custom_spinner=dmc.Skeleton(height=skeleton_h, radius="md", animate=True),
        )
    )
    return dmc.Card(children, withBorder=True, radius="lg", p="md", shadow="xs",
                    style={"height": "100%"})


# ---------------------------------------------------------------------------
# Section header with number + date-basis badge (Aufenthalt = stay date,
# Erstellung = booking date) - the visual convention carried over from the
# old section scaffolding.
# ---------------------------------------------------------------------------
_BASIS_BADGES = {
    "stay": ("Aufenthalt", "yellow"),
    "created": ("Erstellung", "gray"),
    "mixed": ("Aufenthalt + Erstellung", "gray"),
}


def section_header(num: int | str, title: str, *, basis: str | None = None,
                   info: str | None = None):
    children = [dmc.Title(f"{num} · {title}", order=4)]
    if basis in _BASIS_BADGES:
        label, color = _BASIS_BADGES[basis]
        children.append(dmc.Badge(label, color=color, variant="light", size="sm"))
    if info:
        children.append(info_icon(info))
    return dmc.Group(children, gap="sm", align="center", mt="md")


# ---------------------------------------------------------------------------
# Alert cards (highlights / auto-alerts). kind: alert | warning | info | success.
# ---------------------------------------------------------------------------
_ALERT_STYLES = {
    "alert": ("red", "bi bi-exclamation-triangle"),
    "warning": ("orange", "bi bi-exclamation-circle"),
    "info": ("blue", "bi bi-info-circle"),
    "success": ("green", "bi bi-check-circle"),
}


def alert(message, kind: str = "info", title: str | None = None):
    color, icon = _ALERT_STYLES.get(kind, _ALERT_STYLES["info"])
    return dmc.Alert(message, title=title, color=color, variant="light",
                     icon=html.I(className=icon), radius="md")


def alert_stack(items: list[tuple[str, str]]):
    """[(message, kind), ...] -> stacked alerts; None for an empty list."""
    if not items:
        return None
    return dmc.Stack([alert(msg, kind) for msg, kind in items], gap="xs")


# ---------------------------------------------------------------------------
# AG Grid from a (display-formatted) DataFrame + optional CSV export button.
# ---------------------------------------------------------------------------
def df_grid(df: pd.DataFrame, grid_id: str, *, height: int | None = None,
            pin_first: bool = True, page_size: int | None = None):
    df = df if isinstance(df, pd.DataFrame) else pd.DataFrame(df)
    col_defs = []
    for i, col in enumerate(df.columns):
        d = {"field": str(col)}
        if i == 0 and pin_first:
            d["pinned"] = "left"
        col_defs.append(d)
    opts = {"animateRows": True, "enableCellTextSelection": True}
    if page_size:
        opts.update({"pagination": True, "paginationPageSize": page_size})
    auto = height is None
    return dag.AgGrid(
        id=grid_id,
        columnDefs=col_defs,
        rowData=df.to_dict("records"),
        columnSize="responsiveSizeToFit",
        defaultColDef={"sortable": True, "resizable": True},
        dashGridOptions=opts | ({"domLayout": "autoHeight"} if auto else {}),
        style={"height": f"{height}px"} if height else {},
    )


def csv_button(grid_id: str, label: str = "CSV"):
    """Small download button; wire it once per grid via register_csv_export."""
    return dmc.Button(label, id=f"{grid_id}-csv", size="xs", variant="subtle",
                      color="gray", leftSection=html.I(className="bi bi-download"))


def register_csv_export(grid_id: str) -> None:
    @callback(Output(grid_id, "exportDataAsCsv"),
              Input(f"{grid_id}-csv", "n_clicks"), prevent_initial_call=True)
    def _export(_n):
        return True


def table_accordion(title: str, children, *, value: str):
    """Collapsed 'Datentabelle' under a chart (replaces the old expander)."""
    return dmc.Accordion(
        [dmc.AccordionItem([dmc.AccordionControl(title),
                            dmc.AccordionPanel(children)], value=value)],
        variant="contained", radius="md", chevronPosition="left")


# ---------------------------------------------------------------------------
# Data freshness badge: green < 5 h, yellow 5-15 h, red older (Europe/Berlin).
# ---------------------------------------------------------------------------
def freshness_badge(meta: dict):
    raw = str(meta.get("refreshed_at") or "").strip()
    ts = pd.to_datetime(raw, errors="coerce") if raw else pd.NaT
    if pd.isna(ts):
        dot, label = theme.GREY, "Daten-Stand unbekannt — bitte Refresh ausführen"
    else:
        if ts.tzinfo is None:
            ts = ts.tz_localize("Europe/Berlin")
        ts = ts.tz_convert("Europe/Berlin")
        age_h = max((pd.Timestamp.now(tz="Europe/Berlin") - ts).total_seconds() / 3600, 0.0)
        dot = theme.GREEN if age_h < 5 else theme.YELLOW if age_h <= 15 else theme.RED
        age = f"vor {age_h:.1f} h" if age_h < 48 else f"vor {age_h / 24:.1f} Tagen"
        label = f"Daten-Stand: {ts:%d.%m.%Y}, {ts:%H:%M} Uhr ({age})"
    return dmc.Group(
        [html.Span(style={"width": "10px", "height": "10px", "borderRadius": "50%",
                          "background": dot, "border": "1px solid rgba(0,0,0,0.25)",
                          "flex": "0 0 auto"}),
         dmc.Text(label, size="xs")],
        gap=8, align="center")


# ---------------------------------------------------------------------------
# Job loader: RingProgress % + spinning hourglass + live message + Cancel.
# IDs: {prefix}-wrap / -ring / -pct / -msg / -cancel. Hidden until a job runs.
# ---------------------------------------------------------------------------
def job_loader(prefix: str, *, with_cancel: bool = True) -> html.Div:
    right = [
        dmc.Group([
            html.I(className="bi bi-hourglass-split stayery-hourglass",
                   style={"color": theme.ORANGE, "fontSize": "1.15rem"}),
            dmc.Text(id=f"{prefix}-msg", size="sm", fw=500),
        ], gap=8, align="center", wrap="nowrap"),
    ]
    if with_cancel:
        right.append(dmc.Button("Abbrechen", id=f"{prefix}-cancel", size="xs",
                                variant="subtle", color="gray",
                                leftSection=html.I(className="bi bi-x-circle")))
    inner = dmc.Group([
        dmc.RingProgress(
            id=f"{prefix}-ring", size=64, thickness=6, roundCaps=True,
            sections=[{"value": 0, "color": "yellow"}],
            label=dmc.Center(dmc.Text("0%", id=f"{prefix}-pct", fw=700, size="sm")),
        ),
        dmc.Stack(right, gap=6),
    ], gap="lg", align="center")
    return html.Div(inner, id=f"{prefix}-wrap", style={"display": "none"})


def loader_view(pct: float, message: str, *, show: bool):
    """(ring_sections, pct_text, message, wrap_style) for the poll callback."""
    p = max(0, min(100, int(round(float(pct)))))
    return ([{"value": p, "color": "yellow"}], f"{p}%", message,
            {"display": "block"} if show else {"display": "none"})
