# dash_app/pages/daten.py
# Daten aktualisieren - snapshot status, a background BigQuery refresh (full or
# plan-only) and a read-only view of the active plan. Port of the source
# 0_Daten_Aktualisieren page onto the overbooking data-update pattern: a click
# starts a file-backed job (backend/jobs.py); a dcc.Interval polls the job file
# and renders real progress that survives page changes; on completion the caches
# are cleared once and a version store bump re-renders the status + plan. The
# ONLY place BigQuery is touched is inside the job function. IDs: du-.

from __future__ import annotations

import dash
import dash_mantine_components as dmc
import pandas as pd
from dash import Input, Output, State, callback, dcc, html, no_update

from dash_app.backend import data, jobs
from dash_app.components import ui
from revenueblindspots import helpers as H
from revenueblindspots.refresh import refresh_plan, run_refresh

dash.register_page(__name__, path="/daten", name="Daten", order=7,
                   title="STAYERY · Daten")


# ---------------------------------------------------------------------------
# Job functions. run_refresh / refresh_plan report progress as (msg, pct|None);
# jobs.Progress is (msg, frac). Bridge with a mutable last-frac so a message
# without a fresh percentage keeps the ring where it was.
# ---------------------------------------------------------------------------
def _refresh_job(progress, lookback, fuzz, props):
    last = [0.0]

    def cb(m, p=None):
        if p is not None:
            last[0] = p
        progress(m, last[0])

    return run_refresh(lookback_years=int(lookback), fuzz_threshold=int(fuzz),
                       properties=props or None, refreshed_via="dash_app", progress=cb)


def _plan_job(progress):
    last = [0.0]

    def cb(m, p=None):
        if p is not None:
            last[0] = p
        progress(m, last[0])

    return refresh_plan(refreshed_via="dash_app", progress=cb)


# ---------------------------------------------------------------------------
# Terminal-state alerts (run_refresh / refresh_plan return dicts of different
# shape - degrade gracefully).
# ---------------------------------------------------------------------------
def _success_alert(res):
    if isinstance(res, dict) and "reservations" in res:
        n_res = int(res.get("reservations", {}).get("rows", 0) or 0)
        n_nig = int(res.get("timeslices", {}).get("rows", 0) or 0)
        n_props = len(res.get("properties", []) or [])
        msg = (f"Voll-Refresh fertig · {n_res:,} Reservations · {n_nig:,} Timeslices · "
               f"{n_props} Standorte. Planzahlen inklusive.").replace(",", ".")
        return ui.alert(msg, "success", title="Refresh fertig")
    if isinstance(res, dict) and ("hotels" in res or "rows" in res):
        earliest = str(res.get("earliest", "?"))[:7]
        latest = str(res.get("latest", "?"))[:7]
        msg = (f"Planzahlen aktualisiert · {res.get('hotels', '?')} Hotels · "
               f"{res.get('rows', '?')} Zeilen · {earliest} bis {latest}.")
        return ui.alert(msg, "success", title="Planzahlen fertig")
    return ui.alert("Refresh abgeschlossen.", "success", title="Fertig")


def _error_alert(state: dict):
    children = [dmc.Text(state.get("error", "unbekannter Fehler"), size="sm", fw=600)]
    trace = state.get("trace")
    if trace:
        children.append(html.Pre(
            trace, style={"background": "#f4f4f5", "padding": "10px",
                          "borderRadius": "8px", "fontSize": "11px",
                          "overflowX": "auto", "whiteSpace": "pre-wrap",
                          "fontFamily": "monospace", "margin": 0}))
    return ui.alert(dmc.Stack(children, gap="xs"), "alert",
                    title="Refresh fehlgeschlagen")


# ---------------------------------------------------------------------------
# "Aktueller Stand" + "Planzahlen einsehen" render bodies (re-run on du-version).
# ---------------------------------------------------------------------------
def _stand_children(meta: dict, plan_df: pd.DataFrame):
    if not meta:
        return ui.alert("Noch kein Snapshot vorhanden. Refresh unten starten, um einen "
                        "zu erstellen.", "info", title="Kein Datenstand")
    refreshed = str(meta.get("refreshed_at", "?"))[:19].replace("T", " ")
    n_res = int(meta.get("reservations", {}).get("rows", 0) or 0)
    n_nig = int(meta.get("timeslices", {}).get("rows", 0) or 0)
    earliest = str(meta.get("reservations", {}).get("earliest", "?"))[:10]
    latest = str(meta.get("reservations", {}).get("latest", "?"))[:10]
    via = meta.get("refreshed_via", "?")

    cards = ui.kpi_strip([
        ui.kpi_card("Letzter Refresh", refreshed, accent=True,
                    sub=f"Quelle: {via}",
                    tooltip="Zeitpunkt des letzten BigQuery-Snapshots (Europe/Berlin)."),
        ui.kpi_card("Reservierungen", f"{n_res:,}".replace(",", "."),
                    sub=f"{n_nig:,} Timeslices".replace(",", "."),
                    tooltip="Zeilen im reservations.parquet (eine je Buchung)."),
        ui.kpi_card("Anreise-Zeitraum", f"{earliest} → {latest}",
                    tooltip="Früheste und späteste Anreise im aktuellen Snapshot."),
    ], cols=3)

    if plan_df is None or plan_df.empty:
        plan_line = dmc.Text("Planzahlen: kein Plan-Snapshot - unten 'Nur Planzahlen' "
                             "ziehen (oder Voll-Refresh).", size="xs", c="dimmed")
    else:
        months = pd.to_datetime(plan_df["month"], errors="coerce").dt.to_period("M")
        plan_line = dmc.Text(
            f"Planzahlen: {int(plan_df['property_code'].nunique())} Hotels · "
            f"{int(months.nunique())} Monate hinterlegt.", size="xs", c="dimmed")
    return dmc.Stack([cards, plan_line], gap="xs")


def _plan_children(plan_df: pd.DataFrame):
    if plan_df is None or plan_df.empty:
        return ui.alert("Noch keine Planzahlen im Snapshot. Oben 'Nur Planzahlen' klicken "
                        "(oder Voll-Refresh).", "info", title="Kein Plan")
    months = pd.to_datetime(plan_df["month"], errors="coerce").dt.to_period("M")
    n_hotels = int(plan_df["property_code"].nunique())
    n_months = int(months.nunique())
    total = float(plan_df["revenue"].fillna(0).sum())

    kpis = ui.kpi_strip([
        ui.kpi_card("Hotels", str(n_hotels), accent=True,
                    tooltip="Standorte mit hinterlegtem Plan."),
        ui.kpi_card("Monate", str(n_months),
                    tooltip="Distinkte Plan-Monate im Snapshot."),
        ui.kpi_card("Total-PLAN (€)", H.fmt_eur(total),
                    tooltip="Summe aller Monats-Planwerte (Netto)."),
    ], cols=3)

    pivot = (plan_df.assign(Monat=months.astype(str))
             .pivot_table(index="property_code", columns="Monat", values="revenue",
                          aggfunc="sum").fillna(0.0))
    pivot["Total (€)"] = pivot.sum(axis=1)
    display = pivot.copy()
    for c in display.columns:
        display[c] = display[c].map(H.fmt_eur)
    display = display.reset_index().rename(columns={"property_code": "Hotel"})

    raw = plan_df.copy()
    if "month" in raw.columns:
        raw["month"] = pd.to_datetime(raw["month"], errors="coerce").dt.strftime("%Y-%m")

    return dmc.Stack([
        kpis,
        dmc.Text(f"Pivot Hotel × Monat ({n_hotels} Hotels × {n_months} Monate)",
                 size="sm", fw=600, mt="xs"),
        ui.df_grid(display, "du-plan-pivot", height=360),
        ui.table_accordion(
            "Rohdaten (inkl. RevPAR, Sold-/House-/OOO-Counts)",
            ui.df_grid(raw, "du-plan-raw"), value="planraw"),
    ], gap="sm")


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
def layout(**_kwargs):
    all_props = H.all_properties()
    prop_data = [{"value": pc, "label": f"{H.city_label(pc)} ({pc})"} for pc in all_props]

    header = dmc.Group([
        dmc.Title("Daten aktualisieren", order=3),
        dmc.Badge("BigQuery-Refresh · Snapshot", color="yellow", variant="light",
                  radius="sm"),
    ], gap="sm", align="center", mb="xs")

    stores = html.Div([
        dcc.Store(id="du-kick", data=0),
        dcc.Store(id="du-seen", data={}),
        dcc.Store(id="du-version", data=0),
        dcc.Interval(id="du-poll", interval=1200, n_intervals=0),
    ])

    stand_card = dmc.Card([
        dmc.Text("Aktueller Stand", fw=600, size="sm", mb=6),
        html.Div(id="du-stand", children=dmc.Skeleton(height=110, radius="lg")),
    ], withBorder=True, radius="lg", p="md", shadow="xs")

    # Refresh configuration.
    config_card = dmc.Card([
        dmc.Text("Voll-Refresh aus BigQuery", fw=600, size="sm"),
        dmc.Text("Reservations + Timeslices + Planzahlen gemeinsam.", size="xs", c="dimmed"),
        dmc.Space(h=8),
        dmc.Group([
            dmc.NumberInput(id="du-lookback", label="Lookback (Jahre)", value=3,
                            min=1, max=10, step=1, style={"width": "160px"},
                            description="Wie weit zurück pullen."),
            dmc.Stack([
                dmc.Text("Fuzzy-Cluster-Schwelle", size="sm", fw=500),
                # marginBottom leaves room for the mark labels so they don't
                # collide with the caption below.
                dmc.Slider(id="du-fuzz", value=85, min=70, max=95, step=5,
                           marks=[{"value": v, "label": str(v)}
                                  for v in (70, 75, 80, 85, 90, 95)],
                           style={"width": "260px", "marginBottom": "22px"}),
                dmc.Text("rapidfuzz token_sort_ratio · höher = strenger.",
                         size="xs", c="dimmed"),
            ], gap=6),
        ], gap="xl", align="flex-start", wrap="wrap"),
        dmc.Space(h=8),
        dmc.MultiSelect(id="du-props", label="Standorte", data=prop_data, value=[],
                        placeholder="leer = alle", clearable=True, searchable=True,
                        comboboxProps={"withinPortal": True},
                        description="Welche Standorte mitgezogen werden (leer = alle)."),
        dmc.Space(h=12),
        dmc.Group([
            dmc.Button("Voll-Refresh starten", id="du-full-btn", size="sm",
                       variant="filled",
                       leftSection=html.I(className="bi bi-cloud-download")),
            dmc.Button("Nur Planzahlen", id="du-plan-btn", size="sm", variant="light",
                       color="gray",
                       leftSection=html.I(className="bi bi-table")),
        ], gap="md", wrap="wrap"),
        ui.job_loader("du-job"),
        html.Div(id="du-result"),
    ], withBorder=True, radius="lg", p="md", shadow="xs")

    confirm_modal = dmc.Modal(
        id="du-modal", title="Voll-Refresh bestätigen", opened=False, centered=True,
        children=dmc.Stack([
            dmc.Text("Der Voll-Refresh zieht Reservations, Timeslices und Planzahlen neu "
                     "aus BigQuery und überschreibt den lokalen Snapshot. Das kann einige "
                     "Minuten dauern. Fortfahren?", size="sm"),
            dmc.Group([
                dmc.Button("Abbrechen", id="du-modal-cancel", variant="subtle",
                           color="gray"),
                dmc.Button("Ja, Refresh starten", id="du-full-confirm", variant="filled",
                           leftSection=html.I(className="bi bi-cloud-download")),
            ], justify="flex-end", gap="sm"),
        ], gap="md"))

    plan_card = dmc.Card([
        dmc.Text("Planzahlen einsehen", fw=600, size="sm", mb=6),
        html.Div(id="du-plan", children=dmc.Skeleton(height=140, radius="lg")),
    ], withBorder=True, radius="lg", p="md", shadow="xs")

    return dmc.Stack([
        header, stores, stand_card, config_card, confirm_modal, plan_card,
    ], gap="md")


# ---------------------------------------------------------------------------
# Modal open / cancel; confirm starts the full refresh, plan button starts the
# plan-only refresh. Both write to the single "refresh" job (one job per name).
# ---------------------------------------------------------------------------
@callback(Output("du-modal", "opened"), Input("du-full-btn", "n_clicks"),
          prevent_initial_call=True)
def _open_modal(_n):
    return True


@callback(Output("du-modal", "opened", allow_duplicate=True),
          Input("du-modal-cancel", "n_clicks"), prevent_initial_call=True)
def _close_modal(_n):
    return False


@callback(
    Output("du-kick", "data"),
    Output("du-modal", "opened", allow_duplicate=True),
    Input("du-full-confirm", "n_clicks"),
    State("du-lookback", "value"),
    State("du-fuzz", "value"),
    State("du-props", "value"),
    State("du-kick", "data"),
    prevent_initial_call=True,
)
def _start_full(n, lookback, fuzz, props, kick):
    jobs.start("refresh", _refresh_job, lookback, fuzz, props)
    return (kick or 0) + 1, False


@callback(
    Output("du-kick", "data", allow_duplicate=True),
    Input("du-plan-btn", "n_clicks"),
    State("du-kick", "data"),
    prevent_initial_call=True,
)
def _start_plan(n, kick):
    jobs.start("refresh", _plan_job)
    return (kick or 0) + 1


# ---------------------------------------------------------------------------
# Poll the job file: stream progress into the loader, disable the buttons while
# running, and on a terminal state render the alert + (once) bump du-version so
# the status/plan re-render on the freshly cleared caches.
# ---------------------------------------------------------------------------
@callback(
    Output("du-job-ring", "sections"),
    Output("du-job-pct", "children"),
    Output("du-job-msg", "children"),
    Output("du-job-wrap", "style"),
    Output("du-result", "children"),
    Output("du-full-btn", "disabled"),
    Output("du-plan-btn", "disabled"),
    Output("du-version", "data"),
    Output("du-seen", "data"),
    Input("du-poll", "n_intervals"),
    Input("du-kick", "data"),
    State("du-version", "data"),
    State("du-seen", "data"),
)
def _poll(_n, _kick, version, seen):
    state = jobs.read("refresh")
    status = state.get("status", "idle")
    seen = dict(seen or {})

    if status == "running":
        sec, pct, msg, wrap = ui.loader_view(float(state.get("progress", 0)) * 100,
                                             state.get("message", ""), show=True)
        return sec, pct, msg, wrap, no_update, True, True, no_update, no_update

    sec, pct, msg, wrap = ui.loader_view(0, "", show=False)
    fin = state.get("finished")
    # Only act on a NEWLY finished job - otherwise the 1.2s interval would
    # re-emit the alert + re-enable the buttons on every tick forever.
    if not fin or seen.get("refresh") == fin:
        return (no_update,) * 4 + (no_update, no_update, no_update, no_update, no_update)
    seen["refresh"] = fin

    bump, result = no_update, no_update
    if status == "done":
        data.clear_caches()
        bump = (version or 0) + 1
        result = _success_alert(state.get("result") or {})
    elif status == "error":
        result = _error_alert(state)
    elif status == "cancelled":
        result = ui.alert("Abgebrochen - vorherige Daten bleiben erhalten.", "warning",
                          title="Abgebrochen")
    return sec, pct, msg, wrap, result, False, False, bump, seen


@callback(Output("du-job-cancel", "children"), Input("du-job-cancel", "n_clicks"),
          prevent_initial_call=True)
def _cancel(_n):
    jobs.cancel("refresh")
    return "Abbrechen …"


# ---------------------------------------------------------------------------
# Status + plan render: fires on load and again on every du-version bump.
# ---------------------------------------------------------------------------
@callback(
    Output("du-stand", "children"),
    Output("du-plan", "children"),
    Input("du-version", "data"),
)
def _render_status(_version):
    plan_df = data.get_plan_df()
    return _stand_children(data.get_metadata(), plan_df), _plan_children(plan_df)
