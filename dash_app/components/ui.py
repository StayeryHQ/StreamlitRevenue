# dash_app/components/ui.py
# Reusable dash-mantine-components building blocks shared across all pages -
# same primitives as the overbooking tool (kpi_card, chart_card, info_icon,
# job_loader) plus the revenue-specific section header, alert cards, AG-Grid
# and freshness badge.

from __future__ import annotations

import dash_ag_grid as dag
import dash_mantine_components as dmc
import pandas as pd
from dash import MATCH, Input, Output, State, callback, dcc, html

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
               height: int | None = 340, header_extra=None):
    # Header-only card - interpretation lives in the info-icon hover. The spacer
    # below the header keeps the plot's top legend from colliding with the title.
    graph_style = {"height": f"{height}px"} if height else {"width": "100%"}
    skeleton_h = height or 380
    header = dmc.Group(
        [dmc.Group([dmc.Text(title, fw=600, size="sm"),
                    info_icon(info) if info else None], gap=6, wrap="nowrap"),
         header_extra if header_extra is not None else html.Span()],
        justify="space-between", align="center", wrap="nowrap",
    )
    return dmc.Card(
        [header,
         dmc.Space(h=10),
         dcc.Loading(
             dcc.Graph(id=graph_id, config={"displayModeBar": False}, style=graph_style),
             custom_spinner=dmc.Skeleton(height=skeleton_h, radius="md", animate=True),
         )],
        withBorder=True, radius="lg", p="md", shadow="xs", style={"height": "100%"})


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


def alert_chips(items):
    """Compact horizontal highlights: each is a colour-coded chip showing just the
    headline; the full detail appears on hover. Space-saving replacement for a
    tall stack of alert boxes. items = list of (title, detail, kind) tuples or
    dicts {title, message, kind}. Returns a wrapping Group, or None if empty."""
    chips = []
    for it in items:
        if isinstance(it, dict):
            title = it.get("title") or it.get("message", "")
            detail, kind = it.get("message", ""), it.get("kind", "info")
        else:
            title = it[0]
            detail = it[1] if len(it) > 1 else ""
            kind = it[2] if len(it) > 2 else "info"
        color, icon = _ALERT_STYLES.get(kind, _ALERT_STYLES["info"])
        badge = dmc.Badge(
            title, color=color, variant="light", size="lg", radius="sm",
            leftSection=html.I(className=icon),
            styles={"root": {"cursor": "help", "maxWidth": "360px"},
                    "label": {"textTransform": "none", "overflow": "hidden",
                              "textOverflow": "ellipsis"}})
        chips.append(
            dmc.Tooltip(badge, label=detail, multiline=True, w=320, withArrow=True,
                        position="bottom") if detail else badge)
    if not chips:
        return None
    return dmc.Group(chips, gap="xs", wrap="wrap")


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
    # Rendered as a subtle brand pill (rounded, off-white, hairline border) with a
    # small status dot - matches the chip/badge language of the rest of the app.
    return dmc.Paper(
        dmc.Group(
            [dmc.Box(w=8, h=8, style={"borderRadius": "50%", "backgroundColor": dot,
                                      "flex": "0 0 auto"}),
             dmc.Text(label, size="xs", c="dark")],
            gap=8, align="center", wrap="nowrap"),
        px="sm", py=6, radius="xl", withBorder=True,
        style={"backgroundColor": "#FAFAF5", "borderColor": "#ECEAE0",
               "display": "inline-flex"})


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


# ---------------------------------------------------------------------------
# Filter shell: a slim STICKY bar holding the always-relevant primary controls,
# an optional "Erweitert" popover trigger on the right, and a reactive chip row
# underneath that echoes the active filters. Pages own the control ids; this is
# pure layout. Advanced/secondary controls live inside advanced_popover().
# ---------------------------------------------------------------------------
def location_select(fid: str, options: list[str], *, data: list[dict] | None = None,
                    width: int = 240, label: str = "Standorte", clearable: bool = True):
    """Compact location MultiSelect: fixed width + capped input height so a full
    selection scrolls inside one row instead of ballooning the whole bar. The
    active count is surfaced by the filter chips, not by growing this control."""
    # No persistence: a stale/empty value in browser localStorage would zero out
    # the whole view (the callbacks guard on an empty selection). Default = all.
    return dmc.MultiSelect(
        id=fid, label=label,
        data=data or [{"label": o, "value": o} for o in options],
        value=list(options), placeholder="Alle Standorte",
        clearable=clearable, searchable=True, hidePickedOptions=True,
        maxDropdownHeight=300, leftSection=html.I(className="bi bi-geo-alt"),
        comboboxProps={"withinPortal": True}, w=width,
        styles={"input": {"maxHeight": "38px", "overflowY": "auto"}},
    )


def advanced_popover(page: str, children: list, *, label: str = "Erweitert"):
    """Descriptor for the secondary filters. Returned to filter_shell, which
    renders the 'Erweitert' toggle + a reliable inline dmc.Collapse (the old
    controlled Popover was flaky). Kept as a function so view call sites are
    unchanged; `page` must be unique per view."""
    return {"__advanced__": True, "page": page, "children": children, "label": label}


def filter_shell(primary: list, *, advanced: dict | None = None,
                 chips_id: str | None = None):
    """Slim STICKY filter bar. `primary` = always-visible compact controls;
    `advanced` = an advanced_popover(...) descriptor revealed in a Collapse;
    `chips_id` = a Div the page fills with the active-filter chips."""
    page = advanced.get("page") if isinstance(advanced, dict) else None
    header_right = html.Span()
    if page:
        header_right = dmc.Button(
            advanced.get("label", "Erweitert"), id={"type": "ui-adv-btn", "page": page},
            variant="subtle", color="gray", size="sm",
            leftSection=html.I(className="bi bi-sliders"),
            rightSection=html.I(className="bi bi-chevron-down"))
    top = dmc.Group(
        [dmc.Group(primary, gap="sm", align="flex-end", wrap="wrap"), header_right],
        justify="space-between", align="flex-end", gap="md", wrap="wrap",
    )
    rows = [top]
    if page:
        rows.append(dmc.Collapse(
            dmc.Paper(dmc.Group(advanced["children"], gap="md", align="flex-end",
                                wrap="wrap"),
                      p="sm", radius="md", withBorder=True,
                      style={"backgroundColor": "#FAFAF5"}),
            id={"type": "ui-adv-pop", "page": page}, opened=False))
    if chips_id:
        rows.append(html.Div(id=chips_id))
    return dmc.Paper(
        dmc.Stack(rows, gap="xs"),
        p="sm", radius="lg", withBorder=True,
        style={"position": "sticky", "top": "8px", "zIndex": 300,
               "backgroundColor": theme.WHITE, "boxShadow": "0 2px 12px rgba(0,0,0,0.07)"},
    )


@callback(
    Output({"type": "ui-adv-pop", "page": MATCH}, "opened"),
    Input({"type": "ui-adv-btn", "page": MATCH}, "n_clicks"),
    State({"type": "ui-adv-pop", "page": MATCH}, "opened"),
    prevent_initial_call=True,
)
def _toggle_advanced(_n, opened):
    return not opened


# ---------------------------------------------------------------------------
# Thematic section tabs: groups a page's many sections so only one is on screen
# at a time. tabs = list of (value, label, content[, icon]); content is any
# node (usually a dmc.Stack of chart_cards / grids the data callback fills).
# ---------------------------------------------------------------------------
def section_tabs(tabs_id: str, tabs: list[tuple], *, value: str | None = None):
    tab_items, panels = [], []
    for t in tabs:
        val, label, content = t[0], t[1], t[2]
        icon = t[3] if len(t) > 3 else None
        tab_items.append(dmc.TabsTab(
            label, value=val,
            leftSection=html.I(className=icon) if icon else None))
        panels.append(dmc.TabsPanel(content, value=val, pt="md"))
    # keepMounted=True: every panel stays in the DOM (hidden) so a single data
    # callback can fill all tabs' graphs in one pass; tabs are purely visual.
    return dmc.Tabs(
        [dmc.TabsList(tab_items), *panels],
        id=tabs_id, value=value or tabs[0][0], keepMounted=True,
        variant="pills", radius="md", color="dark",
    )
