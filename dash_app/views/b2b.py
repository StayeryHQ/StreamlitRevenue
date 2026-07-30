# dash_app/views/b2b.py
# VIEW - B2B Deep-Dive (Sales-Gruppe). Alle Codes & Firmen ueber die Historie
# plus die B2B-lastigen Standort-Sektionen 11-13 (Firmenkunden-Uebersicht,
# Direct-Offline, Top-Vertragscodes), die von der Standort-Analyse hierher
# umgezogen sind. Port von the previous app +
# the Standort_Analyse view (§11-13). Kein register_page - der
# Sales-Hub importiert dieses Modul und ruft layout(). Alle Callbacks sind beim
# Import registriert. Roster-Aggregation in backend/b2b_tables, die §11-13-Figuren
# in components/b2b_charts (Plotly), Timeline im Drilldown aus components/
# code_charts. Daten aus dem Parquet-Snapshot via backend/data.,
# kein BigQuery.

from __future__ import annotations

from types import SimpleNamespace

import dash_mantine_components as dmc
import pandas as pd
from dash import Input, Output, State, callback, ctx, dcc, html, no_update

from dash_app.backend import b2b_tables as B
from dash_app.backend import data
from dash_app.backend import exports as XLS
from dash_app.components import b2b_charts as BC
from dash_app.components import code_charts as CC
from dash_app.components import ui
from dash_app.components.tooltips import CHART_TOOLTIPS
from revenueblindspots import helpers as H

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
    grid = ui.df_grid(pd.DataFrame(), grid_id, height=520)
    grid.dashGridOptions = {**(getattr(grid, "dashGridOptions", None) or {}),
                            "rowSelection": "single"}
    return grid


def _disp_grid(df: pd.DataFrame, grid_id: str, eur_cols=()):
    """Display grid with the given €-columns formatted German (raw stays numeric)."""
    d = df.copy()
    for c in eur_cols:
        if c in d.columns:
            d[c] = d[c].map(lambda v: H.fmt_eur(v) if pd.notna(v) else "–")
    return ui.df_grid(d, grid_id)


def _fig_card(title: str, fig, *, info: str | None = None, height: int = 420):
    header = dmc.Group([dmc.Text(title, fw=600, size="sm"),
                        ui.info_icon(info) if info else None], gap=6, wrap="nowrap")
    return dmc.Card([
        header,
        dcc.Graph(figure=fig, config={"displayModeBar": False},
                  style={"height": f"{height}px"}),
    ], withBorder=True, radius="lg", p="md", shadow="xs")


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
    month_end = month_start + pd.offsets.MonthEnd(0)

    primary = [
        ui.location_select("b2b-props", all_props, data=prop_data, clearable=False),
        dmc.DatePickerInput(id="b2b-lookback", label="Historie ab",
                            value=_iso(lookback_default), valueFormat="DD.MM.YYYY",
                            style={"minWidth": "150px"}, **_PERSIST),
        dmc.DatePickerInput(id="b2b-active", label='Aktiv-Schwelle',
                            value=_iso(month_start), valueFormat="DD.MM.YYYY",
                            style={"minWidth": "150px"}, **_PERSIST),
        dmc.DatePickerInput(id="b2b-ns", label="Fokus-Start", value=_iso(month_start),
                            valueFormat="DD.MM.YYYY", style={"minWidth": "150px"}, **_PERSIST),
        dmc.DatePickerInput(id="b2b-ne", label="Fokus-Ende", value=_iso(month_end),
                            valueFormat="DD.MM.YYYY", style={"minWidth": "150px"}, **_PERSIST),
    ]
    advanced = ui.advanced_popover("b2b", [
        dmc.Switch(id="b2b-cxl", label="Storno + No-Show einbeziehen", checked=False,
                   size="sm", **_PERSIST),
        dmc.Text("Wirkt auf die Firmenkunden-/Direct-Offline-/Vertragscode-Sektionen "
                 "(Fokus vs. Vorjahr). Der Code-/Firmen-Roster oben zeigt immer die "
                 "volle Historie inkl. Storno + No-Show.", size="xs", c="dimmed"),
    ])
    filter_bar = ui.filter_shell(primary=primary, advanced=advanced)

    # ---- Section-Tab-Panels (statische Struktur; der Daten-Callback fuellt sie) ----
    tab_cp = dmc.Stack([
        dmc.Text("Es wird i.d.R. corporateCode gepflegt (Corporate-Rate / OTA-Code), "
                 "nicht der harte apaleo company_code - das ist die primaere Code-Sicht. "
                 "Zeile anklicken oeffnet den Drilldown-Drawer.", size="sm", c="dimmed"),
        html.Div(id="b2b-cp-summary"),
        _roster_grid("b2b-cp-grid"),
    ], gap="sm")

    tab_fm = dmc.Stack([
        dmc.Text("Fuzzy-Cluster - company_name-Varianten werden zu einer Firma "
                 "zusammengezogen. Zeile anklicken oeffnet den Drilldown-Drawer.",
                 size="sm", c="dimmed"),
        html.Div(id="b2b-fm-summary"),
        _roster_grid("b2b-fm-grid"),
    ], gap="sm")

    tab_corp = dmc.Stack([
        ui.section_header(11, "Firmenkunden - Ueberblick & Channel-Split",
                          basis="created", info=CHART_TOOLTIPS["corp_overview"]),
        html.Div(id="b2b-corp-content"),
    ], gap="md")

    tab_do = dmc.Stack([
        ui.section_header(12, "Direct Offline - Detail-Segmente", basis="created",
                          info=CHART_TOOLTIPS["do_waterfall"]),
        html.Div(id="b2b-do-content"),
    ], gap="md")

    tab_codes = dmc.Stack([
        ui.section_header(13, "Top Vertragscodes (Fokus-Periode)", basis="created",
                          info=CHART_TOOLTIPS["codes"]),
        html.Div(id="b2b-codes-content"),
    ], gap="md")

    section_tabs = ui.section_tabs("b2b-sectiontabs", [
        ("corp-codes", "Corporate-Codes", tab_cp, "bi bi-upc-scan"),
        ("firms", "Firmen (Fuzzy)", tab_fm, "bi bi-people"),
        ("corp-ov", "Firmenkunden-Übersicht", tab_corp, "bi bi-building"),
        ("directoffline", "Direct-Offline", tab_do, "bi bi-telephone-outbound"),
        ("codes", "Top-Vertragscodes", tab_codes, "bi bi-file-earmark-text"),
    ])

    header = dmc.Group([
        dmc.Title("B2B Deep-Dive", order=3),
        dmc.Badge("Alle Codes & Firmen · Sales", color="yellow", variant="light",
                  radius="sm"),
    ], gap="sm", align="center", mb="xs")

    body = html.Div(dmc.Stack([
        html.Div(id="b2b-setup"),
        section_tabs,
        dmc.Group([
            dmc.Button("Alle Tabellen als Excel", id="b2b-dl-btn", variant="light",
                       leftSection=html.I(className="bi bi-file-earmark-excel")),
        ], mt="sm"),
        dcc.Download(id="b2b-dl"),
    ], gap="md"), id="b2b-body")

    drawer = dmc.Drawer(html.Div(id="b2b-drawer-body"), id="b2b-drawer",
                        title="Drilldown", position="right", size="xl", padding="md",
                        zIndex=1000, opened=False)

    return dmc.Stack([
        header,
        filter_bar,
        html.Div(id="b2b-alerts"),
        html.Div(id="b2b-guard"),
        body,
        drawer,
    ], gap="md")


# ---------------------------------------------------------------------------
# Ableitungen + Datenladen (zentral fuer Haupt-, Drilldown- und Export-Callback).
# ---------------------------------------------------------------------------
def _derive(props, lookback, active, ns, ne):
    if not props:
        return None, "Bitte mindestens einen Standort wählen."
    if not lookback or not active:
        return None, "Bitte Historie- und Aktiv-Datum wählen."
    if not ns or not ne:
        return None, "Bitte Fokus-Periode wählen."
    new_start, new_end = pd.Timestamp(ns), pd.Timestamp(ne)
    old_start, old_end = H.mirror_years(new_start, 1), H.mirror_years(new_end, 1)
    ctx_ns = SimpleNamespace(
        props=list(props), lookback_ts=pd.Timestamp(lookback), active_ts=pd.Timestamp(active),
        new_start=new_start, new_end=new_end, old_start=old_start, old_end=old_end,
        year_new=int(new_start.year), year_old=int(old_start.year))
    return ctx_ns, None


def _load(props, lookback):
    """(res, enriched, nightly). res is None when the filter selection is invalid."""
    if not props or not lookback:
        return None, False, None
    lb = pd.Timestamp(lookback)
    nightly = data.get_timeslices(start=lb, end=None, properties=list(props))
    enriched = H.timeslices_are_enriched(nightly)
    if enriched:
        res = H.reservations_from_timeslices(nightly)
    else:
        res = data.get_reservations(start=lb, end=None, properties=list(props))
    if res is not None and not res.empty and "firm_by_effective_fuzzy" in res.columns:
        res = res.copy()
        if "company" in res.columns:
            res["company"] = res["firm_by_effective_fuzzy"].fillna(res["company"])
        else:
            res["company"] = res["firm_by_effective_fuzzy"]
        res["has_company"] = res["company"].notna()
    return res, enriched, nightly


def _summary(t: pd.DataFrame, label: str, active_ts: pd.Timestamp):
    if t is None or t.empty:
        return ui.alert(f"Keine {label} im Lookback gefunden.", "info")
    n = f"{len(t):,}".replace(",", ".")
    n_active = f"{int((t['Aktiv seit Schwelle?'] == '✓ ja').sum()):,}".replace(",", ".")
    rev_tot = H.fmt_eur(float(t["Revenue gesamt (€)"].sum()))
    rev_real = H.fmt_eur(float(t["Revenue realisiert (€)"].sum()))
    return dcc.Markdown(
        f"**{n} {label}** im Lookback · davon **{n_active} aktiv** seit "
        f"{active_ts:%d.%m.%Y} · Total-Revenue: **{rev_tot}** (realisiert: {rev_real}).")


# ---------------------------------------------------------------------------
# §11-13 Content-Builder (Fokus vs. Vorjahr, created-basiert).
# ---------------------------------------------------------------------------
def _corp_content(res_old, res_new, ctx_ns, realized_only, label):
    fig = BC.corporate_overview(res_old, res_new, ctx_ns.year_old, ctx_ns.year_new,
                                label, realized_only=realized_only)
    top = BC.top_companies_table(res_old, res_new, ctx_ns.year_old, ctx_ns.year_new,
                                 realized_only=realized_only).head(12)
    eur = [f"Revenue {ctx_ns.year_old} (€)", f"Revenue {ctx_ns.year_new} (€)", "Δ Revenue (€)"]
    grid = (_disp_grid(top, "b2b-corp-firm-grid", eur_cols=eur) if not top.empty
            else ui.alert("Keine Firmenkunden mit Revenue in der Fokus-Periode.", "info"))
    return dmc.Stack([
        _fig_card("Firmenkunden vs. Privat · Channel-Split", fig, height=440),
        dmc.Text(f"Top-Firmenkunden nach Revenue {ctx_ns.year_new} (alle Channels)",
                 fw=600, size="sm"),
        grid,
    ], gap="md")


def _do_content(res_old, res_new, ctx_ns, realized_only, label):
    fig_wf, buckets = BC.directoffline_waterfall(res_old, res_new, ctx_ns.year_old,
                                                 ctx_ns.year_new, label,
                                                 realized_only=realized_only)
    fig_seg = BC.directoffline_segments(res_old, res_new, ctx_ns.year_old, ctx_ns.year_new,
                                        label, realized_only=realized_only)
    children = [
        _fig_card("Direct-Offline Firmen-Revenue · Waterfall", fig_wf, height=420),
        _fig_card("Direct-Offline Detail-Segmente", fig_seg, height=400),
    ]
    if buckets is not None:
        n = {k: len(buckets[k]) for k in ("lost", "shrunk", "grown", "gained")}
        children.append(ui.alert(
            f"verloren: {n['lost']} · geschrumpft: {n['shrunk']} · "
            f"gewachsen: {n['grown']} · neu: {n['gained']}", "info"))
        top_tbl = (BC.build_channel_table(buckets["all"].index, res_old, res_new,
                                          realized_only=realized_only)
                   .sort_values("Total new (€)", ascending=False).head(12))
        eur = [c for c in top_tbl.columns if c.endswith("(€)")]
        children.append(dmc.Text(f"Top-Firmenkunden nach Total-Revenue ({ctx_ns.year_new})",
                                 fw=600, size="sm"))
        children.append(_disp_grid(top_tbl, "b2b-do-top-grid", eur_cols=eur))

        segs = [
            ("Verlorene Firmen", buckets["lost"].index, "Direct_Offline old (€)", "do-lost"),
            ("Geschrumpfte Firmen", buckets["shrunk"].index, "Δ Direct_Offline (€)", "do-shrunk"),
            ("Gewachsene Firmen", buckets["grown"].index, "Δ Direct_Offline (€)", "do-grown"),
            ("Neue Firmen", buckets["gained"].index, "Direct_Offline new (€)", "do-gained"),
        ]
        for title, idx, sort_col, gid in segs:
            if len(idx) == 0:
                continue
            tbl = (BC.build_channel_table(idx, res_old, res_new, realized_only=realized_only)
                   .sort_values(sort_col, ascending=False).head(5))
            eur_c = [c for c in tbl.columns if c.endswith("(€)")]
            children.append(ui.table_accordion(
                f"{title} ({ctx_ns.year_old} → {ctx_ns.year_new}) · Top 5",
                _disp_grid(tbl, f"b2b-{gid}-grid", eur_cols=eur_c), value=gid))
    return dmc.Stack(children, gap="md")


def _codes_content(res_new, realized_only, period_tag):
    top = BC.top_codes_in_period(res_new, realized_only=realized_only)
    if top.empty:
        return ui.alert(f"Keine Buchungen mit gefuelltem Vertragscode in der Fokus-"
                        f"Periode ({period_tag}).", "info")
    show = top.head(15)
    rev_tot = H.fmt_eur(float(top["Revenue (€)"].sum()))
    head = dcc.Markdown(f"**{len(top)} Codes mit Aktivitaet in {period_tag}** · "
                        f"Total-Revenue: **{rev_tot}**")
    grid = _disp_grid(show, "b2b-codes-grid", eur_cols=["Revenue (€)", "ADR (€)"])
    return dmc.Stack([head, grid], gap="sm")


# ---------------------------------------------------------------------------
# Haupt-Callback: Setup, Alerts, Guard, Roster-Grids + §11-13 Content.
# ---------------------------------------------------------------------------
_OUTPUTS = [
    Output("b2b-alerts", "children"),
    Output("b2b-guard", "children"),
    Output("b2b-body", "style"),
    Output("b2b-setup", "children"),
    Output("b2b-cp-grid", "columnDefs"), Output("b2b-cp-grid", "rowData"),
    Output("b2b-cp-summary", "children"),
    Output("b2b-fm-grid", "columnDefs"), Output("b2b-fm-grid", "rowData"),
    Output("b2b-fm-summary", "children"),
    Output("b2b-corp-content", "children"),
    Output("b2b-do-content", "children"),
    Output("b2b-codes-content", "children"),
]

_INPUTS = [
    Input("b2b-props", "value"), Input("b2b-lookback", "value"),
    Input("b2b-active", "value"), Input("b2b-ns", "value"), Input("b2b-ne", "value"),
    Input("b2b-cxl", "checked"),
]


def _guard(alerts, guard):
    """Full output tuple with body hidden + empty roster/content (early return)."""
    return (alerts, guard, {"display": "none"}, None, [], [], None, [], [], None,
            None, None, None)


@callback(_OUTPUTS, _INPUTS)
def _update(props, lookback, active, ns, ne, cxl):
    ctx_ns, err = _derive(props, lookback, active, ns, ne)
    if err:
        kind = "info" if err.startswith("Bitte mindestens") else "warning"
        return _guard(None, ui.alert(err, kind))

    res, enriched, _nightly = _load(ctx_ns.props, ctx_ns.lookback_ts)
    if res is None or res.empty:
        return _guard(None, ui.alert("Keine Reservierungen im gewählten Zeitraum.", "warning"))

    # ---- Datenbasis-/Spaetstart-Hinweise --------------------------------------
    alerts = []
    if not enriched:
        alerts.append(ui.alert(
            "Firmen-/Code-Revenue laeuft noch auf der services-inklusiven Reservations-"
            "Basis. Fuer die konsistente Stay-Netto-Sicht einmal Voll-Refresh ziehen "
            "(Daten aktualisieren).", "info"))
    late = H.properties_without_old_data(ctx_ns.props, ctx_ns.lookback_ts)
    if late:
        lines = ", ".join(f"{pc} (eroeffnet {H.opening_date(pc):%d.%m.%Y})" for pc in late)
        alerts.append(ui.alert(
            f"Standorte ohne historische Daten zu Beginn des Lookbacks: {lines}. Die "
            f"Tabellen enthalten dort nur Daten ab Eroeffnungsdatum.", "info"))
    alerts_out = dmc.Stack(alerts, gap="xs") if alerts else None

    setup = dcc.Markdown(
        f"**Analyse-Setup** · Historie ab **{ctx_ns.lookback_ts:%d.%m.%Y}** · Aktiv-"
        f"Schwelle **{ctx_ns.active_ts:%d.%m.%Y}** · Fokus **{ctx_ns.new_start:%d.%m}–"
        f"{ctx_ns.new_end:%d.%m.%Y}** (YoY vs {ctx_ns.old_start:%d.%m}–"
        f"{ctx_ns.old_end:%d.%m.%Y}) · Standorte **{len(ctx_ns.props)}**.")

    # ---- Roster (immer volle Historie inkl. Storno + No-Show) ------------------
    cp_raw = B.aggregate_corporate_codes(res, ctx_ns.active_ts)
    fm_raw = B.aggregate_firms(res, ctx_ns.active_ts)
    cp_cols, cp_rows = _grid_out(B.format_display(cp_raw, "corporate"))
    fm_cols, fm_rows = _grid_out(B.format_display(fm_raw, "firm"))
    cp_summary = _summary(cp_raw, "Corporate-Codes", ctx_ns.active_ts)
    fm_summary = _summary(fm_raw, "Firmen", ctx_ns.active_ts)

    # ---- §11-13 (Fokus vs. Vorjahr, created-basiert) ---------------------------
    realized_only = not bool(cxl)
    label = "alle Standorte" if len(ctx_ns.props) >= len(H.all_properties()) \
        else f"{len(ctx_ns.props)} Standorte"
    period_tag = f"{ctx_ns.new_start:%d.%m.%Y}–{ctx_ns.new_end:%d.%m.%Y}"
    if "created" in res.columns:
        res_old = H.filter_period(res, ctx_ns.old_start, ctx_ns.old_end, "created")
        res_new = H.filter_period(res, ctx_ns.new_start, ctx_ns.new_end, "created")
        corp_content = _corp_content(res_old, res_new, ctx_ns, realized_only, label)
        do_content = _do_content(res_old, res_new, ctx_ns, realized_only, label)
        codes_content = _codes_content(res_new, realized_only, period_tag)
    else:
        note = ui.alert("Spalte 'created' fehlt im Snapshot - Fokus-/Vorjahres-"
                        "Sektionen nicht verfuegbar.", "warning")
        corp_content = do_content = codes_content = note

    return (alerts_out, None, {}, setup, cp_cols, cp_rows, cp_summary,
            fm_cols, fm_rows, fm_summary, corp_content, do_content, codes_content)


# ---------------------------------------------------------------------------
# Drilldown-Drawer: aus Roster-Zeilen-Auswahl (AG Grid selectedRows). Mini-360°
# mit code_charts.revenue_timeline + Deep-Link ins Code-Deepdive (/sales?tab=code).
# ---------------------------------------------------------------------------
def _drill_body(sub: pd.DataFrame, label: str, kind: str, open_code, active_ts):
    realized = sub[sub["is_realized"]]
    lifetime_rev = float(realized["revenue"].sum())
    n_book = len(sub)
    n_real = len(realized)
    nights = int(realized["nights"].fillna(0).sum())
    today = pd.Timestamp.today().normalize()
    arr_max = pd.Timestamp(sub["arrival"].max()) if len(sub) else today
    period_end = max(today, arr_max)
    fig, _monthly, _cum = CC.revenue_timeline(sub, label, active_ts, period_end)

    kpis = ui.kpi_strip([
        ui.kpi_card("Lifetime Revenue", H.fmt_eur(lifetime_rev), accent=True,
                    delta=f"{n_real:,} realisiert".replace(",", ".")),
        ui.kpi_card("Buchungen", f"{n_book:,}".replace(",", ".")),
        ui.kpi_card("Nächte (real.)", f"{nights:,}".replace(",", ".")),
    ], cols=3)

    if open_code:
        link = dcc.Link(
            dmc.Button("Im Code-Deepdive öffnen", variant="light",
                       leftSection=html.I(className="bi bi-box-arrow-up-right")),
            href=f"/sales?tab=code&code={open_code}")
    else:
        link = dmc.Text("Kein Vertragscode fuer den Deep-Link verfuegbar.", size="xs",
                        c="dimmed")

    return dmc.Stack([
        dmc.Badge(kind, color="yellow", variant="light", radius="sm"),
        kpis,
        dmc.Text("Revenue-Verlauf · realisiert, nach Anreise-Monat", fw=600, size="sm",
                 mt="sm"),
        dcc.Graph(figure=fig, config={"displayModeBar": False}, style={"height": "340px"}),
        link,
    ], gap="sm")


@callback(
    Output("b2b-drawer", "opened"),
    Output("b2b-drawer", "title"),
    Output("b2b-drawer-body", "children"),
    Input("b2b-cp-grid", "selectedRows"),
    Input("b2b-fm-grid", "selectedRows"),
    State("b2b-props", "value"), State("b2b-lookback", "value"),
    State("b2b-active", "value"),
    prevent_initial_call=True,
)
def _drilldown(cp_sel, fm_sel, props, lookback, active):
    trig = ctx.triggered_id
    rows = cp_sel if trig == "b2b-cp-grid" else fm_sel
    if not rows:
        return no_update, no_update, no_update

    res, _enriched, _nightly = _load(props, lookback)
    if res is None or res.empty:
        return no_update, no_update, no_update
    active_ts = pd.Timestamp(active) if active else pd.Timestamp.today().normalize()

    if trig == "b2b-cp-grid":
        code = str(rows[0].get("Corporate-Code", "")).strip()
        if not code or "corporateCode" not in res.columns:
            return no_update, no_update, no_update
        sub = res[res["corporateCode"].astype(str).str.strip().str.upper() == code.upper()]
        label, kind, open_code = code, "Corporate-Code", code
    else:
        firm = str(rows[0].get("Firma", "")).strip()
        if not firm or "firm_by_effective_fuzzy" not in res.columns:
            return no_update, no_update, no_update
        sub = res[res["firm_by_effective_fuzzy"].astype(str).str.strip() == firm]
        open_code = None
        if "corporateCode" in sub.columns:
            cc = sub["corporateCode"].dropna().astype(str).str.strip()
            cc = cc[~cc.str.lower().isin(_NULLISH)]
            if not cc.empty:
                open_code = str(cc.value_counts().index[0])
        label, kind = firm, "Firma (Fuzzy)"

    if sub.empty:
        return True, f"Drilldown · {label}", ui.alert("Keine Buchungen fuer diese Auswahl.",
                                                       "info")
    return True, f"Drilldown · {label}", _drill_body(sub, label, kind, open_code, active_ts)


# ---------------------------------------------------------------------------
# Export: Multi-Sheet-Excel (corporate_codes + firmen_fuzzy, Roh-Werte).
# ---------------------------------------------------------------------------
@callback(Output("b2b-dl", "data"), Input("b2b-dl-btn", "n_clicks"),
          State("b2b-props", "value"), State("b2b-lookback", "value"),
          State("b2b-active", "value"), prevent_initial_call=True)
def _export(_n, props, lookback, active):
    if not props or not lookback or not active:
        return no_update
    res, _enriched, _nightly = _load(props, lookback)
    if res is None or res.empty:
        return no_update
    active_ts = pd.Timestamp(active)
    sheets = {
        "corporate_codes": B.export_frame(B.aggregate_corporate_codes(res, active_ts),
                                          "corporate"),
        "firmen_fuzzy": B.export_frame(B.aggregate_firms(res, active_ts), "firm"),
    }
    fname = f"b2b_deepdive_{pd.Timestamp(lookback):%Y%m%d}.xlsx"
    return dcc.send_bytes(lambda buf: XLS.write_workbook(buf, sheets), fname)
