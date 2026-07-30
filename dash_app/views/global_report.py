# dash_app/pages/global_report.py
# Global Report - portfolio revenue recap (IST vs PLAN vs Vorjahr, Channel-Mix,
# Heatmaps). Port of the Global_Report view. The filter bar is a
# dmc.Paper on top (no sidebar); every control has a direct effect. Layout is
# light - all tables and figures are produced by one callback. Grids receive both
# columnDefs and rowData from the callback. No live BigQuery: reads the parquet
# snapshot via dash_app.backend.data.

from __future__ import annotations

import dash_mantine_components as dmc
import pandas as pd
from dash import Input, Output, callback, dcc, html

from dash_app.backend import chart_data as CDT
from dash_app.backend import data
from dash_app.backend import global_tables as GT
from dash_app.components import global_report_charts as GRC
from dash_app.components import ui
from dash_app.components.tooltips import (
    CHART_TOOLTIPS,
    KPI_GLOBAL_IST_OLD,
    KPI_GLOBAL_IST_STAY,
    KPI_GLOBAL_PLAN,
    KPI_GLOBAL_SALES,
)
from revenueblindspots import helpers as H

_PERSIST = dict(persistence=True, persistence_type="local")
_HIDE = {"display": "none"}
_SHOW = {"display": "flex", "flexWrap": "wrap", "gap": "12px", "alignItems": "flex-end"}


def _quarter_bounds(year: int, q: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Inclusive [start, end] Timestamps for calendar quarter ``q`` of ``year``."""
    start_month = (q - 1) * 3 + 1
    start = pd.Timestamp(year=year, month=start_month, day=1)
    end = pd.Timestamp(year=year, month=start_month + 2, day=1) + pd.offsets.MonthEnd(0)
    return start, end


def _signed_eur(value: float) -> str:
    """German euro string with an explicit sign, e.g. '+1.234 €' / '-5.000 €'."""
    return f"{value:+,.0f} €".replace(",", ".")


def _coldefs(df: pd.DataFrame, *, pin_first: bool = True) -> list[dict]:
    """columnDefs from a DataFrame's columns (first column pinned left)."""
    defs = []
    for i, col in enumerate(df.columns):
        d = {"field": str(col)}
        if i == 0 and pin_first:
            d["pinned"] = "left"
        defs.append(d)
    return defs


def _grid_out(df: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    """(columnDefs, rowData) for a grid; empty frame -> empty grid."""
    if df is None or df.empty:
        return [], []
    return _coldefs(df), df.to_dict("records")


# ---------------------------------------------------------------------------
# Layout (callable => the property list is re-read on each navigation).
# ---------------------------------------------------------------------------
def layout(**_kwargs):
    meta = data.get_metadata()
    all_props = (meta.get("properties") if meta else None) or H.all_properties()
    prop_data = [{"label": f"{H.city(pc)} ({pc})", "value": pc} for pc in all_props]

    today = pd.Timestamp.today().normalize()
    cur_year = int(today.year)
    cur_q = ((int(today.month) - 1) // 3) + 1
    prev_year = cur_year - 1
    cur_q_start, cur_q_end = _quarter_bounds(cur_year, cur_q)
    prev_q_start, prev_q_end = _quarter_bounds(prev_year, cur_q)
    q_data = [{"label": f"Q{i}", "value": str(i)} for i in (1, 2, 3, 4)]

    quartal_block = html.Div([
        dmc.NumberInput(id="gr-y-new", label="Jahr (aktuell)", value=cur_year,
                        min=2018, max=2035, step=1, w=130, **_PERSIST),
        dmc.Select(id="gr-q-new", label="Quartal (aktuell)", data=q_data,
                   value=str(cur_q), allowDeselect=False, w=120, **_PERSIST),
        dmc.NumberInput(id="gr-y-old", label="Jahr (Vergleich)", value=prev_year,
                        min=2018, max=2035, step=1, w=130, **_PERSIST),
        dmc.Select(id="gr-q-old", label="Quartal (Vergleich)", data=q_data,
                   value=str(cur_q), allowDeselect=False, w=120, **_PERSIST),
    ], id="gr-quartal-block", style=_SHOW)

    frei_block = html.Div([
        dmc.DatePickerInput(id="gr-old-start", label="OLD Start", valueFormat="DD.MM.YYYY",
                            value=prev_q_start.date().isoformat(), w=160, **_PERSIST),
        dmc.DatePickerInput(id="gr-old-end", label="OLD Ende", valueFormat="DD.MM.YYYY",
                            value=prev_q_end.date().isoformat(), w=160, **_PERSIST),
        dmc.DatePickerInput(id="gr-new-start", label="NEW Start", valueFormat="DD.MM.YYYY",
                            value=cur_q_start.date().isoformat(), w=160, **_PERSIST),
        dmc.DatePickerInput(id="gr-new-end", label="NEW Ende", valueFormat="DD.MM.YYYY",
                            value=cur_q_end.date().isoformat(), w=160, **_PERSIST),
    ], id="gr-frei-block", style=_HIDE)

    primary = [
        ui.location_select("gr-props", all_props, data=prop_data),
        dmc.SegmentedControl(
            id="gr-mode", value="quartal", size="sm", radius="md",
            data=[{"label": "Quartal", "value": "quartal"},
                  {"label": "Freie Periode", "value": "frei"}], **_PERSIST),
        quartal_block,
        frei_block,
    ]
    advanced = ui.advanced_popover("gr", [
        dmc.Stack([
            dmc.Group([dmc.Text("Schwelle 🟢 (≥ PLAN + %)", size="xs", fw=600, c="dimmed"),
                       ui.info_icon("Ab dieser Δ-vs-PLAN-Schwelle gilt ein Standort als grün.")],
                      gap=4, wrap="nowrap"),
            dmc.Slider(id="gr-green", min=0.5, max=10.0, step=0.5, value=2.0,
                       w=200, marks=[{"value": 2.0}, {"value": 10.0}], **_PERSIST),
        ], gap=4),
        dmc.Stack([
            dmc.Group([dmc.Text("Schwelle 🔴 (≤ PLAN − %)", size="xs", fw=600, c="dimmed"),
                       ui.info_icon("Bis zu dieser Δ-vs-PLAN-Schwelle gilt ein Standort als rot.")],
                      gap=4, wrap="nowrap"),
            dmc.Slider(id="gr-red", min=-30.0, max=-1.0, step=1.0, value=-10.0,
                       w=200, marks=[{"value": -10.0}, {"value": -1.0}], **_PERSIST),
        ], gap=4),
        dmc.Switch(id="gr-late", label="Späte Öffner einbeziehen", checked=False,
                   size="sm", **_PERSIST),
        dmc.Switch(id="gr-cxl", label="Storno + No-Show einbeziehen", checked=False,
                   size="sm", **_PERSIST),
    ])

    filter_bar = ui.filter_shell(primary=primary, advanced=advanced)

    header = dmc.Group([
        dmc.Title("Global Report", order=3),
        dmc.Badge("Portfolio · Revenue-Recap", color="gray", variant="light", radius="sm"),
    ], gap="sm", align="center")

    tab_overview = dmc.Stack([
        dmc.Title("Executive Summary", order=4),
        html.Div(id="gr-kpis", children=dmc.Skeleton(height=110, radius="lg")),
        html.Div(id="gr-exec-alerts"),
        ui.section_header(1, "Visual Scorecard", basis="stay", info=CHART_TOOLTIPS["scorecard"]),
        ui.chart_card("Visual Scorecard", "gr-fig-scorecard", height=480),
        ui.table_accordion("Datentabelle",
                           ui.df_grid(pd.DataFrame(), "gr-grid-scorecard"), value="scorecard"),
        ui.section_header("Top-Movers", "Δ Revenue YoY je Standort", basis="stay",
                          info=CHART_TOOLTIPS["top_movers"]),
        ui.chart_card("Top-Movers · Δ Revenue YoY", "gr-fig-movers", height=460),
        ui.table_accordion("Datentabelle",
                           ui.df_grid(pd.DataFrame(), "gr-grid-movers"), value="movers"),
    ], gap="md")

    tab_erstellung = dmc.Stack([
        ui.section_header(2, "Performance nach Erstellungsdatum", basis="created"),
        ui.section_header("2.A", "Performance Standorte (Erstellung)", basis="created",
                          info=CHART_TOOLTIPS["perf_created"]),
        html.Div(id="gr-created-alert"),
        dmc.Card(ui.df_grid(pd.DataFrame(), "gr-grid-created"),
                 withBorder=True, radius="lg", p="md"),
        ui.section_header("2.B", "Buchungskanäle (Erstellung)", basis="created",
                          info=CHART_TOOLTIPS["chan_created"]),
        dmc.Card(ui.df_grid(pd.DataFrame(), "gr-grid-chan-created"),
                 withBorder=True, radius="lg", p="md"),
    ], gap="md")

    tab_aufenthalt = dmc.Stack([
        ui.section_header(3, "Performance nach Aufenthaltsdatum", basis="stay"),
        ui.section_header("3.A", "Performance Standorte (Aufenthalt)", basis="stay",
                          info=CHART_TOOLTIPS["perf_stay"]),
        dmc.Card(ui.df_grid(pd.DataFrame(), "gr-grid-perf-stay"),
                 withBorder=True, radius="lg", p="md"),
        ui.section_header("3.B", "Buchungskanäle (Aufenthalt)", basis="stay",
                          info=CHART_TOOLTIPS["chan_stay"]),
        dmc.Card(ui.df_grid(pd.DataFrame(), "gr-grid-chan-stay"),
                 withBorder=True, radius="lg", p="md"),
        ui.alert("Die Pace-to-PLAN-Analyse (OTB vs. Ziel + Zeit-Fortschritt) ist auf die "
                 "Seite Pickup / Vorlauf-Analyse umgezogen.", "info",
                 title="4 · IST vs PLAN · Pace-Fortschritt"),
    ], gap="md")

    tab_channelmix = dmc.Stack([
        ui.section_header(5, "Channel-Mix Detail", basis="stay",
                          info=CHART_TOOLTIPS["channel_detail"]),
        dmc.SimpleGrid([
            ui.chart_card("Channel-Mix Donuts", "gr-fig-donut", height=380),
            ui.chart_card("Top-Channels YoY", "gr-fig-bars", height=420),
        ], cols={"base": 1, "md": 2}, spacing="md"),
        ui.table_accordion("Datentabelle",
                           ui.df_grid(pd.DataFrame(), "gr-grid-chan-detail"), value="chan_detail"),
    ], gap="md")

    tab_heatmaps = dmc.Stack([
        ui.section_header(6, "Supporting Insights"),
        ui.section_header("6.A", "Revenue-Heatmap Standort × Monat", basis="stay",
                          info=CHART_TOOLTIPS["heat_loc_month"]),
        ui.chart_card("Revenue-Heatmap Standort × Monat", "gr-fig-heat-loc", height=460),
        ui.table_accordion("Datentabelle",
                           ui.df_grid(pd.DataFrame(), "gr-grid-heat-loc"), value="heat_loc"),
        ui.section_header("6.B", "Channel-Mix je Standort", basis="stay",
                          info=CHART_TOOLTIPS["heat_chan_loc"]),
        ui.chart_card("Channel-Mix je Standort (Anteil %)", "gr-fig-heat-chloc", height=460),
        ui.table_accordion("Datentabelle",
                           ui.df_grid(pd.DataFrame(), "gr-grid-heat-chloc"), value="heat_chloc"),
        ui.section_header("6.C", "Channel × LOS (granular)", basis="stay",
                          info=CHART_TOOLTIPS["heat_ch_los_granular"]),
        ui.chart_card("Channel × LOS (granular)", "gr-fig-heat-chlos", height=560),
        ui.table_accordion("Datentabelle",
                           ui.df_grid(pd.DataFrame(), "gr-grid-heat-chlos"), value="heat_chlos"),
    ], gap="md")

    section_tabs = ui.section_tabs("gr-sectiontabs", [
        ("overview", "Überblick", tab_overview, "bi bi-speedometer2"),
        ("erstellung", "Erstellung", tab_erstellung, "bi bi-pencil-square"),
        ("aufenthalt", "Aufenthalt", tab_aufenthalt, "bi bi-calendar-check"),
        ("channelmix", "Channel-Mix", tab_channelmix, "bi bi-diagram-3"),
        ("heatmaps", "Heatmaps", tab_heatmaps, "bi bi-grid-3x3"),
    ])

    return dmc.Stack([
        header,
        filter_bar,
        html.Div(id="gr-filter-alerts"),
        section_tabs,
    ], gap="md")


# ---------------------------------------------------------------------------
# Filter-mode toggle: Quartal-Picker vs Freie-Perioden-Datumsfelder.
# ---------------------------------------------------------------------------
@callback(
    Output("gr-quartal-block", "style"),
    Output("gr-frei-block", "style"),
    Input("gr-mode", "value"),
)
def _toggle_mode(mode):
    if mode == "frei":
        return _HIDE, _SHOW
    return _SHOW, _HIDE


# ---------------------------------------------------------------------------
# Period resolution + late-opener / lookback guards.
# ---------------------------------------------------------------------------
def _resolve_period(mode, y_new, q_new, y_old, q_old, o_start, o_end, n_start, n_end):
    if mode == "frei":
        start_old, end_old = pd.Timestamp(o_start), pd.Timestamp(o_end)
        start_new, end_new = pd.Timestamp(n_start), pd.Timestamp(n_end)
        tag_new = f"{start_new:%d.%m.%Y}–{end_new:%d.%m.%Y}"
        tag_old = f"{start_old:%d.%m.%Y}–{end_old:%d.%m.%Y}"
    else:
        yn, qn, yo, qo = int(y_new), int(q_new), int(y_old), int(q_old)
        start_new, end_new = _quarter_bounds(yn, qn)
        start_old, end_old = _quarter_bounds(yo, qo)
        tag_new, tag_old = f"Q{qn} {yn}", f"Q{qo} {yo}"
    return start_old, end_old, start_new, end_new, tag_new, tag_old


_OUTPUTS = [
    Output("gr-filter-alerts", "children"),
    Output("gr-kpis", "children"),
    Output("gr-exec-alerts", "children"),
    Output("gr-fig-scorecard", "figure"),
    Output("gr-grid-scorecard", "columnDefs"), Output("gr-grid-scorecard", "rowData"),
    Output("gr-created-alert", "children"),
    Output("gr-grid-created", "columnDefs"), Output("gr-grid-created", "rowData"),
    Output("gr-grid-chan-created", "columnDefs"), Output("gr-grid-chan-created", "rowData"),
    Output("gr-grid-perf-stay", "columnDefs"), Output("gr-grid-perf-stay", "rowData"),
    Output("gr-grid-chan-stay", "columnDefs"), Output("gr-grid-chan-stay", "rowData"),
    Output("gr-fig-donut", "figure"), Output("gr-fig-bars", "figure"),
    Output("gr-grid-chan-detail", "columnDefs"), Output("gr-grid-chan-detail", "rowData"),
    Output("gr-fig-heat-loc", "figure"),
    Output("gr-grid-heat-loc", "columnDefs"), Output("gr-grid-heat-loc", "rowData"),
    Output("gr-fig-heat-chloc", "figure"),
    Output("gr-grid-heat-chloc", "columnDefs"), Output("gr-grid-heat-chloc", "rowData"),
    Output("gr-fig-movers", "figure"),
    Output("gr-grid-movers", "columnDefs"), Output("gr-grid-movers", "rowData"),
    Output("gr-fig-heat-chlos", "figure"),
    Output("gr-grid-heat-chlos", "columnDefs"), Output("gr-grid-heat-chlos", "rowData"),
]

_INPUTS = [
    Input("gr-props", "value"), Input("gr-mode", "value"),
    Input("gr-y-new", "value"), Input("gr-q-new", "value"),
    Input("gr-y-old", "value"), Input("gr-q-old", "value"),
    Input("gr-old-start", "value"), Input("gr-old-end", "value"),
    Input("gr-new-start", "value"), Input("gr-new-end", "value"),
    Input("gr-green", "value"), Input("gr-red", "value"),
    Input("gr-late", "value"), Input("gr-cxl", "value"),
]


def _blank_outputs(filter_alerts, note):
    """Full output tuple with blank figures/grids (used for guard early-returns)."""
    blank_fig = GRC._empty(note)
    blanks_fig_grid = [blank_fig, [], []]
    return (
        filter_alerts,
        dmc.Text(note, c="dimmed", size="sm"), None,
        blank_fig, [], [],           # scorecard
        None, [], [], [], [],        # created alert + created grid + chan-created grid
        [], [], [], [],              # perf-stay + chan-stay grids
        blank_fig, blank_fig, [], [],  # donut, bars, chan-detail grid
        *blanks_fig_grid,            # heat-loc
        *blanks_fig_grid,            # heat-chloc
        *blanks_fig_grid,            # movers
        *blanks_fig_grid,            # heat-chlos
    )


@callback(_OUTPUTS, _INPUTS)
def _update(props, mode, y_new, q_new, y_old, q_old,
            o_start, o_end, n_start, n_end, green, red, late_incl, cxl):
    green = float(green if green is not None else 2.0)
    red = float(red if red is not None else -10.0)
    cxl = bool(cxl)
    props = list(props) if props else []
    if not props:
        return _blank_outputs(ui.alert("Bitte mindestens einen Standort wählen.", "warning"),
                              "Keine Standort-Auswahl")

    start_old, end_old, start_new, end_new, tag_new, tag_old = _resolve_period(
        mode, y_new, q_new, y_old, q_old, o_start, o_end, n_start, n_end)
    year_old, year_new = start_old.year, start_new.year

    meta = data.get_metadata()
    plan_dict = data.get_active_plan()
    snap_date = pd.Timestamp(str(meta.get("refreshed_at", ""))[:10] or
                             pd.Timestamp.today().date())

    # One nightly pull covering both windows, extended to full calendar years so the
    # Standort × Monat heatmap shows the whole span (as the source page did).
    pull_start, pull_end = H.union_period((start_old, end_old), (start_new, end_new))
    pull_start = min(pull_start, pd.Timestamp(f"{year_old}-01-01"))
    pull_end = max(pull_end, pd.Timestamp(f"{year_new}-12-31"))
    nightly = data.get_timeslices(start=pull_start, end=None, properties=props)

    # ---- Late-opener detection / removal (mirrors the source ~253-327) --------
    filter_alerts = []
    props_eff = list(props)
    late = H.properties_without_old_data(props, end_old)
    if late:
        lines = " · ".join(
            f"{pc} ({H.city(pc)}, eröffnet {H.opening_date(pc):%d.%m.%Y})" for pc in late)
        if late_incl:
            filter_alerts.append(ui.alert(
                dcc.Markdown(f"{lines}\n\nDiese Standorte sind in {tag_old} noch nicht offen - "
                             "Spalten zeigen 0 €. Schalter 'Späte Öffner einbeziehen' ausschalten "
                             "zum Ausschluss."),
                "warning", title=f"Späte Öffner einbezogen ({tag_old})"))
        else:
            filter_alerts.append(ui.alert(
                dcc.Markdown(f"{lines}\n\nWurden automatisch ausgeschlossen, weil in {tag_old} "
                             "noch nicht offen. Schalter 'Späte Öffner einbeziehen' aktivieren "
                             "um sie trotzdem zu zeigen."),
                "info", title=f"Späte Öffner ausgeschlossen ({tag_old})"))
            props_eff = [p for p in props_eff if p not in late]
            nightly = nightly[~nightly["property_code"].isin(late)]

    if not props_eff:
        filter_alerts.append(ui.alert(
            "Nach Ausschluss der späten Öffner ist die Standort-Auswahl leer. Bitte OLD-Periode "
            "später wählen oder 'Späte Öffner einbeziehen' aktivieren.", "alert"))
        return _blank_outputs(dmc.Stack(filter_alerts, gap="xs"), "Keine Standorte übrig")

    if start_new > snap_date:
        filter_alerts.append(ui.alert(
            f"NEW-Periode ({tag_new}) liegt ganz in der Zukunft des Snapshots "
            f"({snap_date:%d.%m.%Y}). Realisiertes Revenue = 0, nur Forward-Bookings sichtbar.",
            "warning", title="NEW-Periode liegt in der Zukunft"))

    data_start = H.snapshot_data_start(meta)
    if data_start is not None:
        before = [(lbl, s) for lbl, s in ((tag_old, start_old), (tag_new, start_new))
                  if s < data_start]
        if before:
            txt = " · ".join(f"{lbl} beginnt {s:%d.%m.%Y}" for lbl, s in before)
            filter_alerts.append(ui.alert(
                f"{txt} - der Snapshot enthält aber erst Daten ab {data_start:%d.%m.%Y}. Der "
                "Zeitraum davor ist leer, die Vorjahres-Werte sind dadurch unvollständig.",
                "warning", title="Periode reicht vor den verfügbaren Datenbestand zurück"))

    # ---- Recap tables --------------------------------------------------------
    disp_stay, raw_stay = GT.performance_by_stay(
        nightly, props_eff, start_new, end_new, start_old, end_old, year_old, year_new,
        tag_new, tag_old, plan=plan_dict, include_cancellations=cxl,
        green_pct=green, red_pct=red)
    disp_chan_stay, raw_chan_stay = GT.channel_volume_by_stay(
        nightly, start_new, end_new, start_old, end_old, year_old, year_new,
        include_cancellations=cxl, green_pct=green, red_pct=red)
    disp_created, raw_created = GT.performance_by_created(
        nightly, props_eff, start_new, end_new, start_old, end_old, year_old, year_new,
        include_cancellations=cxl, green_pct=green, red_pct=red)
    disp_chan_created, _ = GT.channel_volume_by_created(
        nightly, start_new, end_new, start_old, end_old, year_old, year_new,
        include_cancellations=cxl, green_pct=green, red_pct=red)

    # ---- Executive Summary KPIs ---------------------------------------------
    def _total(raw, col):
        if raw.empty:
            return 0.0
        sub = raw[raw["Standort"] == "Total"]
        return float(sub.iloc[0][col]) if len(sub) else 0.0

    ist_stay = _total(raw_stay, "ist_new")
    plan_stay = _total(raw_stay, "plan_new")
    ly_stay = _total(raw_stay, "ist_old")
    ist_cre = _total(raw_created, "ist_new")
    ly_cre = _total(raw_created, "ist_old")
    plan_missing = (not plan_dict) or plan_stay <= 0

    kpis = ui.kpi_strip([
        ui.kpi_card(f"IST {tag_new} (Stay)", H.fmt_eur(ist_stay), accent=True,
                    tooltip=KPI_GLOBAL_IST_STAY,
                    delta=None if plan_missing else f"{_signed_eur(ist_stay - plan_stay)} vs PLAN",
                    delta_good=None if plan_missing else (ist_stay - plan_stay) >= 0),
        ui.kpi_card(f"PLAN {tag_new}", "—" if plan_missing else H.fmt_eur(plan_stay),
                    tooltip=KPI_GLOBAL_PLAN),
        ui.kpi_card(f"IST {tag_old} (Stay)", H.fmt_eur(ly_stay), tooltip=KPI_GLOBAL_IST_OLD,
                    delta=f"{_signed_eur(ist_stay - ly_stay)} YoY",
                    delta_good=(ist_stay - ly_stay) >= 0),
        ui.kpi_card("Sales-Volumen NEW (Created)", H.fmt_eur(ist_cre), tooltip=KPI_GLOBAL_SALES,
                    delta=f"{_signed_eur(ist_cre - ly_cre)} YoY",
                    delta_good=(ist_cre - ly_cre) >= 0),
    ])

    alerts = GT.auto_alerts(raw_stay, raw_created, year_old, year_new,
                            include_cancellations=cxl, green_pct=green, red_pct=red)
    exec_alerts = (ui.alert_chips([(a["title"], a["message"], a["kind"]) for a in alerts])
                   or ui.alert_chips([("Keine Auffälligkeiten",
                                       "Alle Standorte im erwarteten Rahmen.", "success")]))

    # ---- 2.A best/worst mover alert -----------------------------------------
    if disp_created.empty:
        created_alert = ui.alert("Keine Reservierungen im Erstellungs-Zeitraum.", "info")
    else:
        no_total = raw_created[raw_created["Standort"] != "Total"]
        txts = []
        if len(no_total):
            w = no_total.nsmallest(1, "d_pct")
            b = no_total.nlargest(1, "d_pct")
            if len(w):
                txts.append(f"🔴 **{w.iloc[0]['Standort']}** {w.iloc[0]['d_pct']:+.1f}% YoY")
            if len(b):
                txts.append(f"🟢 **{b.iloc[0]['Standort']}** {b.iloc[0]['d_pct']:+.1f}% YoY")
        created_alert = (ui.alert(dcc.Markdown(" · ".join(txts)), "info",
                                  title="Sales-Bewegungen (nach Erstellung)") if txts else None)

    # ---- Figures -------------------------------------------------------------
    coded = GT.with_code_labels(raw_stay)
    fig_scorecard = GRC.visual_scorecard(coded, year_old, year_new, tag_new, green, red)
    fig_donut = GRC.channel_mix_donuts(raw_chan_stay, year_old, year_new)
    fig_bars = GRC.channel_mix_bars(raw_chan_stay, year_old, year_new)
    heat_suffix = (" (nach Aufenthalt, inkl. Storno+No-Show)" if cxl
                   else " (nach Aufenthalt, realized)")
    fig_heat_loc = GRC.location_revenue_heatmap(
        nightly, pull_start, pull_end, realized_only=not cxl, title_suffix=heat_suffix)
    fig_heat_chloc = GRC.channel_x_location_heatmap(
        nightly, start_new, end_new, realized_only=not cxl)
    fig_movers = GRC.top_movers(coded, year_old, year_new)
    fig_heat_chlos = GRC.channel_los_heatmap_granular(
        nightly, start_old, end_old, start_new, end_new, year_old, year_new,
        realized_only=not cxl)

    # ---- Supporting tables ---------------------------------------------------
    tbl_locrev = CDT.location_revenue_table(nightly, pull_start, pull_end,
                                            realized_only=not cxl)
    tbl_chloc = CDT.channel_x_location_table(nightly, start_new, end_new,
                                             realized_only=not cxl)
    tbl_chlos = CDT.channel_los_granular_table(
        nightly, start_old, end_old, start_new, end_new, year_old, year_new,
        realized_only=not cxl)

    if not raw_stay.empty:
        mv = (raw_stay[raw_stay["Standort"] != "Total"]
              [["Standort", "ist_new", "ist_old", "d_ly_eur", "d_ly_pct"]]
              .sort_values("d_ly_eur").reset_index(drop=True))
        mv["ist_new"] = mv["ist_new"].round(0)
        mv["ist_old"] = mv["ist_old"].round(0)
        mv["d_ly_eur"] = mv["d_ly_eur"].round(0)
        mv["d_ly_pct"] = mv["d_ly_pct"].round(1)
        mv.columns = ["Standort", f"IST {year_new} (€)", f"IST {year_old} (€)",
                      "Δ Revenue (€)", "Δ Revenue (%)"]
    else:
        mv = pd.DataFrame()

    sc_cols, sc_rows = _grid_out(disp_stay)
    cr_cols, cr_rows = _grid_out(disp_created)
    ccr_cols, ccr_rows = _grid_out(disp_chan_created)
    ps_cols, ps_rows = _grid_out(disp_stay)
    cs_cols, cs_rows = _grid_out(disp_chan_stay)
    cd_cols, cd_rows = _grid_out(disp_chan_stay)
    hl_cols, hl_rows = _grid_out(tbl_locrev)
    hc_cols, hc_rows = _grid_out(tbl_chloc)
    mv_cols, mv_rows = _grid_out(mv)
    cl_cols, cl_rows = _grid_out(tbl_chlos)

    return (
        dmc.Stack(filter_alerts, gap="xs") if filter_alerts else None,
        kpis, exec_alerts,
        fig_scorecard, sc_cols, sc_rows,
        created_alert, cr_cols, cr_rows, ccr_cols, ccr_rows,
        ps_cols, ps_rows, cs_cols, cs_rows,
        fig_donut, fig_bars, cd_cols, cd_rows,
        fig_heat_loc, hl_cols, hl_rows,
        fig_heat_chloc, hc_cols, hc_rows,
        fig_movers, mv_cols, mv_rows,
        fig_heat_chlos, cl_cols, cl_rows,
    )
