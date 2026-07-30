# dash_app/pages/pickup.py
# PAGE - Pickup / Vorlauf-Analyse (Revenue-Gruppe). Stay × Creation Booking-Pace:
# wie viel Umsatz eines Aufenthalts-Zeitraums war zu einem Stichtag schon gebucht,
# YoY auf denselben Vorlauf normiert. Portiert aus
# the Pickup_Analyse view. Alle Aggregation läuft über
# backend/global_tables (GT) + revenueblindspots.helpers (H); die Grafiken bauen
# in components/pickup_charts (PC). Kein BigQuery.

from __future__ import annotations

from types import SimpleNamespace

import dash_ag_grid as dag
import dash_mantine_components as dmc
import pandas as pd
from dash import Input, Output, State, callback, dcc, html, no_update

from dash_app.backend import data as D
from dash_app.backend import exports as XLS
from dash_app.backend import global_tables as GT
from dash_app.components import pickup_charts as PC
from dash_app.components import tooltips as TT
from dash_app.components import ui
from revenueblindspots import helpers as H
from revenueblindspots.helpers import CancelMode

# Storno-Modus-Labels (Select-Optionen) -> CancelMode (via .value als String).
_CMODE_DATA = [
    {"label": "As-of (Stichtag, point-in-time)", "value": CancelMode.AS_OF.value},
    {"label": "All out (realized-only)", "value": CancelMode.ALL_OUT.value},
    {"label": "All in (inkl. Storno/No-Show)", "value": CancelMode.ALL_IN.value},
]
_CMODE_LABEL = {d["value"]: d["label"] for d in _CMODE_DATA}

_CUM_FLOOR = pd.Timestamp("2000-01-01")

# ---- KPI-/Chart-Tooltips (deutsch) ----------------------------------------
_T = {
    "kpi_cum": "Anteil des OTB, der bis zum Ende des Erstellungs-Fensters gebucht "
               "war (ohne untere Grenze). In Klammern: Fenster-Pickup = nur der im "
               "Erstellungs-Fenster erstellte Umsatz ÷ OTB.",
    "kpi_otb_delta": "OTB des Stay-Fensters am Stichtag vs. Vorjahres-Stichtag - "
                     "reine As-of-Logik (No-Shows raus, Storno bis cancel_time), "
                     "unabhängig vom Storno-Modus-Schalter.",
    "kpi_otb": "Zum Stichtag gebuchter Stay-Umsatz (NEW), unabhängig vom "
               "Erstellungs-Fenster.",
    "pace": "Migriert aus dem Global Report - eigene Einstellungen: aktuelles "
            "Kalenderjahr vs. Vorjahr, Stichtag = Snapshot, Storno-Modus immer "
            "As-of. Die Seiten-Filter greifen hier NICHT.",
    "curve": "Kumulierter Pickup-Anteil über die Zeit, NEW vs. OLD. NEW über OLD = "
             "wir buchen früher/stärker vor als im Vorjahr.",
    "bars": "Pickup-Anteil je Standort / Buchungskanal / Stay-Segment (ohne Total), "
            "NEW vs. OLD. Höhere Balken = mehr des Stay-Umsatzes bereits gesichert.",
}

_INTRO_MD = """
**Zwei Datumsachsen kombiniert.** *Stay-Datum* = wann der Gast übernachtet;
*Erstellungs-Datum* = wann gebucht wurde. Diese Seite beantwortet:
**Wie viel Umsatz eines Aufenthalts-Zeitraums war zu einem Stichtag schon
gebucht - und wie schlägt sich das gegen das Vorjahr?**

**Pickup-Anteil - die Kernzahl.**
`Pickup-Anteil = Erstellt-im-Fenster ÷ OTB gesamt`

- *Erstellt-im-Fenster (€)* = Umsatz für Stays im Stay-Fenster, der im gewählten
  **Erstellungs-Fenster** gebucht wurde.
- *OTB gesamt (€)* = gesamter Stay-Umsatz **on-the-books** zum Stichtag, ohne
  Erstellungs-Filter. Beide zum **selben Stichtag** gemessen.

**Fairer Jahresvergleich.** Der Vorjahres-Stichtag ist der aktuelle Stichtag
minus ganze Jahre. Beide Jahre werden so auf **demselben Buchungsvorlauf**
verglichen - egal ob der Monat noch **in der Zukunft** liegt (füllt sich noch)
oder schon **vorbei** ist (im Nachhinein lernen, z.B. im Februar den Januar).

**Storno-Modus.** *All in* = alle Buchungen (inkl. später
storniert / No-Show). *All out* = nur realisierte (finaler Status). *As-of* =
point-in-time zum Stichtag (Storno bis `cancel_time`, No-Show bis Anreise). Für
vergangene Monate sind As-of und All out gleich; für Zukunftsmonate zeigt As-of
den Stand, wie er am Stichtag aussah.

**Creation-Fenster.** *Festes Fenster* = z.B. nur im Juni gebucht (eine konkrete
Vorlauf-Phase). *Alles bis Stichtag* = kompletter Vorlauf ohne untere Grenze.
"""


# ---------------------------------------------------------------------------
# Ableitungen - EINMAL zentral (Semantik exakt wie die Ursprungs-Seite, ~192-277).
# Gibt (ctx, None) oder (None, Fehlermeldung) zurück; ctx ist ein SimpleNamespace
# mit allen abgeleiteten Timestamps/Parametern. Keine Daten werden hier geladen -
# nur Timestamps/Parameter + Standort-Auflösung (Späte-Öffner).
# ---------------------------------------------------------------------------
def _derive(props_value, sn, en, vgl_year, cre_mode, cv, cb, asof_value,
            include_late, cmode_value):
    props = list(props_value) if props_value else []
    if not props:
        return None, "Bitte mindestens einen Standort wählen."
    if sn is None or en is None or asof_value is None:
        return None, "Bitte Stay-Fenster und Stichtag wählen."
    start_new = pd.Timestamp(sn)
    end_new = pd.Timestamp(en)
    if end_new < start_new:
        return None, "Stay-Fenster ist leer: Start liegt nach Ende."

    year_new = int(start_new.year)
    year_old = int(vgl_year)
    year_delta = year_new - year_old
    if year_delta == 0:
        return None, "Vergleichsjahr muss sich vom Stay-Jahr unterscheiden."

    start_old = H.mirror_years(start_new, year_delta)
    end_old = H.mirror_years(end_new, year_delta)
    asof_new = pd.Timestamp(asof_value)
    asof_old = H.mirror_years(asof_new, year_delta)
    cmode = CancelMode(cmode_value)
    cmode_label = _CMODE_LABEL.get(cmode_value, str(cmode_value))

    if cre_mode == "fixed":
        if cv is None or cb is None:
            return None, "Bitte Creation von/bis wählen (Modus Festes Fenster)."
        cre_start_new = pd.Timestamp(cv)
        cre_end_new = pd.Timestamp(cb)
        cre_tag = f"{cre_start_new:%d.%m.%Y}–{cre_end_new:%d.%m.%Y}"
    else:
        # Kein unteres Datum: 3 Jahre vor Stay-Start als praktische Untergrenze.
        cre_start_new = pd.Timestamp(year=year_new - 3, month=1, day=1)
        cre_end_new = asof_new
        cre_tag = f"alles bis {asof_new:%d.%m.%Y}"

    if cre_end_new < cre_start_new:
        return None, "Erstellungs-Fenster ist leer: von liegt nach bis."

    cre_start_old = H.mirror_years(cre_start_new, year_delta)
    cre_end_old = H.mirror_years(cre_end_new, year_delta)
    period_tag_new = f"{start_new:%d.%m.%Y}–{end_new:%d.%m.%Y}"
    period_tag_old = f"{start_old:%d.%m.%Y}–{end_old:%d.%m.%Y}"

    # Proactive: Standorte, die in der OLD-Periode noch nicht offen waren, werden
    # standardmäßig ausgeschlossen (sonst verfälschen 0-€-Zeilen Totale & YoY).
    late_alert = None
    late = H.properties_without_old_data(props, end_old)
    if late:
        lines = "  ·  ".join(
            f"{pc} ({H.city(pc)}, eröffnet {H.opening_date(pc):%d.%m.%Y})" for pc in late
        )
        if include_late:
            late_alert = ui.alert(
                f"{lines} - diese Standorte sind in {period_tag_old} noch nicht "
                f"offen, OLD-Werte zeigen 0 €. Toggle „Späte Öffner einbeziehen“ "
                f"in der Filterleiste zum Ausschluss.",
                kind="warning", title=f"Späte Öffner einbezogen ({period_tag_old})")
        else:
            late_alert = ui.alert(
                f"{lines} - wurden automatisch ausgeschlossen, weil in "
                f"{period_tag_old} noch nicht offen. Toggle „Späte Öffner "
                f"einbeziehen“ in der Filterleiste, um sie trotzdem zu zeigen.",
                kind="info", title=f"Späte Öffner ausgeschlossen ({period_tag_old})")
            props = [p for p in props if p not in late]
            if not props:
                return None, ("Nach Ausschluss der späten Öffner ist die "
                              "Standort-Auswahl leer. Perioden anpassen oder "
                              "„Späte Öffner einbeziehen“ aktivieren.")

    return SimpleNamespace(
        props=props, start_new=start_new, end_new=end_new, start_old=start_old,
        end_old=end_old, cre_start_new=cre_start_new, cre_end_new=cre_end_new,
        cre_start_old=cre_start_old, cre_end_old=cre_end_old, asof_new=asof_new,
        asof_old=asof_old, cmode=cmode, cmode_label=cmode_label, year_new=year_new,
        year_old=year_old, cre_tag=cre_tag, period_tag_new=period_tag_new,
        period_tag_old=period_tag_old, late_alert=late_alert), None


def _load_nightly(ctx) -> pd.DataFrame:
    pull_start = min(ctx.start_old, ctx.start_new, ctx.cre_start_old, ctx.cre_start_new)
    return D.get_timeslices(start=pull_start, end=None, properties=ctx.props)


# ---------------------------------------------------------------------------
# Kleine Formatter / Grid-Helfer.
# ---------------------------------------------------------------------------
def _pct(v: float) -> str:
    return f"{v:.1f} %" if pd.notna(v) else "–"


def _signed_eur_de(v: float) -> str:
    return f"{v:+,.0f} €".replace(",", ".")


def _grid_data(df, *, pin_first: bool = True):
    """(columnDefs, rowData) aus einem Display-DataFrame; leer -> ([], [])."""
    if df is None or getattr(df, "empty", True):
        return [], []
    cols = []
    for i, c in enumerate(df.columns):
        d = {"field": str(c)}
        if i == 0 and pin_first:
            d["pinned"] = "left"
        cols.append(d)
    return cols, df.to_dict("records")


def _make_grid(gid: str, *, height: int | None = None, pin_first: bool = True):
    opts = {"animateRows": True, "enableCellTextSelection": True}
    style = {}
    if height:
        style = {"height": f"{height}px"}
    else:
        opts["domLayout"] = "autoHeight"
    return dag.AgGrid(id=gid, columnDefs=[], rowData=[],
                      columnSize="responsiveSizeToFit",
                      defaultColDef={"sortable": True, "resizable": True},
                      dashGridOptions=opts, style=style)


def _asof_window_otb(df: pd.DataFrame, s_: pd.Timestamp, e_: pd.Timestamp,
                     asof_: pd.Timestamp) -> float:
    """OTB „heute" (am Stichtag) mit REINER As-of-Logik - unabhängig vom
    Storno-Modus-Schalter (No-Shows raus, Storno löst zu cancel_time auf)."""
    sub = H.filter_period(df, s_, e_, "stay_date")
    if "is_no_show" in sub.columns:
        sub = sub[~sub["is_no_show"].astype(bool)]
    if sub.empty:
        return 0.0
    on = H.asof_on_the_books_mask(sub, asof_, include_cancellations=False)
    return float(sub.loc[on, "revenue"].sum())


# ---------------------------------------------------------------------------
# Layout (callable => Property-Liste + Defaults bei jeder Navigation neu).
# ---------------------------------------------------------------------------
def layout(**_kwargs):
    meta = D.get_metadata()
    props_all = meta.get("properties") or H.all_properties()
    snap_raw = str(meta.get("refreshed_at", ""))[:10]
    try:
        snap_date = pd.Timestamp(snap_raw) if snap_raw else pd.Timestamp.today().normalize()
    except (ValueError, TypeError):
        snap_date = pd.Timestamp.today().normalize()

    today = pd.Timestamp.today().normalize()
    stay_first = today.replace(day=1) + pd.offsets.MonthBegin(1)
    stay_last = stay_first + pd.offsets.MonthEnd(0)
    cre_first = stay_first - pd.offsets.MonthBegin(1)
    cre_last = cre_first + pd.offsets.MonthEnd(0)

    def _iso(ts):
        return pd.Timestamp(ts).date().isoformat()

    header = dmc.Group([
        dmc.Title("Pickup / Vorlauf-Analyse", order=3),
        dmc.Badge("Portfolio · Booking-Pace", color="yellow", variant="light", radius="sm"),
    ], gap="sm", align="center", mb="xs")

    intro = dmc.Accordion([
        dmc.AccordionItem([
            dmc.AccordionControl("Was zeigt diese Seite? (kurz erklärt)"),
            dmc.AccordionPanel(dcc.Markdown(_INTRO_MD)),
        ], value="intro"),
    ], variant="contained", radius="md", chevronPosition="left")

    filter_bar = _filter_bar(props_all, {
        "stay_first": _iso(stay_first), "stay_last": _iso(stay_last),
        "cre_first": _iso(cre_first), "cre_last": _iso(cre_last),
        "asof": _iso(snap_date), "vgl_year": int(stay_first.year) - 1,
    })

    curve_axis = dmc.SegmentedControl(
        id="pu-curve-axis", size="xs", radius="md", value="created",
        persistence=True, persistence_type="local",
        data=[{"label": "Erstellungs-Tag", "value": "created"},
              {"label": "Lead-Time", "value": "lead"}])
    bar_cat = dmc.SegmentedControl(
        id="pu-bar-cat", size="xs", radius="md", value="loc",
        persistence=True, persistence_type="local",
        data=[{"label": "Standort", "value": "loc"},
              {"label": "Buchungskanal", "value": "ch"},
              {"label": "Stay-Segment", "value": "seg"}])

    # §1 Headline
    sec1 = [
        ui.section_header(1, "Headline-Kennzahlen", basis="mixed",
                          info="Portfolio-Summe über alle gewählten Standorte."),
        html.Div(id="pu-kpis", children=dmc.Skeleton(height=110, radius="lg")),
    ]

    # §2 Pace by Month
    sec2 = [
        ui.section_header(2, "Pace by Month", basis="stay", info=_T["pace"]),
        html.Div(id="pu-pace-caption"),
        ui.chart_card("Revenue je Übernachtungs-Monat", "pu-pace-fig",
                      info=_T["pace"], height=420),
        html.Div(id="pu-pace-stichtag-title"),
        html.Div(id="pu-pace-stichtag-note"),
        _make_grid("pu-pace-stichtag", height=420),
    ]

    # §3 Buchungskurve
    sec3 = [
        ui.section_header(3, "Buchungskurve", basis="created", info=_T["curve"]),
        ui.chart_card("Kumulierter Pickup-Anteil", "pu-curve-fig", info=_T["curve"],
                      height=360, header_extra=curve_axis),
        html.Div(id="pu-curve-caption"),
    ]

    # §4 Pickup-Balken
    sec4 = [
        ui.section_header(4, "Pickup-Anteil je Kategorie", basis="mixed", info=_T["bars"]),
        ui.chart_card("Pickup-Anteil je Kategorie", "pu-bars-fig", info=_T["bars"],
                      height=360, header_extra=bar_cat),
    ]

    # §5 Tabellen
    sec5 = [
        ui.section_header(5, "Tabellen", basis="mixed", info=TT.CHART_TOOLTIPS["stay_created"]),
        ui.table_accordion("Spalten einfach erklärt (Klartext)",
                           html.Div(id="pu-tables-explainer"), value="explain"),
        dmc.Text("Nach Standort", fw=600, size="sm", mt="xs"),
        _make_grid("pu-grid-loc"),
        dmc.Text("Nach Buchungskanal", fw=600, size="sm", mt="xs"),
        _make_grid("pu-grid-ch"),
        dmc.Text("Nach Stay-Segment (kurz ≤6 / mittel 7-28 / lang 29+)",
                 fw=600, size="sm", mt="xs"),
        _make_grid("pu-grid-seg"),
    ]

    # §6 Pace-to-PLAN
    sec6 = [
        ui.section_header(6, "Pace-to-PLAN · OTB vs. Ziel", basis="stay",
                          info=TT.CHART_TOOLTIPS["pace_plan"]),
        html.Div(id="pu-pace-plan-note"),
        _make_grid("pu-grid-paceplan"),
        ui.chart_card("IST vs PLAN je Standort", "pu-pace-plan-fig",
                      info=TT.CHART_TOOLTIPS["pace_plan"], height=None),
    ]

    # §7 Downloads
    sec7 = [
        ui.section_header(7, "Downloads",
                          info="Drei getrennte Exporte - genau für diese Sicht."),
        dmc.Text("Pickup-Tabellen (Excel) = die drei aggregierten Tabellen, rohe "
                 "Zahlen. Roh-Timeslices (Excel) = eine Zeile je Nacht mit allen "
                 "Flags. Buchungskurve (CSV) = je Erstellungs-Tag Umsatz + "
                 "kumulierter Pickup-Anteil, beide Jahre.", size="sm", c="dimmed"),
        dmc.Group([
            dmc.Button("Pickup-Tabellen (Excel)", id="pu-dl-tables", variant="light",
                       leftSection=html.I(className="bi bi-file-earmark-excel")),
            dmc.Button("Roh-Timeslices (Excel)", id="pu-dl-raw", variant="light",
                       leftSection=html.I(className="bi bi-file-earmark-excel")),
            dmc.Button("Buchungskurve (CSV)", id="pu-dl-curve", variant="light",
                       leftSection=html.I(className="bi bi-filetype-csv")),
        ], gap="md", wrap="wrap"),
        dcc.Download(id="pu-dl-tables-dl"),
        dcc.Download(id="pu-dl-raw-dl"),
        dcc.Download(id="pu-dl-curve-dl"),
    ]

    tabs = ui.section_tabs("pu-sectiontabs", [
        ("pace", "Pace by Month", dmc.Stack(sec2, gap="md"), "bi bi-calendar-month"),
        ("kennzahlen", "Kennzahlen & Kurve", dmc.Stack([*sec1, *sec3], gap="md"),
         "bi bi-speedometer2"),
        ("kategorie", "Kategorie & Tabellen", dmc.Stack([*sec4, *sec5, *sec6], gap="md"),
         "bi bi-table"),
        ("downloads", "Downloads", dmc.Stack(sec7, gap="md"), "bi bi-download"),
    ])

    return dmc.Stack([
        header,
        intro,
        filter_bar,
        html.Div(id="pu-context"),
        html.Div(id="pu-late-alert"),
        tabs,
    ], gap="md")


def _filter_bar(props_all, defaults):
    props_opts = [{"label": f"{H.city(p)} ({p})", "value": p} for p in props_all]
    _pers = dict(persistence=True, persistence_type="local")
    primary = [
        ui.location_select("pu-props", props_all, data=props_opts),
        dmc.DatePickerInput(id="pu-sn", label="Stay-Start", value=defaults["stay_first"],
                            valueFormat="DD.MM.YYYY", style={"minWidth": "150px"}, **_pers),
        dmc.DatePickerInput(id="pu-en", label="Stay-Ende", value=defaults["stay_last"],
                            valueFormat="DD.MM.YYYY", style={"minWidth": "150px"}, **_pers),
        dmc.NumberInput(id="pu-vgl-year", label="Vergleichsjahr (OLD)",
                        value=defaults["vgl_year"], min=2018, max=2035, step=1,
                        style={"width": "150px"}, **_pers),
        dmc.DatePickerInput(id="pu-asof", label="Stichtag (As-of)", value=defaults["asof"],
                            valueFormat="DD.MM.YYYY", style={"minWidth": "150px"}, **_pers),
    ]
    advanced = ui.advanced_popover("pu", [
        dmc.Text("Erstellungs-Fenster · Creation von/bis gelten nur im Modus "
                 "Festes Fenster", fw=600, size="xs", c="dimmed"),
        dmc.SegmentedControl(
            id="pu-cre-mode", size="sm", radius="md", value="fixed",
            data=[{"label": "Festes Fenster (von–bis)", "value": "fixed"},
                  {"label": "Alles bis Stichtag", "value": "until"}], **_pers),
        dmc.DatePickerInput(id="pu-cv", label="Creation von", value=defaults["cre_first"],
                            valueFormat="DD.MM.YYYY", style={"minWidth": "150px"}, **_pers),
        dmc.DatePickerInput(id="pu-cb", label="Creation bis", value=defaults["cre_last"],
                            valueFormat="DD.MM.YYYY", style={"minWidth": "150px"}, **_pers),
        dmc.Select(id="pu-cmode", label="Storno-Modus", data=_CMODE_DATA,
                   value=CancelMode.AS_OF.value, style={"minWidth": "260px"}, **_pers),
        dmc.Switch(id="pu-late", label="Späte Öffner einbeziehen", checked=False, **_pers),
    ])
    return ui.filter_shell(primary=primary, advanced=advanced)


# Gemeinsame Filter-Inputs/States (Reihenfolge == _derive-Signatur).
_FILTER_INPUTS = (
    Input("pu-props", "value"), Input("pu-sn", "value"), Input("pu-en", "value"),
    Input("pu-vgl-year", "value"), Input("pu-cre-mode", "value"),
    Input("pu-cv", "value"), Input("pu-cb", "value"), Input("pu-asof", "value"),
    Input("pu-late", "checked"), Input("pu-cmode", "value"),
)
_FILTER_STATES = (
    State("pu-props", "value"), State("pu-sn", "value"), State("pu-en", "value"),
    State("pu-vgl-year", "value"), State("pu-cre-mode", "value"),
    State("pu-cv", "value"), State("pu-cb", "value"), State("pu-asof", "value"),
    State("pu-late", "checked"), State("pu-cmode", "value"),
)


# ===========================================================================
# Haupt-Callback: Kontext, KPIs, 3 Tabellen, Klartext-Explainer, Pace-to-PLAN.
# ===========================================================================
@callback(
    Output("pu-context", "children"),
    Output("pu-late-alert", "children"),
    Output("pu-kpis", "children"),
    Output("pu-grid-loc", "columnDefs"), Output("pu-grid-loc", "rowData"),
    Output("pu-grid-ch", "columnDefs"), Output("pu-grid-ch", "rowData"),
    Output("pu-grid-seg", "columnDefs"), Output("pu-grid-seg", "rowData"),
    Output("pu-tables-explainer", "children"),
    Output("pu-pace-plan-fig", "figure"),
    Output("pu-grid-paceplan", "columnDefs"), Output("pu-grid-paceplan", "rowData"),
    Output("pu-pace-plan-note", "children"),
    *_FILTER_INPUTS,
)
def _render_main(props, sn, en, vgl_year, cre_mode, cv, cb, asof, late, cmode):
    blank_fig = PC.empty_fig("–")
    ctx, err = _derive(props, sn, en, vgl_year, cre_mode, cv, cb, asof, late, cmode)
    if err:
        return (ui.alert(err, kind="warning"), None, None,
                [], [], [], [], [], [], None, blank_fig, [], [], None)

    nightly = _load_nightly(ctx)
    if nightly is None or nightly.empty:
        return (ui.alert("Keine Timeslices im gewählten Bereich.", kind="info"),
                ctx.late_alert, None, [], [], [], [], [], [], None, blank_fig, [], [], None)

    common = dict(cancel_mode=ctx.cmode, pickup=True)
    disp_loc, raw_loc = GT.performance_by_stay_created(
        nightly, ctx.props, ctx.start_new, ctx.end_new, ctx.start_old, ctx.end_old,
        ctx.cre_start_new, ctx.cre_end_new, ctx.cre_start_old, ctx.cre_end_old,
        ctx.asof_new, ctx.asof_old, ctx.year_old, ctx.year_new, **common)
    disp_ch, raw_ch = GT.channel_volume_by_stay_created(
        nightly, ctx.start_new, ctx.end_new, ctx.start_old, ctx.end_old,
        ctx.cre_start_new, ctx.cre_end_new, ctx.cre_start_old, ctx.cre_end_old,
        ctx.asof_new, ctx.asof_old, ctx.year_old, ctx.year_new, **common)
    disp_seg, raw_seg = GT.segment_volume_by_stay_created(
        nightly, ctx.start_new, ctx.end_new, ctx.start_old, ctx.end_old,
        ctx.cre_start_new, ctx.cre_end_new, ctx.cre_start_old, ctx.cre_end_old,
        ctx.asof_new, ctx.asof_old, ctx.year_old, ctx.year_new, **common)

    if raw_loc.empty:
        note = ui.alert("Keine Buchungen mit Aufenthalt im Stay-Fenster im gewählten "
                        "Erstellungs-Fenster / Storno-Modus.", kind="info")
        return (None, ctx.late_alert, note, [], [], [], [], [], [], None,
                blank_fig, [], [], None)

    # ---- KPIs (~318-405) --------------------------------------------------
    tot = raw_loc[raw_loc["property_code"] == "TOTAL"].iloc[0]
    otb_new, otb_old = float(tot["stay_new"]), float(tot["stay_old"])
    erst_new, erst_old = float(tot["ist_new"]), float(tot["ist_old"])
    pu_new = (erst_new / otb_new * 100.0) if otb_new > 0 else float("nan")
    pu_old = (erst_old / otb_old * 100.0) if otb_old > 0 else float("nan")

    cum_new = float(GT.stay_created_scope(
        nightly, ctx.start_new, ctx.end_new, _CUM_FLOOR, ctx.cre_end_new, ctx.asof_new,
        cancel_mode=ctx.cmode)["revenue"].sum())
    cum_old = float(GT.stay_created_scope(
        nightly, ctx.start_old, ctx.end_old, _CUM_FLOOR, ctx.cre_end_old, ctx.asof_old,
        cancel_mode=ctx.cmode)["revenue"].sum())
    pu_cum_new = (cum_new / otb_new * 100.0) if otb_new > 0 else float("nan")
    pu_cum_old = (cum_old / otb_old * 100.0) if otb_old > 0 else float("nan")

    aotb_new = _asof_window_otb(nightly, ctx.start_new, ctx.end_new, ctx.asof_new)
    aotb_old = _asof_window_otb(nightly, ctx.start_old, ctx.end_old, ctx.asof_old)
    aotb_delta_abs = aotb_new - aotb_old
    aotb_delta_pct = (aotb_new / aotb_old - 1) * 100.0 if aotb_old > 0 else float("nan")

    kpis = ui.kpi_strip([
        ui.kpi_card(f"Pickup kumuliert {ctx.year_new}", _pct(pu_cum_new),
                    delta=f"im Fenster: {_pct(pu_new)}", delta_good=None, accent=True,
                    tooltip=_T["kpi_cum"]),
        ui.kpi_card(f"Pickup kumuliert {ctx.year_old}", _pct(pu_cum_old),
                    delta=f"im Fenster: {_pct(pu_old)}", delta_good=None,
                    tooltip=_T["kpi_cum"]),
        ui.kpi_card(f"OTB Δ heute vs {ctx.year_old}",
                    f"{aotb_delta_pct:+.1f} %" if pd.notna(aotb_delta_pct) else "–",
                    delta=_signed_eur_de(aotb_delta_abs),
                    delta_good=(aotb_delta_abs >= 0), tooltip=_T["kpi_otb_delta"]),
        ui.kpi_card(f"OTB gesamt {ctx.year_new}", H.fmt_eur(otb_new), tooltip=_T["kpi_otb"]),
    ])

    loc_cols, loc_rows = _grid_data(disp_loc)
    ch_cols, ch_rows = _grid_data(disp_ch)
    seg_cols, seg_rows = _grid_data(disp_seg)
    explainer = dcc.Markdown(_explainer_md(ctx.year_new, ctx.year_old))

    # ---- Pace-to-PLAN (§6) -----------------------------------------------
    pp_fig, pp_cols, pp_rows, pp_note = _pace_to_plan(ctx, raw_loc)

    return (None, ctx.late_alert, kpis,
            loc_cols, loc_rows, ch_cols, ch_rows, seg_cols, seg_rows,
            explainer, pp_fig, pp_cols, pp_rows, pp_note)


def _pace_to_plan(ctx, raw_loc: pd.DataFrame):
    plan_dict = D.get_active_plan()
    if not plan_dict:
        msg = "Kein PLAN-Snapshot geladen - Pace-to-PLAN nicht verfügbar."
        return PC.empty_fig(msg), [], [], ui.alert(msg, kind="info")
    src = raw_loc[raw_loc["property_code"] != "TOTAL"][
        ["Standort", "property_code", "stay_new"]].copy()
    src["ist_new"] = src["stay_new"]
    src["plan_new"] = [H.plan_revenue(pc, ctx.start_new, ctx.end_new, plan=plan_dict)
                       for pc in src["property_code"]]
    pace_df = PC.build_pace_table(src, ctx.start_new, ctx.end_new, today=ctx.asof_new)
    if pace_df.empty:
        msg = "Keine Pace-Daten (kein PLAN für dieses Stay-Fenster)."
        return PC.empty_fig(msg), [], [], ui.alert(msg, kind="info")
    disp = pace_df.copy()
    for c in ("IST (€)", "PLAN (€)"):
        disp[c] = disp[c].map(H.fmt_eur)
    for c in ("IST / PLAN (%)", "Fortschritt Zeit (%)"):
        disp[c] = disp[c].map(lambda v: f"{v:.1f}" if pd.notna(v) else "-")
    cols, rows = _grid_data(disp)
    return PC.pace_to_plan_fig(pace_df, ctx.year_new, ctx.period_tag_new), cols, rows, None


# ===========================================================================
# §2 Pace by Month - eigene Einstellungen (aktuelles Jahr vs. Vorjahr, Stichtag
# = Snapshot, immer As-of). Standort-Basis = Filterleiste (inkl. Späte-Öffner).
# ===========================================================================
@callback(
    Output("pu-pace-fig", "figure"),
    Output("pu-pace-caption", "children"),
    Output("pu-pace-stichtag-title", "children"),
    Output("pu-pace-stichtag-note", "children"),
    Output("pu-pace-stichtag", "columnDefs"),
    Output("pu-pace-stichtag", "rowData"),
    *_FILTER_INPUTS,
)
def _render_pace(props, sn, en, vgl_year, cre_mode, cv, cb, asof, late, cmode):
    ctx, err = _derive(props, sn, en, vgl_year, cre_mode, cv, cb, asof, late, cmode)
    if err:
        return PC.empty_fig(err, height=420), None, None, None, [], []

    meta = D.get_metadata()
    snap_raw = str(meta.get("refreshed_at", ""))[:10]
    try:
        snap_date = pd.Timestamp(snap_raw) if snap_raw else pd.Timestamp.today().normalize()
    except (ValueError, TypeError):
        snap_date = pd.Timestamp.today().normalize()
    pace_year = int(pd.Timestamp.today().year)
    pace_snap = snap_date.normalize()
    pace_snap_old = H.mirror_years(pace_snap, 1)

    pace_nig = D.get_timeslices(
        start=pd.Timestamp(year=pace_year - 1, month=1, day=1), end=None,
        properties=ctx.props)
    pdf = H.pace_by_month(pace_nig, pace_year - 1, pace_year, pace_snap,
                          properties=list(ctx.props))
    fig = PC.pace_fig(pdf, pace_year)

    caption = dmc.Stack([
        dmc.Text(
            f"Eigene Einstellungen: {pace_year} vs {pace_year - 1} · Stichtag = "
            f"Snapshot ({pace_snap:%d.%m.%Y}, Vorjahr tagesgenau gespiegelt: "
            f"{pace_snap_old:%d.%m.%Y}) · Standorte = Filterleiste. Storno-Modus "
            "ist hier immer As-of - der Schalter der Seite greift nicht.",
            size="xs", c="dimmed"),
        dmc.Text(
            f"🟡 {pace_year - 1}/EoM = finale Vorjahres-Realität (realized) · "
            f"⚪ {pace_year - 1}/Stichtag = on-the-books am {pace_snap_old:%d.%m.%Y} · "
            f"🔵 {pace_year}/Stichtag = on-the-books am {pace_snap:%d.%m.%Y}. "
            "Grau vs. Blau = besser/schlechter als zum gleichen Zeitpunkt im "
            "Vorjahr · Grau vs. Gelb = was im Vorjahr nach dem Stichtag noch reinkam.",
            size="xs", c="dimmed"),
    ], gap=2)

    cur_month = int(pd.Timestamp.today().month)
    title = dmc.Text(
        f"Stichtagsblick {PC.MONTH_NAMES_DE[cur_month - 1]} {pace_year} - jede "
        "Zeile = ein As-of-Stichtag (Tagesende): Stand des kompletten Stay-Monats "
        "an diesem Tag, Vorjahr tagesgenau gespiegelt.", fw=600, size="sm", mt="xs")

    daily = PC.pace_stichtag_table(pace_year, cur_month, pace_snap,
                                   list(ctx.props), pace_nig)
    if daily is None or daily.empty:
        note = ui.alert(
            f"Der Snapshot ({pace_snap:%d.%m.%Y}) liegt vor dem Beginn des aktuellen "
            "Monats - Stichtage erscheinen nach dem nächsten Daten-Refresh.", kind="info")
        return fig, caption, title, note, [], []

    disp = _format_stichtag(daily, pace_year)
    cols, rows = _grid_data(disp, pin_first=True)
    return fig, caption, title, None, cols, rows


def _format_stichtag(daily: pd.DataFrame, year: int) -> pd.DataFrame:
    d = daily.copy()
    for c in (f"OTB {year - 1} (€)", f"OTB {year} (€)", "Δ (€)", f"IST {year - 1} final (€)"):
        d[c] = d[c].map(H.fmt_eur)
    d["Δ (%)"] = d["Δ (%)"].map(lambda v: f"{v:+.1f} %" if pd.notna(v) else "–")
    return d


# ===========================================================================
# §3 Buchungskurve - X-Achse Erstellungs-Tag oder Lead-Time.
# ===========================================================================
@callback(
    Output("pu-curve-fig", "figure"),
    Output("pu-curve-caption", "children"),
    Input("pu-curve-axis", "value"),
    *_FILTER_INPUTS,
)
def _render_curve(axis, props, sn, en, vgl_year, cre_mode, cv, cb, asof, late, cmode):
    ctx, err = _derive(props, sn, en, vgl_year, cre_mode, cv, cb, asof, late, cmode)
    if err:
        return PC.empty_fig(err, height=360), None
    nightly = _load_nightly(ctx)
    if nightly is None or nightly.empty:
        return PC.empty_fig("Keine Timeslices im gewählten Bereich.", height=360), None

    otb_new = float(GT.stay_only_scope(
        nightly, ctx.start_new, ctx.end_new, ctx.asof_new, cancel_mode=ctx.cmode)["revenue"].sum())
    otb_old = float(GT.stay_only_scope(
        nightly, ctx.start_old, ctx.end_old, ctx.asof_old, cancel_mode=ctx.cmode)["revenue"].sum())

    if axis == "lead":
        caption = dmc.Text(
            "Anteil des Stay-OTB, der mindestens so viele Tage vor Anreise gebucht "
            "war (Lead-Time). NEW über OLD = wir buchen weiter im Voraus. Über Monate "
            "hinweg vergleichbar, weil an der Anreise statt am Kalendertag ausgerichtet.",
            size="xs", c="dimmed")
        scope_new = GT.stay_only_scope(nightly, ctx.start_new, ctx.end_new, ctx.asof_new,
                                       cancel_mode=ctx.cmode)
        scope_old = GT.stay_only_scope(nightly, ctx.start_old, ctx.end_old, ctx.asof_old,
                                       cancel_mode=ctx.cmode)
        lead = GT.pickup_leadtime_curve(scope_new, scope_old, otb_new, otb_old,
                                        ctx.year_new, ctx.year_old)
        if lead.dropna(how="all").empty:
            return PC.empty_fig("Keine Lead-Time-Daten im gewählten Fenster.", height=360), caption
        fig = PC.booking_curve_fig(lead, ctx.year_new, ctx.year_old,
                                   "Tage vor Anreise", "kum. Anteil des OTB (%)")
        return fig, caption

    caption = dmc.Text(
        "Jeder Punkt = kumulierter Anteil des Stay-OTB, der bis zu diesem "
        "Erstellungs-Tag gebucht war. Liegt die NEW-Linie über OLD, buchen wir "
        "früher/stärker vor als im Vorjahr; darunter = wir hinken hinterher. Am "
        "aussagekräftigsten im Modus Festes Fenster.", size="xs", c="dimmed")
    scope_new = GT.stay_created_scope(nightly, ctx.start_new, ctx.end_new,
                                      ctx.cre_start_new, ctx.cre_end_new, ctx.asof_new,
                                      cancel_mode=ctx.cmode)
    scope_old = GT.stay_created_scope(nightly, ctx.start_old, ctx.end_old,
                                      ctx.cre_start_old, ctx.cre_end_old, ctx.asof_old,
                                      cancel_mode=ctx.cmode)
    line_df = GT.daily_created_line_data(scope_new, scope_old,
                                         ctx.cre_start_new, ctx.cre_start_old)
    curve = GT.pickup_pace_curve(line_df, otb_new, otb_old, ctx.year_new, ctx.year_old)
    if curve.empty:
        return PC.empty_fig("Keine Tages-Daten für die Buchungskurve.", height=360), caption
    fig = PC.booking_curve_fig(curve, ctx.year_new, ctx.year_old,
                               "Erstellungs-Tag", "Kumulierter Pickup-Anteil (%)")
    return fig, caption


# ===========================================================================
# §4 Pickup-Balken - Standort / Buchungskanal / Stay-Segment.
# ===========================================================================
@callback(
    Output("pu-bars-fig", "figure"),
    Input("pu-bar-cat", "value"),
    *_FILTER_INPUTS,
)
def _render_bars(cat, props, sn, en, vgl_year, cre_mode, cv, cb, asof, late, cmode):
    ctx, err = _derive(props, sn, en, vgl_year, cre_mode, cv, cb, asof, late, cmode)
    if err:
        return PC.empty_fig(err, height=360)
    nightly = _load_nightly(ctx)
    if nightly is None or nightly.empty:
        return PC.empty_fig("Keine Timeslices im gewählten Bereich.", height=360)

    common = dict(cancel_mode=ctx.cmode, pickup=True)
    if cat == "ch":
        _, raw = GT.channel_volume_by_stay_created(
            nightly, ctx.start_new, ctx.end_new, ctx.start_old, ctx.end_old,
            ctx.cre_start_new, ctx.cre_end_new, ctx.cre_start_old, ctx.cre_end_old,
            ctx.asof_new, ctx.asof_old, ctx.year_old, ctx.year_new, **common)
        bars = GT.pickup_bars_data(raw, "Channel", "rev_new", "rev_old",
                                   ctx.year_new, ctx.year_old)
    elif cat == "seg":
        _, raw = GT.segment_volume_by_stay_created(
            nightly, ctx.start_new, ctx.end_new, ctx.start_old, ctx.end_old,
            ctx.cre_start_new, ctx.cre_end_new, ctx.cre_start_old, ctx.cre_end_old,
            ctx.asof_new, ctx.asof_old, ctx.year_old, ctx.year_new, **common)
        bars = GT.pickup_bars_data(raw, "Segment", "rev_new", "rev_old",
                                   ctx.year_new, ctx.year_old)
    else:
        _, raw = GT.performance_by_stay_created(
            nightly, ctx.props, ctx.start_new, ctx.end_new, ctx.start_old, ctx.end_old,
            ctx.cre_start_new, ctx.cre_end_new, ctx.cre_start_old, ctx.cre_end_old,
            ctx.asof_new, ctx.asof_old, ctx.year_old, ctx.year_new, **common)
        bars = GT.pickup_bars_data(raw, "Standort", "ist_new", "ist_old",
                                   ctx.year_new, ctx.year_old)
    return PC.pickup_bars_fig(bars, ctx.year_new, ctx.year_old, "Pickup-Anteil (%)")


# ===========================================================================
# §7 Downloads - 3 getrennte Exporte (pure Frame-Builder + dcc.send_*).
# ===========================================================================
def _numeric_pickup_frame(raw: pd.DataFrame, label_col: str, rev_new_col: str,
                          rev_old_col: str, year_new: int, year_old: int) -> pd.DataFrame:
    """Pickup-Tabelle mit ROHEN Zahlen für den Excel-Export (sortier-/rechenbar)."""
    if raw is None or raw.empty:
        return pd.DataFrame()
    d = raw.copy()
    out = pd.DataFrame({
        label_col: d[label_col],
        f"Erstellt {year_new} (EUR)": d[rev_new_col].astype(float).round(2),
        f"Erstellt {year_old} (EUR)": d[rev_old_col].astype(float).round(2),
        "Delta absolut (EUR)": d["d_eur"].astype(float).round(2),
        "Delta relativ (%)": d["d_pct"].astype(float).round(1),
        f"OTB {year_new} (EUR)": d["stay_new"].astype(float).round(2),
        f"OTB {year_old} (EUR)": d["stay_old"].astype(float).round(2),
    })
    pu_new = GT._pickup_pct(d[rev_new_col], d["stay_new"])
    pu_old = GT._pickup_pct(d[rev_old_col], d["stay_old"])
    out[f"Pickup-Anteil {year_new} (%)"] = pu_new.astype(float).round(1).to_numpy()
    out[f"Pickup-Anteil {year_old} (%)"] = pu_old.astype(float).round(1).to_numpy()
    out["Delta Pickup (pp)"] = (pu_new - pu_old).astype(float).round(1).to_numpy()
    if "d_share_pp" in d.columns:
        out["Delta Anteil (pp)"] = d["d_share_pp"].astype(float).round(2)
    return out


def _curve_csv(line_df: pd.DataFrame, otb_new: float, otb_old: float,
               year_new: int, year_old: int) -> str:
    if line_df is None or line_df.empty:
        return "keine Daten"
    out = line_df.copy()
    out["cum_rev_new"] = out["rev_new"].cumsum()
    out["cum_rev_old"] = out["rev_old"].cumsum()
    out[f"pickup_pct_{year_new}"] = out["cum_rev_new"] / otb_new * 100.0 if otb_new else 0.0
    out[f"pickup_pct_{year_old}"] = out["cum_rev_old"] / otb_old * 100.0 if otb_old else 0.0
    return out.to_csv(index=False)


def _fname(ctx) -> str:
    return f"pickup_{ctx.start_new:%Y%m%d}_vs_{ctx.start_old:%Y%m%d}"


@callback(Output("pu-dl-tables-dl", "data"), Input("pu-dl-tables", "n_clicks"),
          *_FILTER_STATES, prevent_initial_call=True)
def _dl_tables(_n, props, sn, en, vgl_year, cre_mode, cv, cb, asof, late, cmode):
    ctx, err = _derive(props, sn, en, vgl_year, cre_mode, cv, cb, asof, late, cmode)
    if err:
        return no_update
    nightly = _load_nightly(ctx)
    if nightly is None or nightly.empty:
        return no_update
    common = dict(cancel_mode=ctx.cmode, pickup=True)
    _, raw_loc = GT.performance_by_stay_created(
        nightly, ctx.props, ctx.start_new, ctx.end_new, ctx.start_old, ctx.end_old,
        ctx.cre_start_new, ctx.cre_end_new, ctx.cre_start_old, ctx.cre_end_old,
        ctx.asof_new, ctx.asof_old, ctx.year_old, ctx.year_new, **common)
    _, raw_ch = GT.channel_volume_by_stay_created(
        nightly, ctx.start_new, ctx.end_new, ctx.start_old, ctx.end_old,
        ctx.cre_start_new, ctx.cre_end_new, ctx.cre_start_old, ctx.cre_end_old,
        ctx.asof_new, ctx.asof_old, ctx.year_old, ctx.year_new, **common)
    _, raw_seg = GT.segment_volume_by_stay_created(
        nightly, ctx.start_new, ctx.end_new, ctx.start_old, ctx.end_old,
        ctx.cre_start_new, ctx.cre_end_new, ctx.cre_start_old, ctx.cre_end_old,
        ctx.asof_new, ctx.asof_old, ctx.year_old, ctx.year_new, **common)
    sheets = {
        "Standort": _numeric_pickup_frame(raw_loc, "Standort", "ist_new", "ist_old",
                                          ctx.year_new, ctx.year_old),
        "Buchungskanal": _numeric_pickup_frame(raw_ch, "Channel", "rev_new", "rev_old",
                                               ctx.year_new, ctx.year_old),
        "Stay-Segment": _numeric_pickup_frame(raw_seg, "Segment", "rev_new", "rev_old",
                                              ctx.year_new, ctx.year_old),
    }
    return dcc.send_bytes(lambda buf: XLS.write_workbook(buf, sheets),
                          f"{_fname(ctx)}_tabellen.xlsx")


@callback(Output("pu-dl-raw-dl", "data"), Input("pu-dl-raw", "n_clicks"),
          *_FILTER_STATES, prevent_initial_call=True)
def _dl_raw(_n, props, sn, en, vgl_year, cre_mode, cv, cb, asof, late, cmode):
    ctx, err = _derive(props, sn, en, vgl_year, cre_mode, cv, cb, asof, late, cmode)
    if err:
        return no_update
    nightly = _load_nightly(ctx)
    if nightly is None or nightly.empty:
        return no_update
    frames = GT.stay_created_export_frames(
        nightly, ctx.props, ctx.start_new, ctx.end_new, ctx.start_old, ctx.end_old,
        ctx.cre_start_new, ctx.cre_end_new, ctx.cre_start_old, ctx.cre_end_old,
        ctx.asof_new, ctx.asof_old, ctx.cmode == CancelMode.ALL_IN)
    return dcc.send_bytes(lambda buf: XLS.write_workbook(buf, frames),
                          f"{_fname(ctx)}_timeslices.xlsx")


@callback(Output("pu-dl-curve-dl", "data"), Input("pu-dl-curve", "n_clicks"),
          *_FILTER_STATES, prevent_initial_call=True)
def _dl_curve(_n, props, sn, en, vgl_year, cre_mode, cv, cb, asof, late, cmode):
    ctx, err = _derive(props, sn, en, vgl_year, cre_mode, cv, cb, asof, late, cmode)
    if err:
        return no_update
    nightly = _load_nightly(ctx)
    if nightly is None or nightly.empty:
        return no_update
    scope_new = GT.stay_created_scope(nightly, ctx.start_new, ctx.end_new,
                                      ctx.cre_start_new, ctx.cre_end_new, ctx.asof_new,
                                      cancel_mode=ctx.cmode)
    scope_old = GT.stay_created_scope(nightly, ctx.start_old, ctx.end_old,
                                      ctx.cre_start_old, ctx.cre_end_old, ctx.asof_old,
                                      cancel_mode=ctx.cmode)
    line_df = GT.daily_created_line_data(scope_new, scope_old,
                                         ctx.cre_start_new, ctx.cre_start_old)
    otb_new = float(GT.stay_only_scope(
        nightly, ctx.start_new, ctx.end_new, ctx.asof_new, cancel_mode=ctx.cmode)["revenue"].sum())
    otb_old = float(GT.stay_only_scope(
        nightly, ctx.start_old, ctx.end_old, ctx.asof_old, cancel_mode=ctx.cmode)["revenue"].sum())
    csv = _curve_csv(line_df, otb_new, otb_old, ctx.year_new, ctx.year_old)
    return dcc.send_string(csv, f"{_fname(ctx)}_kurve.csv")


# ---------------------------------------------------------------------------
# §5 Klartext-Explainer (deutscher Text, mit Jahres-Platzhaltern).
# ---------------------------------------------------------------------------
def _explainer_md(year_new: int, year_old: int) -> str:
    return f"""
Jede Zeile ist **eine Gruppe** (ein Standort, ein Buchungskanal oder ein
Stay-Segment):

- **Erstellt {year_new} (€)** - Umsatz für diesen Zeitraum, der **im ausgewählten
  Buchungs-Fenster** reingekommen ist. Beispiel: Umsatz für
  Juli-Übernachtungen, der im Juni gebucht wurde.
- **Erstellt {year_old} (€)** - genau dasselbe, aber im **Vorjahr** (zum
  Vergleichen).
- **Δ absolut (€)** - der Unterschied in Euro: dieses Jahr **minus** letztes
  Jahr. Plus = mehr als letztes Jahr, Minus = weniger.
- **Δ relativ (%)** - derselbe Unterschied in **Prozent**. Die Ampel zeigt es
  auf einen Blick: 🟢 deutlich besser, 🟠 ähnlich, 🔴 deutlich schlechter.
- **OTB {year_new} (€)** - der **gesamte** zum Stichtag gebuchte Umsatz für den
  Zeitraum, **egal wann** gebucht wurde. „On-the-books" = steht schon fest
  auf den Büchern.
- **OTB {year_old} (€)** - dasselbe fürs **Vorjahr**.
- **Pickup-Anteil {year_new} (%)** - wie viel **Prozent** des gesamten
  Umsatzes **genau im gewählten Buchungs-Fenster** reinkam - **NICHT
  kumuliert**. 40 % heißt: 40 % des OTB wurde zwischen dem 01.06. und
  30.06. gebucht; was davor schon gebucht war, steckt hier nicht drin.
  Die kumulierte Sicht („wie viel stand Ende Juni insgesamt schon in den
  Büchern?") zeigen die Kacheln oben unter **Pickup kumuliert**.
- **Pickup-Anteil {year_old} (%)** - dasselbe fürs Vorjahr: sind wir dieses
  Jahr **früher oder später** dran als damals?
- **Δ Pickup (pp)** - um wie viele **Prozentpunkte** unser Vorlauf besser (+)
  oder schlechter (−) ist als letztes Jahr. Plus = wir buchen früher.
- **Δ Anteil (pp)** *(nur Kanal/Segment)* - wie sich der **Anteil dieser
  Gruppe am Gesamt-Umsatz** verschoben hat (der „Kuchen-Anteil"). Das ist der
  **Mix**, nicht der Vorlauf.

*„pp" = Prozentpunkte: der einfache Abstand zweier Prozentzahlen. Von 60 % auf
66 % sind es +6 pp.*
"""
