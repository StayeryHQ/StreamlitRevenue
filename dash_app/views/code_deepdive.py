# dash_app/views/code_deepdive.py
# VIEW - Code Deep-Dive (Sales-Gruppe). Eine Firma / ein Code im 360-Grad-Blick:
# Identität, Revenue-Verlauf, Channel-Evolution, Stay-Pattern, Storno-Verhalten,
# Future Pipeline, Reservations-Export. Port von
# the Code_Deepdive view. Kein register_page - ein Hub importiert
# dieses Modul und ruft layout(). Alle Callbacks sind beim Import registriert.
# Figuren + Tabellen bauen in components/code_charts (CC); Daten kommen aus dem
# Parquet-Snapshot via backend/data. Kein BigQuery.

from __future__ import annotations

from types import SimpleNamespace

import dash_mantine_components as dmc
import pandas as pd
from dash import Input, Output, State, callback, dcc, html, no_update

from dash_app.backend import data
from dash_app.backend import exports as XLS
from dash_app.components import code_charts as CC
from dash_app.components import ui
from revenueblindspots import helpers as H
from revenueblindspots import overrides as OV

_PERSIST = dict(persistence=True, persistence_type="local")

_INFO_REV = ("Monats-Revenue (Bars) + 3M-rollender Mittelwert + kumulative Linie "
             "(2. Y-Achse). Fokus-Periode markiert. Realisiert only.")
_INFO_CHAN = ("Channel-Mix über die Lifetime (gestapelt) + Fokus- vs. Vorperiode-"
              "Anteil je Channel (pp-Verschiebung).")
_INFO_STAY = ("6 Panels über alle realisierten Buchungen: LOS · Standort · "
              "Anreise-Wochentag · Zimmerkategorie · Vorlauf · Gruppen-Größe.")
_INFO_STORNO = ("Storno-Timing vor Anreise (cancellationTime, Fallback modified) + "
                "monatliche Storno-Quote mit Alert-Schwelle.")


# ---------------------------------------------------------------------------
# Kleine Grid-/Format-Helfer.
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


# ---------------------------------------------------------------------------
# Layout (callable -> Standort-Liste + Defaults werden bei jeder Navigation neu
# gelesen). code=None wird aus dem Query-Param vorbelegt (Deep-Link von der Promo-
# Page); der Query gewinnt beim Laden gegen die Persistenz -> das Code-Feld trägt
# KEINE persistence.
# ---------------------------------------------------------------------------
def layout(code=None, **_kwargs):
    meta = data.get_metadata()
    all_props = (meta.get("properties") if meta else None) or H.all_properties()
    prop_data = [{"label": f"{H.city_label(pc)} ({pc})", "value": pc} for pc in all_props]

    today = pd.Timestamp.today().normalize()
    month_start = today.replace(day=1)
    month_end = month_start + pd.offsets.MonthEnd(0)

    primary = [
        dmc.TextInput(id="cd-code", label="Code(s)", value=code or "",
                      placeholder="z.B. GBG10 oder mehrere komma-getrennt",
                      leftSection=html.I(className="bi bi-upc-scan"),
                      style={"minWidth": "240px"}),
        ui.location_select("cd-props", all_props, data=prop_data, clearable=False),
        dmc.DatePickerInput(id="cd-ps", label="Fokus-Start", value=_iso(month_start),
                            valueFormat="DD.MM.YYYY", style={"minWidth": "150px"}, **_PERSIST),
        dmc.DatePickerInput(id="cd-pe", label="Fokus-Ende", value=_iso(month_end),
                            valueFormat="DD.MM.YYYY", style={"minWidth": "150px"}, **_PERSIST),
    ]
    advanced = ui.advanced_popover("cd", [
        dmc.Switch(id="cd-include-promo", label="Promocodes einbeziehen", checked=True,
                   size="sm", **_PERSIST),
        dmc.Text("Matcht den/die Code(s) zusätzlich gegen promoCode. Aus = strikt nur "
                 "Corporate-/Company-/Effective-Code.", size="xs", c="dimmed"),
        dmc.Stack([
            dmc.Text("Lookback-Jahre", size="sm", fw=600),
            dmc.Slider(id="cd-lookback", min=1, max=7, step=1, value=3,
                       marks=[{"value": v, "label": str(v)} for v in range(1, 8)],
                       **_PERSIST),
        ], gap=4),
        dmc.Stack([
            dmc.Text("Alert-Schwelle Storno-Quote (%)", size="sm", fw=600),
            dmc.Slider(id="cd-alert", min=10, max=50, step=5, value=25,
                       marks=[{"value": v, "label": str(v)} for v in (10, 25, 50)],
                       **_PERSIST),
        ], gap=4),
    ])

    filter_bar = ui.filter_shell(primary=primary, advanced=advanced)

    # ---- Tab-Panels (statische Struktur; die Daten-Callback füllt Figuren/Grids) ----
    tab_identity = dmc.Stack([
        html.Div(id="cd-identity-head"),
        html.Div(id="cd-coverage"),
        html.Div(id="cd-kpis", children=dmc.Skeleton(height=110, radius="lg")),
        html.Div(id="cd-kpis2"),
    ], gap="md")

    tab_revchan = dmc.Stack([
        ui.section_header(2, "Revenue-Verlauf", basis="stay", info=_INFO_REV),
        ui.chart_card("Revenue-Verlauf · monatlich / kumulativ", "cd-fig-rev", height=420),
        ui.table_accordion("Monats-Tabelle",
                           ui.df_grid(pd.DataFrame(), "cd-grid-rev"), value="rev"),
        ui.section_header(3, "Channel-Evolution", basis="stay", info=_INFO_CHAN),
        ui.chart_card("Channel-Evolution", "cd-fig-chan", height=440),
        ui.table_accordion("Channel-Tabelle · Periode-Vergleich",
                           ui.df_grid(pd.DataFrame(), "cd-grid-chan"), value="chan"),
    ], gap="md")

    tab_staystorno = dmc.Stack([
        ui.section_header(4, "Stay-Pattern", basis="stay", info=_INFO_STAY),
        ui.chart_card("Stay-Pattern (6 Panels)", "cd-fig-stay", height=640),
        ui.table_accordion("Standort-Aufteilung",
                           ui.df_grid(pd.DataFrame(), "cd-grid-loc"), value="loc"),
        ui.section_header(5, "Storno-Verhalten", basis="stay", info=_INFO_STORNO),
        ui.chart_card("Storno-Timing & monatliche Quote", "cd-fig-storno", height=420),
        html.Div(id="cd-storno-econ"),
        ui.table_accordion("Monatliche Storno-Quote",
                           ui.df_grid(pd.DataFrame(), "cd-grid-storno"), value="storno"),
    ], gap="md")

    tab_pipeline = dmc.Stack([
        ui.section_header(6, "Future Pipeline", basis="stay",
                          info="Offene Buchungen mit Anreise > heute (nicht storniert)."),
        html.Div(id="cd-pipe-head"),
        ui.df_grid(pd.DataFrame(), "cd-grid-pipe"),
        ui.section_header(7, "Reservations-Tabelle", basis="mixed",
                          info="Alle Buchungen für diese Code(s) - Lifetime-Schnitt."),
        html.Div(id="cd-res-head"),
        ui.df_grid(pd.DataFrame(), "cd-grid-res"),
        dmc.Group([
            dmc.Button("Alle Daten als Excel", id="cd-dl-btn", variant="light",
                       leftSection=html.I(className="bi bi-file-earmark-excel")),
        ], mt="sm"),
        dcc.Download(id="cd-dl"),
    ], gap="md")

    section_tabs = ui.section_tabs("cd-sectiontabs", [
        ("identity", "Identität", tab_identity, "bi bi-person-vcard"),
        ("revchan", "Umsatz & Kanäle", tab_revchan, "bi bi-graph-up"),
        ("staystorno", "Aufenthalt & Storno", tab_staystorno, "bi bi-calendar-week"),
        ("pipeline", "Pipeline & Buchungen", tab_pipeline, "bi bi-list-check"),
    ])

    header = dmc.Group([
        dmc.Title("Code Deep-Dive", order=3),
        dmc.Badge("Firma · 360-Grad-Blick · Sales", color="yellow", variant="light",
                  radius="sm"),
    ], gap="sm", align="center", mb="xs")

    body = html.Div(dmc.Stack([html.Div(id="cd-setup"), section_tabs], gap="md"),
                    id="cd-body")

    return dmc.Stack([
        header,
        filter_bar,
        html.Div(id="cd-alerts"),
        html.Div(id="cd-guard"),
        body,
    ], gap="md")


# ---------------------------------------------------------------------------
# Ableitungen + Datenladen (einmal zentral; von Haupt- und Export-Callback genutzt).
# Gibt (ctx, data_ns, error) zurück - ctx/None, data_ns/None, err-String/None.
# ---------------------------------------------------------------------------
def _derive(code, props, ps, pe, lookback_years):
    codes = [c.strip() for c in (code or "").split(",") if c.strip()]
    if not codes:
        return None, "Mindestens einen Code eingeben."
    if not props:
        return None, "Bitte mindestens einen Standort wählen."
    if ps is None or pe is None:
        return None, "Bitte Fokus-Periode wählen."
    period_start, period_end = pd.Timestamp(ps), pd.Timestamp(pe)
    window_days = (period_end - period_start).days + 1
    prev_period_end = period_start - pd.Timedelta(days=1)
    prev_period_start = prev_period_end - pd.Timedelta(days=window_days - 1)
    lookback_start = (period_start - pd.DateOffset(years=int(lookback_years))).normalize()
    lookback_end = max(pd.Timestamp.today().normalize(),
                       period_end + pd.Timedelta(days=180))
    ctx = SimpleNamespace(
        codes=codes, props=list(props), period_start=period_start, period_end=period_end,
        window_days=window_days, prev_period_start=prev_period_start,
        prev_period_end=prev_period_end, lookback_start=lookback_start,
        lookback_end=lookback_end, lookback_years=int(lookback_years))
    return ctx, None


def _prepare(code, props, ps, pe, lookback_years, include_promo):
    ctx, err = _derive(code, props, ps, pe, lookback_years)
    if err:
        return None, None, err

    nightly = data.get_timeslices(start=ctx.lookback_start, end=ctx.lookback_end,
                                  properties=ctx.props)
    enriched = H.timeslices_are_enriched(nightly)
    if enriched:
        res_all = H.reservations_from_timeslices(nightly)
    else:
        res_all = data.get_reservations(start=ctx.lookback_start, end=ctx.lookback_end,
                                        properties=ctx.props)
    if res_all.empty:
        return ctx, None, "Keine Reservierungen im Lookback-Zeitraum."

    # promoCode lebt (vor dem Foundation-Refresh) nur in den Reservations - per id
    # nachjoinen, damit reine Promocodes auch auf der Stay-Netto-Basis auflösen.
    if include_promo and "promoCode" not in res_all.columns and "id" in res_all.columns:
        pmap = data.get_reservations(start=ctx.lookback_start, end=ctx.lookback_end,
                                     properties=ctx.props)
        if {"id", "promoCode"}.issubset(pmap.columns):
            res_all = res_all.merge(pmap[["id", "promoCode"]].drop_duplicates("id"),
                                    on="id", how="left")

    res, firm_fuzzy, firm_raw = CC.resolve_codes_to_res(res_all, ctx.codes,
                                                        include_promo=include_promo)
    if res.empty:
        return ctx, None, f"Keine Buchungen für Code(s) {', '.join(ctx.codes)} im Lookback."

    # Code-Spalte robust: für reine Promo-Buchungen ist effective_code leer ->
    # Fallback auf promoCode, damit die Tabellen immer einen Code zeigen.
    if "effective_code" in res.columns and "promoCode" in res.columns:
        eff = res["effective_code"].astype("string").str.strip()
        empty = eff.isna() | eff.str.lower().isin(["", "nan", "none", "<na>", "null"])
        res.loc[empty, "effective_code"] = res.loc[empty, "promoCode"].astype("string").str.strip()

    ns = SimpleNamespace(res=res, firm_fuzzy=firm_fuzzy, firm_raw=firm_raw,
                         enriched=enriched)
    return ctx, ns, None


def _setup_block(ctx) -> object:
    codes_md = ", ".join(f"`{c}`" for c in ctx.codes)
    return dcc.Markdown(
        f"**Analyse-Setup**  \n"
        f"- Code(s): {codes_md}  \n"
        f"- Fokus-Periode: **{ctx.period_start:%d.%m.%Y} – {ctx.period_end:%d.%m.%Y}** "
        f"({ctx.window_days} Tage)  \n"
        f"- Vorperiode (auto): **{ctx.prev_period_start:%d.%m.%Y} – "
        f"{ctx.prev_period_end:%d.%m.%Y}**  \n"
        f"- Lookback: **{ctx.lookback_start:%d.%m.%Y} – {ctx.lookback_end:%d.%m.%Y}**")


# ---------------------------------------------------------------------------
# §1 Identität - Metriken, Code-Typ-Erkennung, KPI-Cards.
# ---------------------------------------------------------------------------
def _code_type(res: pd.DataFrame, codes: list[str]) -> str:
    codes_up = {c.upper() for c in codes}
    reclassified = set(OV.promo_overrides().keys())
    as_promo = (res["promoCode"].astype("string").str.strip().str.upper().isin(codes_up).any()
                if "promoCode" in res.columns else False)
    as_corp = (res["corporateCode"].astype("string").str.strip().str.upper().isin(codes_up).any()
               if "corporateCode" in res.columns else False)
    if codes_up & reclassified:
        return "Promo → reklass. Firmencode"
    if as_corp and as_promo:
        return "Corporate & Promo"
    if as_corp:
        return "Corporatecode"
    if as_promo:
        return "Promocode"
    return "—"


def _identity(ctx, ns, alert_rate):
    res = ns.res
    firm_label = ns.firm_fuzzy[0] if ns.firm_fuzzy else ", ".join(ctx.codes)
    all_variants = " · ".join(ns.firm_raw[:5]) + (" …" if len(ns.firm_raw) > 5 else "")

    realized = res[res["is_realized"]]
    n_total = len(res)
    n_realized = len(realized)
    n_cancelled = int(res["is_cancelled"].sum())
    lifetime_revenue = float(realized["revenue"].sum())
    lifetime_nights = int(realized["nights"].fillna(0).sum())
    adr_lifetime = lifetime_revenue / lifetime_nights if lifetime_nights else float("nan")
    first_booking = res["arrival"].min()
    last_booking = res["arrival"].max()
    cancel_rate = (n_cancelled / n_total * 100) if n_total else 0.0

    in_period = res[(res["arrival"] >= ctx.period_start) & (res["arrival"] <= ctx.period_end)]
    in_period_real = in_period[in_period["is_realized"]]
    period_has_data = not in_period_real.empty
    period_revenue = float(in_period_real["revenue"].sum())
    period_nights = int(in_period_real["nights"].fillna(0).sum())
    period_bookings = len(in_period)

    prev_period = res[(res["arrival"] >= ctx.prev_period_start)
                      & (res["arrival"] <= ctx.prev_period_end)]
    prev_period_real = prev_period[prev_period["is_realized"]]
    prev_has_data = not prev_period_real.empty
    prev_revenue = float(prev_period_real["revenue"].sum())
    prev_bookings = len(prev_period)

    if period_has_data and prev_has_data and prev_revenue > 0:
        period_yoy_pct = (period_revenue / prev_revenue - 1) * 100
    else:
        period_yoy_pct = float("nan")

    today = pd.Timestamp.today().normalize()
    future = res[(res["arrival"] > today) & ~res["is_cancelled"]]
    future_revenue = float(future["revenue"].sum())
    future_bookings = len(future)

    code_type = _code_type(res, ctx.codes)

    head = dmc.Stack([
        dmc.Title(f"1 · {firm_label}", order=4),
        dmc.Text(f"Code(s): {', '.join(ctx.codes)}  ·  Firmennamen-Varianten (raw): "
                 f"{all_variants or '-'}", size="sm", c="dimmed"),
    ], gap=2)

    warns = []
    if not period_has_data:
        warns.append(f"Fokus-Periode {ctx.period_start:%d.%m.%Y}–{ctx.period_end:%d.%m.%Y}: "
                     "keine realisierten Buchungen")
    if not prev_has_data:
        warns.append(f"Vorperiode {ctx.prev_period_start:%d.%m.%Y}–"
                     f"{ctx.prev_period_end:%d.%m.%Y}: keine realisierten Buchungen")
    if warns:
        coverage = ui.alert(
            dcc.Markdown("- " + "\n- ".join(warns) + "\n\nPeriode-spezifische Werte als "
                         "\"-\"; Lifetime + Charts zeigen die volle Historie."),
            "warning", title="Hinweis zur Datenabdeckung")
    else:
        coverage = None

    cards1 = ui.kpi_strip([
        ui.kpi_card("Lifetime Revenue", H.fmt_eur(lifetime_revenue), accent=True,
                    delta=f"{n_realized:,} realisiert".replace(",", ".")),
        ui.kpi_card("Lifetime Nights", f"{lifetime_nights:,}".replace(",", "."),
                    delta=f"ADR ø {H.fmt_eur(adr_lifetime)}"),
        ui.kpi_card("Erste Buchung", f"{first_booking:%d.%m.%Y}",
                    sub=f"letzte {last_booking:%d.%m.%Y}"),
        ui.kpi_card("Code-Typ", code_type),
        ui.kpi_card("Cancel-Rate", f"{cancel_rate:.1f} %",
                    delta="über Alert" if cancel_rate > alert_rate else "im Korridor",
                    delta_good=cancel_rate <= alert_rate),
    ], cols=5)

    cards2 = ui.kpi_strip([
        ui.kpi_card(f"Period Revenue ({ctx.period_start:%d.%m}–{ctx.period_end:%d.%m})",
                    H.fmt_eur(period_revenue) if period_has_data else "-",
                    delta=(f"{period_bookings} B. · {period_nights} N."
                           if period_has_data else None)),
        ui.kpi_card("vs. Vorperiode",
                    f"{period_yoy_pct:+.1f} %" if pd.notna(period_yoy_pct) else "-",
                    delta=(f"Vorperiode {H.fmt_eur(prev_revenue)} · {prev_bookings} B."
                           if prev_has_data else None),
                    delta_good=(period_yoy_pct >= 0) if pd.notna(period_yoy_pct) else None),
        ui.kpi_card("Future Pipeline", H.fmt_eur(future_revenue),
                    delta=f"{future_bookings} offene Buchungen"),
    ], cols=3)

    return head, coverage, cards1, cards2, firm_label


# ---------------------------------------------------------------------------
# Haupt-Callback: füllt Setup, Alerts, Guard + alle Sektionen. Bare @callback -
# jeder Filter wirkt direkt.
# ---------------------------------------------------------------------------
_OUTPUTS = [
    Output("cd-setup", "children"),
    Output("cd-alerts", "children"),
    Output("cd-guard", "children"),
    Output("cd-body", "style"),
    Output("cd-identity-head", "children"),
    Output("cd-coverage", "children"),
    Output("cd-kpis", "children"),
    Output("cd-kpis2", "children"),
    Output("cd-fig-rev", "figure"),
    Output("cd-grid-rev", "columnDefs"), Output("cd-grid-rev", "rowData"),
    Output("cd-fig-chan", "figure"),
    Output("cd-grid-chan", "columnDefs"), Output("cd-grid-chan", "rowData"),
    Output("cd-fig-stay", "figure"),
    Output("cd-grid-loc", "columnDefs"), Output("cd-grid-loc", "rowData"),
    Output("cd-fig-storno", "figure"),
    Output("cd-storno-econ", "children"),
    Output("cd-grid-storno", "columnDefs"), Output("cd-grid-storno", "rowData"),
    Output("cd-pipe-head", "children"),
    Output("cd-grid-pipe", "columnDefs"), Output("cd-grid-pipe", "rowData"),
    Output("cd-res-head", "children"),
    Output("cd-grid-res", "columnDefs"), Output("cd-grid-res", "rowData"),
]

_INPUTS = [
    Input("cd-code", "value"), Input("cd-props", "value"),
    Input("cd-ps", "value"), Input("cd-pe", "value"),
    Input("cd-include-promo", "checked"),
    Input("cd-lookback", "value"), Input("cd-alert", "value"),
]

_FILTER_STATES = [
    State("cd-code", "value"), State("cd-props", "value"),
    State("cd-ps", "value"), State("cd-pe", "value"),
    State("cd-include-promo", "checked"),
    State("cd-lookback", "value"), State("cd-alert", "value"),
]


def _guard(setup, alerts, guard):
    """Full output tuple with body hidden + blank figures/grids (early return)."""
    blank = CC._empty("–")
    return (setup, alerts, guard, {"display": "none"}, None, None, None, None,
            blank, [], [], blank, [], [], blank, [], [], blank, None, [], [],
            None, [], [], None, [], [])


@callback(_OUTPUTS, _INPUTS)
def _update(code, props, ps, pe, include_promo, lookback_years, alert_rate):
    ctx, ns, err = _prepare(code, props, ps, pe, lookback_years, include_promo)
    if err:
        setup = _setup_block(ctx) if ctx is not None else None
        kind = "info" if err.startswith("Mindestens") else "warning"
        return _guard(setup, None, ui.alert(err, kind))

    # Datenbasis-Hinweis wenn Timeslices noch nicht angereichert sind.
    alerts = None
    if not ns.enriched:
        alerts = ui.alert(
            "Code-/Firmen-Revenue läuft noch auf der services-inklusiven Reservations-"
            "Basis. Für die konsistente Stay-Netto-Sicht einmal Voll-Refresh ziehen "
            "(Daten aktualisieren).", "info")

    res = ns.res
    today = pd.Timestamp.today().normalize()

    # §1 Identität
    head, coverage, cards1, cards2, firm_label = _identity(ctx, ns, alert_rate)

    # §2 Revenue-Verlauf
    fig_rev, monthly, cum = CC.revenue_timeline(res, firm_label, ctx.period_start,
                                                ctx.period_end)
    tbl_rev = CC.monthly_revenue_table(monthly, cum)

    # §3 Channel-Evolution
    fig_chan, cur_ch, prev_ch = CC.channel_evolution(
        res, firm_label, ctx.period_start, ctx.period_end,
        ctx.prev_period_start, ctx.prev_period_end)
    tbl_chan = CC.channel_shift_table(cur_ch, prev_ch)

    # §4 Stay-Pattern
    fig_stay = CC.stay_patterns(res, firm_label)
    tbl_loc = CC.location_table(res)

    # §5 Storno-Verhalten
    fig_storno = CC.storno_view(res, firm_label, alert_cancel_rate_pct=float(alert_rate))
    lost_total = float(res["lost_revenue"].sum()) if "lost_revenue" in res.columns else 0.0
    realized_rev = float(res[res["is_realized"]]["revenue"].sum())
    storno_econ = dmc.Stack([
        dcc.Markdown(
            f"**Storno-Ökonomie über die Lifetime:**  \n"
            f"- realisierter Revenue: **{H.fmt_eur(realized_rev)}**  \n"
            f"- verlorener Revenue: **{H.fmt_eur(lost_total)}**"),
        dmc.Text("Verlorener Revenue = Stay-Netto der Stornos/No-Shows MINUS einbehaltene "
                 "Netto-Fee (nicht die volle Buchung). Storno-Timing über cancellationTime "
                 "(Fallback modified als Proxy).", size="xs", c="dimmed"),
    ], gap="xs")
    tbl_storno = CC.storno_monthly_table(res)

    # §6 Future Pipeline
    tbl_pipe = CC.pipeline_table(res, today)
    if tbl_pipe.empty:
        pipe_head = ui.alert("Keine offenen Buchungen mit Anreise in der Zukunft.", "info")
    else:
        exp_rev = (H.fmt_eur(float(tbl_pipe["Revenue (€)"].sum()))
                   if "Revenue (€)" in tbl_pipe.columns else "-")
        pipe_head = dcc.Markdown(
            f"**{len(tbl_pipe)} offene Buchungen** · erwarteter Revenue: **{exp_rev}**")

    # §7 Reservations-Tabelle
    tbl_res = CC.reservations_table(res)
    res_head = dcc.Markdown(
        f"**{len(tbl_res):,} Reservierungen** - Lifetime-Schnitt für die Code(s).".replace(",", "."))

    c_rev = _grid_out(tbl_rev)
    c_chan = _grid_out(tbl_chan)
    c_loc = _grid_out(tbl_loc)
    c_storno = _grid_out(tbl_storno)
    c_pipe = _grid_out(tbl_pipe)
    c_res = _grid_out(tbl_res)

    return (_setup_block(ctx), alerts, None, {}, head, coverage, cards1, cards2,
            fig_rev, c_rev[0], c_rev[1],
            fig_chan, c_chan[0], c_chan[1],
            fig_stay, c_loc[0], c_loc[1],
            fig_storno, storno_econ, c_storno[0], c_storno[1],
            pipe_head, c_pipe[0], c_pipe[1],
            res_head, c_res[0], c_res[1])


# ---------------------------------------------------------------------------
# Export: Multi-Sheet-Excel (reservations + pipeline) via dcc.Download.
# ---------------------------------------------------------------------------
@callback(Output("cd-dl", "data"), Input("cd-dl-btn", "n_clicks"),
          *_FILTER_STATES, prevent_initial_call=True)
def _export(_n, code, props, ps, pe, include_promo, lookback_years, alert_rate):
    ctx, ns, err = _prepare(code, props, ps, pe, lookback_years, include_promo)
    if err:
        return no_update
    today = pd.Timestamp.today().normalize()
    sheets = {
        "reservations": CC.reservations_table(ns.res),
        "pipeline": CC.pipeline_table(ns.res, today),
    }
    fname = f"code_{ctx.codes[0]}_export.xlsx"
    return dcc.send_bytes(lambda buf: XLS.write_workbook(buf, sheets), fname)
