# dash_app/views/promo.py
# VIEW - Promo-Codes (Sales-Gruppe). Alle promoCodes ueber die Historie als
# Roster, ein Drilldown-Drawer je Code und ein Reklassifizierungs-Werkzeug, das
# als Firmencode getarnte Promocodes global umzieht (schreibt data/
# code_overrides.json via overrides.OV). Port von the previous app
# 6_Promo_Codes.py. Kein register_page - der Sales-Hub importiert dieses Modul
# und ruft layout(). Alle Callbacks sind beim Import registriert. Roster-
# Aggregation in backend/promo_tables, das Firmencode-Sheet aus backend/
# b2b_tables, die Timeline im Drilldown aus components/code_charts. Daten aus dem
# Parquet-Snapshot via backend/data. Kein BigQuery.

from __future__ import annotations

import dash_mantine_components as dmc
import pandas as pd
from dash import Input, Output, State, callback, ctx, dcc, html, no_update

from dash_app.backend import b2b_tables as B
from dash_app.backend import data
from dash_app.backend import exports as XLS
from dash_app.backend import promo_tables as P
from dash_app.components import code_charts as CC
from dash_app.components import ui
from revenueblindspots import helpers as H
from revenueblindspots import overrides as OV

_PERSIST = dict(persistence=True, persistence_type="local")
_NULLISH = {"", "nan", "none", "<na>", "null"}


# ---------------------------------------------------------------------------
# Grid-/Format-Helfer.
# ---------------------------------------------------------------------------
def _grid_out(df: pd.DataFrame):
    """(columnDefs, rowData) from a display DataFrame; empty frame -> ([], [])."""
    if df is None or getattr(df, "empty", True):
        return [], []
    cols = []
    for i, c in enumerate(df.columns):
        d = {"field": str(c)}
        if i == 0:
            d["pinned"] = "left"
        cols.append(d)
    return cols, df.to_dict("records")


def _iso(ts) -> str:
    return pd.Timestamp(ts).date().isoformat()


def _roster_grid(grid_id: str):
    """AG Grid with single-row selection wired for the drilldown drawer."""
    grid = ui.df_grid(pd.DataFrame(), grid_id, height=560)
    grid.dashGridOptions = {**(getattr(grid, "dashGridOptions", None) or {}),
                            "rowSelection": "single"}
    return grid


def _parse_paste(text: str) -> dict[str, str | None]:
    """Parse the pasted list into {CODE: firm_or_None}."""
    result: dict[str, str | None] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        firm: str | None = None
        for sep in ("=", ":", "\t", ","):
            if sep in line:
                code_part, firm_part = line.split(sep, 1)
                line = code_part.strip()
                firm = firm_part.strip() or None
                break
        if line:
            result[line.upper()] = firm
    return result


# ---------------------------------------------------------------------------
# Layout (callable -> Standort-Liste + Defaults werden bei jeder Navigation neu
# gelesen).
# ---------------------------------------------------------------------------
def layout(**_kwargs):
    meta = data.get_metadata()
    all_props = (meta.get("properties") if meta else None) or H.all_properties()
    prop_data = [{"label": f"{H.city_label(pc)} ({pc})", "value": pc} for pc in all_props]

    today = pd.Timestamp.today().normalize()
    lookback_default = (today - pd.DateOffset(years=3)).normalize()
    month_start = today.replace(day=1)

    primary = [
        ui.location_select("pr-props", all_props, data=prop_data, clearable=False),
        dmc.DatePickerInput(id="pr-lookback", label="Historie ab",
                            value=_iso(lookback_default), valueFormat="DD.MM.YYYY",
                            style={"minWidth": "150px"}, **_PERSIST),
        dmc.DatePickerInput(id="pr-active", label="Aktiv-Schwelle",
                            value=_iso(month_start), valueFormat="DD.MM.YYYY",
                            style={"minWidth": "150px"}, **_PERSIST),
    ]
    advanced = ui.advanced_popover("pr", [
        dmc.Switch(id="pr-suspect-only", label="Nur Firmencode-Verdacht", checked=False,
                   size="sm", **_PERSIST),
        dmc.Text("Filtert den Roster auf Codes mit Firmencode-Verdacht (⚑).",
                 size="xs", c="dimmed"),
    ])
    filter_bar = ui.filter_shell(primary=primary, advanced=advanced)

    # ---- Section-Tab-Panels ----------------------------------------------------
    tab_roster = dmc.Stack([
        dmc.Text("Alle promoCodes ueber die Historie. Spalte Firmencode-Verdacht (⚑) "
                 "markiert Codes, die wahrscheinlich Firmencodes sind. Zeile anklicken "
                 "oeffnet den Drilldown-Drawer.", size="sm", c="dimmed"),
        html.Div(id="pr-summary"),
        _roster_grid("pr-grid"),
    ], gap="sm")

    tab_reklass = dmc.Stack([
        dmc.Text("Traegt man hier Codes ein, werden ihre Buchungen global als "
                 "Firmencode-Buchungen behandelt (corporateCode = Promocode). Wirkt "
                 "sofort - die Caches werden neu geladen.", size="sm", c="dimmed"),
        html.Div(id="pr-recl-msg"),
        dmc.Title("Aktuell reklassifiziert", order=5),
        html.Div(id="pr-ov-current"),
        dmc.Group([
            dmc.MultiSelect(id="pr-remove-pick", label="Reklassifizierung entfernen",
                            data=[], searchable=True, clearable=True,
                            style={"minWidth": "320px"}),
            dmc.Button("Ausgewählte entfernen", id="pr-remove-btn", variant="light",
                       color="red", leftSection=html.I(className="bi bi-trash")),
        ], gap="md", align="flex-end"),
        dmc.Divider(my="sm"),
        dmc.Title("Neue Codes als Firmencode markieren", order=5),
        dmc.MultiSelect(id="pr-quick-pick", label="Schnellauswahl (Firmencode-Verdacht)",
                        data=[], searchable=True, clearable=True,
                        style={"minWidth": "320px"}),
        dmc.Textarea(id="pr-paste", autosize=False, minRows=4,
                     label="Oder Liste einfuegen - eine Zeile pro Code, optional "
                           "CODE = Firmenname",
                     placeholder="BCDB = BCD Travel\nBAU10\nIANUS10 = Ianus GmbH"),
        dmc.Group([
            dmc.Button("Als Firmencodes speichern", id="pr-save-btn", variant="filled",
                       color="dark", leftSection=html.I(className="bi bi-save")),
        ]),
    ], gap="sm")

    section_tabs = ui.section_tabs("pr-sectiontabs", [
        ("roster", "Promo-Roster", tab_roster, "bi bi-tag"),
        ("reklass", "Reklassifizierung", tab_reklass, "bi bi-arrow-left-right"),
    ])

    header = dmc.Group([
        dmc.Title("Promo-Codes", order=3),
        dmc.Badge("Marketing-Codes & Reklassifizierung · Sales", color="yellow",
                  variant="light", radius="sm"),
    ], gap="sm", align="center", mb="xs")

    body = html.Div(dmc.Stack([
        html.Div(id="pr-setup"),
        section_tabs,
        dmc.Group([
            dmc.Button("Alle Tabellen als Excel", id="pr-dl-btn", variant="light",
                       leftSection=html.I(className="bi bi-file-earmark-excel")),
        ], mt="sm"),
        dcc.Download(id="pr-dl"),
    ], gap="md"), id="pr-body")

    drawer = dmc.Drawer(html.Div(id="pr-drawer-body"), id="pr-drawer",
                        title="Drilldown", position="right", size="xl", padding="md",
                        zIndex=1000, opened=False)

    return dmc.Stack([
        dcc.Store(id="pr-ov-version", data=0),
        header,
        filter_bar,
        html.Div(id="pr-alerts"),
        html.Div(id="pr-guard"),
        body,
        drawer,
    ], gap="md")


# ---------------------------------------------------------------------------
# Datenladen (zentral fuer Haupt-, Drilldown- und Export-Callback).
# ---------------------------------------------------------------------------
def _load(props, lookback):
    """(res, basis). res is None when the filter selection is invalid/empty."""
    if not props or not lookback:
        return None, ""
    lb = pd.Timestamp(lookback)
    nightly = data.get_timeslices(start=lb, end=None, properties=list(props))
    if H.timeslices_are_enriched(nightly) and "promoCode" in nightly.columns:
        res = H.reservations_from_timeslices(nightly)
        basis = "Stay-Netto (Timeslices)"
    else:
        res = data.get_reservations(start=lb, end=None, properties=list(props))
        basis = "services-inklusive Reservations"
    return res, basis


def _corp_set(res: pd.DataFrame) -> set[str]:
    if "corporateCode" not in res.columns:
        return set()
    cc = res["corporateCode"].dropna().astype(str).str.strip().str.upper()
    return set(cc[cc != ""].unique())


def _ov_current(override_map: dict):
    if not override_map:
        return dmc.Text("Noch keine Reklassifizierungen gespeichert.", size="sm", c="dimmed")
    rows = [html.Tr([html.Td(c), html.Td(p.get("firm") or "-"), html.Td(p.get("added", "-"))])
            for c, p in sorted(override_map.items())]
    return dmc.Table([
        html.Thead(html.Tr([html.Th("Promocode"), html.Th("Firmenname"), html.Th("seit")])),
        html.Tbody(rows),
    ], striped=True, withTableBorder=True, highlightOnHover=True)


# ---------------------------------------------------------------------------
# Haupt-Callback: Setup, Alerts, Guard, Roster-Grid + Reklassifizierungs-Panel.
# ---------------------------------------------------------------------------
_OUTPUTS = [
    Output("pr-alerts", "children"),
    Output("pr-guard", "children"),
    Output("pr-body", "style"),
    Output("pr-setup", "children"),
    Output("pr-grid", "columnDefs"), Output("pr-grid", "rowData"),
    Output("pr-summary", "children"),
    Output("pr-ov-current", "children"),
    Output("pr-remove-pick", "data"),
    Output("pr-quick-pick", "data"),
]

_INPUTS = [
    Input("pr-props", "value"), Input("pr-lookback", "value"),
    Input("pr-active", "value"), Input("pr-suspect-only", "checked"),
    Input("pr-ov-version", "data"),
]


def _guard(alerts, guard):
    return (alerts, guard, {"display": "none"}, None, [], [], None, None, [], [])


@callback(_OUTPUTS, _INPUTS)
def _update(props, lookback, active, suspect_only, _ov_version):
    if not props:
        return _guard(None, ui.alert("Bitte mindestens einen Standort wählen.", "info"))
    if not lookback or not active:
        return _guard(None, ui.alert("Bitte Historie- und Aktiv-Datum wählen.", "warning"))

    res, basis = _load(props, lookback)
    if res is None or res.empty:
        return _guard(None, ui.alert("Keine Reservierungen im gewählten Zeitraum.", "warning"))
    if "promoCode" not in res.columns:
        return _guard(None, ui.alert(
            "Im aktuellen Snapshot fehlt die Spalte promoCode - bitte einmal "
            "Daten aktualisieren.", "warning"))

    active_ts = pd.Timestamp(active)
    override_map = OV.promo_overrides()
    reclassified = set(override_map.keys())
    promo_table = P.aggregate_promo_codes(res, active_ts, corporate_code_set=_corp_set(res),
                                           reclassified_codes=reclassified)

    setup = dcc.Markdown(
        f"**Analyse-Setup** · Historie ab **{pd.Timestamp(lookback):%d.%m.%Y}** · "
        f"Aktiv-Schwelle **{active_ts:%d.%m.%Y}** · Standorte **{len(props)}** · "
        f"Revenue-Basis: {basis}.")

    if promo_table.empty:
        return (None, ui.alert("Keine promoCode-Werte im Lookback gefunden.", "info"),
                {"display": "none"}, setup, [], [], None,
                _ov_current(override_map), sorted(override_map.keys()), [])

    n_codes = f"{len(promo_table):,}".replace(",", ".")
    n_suspect = f"{int((promo_table['Firmencode-Verdacht'] == '⚑ ja').sum()):,}".replace(",", ".")
    n_reclass = f"{int(promo_table['Status'].str.startswith('✓').sum()):,}".replace(",", ".")
    rev_tot = H.fmt_eur(float(promo_table["Revenue gesamt (€)"].sum()))
    summary = dcc.Markdown(
        f"**{n_codes} Promocodes** im Lookback · **{n_suspect}** mit Firmencode-Verdacht "
        f"· **{n_reclass}** bereits reklassifiziert · Total-Revenue **{rev_tot}**.")

    disp = P.format_display(promo_table)
    if suspect_only:
        disp = disp[disp["Firmencode-Verdacht"] == "⚑ ja"]
    cols, rows = _grid_out(disp)

    suspect_codes = (promo_table.loc[promo_table["Firmencode-Verdacht"] == "⚑ ja",
                                     "Promocode"].astype(str).tolist())
    quick_opts = [c for c in suspect_codes if c.upper() not in reclassified]

    return (None, None, {}, setup, cols, rows, summary,
            _ov_current(override_map), sorted(override_map.keys()), quick_opts)


# ---------------------------------------------------------------------------
# Reklassifizierung: hinzufuegen (quick-pick + paste) / entfernen. Nach jedem
# Schreibvorgang data.clear_caches() + Store-Bump, der den Haupt-Callback neu
# laufen laesst (Roster + Override-Liste ziehen nach).
# ---------------------------------------------------------------------------
@callback(
    Output("pr-ov-version", "data"),
    Output("pr-recl-msg", "children"),
    Output("pr-quick-pick", "value"),
    Output("pr-paste", "value"),
    Output("pr-remove-pick", "value"),
    Input("pr-save-btn", "n_clicks"),
    Input("pr-remove-btn", "n_clicks"),
    State("pr-quick-pick", "value"), State("pr-paste", "value"),
    State("pr-remove-pick", "value"), State("pr-ov-version", "data"),
    prevent_initial_call=True,
)
def _reclassify(_save, _remove, quick, paste, remove, version):
    trig = ctx.triggered_id
    version = int(version or 0)

    if trig == "pr-save-btn":
        to_add: dict[str, str | None] = {c.upper(): None for c in (quick or [])}
        to_add.update(_parse_paste(paste or ""))
        if not to_add:
            return (no_update, ui.alert("Keine Codes angegeben.", "warning"),
                    no_update, no_update, no_update)
        OV.add_promo_overrides(to_add)
        data.clear_caches()
        msg = ui.alert(f"{len(to_add)} Code(s) als Firmencode reklassifiziert: "
                       f"{', '.join(sorted(to_add))}. Wirkt jetzt global.", "success")
        return version + 1, msg, [], "", no_update

    if trig == "pr-remove-btn":
        if not remove:
            return (no_update, ui.alert("Keine Reklassifizierung ausgewählt.", "warning"),
                    no_update, no_update, no_update)
        for code in remove:
            OV.remove_promo_override(code)
        data.clear_caches()
        msg = ui.alert(f"{len(remove)} Reklassifizierung(en) entfernt.", "success")
        return version + 1, msg, no_update, no_update, []

    return no_update, no_update, no_update, no_update, no_update


# ---------------------------------------------------------------------------
# Drilldown-Drawer aus Roster-Zeilen-Auswahl (AG Grid selectedRows).
# ---------------------------------------------------------------------------
def _drill_body(sub: pd.DataFrame, code: str, active_ts):
    realized = sub[sub["is_realized"]]
    lifetime_rev = float(realized["revenue"].sum())
    n_book = len(sub)
    n_real = len(realized)
    nights = int(realized["nights"].fillna(0).sum())
    is_reclass = code.upper() in set(OV.promo_overrides().keys())
    status = "✓ als Firmencode reklassifiziert" if is_reclass else "Promo (nicht reklassifiziert)"
    today = pd.Timestamp.today().normalize()
    arr_max = pd.Timestamp(sub["arrival"].max()) if len(sub) else today
    fig, _monthly, _cum = CC.revenue_timeline(sub, code, active_ts, max(today, arr_max))

    kpis = ui.kpi_strip([
        ui.kpi_card("Lifetime Revenue", H.fmt_eur(lifetime_rev), accent=True,
                    delta=f"{n_real:,} realisiert".replace(",", ".")),
        ui.kpi_card("Buchungen", f"{n_book:,}".replace(",", ".")),
        ui.kpi_card("Nächte (real.)", f"{nights:,}".replace(",", ".")),
    ], cols=3)

    return dmc.Stack([
        dmc.Badge(status, color="yellow" if is_reclass else "gray", variant="light",
                  radius="sm"),
        kpis,
        dmc.Text("Revenue-Verlauf · realisiert, nach Anreise-Monat", fw=600, size="sm",
                 mt="sm"),
        dcc.Graph(figure=fig, config={"displayModeBar": False}, style={"height": "340px"}),
        dcc.Link(
            dmc.Button("Im Code-Deepdive öffnen", variant="light",
                       leftSection=html.I(className="bi bi-box-arrow-up-right")),
            href=f"/sales?tab=code&code={code}"),
    ], gap="sm")


@callback(
    Output("pr-drawer", "opened"),
    Output("pr-drawer", "title"),
    Output("pr-drawer-body", "children"),
    Input("pr-grid", "selectedRows"),
    State("pr-props", "value"), State("pr-lookback", "value"), State("pr-active", "value"),
    prevent_initial_call=True,
)
def _drilldown(sel, props, lookback, active):
    if not sel:
        return no_update, no_update, no_update
    res, _basis = _load(props, lookback)
    if res is None or res.empty or "promoCode" not in res.columns:
        return no_update, no_update, no_update
    code = str(sel[0].get("Promocode", "")).strip()
    if not code:
        return no_update, no_update, no_update
    active_ts = pd.Timestamp(active) if active else pd.Timestamp.today().normalize()
    sub = res[res["promoCode"].astype(str).str.strip().str.upper() == code.upper()]
    if sub.empty:
        return True, f"Drilldown · {code}", ui.alert("Keine Buchungen fuer diesen Code.",
                                                     "info")
    return True, f"Drilldown · {code}", _drill_body(sub, code, active_ts)


# ---------------------------------------------------------------------------
# Export: promo_codes + firmencodes_aktualisiert (post-override) + reklassifizierung.
# ---------------------------------------------------------------------------
@callback(Output("pr-dl", "data"), Input("pr-dl-btn", "n_clicks"),
          State("pr-props", "value"), State("pr-lookback", "value"),
          State("pr-active", "value"), prevent_initial_call=True)
def _export(_n, props, lookback, active):
    if not props or not lookback or not active:
        return no_update
    res, _basis = _load(props, lookback)
    if res is None or res.empty or "promoCode" not in res.columns:
        return no_update
    active_ts = pd.Timestamp(active)
    override_map = OV.promo_overrides()
    promo_table = P.aggregate_promo_codes(res, active_ts, corporate_code_set=_corp_set(res),
                                           reclassified_codes=set(override_map.keys()))
    sheets = {"promo_codes": promo_table}
    firmencode_sheet = B.export_frame(B.aggregate_corporate_codes(res, active_ts), "corporate")
    if not firmencode_sheet.empty:
        sheets["firmencodes_aktualisiert"] = firmencode_sheet
    if override_map:
        sheets["reklassifizierung"] = pd.DataFrame(
            [{"Promocode": c, "Firmenname": (p.get("firm") or ""), "seit": p.get("added", "")}
             for c, p in sorted(override_map.items())])
    fname = f"promo_codes_{pd.Timestamp(lookback):%Y%m%d}.xlsx"
    return dcc.send_bytes(lambda buf: XLS.write_workbook(buf, sheets), fname)
