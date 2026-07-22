# dash_app/pages/standort.py
# Standort-Analyse - single-location deep dive comparing two periods (OLD vs NEW).
# Port of streamlit_app/pages/3_Standort_Analyse.py, sections 1-10 (the corporate/
# code sections 11-13 live on the B2B page). The filter bar is a dmc.Paper on top
# (one property Select, OLD + NEW date pairs, a Storno/No-Show switch); every
# control has a direct effect. One callback renders highlights, opening guards and
# all ten sections. Figures come from components/standort_charts (Plotly), tables
# from backend/chart_data. No live BigQuery: reads the parquet snapshot via
# dash_app.backend.data.

from __future__ import annotations

import dash
import dash_mantine_components as dmc
import numpy as np
import pandas as pd
from dash import Input, Output, callback, dcc, html

from dash_app.backend import chart_data as CDT
from dash_app.backend import data
from dash_app.components import standort_charts as SC
from dash_app.components import ui
from dash_app.components.tooltips import (
    CHART_TOOLTIPS,
    KPI_ADR,
    KPI_ALOS,
    KPI_OCCUPANCY,
    KPI_REVENUE,
)
from revenueblindspots import helpers as H

dash.register_page(__name__, path="/standort", name="Standort", order=3,
                   title="STAYERY · Standort", group="Revenue")

_PERSIST = dict(persistence=True, persistence_type="local")
_KPI_PLAN_INFO = ("IST-Revenue der NEW-Periode vs. PLAN aus dem BigQuery-Snapshot "
                  "(ref_tables.plan). Grau = kein PLAN hinterlegt.")
_INTRO = ("Datenbasis & Filter: alle €-Werte = Staydate-Netto exkl. extra Services. "
          "Badge je Sektion zeigt die Datumsachse: Aufenthalt (KPIs, Channels, LOS, "
          "Wochentag, Inland/Ausland, Länder) vs. Erstellung (Gruppen-Größe). "
          "Storno/No-Show via Schalter in der Filterleiste.")


# ---------------------------------------------------------------------------
# Kleine Formatter / Grid-Helfer.
# ---------------------------------------------------------------------------
def _signed_eur(value: float) -> str:
    return f"{value:+,.0f} €".replace(",", ".")


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


def _f_de(v, dec: int = 2, suffix: str = "") -> str:
    """German-formatted number (thousands '.', decimal ','); NaN -> en dash."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "–"
    return f"{v:,.{dec}f}{suffix}".replace(",", "X").replace(".", ",").replace("X", ".")


# ---------------------------------------------------------------------------
# Layout (callable => property list + defaults re-read on each navigation).
# ---------------------------------------------------------------------------
def layout(**_kwargs):
    meta = data.get_metadata()
    all_props = (meta.get("properties") if meta else None) or H.all_properties()
    prop_data = [{"label": H.city_label(pc) + f" ({pc})", "value": pc} for pc in all_props]
    default_prop = "FRA_SH" if "FRA_SH" in all_props else (all_props[0] if all_props else None)

    today = pd.Timestamp.today().normalize()
    month_start = today.replace(day=1)
    month_end = month_start + pd.offsets.MonthEnd(0)
    ly_start = month_start - pd.DateOffset(years=1)
    ly_end = ly_start + pd.offsets.MonthEnd(0)

    def _iso(ts):
        return pd.Timestamp(ts).date().isoformat()

    header = dmc.Stack([
        dmc.Group([
            dmc.Title("Standort-Analyse", order=3),
            dmc.Badge("Standort Deep Dive · Revenue", color="yellow", variant="light",
                      radius="sm"),
        ], gap="sm", align="center"),
        dmc.Text("Tiefer Vergleich zwischen zwei Perioden für einen Standort - "
                 "Landscape-KPIs, Channel-Mix, LOS, Wochentag, Herkunft und "
                 "Gruppen-Größe.", size="sm", c="dimmed"),
    ], gap=4, mb="xs")

    filter_bar = dmc.Paper(dmc.Stack([
        dmc.Text("Filter", fw=700, size="sm"),
        dmc.Group([
            dmc.Select(id="st-prop", label="Standort", data=prop_data,
                       value=default_prop, allowDeselect=False, searchable=True,
                       leftSection=html.I(className="bi bi-geo-alt"),
                       comboboxProps={"withinPortal": True},
                       style={"minWidth": "260px"}, **_PERSIST),
            dmc.Switch(id="st-cxl", label="Storno + No-Show einbeziehen", checked=False,
                       size="sm", **_PERSIST),
        ], gap="lg", wrap="wrap", align="flex-end"),
        dmc.Text("Vergleichs-Periode (OLD)", fw=600, size="xs", c="dimmed"),
        dmc.Group([
            dmc.DatePickerInput(id="st-old-start", label="Start OLD", value=_iso(ly_start),
                                valueFormat="DD.MM.YYYY", style={"minWidth": "150px"}, **_PERSIST),
            dmc.DatePickerInput(id="st-old-end", label="Ende OLD", value=_iso(ly_end),
                                valueFormat="DD.MM.YYYY", style={"minWidth": "150px"}, **_PERSIST),
        ], gap="md", wrap="wrap", align="flex-end"),
        dmc.Text("Aktuelle Periode (NEW)", fw=600, size="xs", c="dimmed"),
        dmc.Group([
            dmc.DatePickerInput(id="st-new-start", label="Start NEW", value=_iso(month_start),
                                valueFormat="DD.MM.YYYY", style={"minWidth": "150px"}, **_PERSIST),
            dmc.DatePickerInput(id="st-new-end", label="Ende NEW", value=_iso(month_end),
                                valueFormat="DD.MM.YYYY", style={"minWidth": "150px"}, **_PERSIST),
        ], gap="md", wrap="wrap", align="flex-end"),
    ], gap="sm"), p="md", radius="lg", withBorder=True,
        style={"position": "sticky", "top": "8px", "zIndex": 200,
               "backgroundColor": "#FFFFFF", "boxShadow": "0 2px 12px rgba(0,0,0,0.06)"})

    # ---- Body (all sections; hidden by the callback when the guard trips) ----
    sec1 = [
        ui.section_header(1, "Landscape KPIs", basis="stay", info=CHART_TOOLTIPS["kpis"]),
        dmc.Text("Headline-KPIs - folgen dem Storno/No-Show-Schalter (Default: realized, "
                 "d.h. Storno + No-Show ausgeschlossen).", size="sm", c="dimmed"),
        html.Div(id="st-kpis", children=dmc.Skeleton(height=110, radius="lg")),
        html.Div(id="st-kpi-details"),
        ui.chart_card("Landscape-Trend · KPIs monatlich", "st-fig-kpis", height=520),
        ui.table_accordion("Datentabelle", ui.df_grid(pd.DataFrame(), "st-grid-kpis"),
                           value="kpis"),
    ]
    sec2 = [
        ui.section_header(2, "Channel-Mix - monatlich & YoY", basis="stay",
                          info=CHART_TOOLTIPS["channel_mix"]),
        ui.chart_card("Channel-Mix", "st-fig-chmix", height=420),
        ui.table_accordion("Datentabelle", ui.df_grid(pd.DataFrame(), "st-grid-chmix"),
                           value="chmix"),
    ]
    sec3 = [
        ui.section_header(3, "Heatmap Channel × Aufenthaltsdauer", basis="stay",
                          info=CHART_TOOLTIPS["heat_ch_los"]),
        ui.chart_card("Heatmap Channel × LOS", "st-fig-chlos", height=460),
        ui.table_accordion("Datentabelle", ui.df_grid(pd.DataFrame(), "st-grid-chlos"),
                           value="chlos"),
    ]
    sec4 = [
        ui.section_header(4, "Heatmap Channel × Business/Leisure × LOS", basis="stay",
                          info=CHART_TOOLTIPS["heat_ch_purpose_los"]),
        ui.chart_card("Heatmap Channel × Reisezweck × LOS", "st-fig-chpl", height=640),
        ui.table_accordion("Datentabelle", ui.df_grid(pd.DataFrame(), "st-grid-chpl"),
                           value="chpl"),
    ]
    sec5 = [
        ui.section_header(5, "Aufenthaltsdauer (LOS) - Revenue YoY", basis="stay",
                          info=CHART_TOOLTIPS["los_yoy"]),
        ui.chart_card("LOS Revenue YoY", "st-fig-los", height=380),
        ui.table_accordion("Datentabelle", ui.df_grid(pd.DataFrame(), "st-grid-los"),
                           value="los"),
    ]
    sec6 = [
        ui.section_header(6, "Wochentag-Pattern - Stay", basis="stay",
                          info=CHART_TOOLTIPS["weekday_stay"]),
        ui.chart_card("Revenue je Stay-Wochentag", "st-fig-wdstay", height=400),
        ui.table_accordion("Datentabelle", ui.df_grid(pd.DataFrame(), "st-grid-wdstay"),
                           value="wdstay"),
    ]
    sec7 = [
        ui.section_header(7, "Check-in-Pattern - Anreise", basis="stay",
                          info=CHART_TOOLTIPS["weekday_arr"]),
        ui.chart_card("Revenue je Anreise-Wochentag", "st-fig-wdarr", height=400),
        ui.table_accordion("Datentabelle", ui.df_grid(pd.DataFrame(), "st-grid-wdarr"),
                           value="wdarr"),
    ]
    sec8 = [
        ui.section_header(8, "Inland vs. Ausland", basis="stay",
                          info=CHART_TOOLTIPS["de_intl"]),
        ui.chart_card("Inland vs. Ausland", "st-fig-deintl", height=420),
        ui.table_accordion("Datentabelle", ui.df_grid(pd.DataFrame(), "st-grid-deintl"),
                           value="deintl"),
    ]
    sec9 = [
        ui.section_header(9, "Top-Herkunftsländer", basis="stay",
                          info=CHART_TOOLTIPS["top_countries"]),
        ui.chart_card("Top-Herkunftsländer", "st-fig-countries", height=440),
        ui.table_accordion("Datentabelle", ui.df_grid(pd.DataFrame(), "st-grid-countries"),
                           value="countries"),
    ]
    sec10 = [
        ui.section_header(10, "Gruppen-Größe", basis="created",
                          info=CHART_TOOLTIPS["group_size"]),
        dmc.Text("nach Erstellungsdatum · Stay-Date", size="sm", c="dimmed"),
        ui.chart_card("Gruppen-Größe (Zimmer je Buchung)", "st-fig-grp", height=380),
        ui.table_accordion("Datentabelle", ui.df_grid(pd.DataFrame(), "st-grid-grp"),
                           value="grp"),
    ]

    body = html.Div(dmc.Stack(
        [*sec1, *sec2, *sec3, *sec4, *sec5, *sec6, *sec7, *sec8, *sec9, *sec10],
        gap="md"), id="st-body")

    return dmc.Stack([
        header,
        filter_bar,
        html.Div(id="st-context"),
        html.Div(id="st-scope"),
        html.Div(id="st-filter-alerts"),
        dmc.Text(_INTRO, size="xs", c="dimmed"),
        dmc.Title("Highlights", order=4, mt="md"),
        html.Div(id="st-highlights"),
        html.Div(id="st-guard"),
        body,
    ], gap="md")


# ---------------------------------------------------------------------------
# KPI cards + Berechnungs-Details Accordion.
# ---------------------------------------------------------------------------
def _kpi_cards(kpi_old, kpi_new, plan_eur):
    rev_delta = kpi_new["revenue_eur"] - kpi_old["revenue_eur"]
    if plan_eur > 0:
        d_plan_eur = kpi_new["revenue_eur"] - plan_eur
        d_plan_pct = (kpi_new["revenue_eur"] / plan_eur - 1) * 100
        plan_value = f"{d_plan_pct:+.1f} %"
        plan_delta = f"{_signed_eur(d_plan_eur)} vs PLAN"
        plan_good = d_plan_eur >= 0
    else:
        plan_value, plan_delta, plan_good = "—", None, None

    adr_o, adr_n = kpi_old.get("adr_eur"), kpi_new.get("adr_eur")
    adr_delta = (f"{adr_n - adr_o:+.2f} €"
                 if adr_o and not np.isnan(adr_o) and not np.isnan(adr_n) else None)
    alos_o, alos_n = kpi_old["alos_nights"], kpi_new["alos_nights"]
    alos_delta = (f"{alos_n - alos_o:+.2f}"
                  if not (np.isnan(alos_o) or np.isnan(alos_n)) else None)

    return ui.kpi_strip([
        ui.kpi_card("Revenue (€)", H.fmt_eur(kpi_new["revenue_eur"]), accent=True,
                    tooltip=KPI_REVENUE, delta=f"{_signed_eur(rev_delta)} YoY",
                    delta_good=rev_delta >= 0),
        ui.kpi_card("Δ vs PLAN", plan_value, tooltip=_KPI_PLAN_INFO,
                    delta=plan_delta, delta_good=plan_good),
        ui.kpi_card("ADR (€)", H.fmt_eur(adr_n), tooltip=KPI_ADR, delta=adr_delta,
                    delta_good=(adr_delta is not None and adr_n >= adr_o)),
        ui.kpi_card("Occupancy", f"{kpi_new['occupancy_pct']:.1f} %", tooltip=KPI_OCCUPANCY,
                    delta=f"{kpi_new['occupancy_pct'] - kpi_old['occupancy_pct']:+.1f} pp",
                    delta_good=(kpi_new["occupancy_pct"] - kpi_old["occupancy_pct"]) >= 0),
        ui.kpi_card("ALOS", f"{alos_n:.1f} N." if not np.isnan(alos_n) else "–",
                    tooltip=KPI_ALOS, delta=alos_delta,
                    delta_good=(alos_delta is not None and alos_n >= alos_o)),
    ], cols=5)


def _kpi_details(kpi_old, kpi_new, year_old, year_new):
    rows = [
        ("ADR (Variante A · Timeslice)", _f_de(kpi_old["adr_eur"], 2, " €"),
         _f_de(kpi_new["adr_eur"], 2, " €")),
        ("ADR (Variante B · Reservation)", _f_de(kpi_old.get("adr_eur_reservation"), 2, " €"),
         _f_de(kpi_new.get("adr_eur_reservation"), 2, " €")),
        ("ALOS (Variante A · Timeslice)", _f_de(kpi_old.get("alos_nights_timeslice"), 2, " N."),
         _f_de(kpi_new.get("alos_nights_timeslice"), 2, " N.")),
        ("ALOS (Variante B · Reservation)", _f_de(kpi_old["alos_nights"], 2, " N."),
         _f_de(kpi_new["alos_nights"], 2, " N.")),
    ]
    table = dmc.Table([
        html.Thead(html.Tr([html.Th("Kennzahl"), html.Th(str(year_old)),
                            html.Th(str(year_new))])),
        html.Tbody([html.Tr([html.Td(n), html.Td(vo), html.Td(vn)]) for n, vo, vn in rows]),
    ], striped=True, highlightOnHover=True, withTableBorder=True, withColumnBorders=True)
    body = dmc.Stack([
        dcc.Markdown(
            "Beide Werte stammen aus `timeslices.parquet` (eine Zeile = eine genutzte "
            "Nacht). Unterschied ist nur der Aggregations-Modus.\n\n"
            "- **Variante A (Timeslice / window-intern):** nur Nächte im Filter-Fenster "
            "zählen.\n"
            "- **Variante B (Reservation-based):** die ganze Booking-LOS zählt, wenn "
            "≥ 1 Nacht im Fenster ist.\n\n"
            "In den Cards oben: **ADR** = Variante A, **ALOS** = Variante B."),
        table,
        dmc.Text("Zahlen können zu existierenden Dashboards abweichen, wenn dort eine "
                 "andere Variante genutzt wurde.", size="xs", c="dimmed"),
    ], gap="xs")
    return ui.table_accordion(
        "Berechnungs-Details · ADR / ALOS (Timeslice vs Reservation)", body,
        value="kpidetails")


def _kpi_table(kpi_old, kpi_new, year_old, year_new) -> pd.DataFrame:
    return pd.DataFrame({
        "Metrik": ["Revenue (€)", "ADR (€)", "Occupancy (%)", "ALOS (Nächte)", "Buchungen"],
        str(year_old): [
            H.fmt_eur(kpi_old["revenue_eur"]), H.fmt_eur(kpi_old["adr_eur"]),
            f"{kpi_old['occupancy_pct']:.1f}",
            f"{kpi_old['alos_nights']:.1f}" if not np.isnan(kpi_old["alos_nights"]) else "–",
            f"{kpi_old['n_bookings']:,}".replace(",", "."),
        ],
        str(year_new): [
            H.fmt_eur(kpi_new["revenue_eur"]), H.fmt_eur(kpi_new["adr_eur"]),
            f"{kpi_new['occupancy_pct']:.1f}",
            f"{kpi_new['alos_nights']:.1f}" if not np.isnan(kpi_new["alos_nights"]) else "–",
            f"{kpi_new['n_bookings']:,}".replace(",", "."),
        ],
    })


# ---------------------------------------------------------------------------
# Main callback: context, scope, filter alerts, highlights, opening guards + all
# ten sections. Every control has a direct effect (bare @callback).
# ---------------------------------------------------------------------------
_OUTPUTS = [
    Output("st-context", "children"),
    Output("st-scope", "children"),
    Output("st-filter-alerts", "children"),
    Output("st-highlights", "children"),
    Output("st-guard", "children"),
    Output("st-body", "style"),
    Output("st-kpis", "children"),
    Output("st-kpi-details", "children"),
    Output("st-fig-kpis", "figure"),
    Output("st-grid-kpis", "columnDefs"), Output("st-grid-kpis", "rowData"),
    Output("st-fig-chmix", "figure"),
    Output("st-grid-chmix", "columnDefs"), Output("st-grid-chmix", "rowData"),
    Output("st-fig-chlos", "figure"),
    Output("st-grid-chlos", "columnDefs"), Output("st-grid-chlos", "rowData"),
    Output("st-fig-chpl", "figure"),
    Output("st-grid-chpl", "columnDefs"), Output("st-grid-chpl", "rowData"),
    Output("st-fig-los", "figure"),
    Output("st-grid-los", "columnDefs"), Output("st-grid-los", "rowData"),
    Output("st-fig-wdstay", "figure"),
    Output("st-grid-wdstay", "columnDefs"), Output("st-grid-wdstay", "rowData"),
    Output("st-fig-wdarr", "figure"),
    Output("st-grid-wdarr", "columnDefs"), Output("st-grid-wdarr", "rowData"),
    Output("st-fig-deintl", "figure"),
    Output("st-grid-deintl", "columnDefs"), Output("st-grid-deintl", "rowData"),
    Output("st-fig-countries", "figure"),
    Output("st-grid-countries", "columnDefs"), Output("st-grid-countries", "rowData"),
    Output("st-fig-grp", "figure"),
    Output("st-grid-grp", "columnDefs"), Output("st-grid-grp", "rowData"),
]

_INPUTS = [
    Input("st-prop", "value"),
    Input("st-old-start", "value"), Input("st-old-end", "value"),
    Input("st-new-start", "value"), Input("st-new-end", "value"),
    Input("st-cxl", "checked"),
]


def _guard_return(context, scope, filter_alerts, highlights, guard):
    """Full output tuple with body hidden + blank figures/grids (guard early-return)."""
    blank = SC._empty("–")
    out = [context, scope, filter_alerts, highlights, guard, {"display": "none"},
           None, None]
    for _ in range(10):
        out.extend([blank, [], []])
    return tuple(out)


@callback(_OUTPUTS, _INPUTS)
def _update(prop, o_start, o_end, n_start, n_end, cxl):
    if not prop or not all([o_start, o_end, n_start, n_end]):
        return _guard_return(None, None, None, None,
                             ui.alert("Bitte Standort und beide Perioden wählen.", "warning"))

    start_old, end_old = pd.Timestamp(o_start), pd.Timestamp(o_end)
    start_new, end_new = pd.Timestamp(n_start), pd.Timestamp(n_end)
    year_old, year_new = int(start_old.year), int(start_new.year)
    tag_old = f"{start_old:%d.%m.%Y}–{end_old:%d.%m.%Y}"
    tag_new = f"{start_new:%d.%m.%Y}–{end_new:%d.%m.%Y}"
    label = f"{H.city(prop)} ({prop})"
    units = H.units_total(prop)
    realized_only = not bool(cxl)

    meta = data.get_metadata()
    snap_date = pd.Timestamp(str(meta.get("refreshed_at", ""))[:10] or
                             pd.Timestamp.today().date())

    context = dmc.Text(f"{label} · OLD {tag_old} vs NEW {tag_new}", size="sm", fw=600)
    scope = dmc.Text(
        "Scope: alle Buchungen (inkl. Storno + No-Show)" if not realized_only
        else "Scope: realized-only (Storno + No-Show ausgeschlossen)",
        size="xs", c="dimmed")

    # ---- Data load (mirrors streamlit ~170-190) --------------------------------
    nightly = data.get_timeslices(properties=[prop])
    enriched = H.timeslices_are_enriched(nightly)
    if enriched:
        res = H.reservations_from_timeslices(nightly)
    else:
        res = data.get_reservations(properties=[prop])
    if "firm_by_effective_fuzzy" in res.columns:
        res["company"] = res["firm_by_effective_fuzzy"].fillna(res["company"])
        res["has_company"] = res["company"].notna()

    nig_old = H.filter_period(nightly, start_old, end_old, "stay_date")
    nig_new = H.filter_period(nightly, start_new, end_new, "stay_date")
    res_old = H.filter_period(res, start_old, end_old, "created")
    res_new = H.filter_period(res, start_new, end_new, "created")

    # ---- Filter-Warnungen (lookback / enriched) --------------------------------
    filter_alerts = []
    data_start = H.snapshot_data_start(meta)
    if data_start is not None:
        before = [(lbl, s) for lbl, s in (("OLD", start_old), ("NEW", start_new))
                  if s < data_start]
        if before:
            txt = " · ".join(f"{lbl} beginnt {s:%d.%m.%Y}" for lbl, s in before)
            filter_alerts.append(ui.alert(
                f"{txt} - der Snapshot enthält aber erst Daten ab {data_start:%d.%m.%Y}. "
                "Der Zeitraum davor ist leer, die Werte sind dadurch unvollständig.",
                "warning", title="Periode reicht vor den verfügbaren Datenbestand zurück"))
    if not enriched:
        filter_alerts.append(ui.alert(
            "Die Reservation-Sektion (Gruppen-Größe) läuft noch auf der services-"
            "inklusiven Reservations-Basis. Für die konsistente Stay-Date-Sicht nach "
            "Erstellungsdatum einmal Voll-Refresh ziehen (Daten aktualisieren).", "info"))

    # ---- KPIs (needed for highlights + Sektion 1) ------------------------------
    days_old = H.period_days(start_old, end_old)
    days_new = H.period_days(start_new, end_new)
    kpi_old = H.landscape_kpis(nig_old, units, days_old, reservations=res,
                               realized_only=realized_only)
    kpi_new = H.landscape_kpis(nig_new, units, days_new, reservations=res,
                               realized_only=realized_only)

    # ---- Highlights (revenue YoY / occupancy / storno) -------------------------
    hl = []
    if kpi_old["revenue_eur"] > 0:
        pct = (kpi_new["revenue_eur"] / kpi_old["revenue_eur"] - 1) * 100
        if pct < -5:
            hl.append((dcc.Markdown(
                f"**Revenue {pct:+.1f}% YoY** — {H.fmt_eur(kpi_new['revenue_eur'])} ggü. "
                f"{H.fmt_eur(kpi_old['revenue_eur'])} · Δ "
                f"{H.fmt_eur(kpi_new['revenue_eur'] - kpi_old['revenue_eur'])}."), "alert"))
        elif pct > 5:
            hl.append((dcc.Markdown(
                f"**Revenue +{pct:.1f}% YoY** — starker Vergleichszeitraum: "
                f"{H.fmt_eur(kpi_new['revenue_eur'])}."), "success"))
    if kpi_old["occupancy_pct"] > 0:
        shift = kpi_new["occupancy_pct"] - kpi_old["occupancy_pct"]
        if shift < -5:
            hl.append((dcc.Markdown(
                f"**Occupancy {shift:+.1f}pp** — von {kpi_old['occupancy_pct']:.1f}% auf "
                f"{kpi_new['occupancy_pct']:.1f}%."), "warning"))
    c_old = (res_old["is_cancelled"].mean() * 100) if len(res_old) else 0.0
    c_new = (res_new["is_cancelled"].mean() * 100) if len(res_new) else 0.0
    if c_new - c_old > 5:
        hl.append((dcc.Markdown(
            f"**Storno-Quote +{c_new - c_old:.1f}pp** — von {c_old:.1f}% auf "
            f"{c_new:.1f}%."), "warning"))
    highlights = ui.alert_stack(hl) or ui.alert("Keine auffälligen Highlights.", "info")

    # ---- Opening guards (mirrors streamlit ~326-365) ---------------------------
    opening = H.opening_date(prop)
    open_old = H.is_open_in_period(prop, start_old, end_old)
    open_new = H.is_open_in_period(prop, start_new, end_new)
    open_str = f"{opening:%d.%m.%Y}" if opening else "(kein Eröffnungsdatum hinterlegt)"

    fa_children = dmc.Stack(filter_alerts, gap="xs") if filter_alerts else None

    if not open_old and not open_new:
        guard = ui.alert(
            f"{label} wurde erst am {open_str} eröffnet und war in keiner der beiden "
            f"gewählten Perioden offen. Für diesen Zeitraum gibt es noch keine Daten. "
            f"Wähle Perioden nach dem Eröffnungsdatum, dann läuft die Analyse.",
            "warning",
            title=f"{H.city(prop)} war im gewählten Zeitraum noch nicht offen")
        return _guard_return(context, scope, fa_children, highlights, guard)

    if not open_old and open_new:
        filter_alerts.append(ui.alert(
            f"{label} wurde erst am {open_str} eröffnet. Die Vergleichs-Periode "
            f"({tag_old}) liegt davor. Die OLD-Werte sind daher 0 und alle YoY-Vergleiche "
            f"sind für diesen Standort nicht aussagekräftig. Die NEW-Periode ({tag_new}) "
            f"wird normal ausgewertet.", "warning",
            title="Vergleichs-Periode liegt vor der Eröffnung - YoY nicht aussagekräftig"))
    if start_new > snap_date:
        filter_alerts.append(ui.alert(
            f"NEW-Periode ({tag_new}) liegt ganz in der Zukunft des Snapshots "
            f"({snap_date:%d.%m.%Y}). Realisiertes Revenue = 0, nur Forward-Bookings "
            f"sind sichtbar.", "warning", title="NEW-Periode liegt in der Zukunft"))
    fa_children = dmc.Stack(filter_alerts, gap="xs") if filter_alerts else None

    # ---- Sektion 1 · Landscape KPIs --------------------------------------------
    plan_eur = H.plan_revenue(prop, start_new, end_new, plan=data.get_active_plan())
    kpi_cards = _kpi_cards(kpi_old, kpi_new, plan_eur)
    kpi_details = _kpi_details(kpi_old, kpi_new, year_old, year_new)

    monthly_o = H.monthly_landscape(nig_old, units, realized_only=realized_only)
    monthly_n = H.monthly_landscape(nig_new, units, realized_only=realized_only)
    show_trend = (len(monthly_o) >= 1 and len(monthly_n) >= 1
                  and max(len(monthly_o), len(monthly_n)) >= 2)
    if show_trend:
        fig_kpis = SC.landscape_kpis_chart(kpi_old, kpi_new, monthly_o, monthly_n,
                                           year_old, year_new, label)
    else:
        fig_kpis = SC._empty("Trend-Linien ausgeblendet - eine der Perioden hat keine "
                             "oder nur einen Monat Daten.")
    tbl_kpis = _kpi_table(kpi_old, kpi_new, year_old, year_new)

    # ---- Sektionen 2-10 · Figuren + Tabellen -----------------------------------
    fig_chmix = SC.channel_mix(nig_old, nig_new, nightly, year_old, year_new, label,
                               realized_only=realized_only)
    tbl_chmix = CDT.channel_mix_table(nig_old, nig_new, year_old, year_new,
                                      realized_only=realized_only)
    fig_chlos = SC.channel_los_heatmap(nig_old, nig_new, year_old, year_new, label,
                                       realized_only=realized_only)
    tbl_chlos = CDT.channel_los_table(nig_old, nig_new, year_old, year_new,
                                      realized_only=realized_only)
    fig_chpl = SC.channel_purpose_los_heatmap(nig_old, nig_new, year_old, year_new, label,
                                              realized_only=realized_only)
    tbl_chpl = CDT.channel_purpose_los_table(nig_old, nig_new, year_old, year_new,
                                             realized_only=realized_only)
    fig_los = SC.los_yoy(nig_old, nig_new, year_old, year_new, label,
                         realized_only=realized_only)
    tbl_los = CDT.los_yoy_table(nig_old, nig_new, year_old, year_new,
                                realized_only=realized_only)
    fig_wdstay = SC.weekday_pattern(nig_old, nig_new, "stay_weekday", year_old, year_new,
                                    label, "Revenue je Stay-Wochentag",
                                    realized_only=realized_only)
    tbl_wdstay = CDT.weekday_table(nig_old, nig_new, "stay_weekday", year_old, year_new,
                                   realized_only=realized_only)
    fig_wdarr = SC.weekday_pattern(nig_old, nig_new, "check_in_weekday", year_old, year_new,
                                   label, "Revenue je Anreise-Wochentag",
                                   realized_only=realized_only)
    tbl_wdarr = CDT.weekday_table(nig_old, nig_new, "check_in_weekday", year_old, year_new,
                                  realized_only=realized_only)
    fig_deintl = SC.de_vs_international(nig_old, nig_new, year_old, year_new, label,
                                       realized_only=realized_only)
    tbl_deintl = CDT.de_international_table(nig_old, nig_new, year_old, year_new,
                                           realized_only=realized_only)
    fig_countries = SC.top_countries(nig_old, nig_new, year_old, year_new, label,
                                     realized_only=realized_only)
    tbl_countries = CDT.top_countries_table(nig_old, nig_new, year_old, year_new,
                                            realized_only=realized_only)
    fig_grp = SC.group_size_yoy(res_old, res_new, year_old, year_new, label,
                                realized_only=realized_only)
    tbl_grp = CDT.group_size_table(res_old, res_new, year_old, year_new,
                                   realized_only=realized_only)

    out = [context, scope, fa_children, highlights, None, {},
           kpi_cards, kpi_details]
    for fig, tbl in [
        (fig_kpis, tbl_kpis), (fig_chmix, tbl_chmix), (fig_chlos, tbl_chlos),
        (fig_chpl, tbl_chpl), (fig_los, tbl_los), (fig_wdstay, tbl_wdstay),
        (fig_wdarr, tbl_wdarr), (fig_deintl, tbl_deintl), (fig_countries, tbl_countries),
        (fig_grp, tbl_grp),
    ]:
        cols, rows = _grid_out(tbl)
        out.extend([fig, cols, rows])
    return tuple(out)
