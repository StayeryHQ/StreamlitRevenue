"""Standort-Analyse - Einzelblick auf einen Standort, 17 Sektionen."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT / "streamlit_app"))

import numpy as np
import pandas as pd
import streamlit as st

from components import (
    alert_card,
    charts,
    download_button,
    inject_brand_css,
    lazy_section,
    preload_all_button,
    push_snippet,
    render_notepad,
    render_toc,
    section,
    sync_snapshot_override,
)
from components import cached_data as CD
from components import chart_data as CDT
from components.alerts import alert_cards
from components.brand import hero
from components.export import register_section, reset_export
from components.tooltips import (
    KPI_ADR,
    KPI_ALOS,
    KPI_OCCUPANCY,
    KPI_REVENUE,
    chart_help,
)
from revenueblindspots import helpers as H

st.set_page_config(
    page_title="Standort-Analyse",
    page_icon="📍",
    layout="wide",
)
inject_brand_css()
CD.apply_stayery_style_once()
sync_snapshot_override()
CD.keep_session_state_alive()  # MUST run before any widget renders this page

PAGE = "standort"
st.session_state["__page"] = PAGE

hero(
    eyebrow="Standort Deep Dive",
    title="Standort-Analyse",
    subtitle="Tiefer Vergleich zwischen zwei Perioden für einen Standort",
)


# ============================== Sidebar filter =============================
with st.sidebar:
    st.header("Filter")

    meta = CD.get_metadata()
    if not meta:
        st.error("Kein Snapshot - bitte erst `Daten aktualisieren` ausführen.")
        st.stop()

    all_props = meta.get("properties") or H.all_properties()

    # `key=` ist nötig damit der Wert beim Tab-Wechsel erhalten bleibt.
    property_code = st.selectbox(
        "Standort",
        options=all_props,
        index=all_props.index("FRA_SH") if "FRA_SH" in all_props else 0,
        key="standort_property_code",
    )

    with st.form("standort_dates", clear_on_submit=False, border=False):
        st.caption("Vergleichs-Periode (OLD)")
        c1, c2 = st.columns(2)
        with c1:
            period_old_start = st.date_input(
                "Start OLD", value=pd.Timestamp("2025-05-01").date(), key="po_start"
            )
        with c2:
            period_old_end = st.date_input(
                "Ende OLD", value=pd.Timestamp("2025-05-31").date(), key="po_end"
            )

        st.caption("Aktuelle Periode (NEW)")
        c3, c4 = st.columns(2)
        with c3:
            period_new_start = st.date_input(
                "Start NEW", value=pd.Timestamp("2026-05-01").date(), key="pn_start"
            )
        with c4:
            period_new_end = st.date_input(
                "Ende NEW", value=pd.Timestamp("2026-05-31").date(), key="pn_end"
            )

        st.checkbox(
            "Storno + No-Show einbeziehen",
            value=False,
            key="standort_include_cancellations",
            help="Default: aus - alle KPIs, Tabellen und Charts sind realized-only "
            "(Storno und No-Show fallen raus). Aktivieren → alle Buchungen "
            "zählen, auch später stornierte und no-shows. Vor allem bei Analyse nach Erstellungsdatum relevant.",
        )

        st.form_submit_button("Perioden anwenden", use_container_width=True)

    st.divider()
    st.caption("Sektionen 6-17 laden erst auf Klick.")
    preload_all_button(list(range(6, 18)), label="Alle Sektionen laden")
    CD.cache_clear_button()
    st.caption(f"Snapshot vom **{str(meta.get('refreshed_at', '?'))[:10]}**")

# Notepad in der Sidebar
render_notepad(PAGE)


start_old = pd.Timestamp(period_old_start)
end_old = pd.Timestamp(period_old_end)
start_new = pd.Timestamp(period_new_start)
end_new = pd.Timestamp(period_new_end)
YEAR_OLD = start_old.year
YEAR_NEW = start_new.year
PERIOD_TAG_OLD = f"{start_old:%d.%m.%Y}–{end_old:%d.%m.%Y}"
PERIOD_TAG_NEW = f"{start_new:%d.%m.%Y}–{end_new:%d.%m.%Y}"
LABEL = f"{H.city(property_code)} ({property_code})"
units = H.units_total(property_code)
SNAP_TAG = CD.snapshot_tag()
SNAP_DATE = pd.Timestamp(str(meta.get("refreshed_at", ""))[:10] or pd.Timestamp.today().date())


def _ck(section_id: str) -> str:
    """Cache-Key - alle Filter plus Snapshot-Tag, damit Snapshot-Refresh
    auch alle gecachten PNGs invalidiert. Der Storno/No-Show-Toggle MUSS
    im Key stehen, sonst liefern die gecachten Chart-PNGs beim Umschalten
    den alten (realized-only) Stand."""
    _c = int(bool(st.session_state.get("standort_include_cancellations", False)))
    return (
        f"std::{SNAP_TAG}::{property_code}::{start_old.date()}::{end_old.date()}"
        f"::{start_new.date()}::{end_new.date()}::c{_c}::{section_id}"
    )


# ============================== Data load ==================================
with st.spinner("Lade Daten aus dem Parquet-Snapshot …"):
    nightly = CD.get_timeslices(properties=[property_code])

    # Reservation-level Sektionen (Gruppen-Größe, Vorlaufzeit/Storno, Firmen-
    # kunden, Vertragscodes) laufen auf der Stay-Date-Basis: nightly auf
    # Buchungs-Ebene zurückfalten (revenue = Stay-Date je Buchung), nach
    # `created` gebucketet ("nach Erstellungsdatum").
    _enriched = H.timeslices_are_enriched(nightly)
    if _enriched:
        res = H.reservations_from_timeslices(nightly)
    else:
        res = CD.get_reservations(properties=[property_code])

    if "firm_by_effective_fuzzy" in res.columns:
        res["company"] = res["firm_by_effective_fuzzy"].fillna(res["company"])
        res["has_company"] = res["company"].notna()

    nig_old = H.filter_period(nightly, start_old, end_old, "stay_date")
    nig_new = H.filter_period(nightly, start_new, end_new, "stay_date")
    res_old = H.filter_period(res, start_old, end_old, "created")
    res_new = H.filter_period(res, start_new, end_new, "created")

# ============================== TOC ========================================
_TOC = [
    (1, "Landscape KPIs"),
    (2, "Pace by Month"),
    (3, "Heatmap Channel × LOS"),
    (4, "Heatmap Channel × Reisezweck × LOS"),
    (5, "LOS Revenue YoY"),
    (6, "Channel-Mix monatlich & YoY"),
    (7, "ALOS pro Channel"),
    (8, "Wochentag · Stay"),
    (9, "Wochentag · Anreise"),
    (10, "Gruppen-Größe · Erstellung"),
    (11, "Inland vs. Ausland"),
    (12, "Top-Herkunftsländer"),
    (13, "Vorlaufzeit & Storno-Risiko · Erstellung"),
    (14, "Daily Occupancy nach LOS"),
    (15, "Firmenkunden · Erstellung"),
    (16, "Direct Offline · Erstellung"),
    (17, "Top Vertragscodes · Erstellung"),
]
render_toc(_TOC)

st.caption(
    "**Datenbasis & Filter:** alle €-Werte = Staydate-Netto exkl. extra Services. "
    "**Aufenthalts-Sektionen** (KPIs, Pace, Channels, LOS, Wochentag, Inland/Ausland, "
    "Länder, Occupancy) → **Aufenthalt**. **Reservation-Sektionen** "
    "(Gruppen-Größe, Vorlaufzeit/Storno, Firmenkunden, Direct-Offline, Vertragscodes) → "
    "**Erstellungsdatum** (created). Storno/No-Show via Sidebar-Toggle einstellbar."
)

# ============================== Highlights =================================
st.subheader("Highlights")
highlights = []

days_old = H.period_days(start_old, end_old)
days_new = H.period_days(start_new, end_new)
# Storno/No-Show-Toggle aus der Sidebar
_include_cancellations = bool(st.session_state.get("standort_include_cancellations", False))
_realized_only = not _include_cancellations
_scope_caption = (
    "**Scope:** alle Buchungen (inkl. Storno + No-Show)"
    if _include_cancellations
    else "**Scope:** realized-only (Storno + No-Show ausgeschlossen)"
)
st.caption(_scope_caption)

# Non-fatale Warnung: gewählte Periode reicht vor den Datenbestand des Snapshots
# zurück (Lookback-Limit) - davor existieren keine Buchungen, Werte sind unvollständig.
_data_start = H.snapshot_data_start(meta)
if _data_start is not None:
    _before = [(lbl, s) for lbl, s in (("OLD", start_old), ("NEW", start_new)) if s < _data_start]
    if _before:
        _txt = " · ".join(f"{lbl} beginnt {s:%d.%m.%Y}" for lbl, s in _before)
        alert_card(
            f"{_txt} - der Snapshot enthält aber erst Daten ab "
            f"{_data_start:%d.%m.%Y}. Der Zeitraum davor ist leer, die Werte sind "
            f"dadurch unvollständig bzw. zu niedrig. Für einen vollständigen "
            f"Rückblick den Snapshot mit größerem Lookback neu ziehen "
            f"(Daten aktualisieren).",
            kind="warning",
            title="Periode reicht vor den verfügbaren Datenbestand zurück",
        )

if not _enriched:
    alert_card(
        "Die Reservation-Sektionen (Gruppen-Größe, Vorlaufzeit/Storno, "
        "Firmenkunden, Vertragscodes) laufen noch auf der services-inklusiven "
        "Reservations-Basis. Für die konsistente Stay-Date-Sicht nach "
        "Erstellungsdatum einmal Voll-Refresh ziehen (Daten aktualisieren).",
        kind="info",
    )

kpi_old = H.landscape_kpis(
    nig_old, units, days_old, reservations=res, realized_only=_realized_only,
)
kpi_new = H.landscape_kpis(
    nig_new, units, days_new, reservations=res, realized_only=_realized_only,
)

if kpi_old["revenue_eur"] > 0:
    pct = (kpi_new["revenue_eur"] / kpi_old["revenue_eur"] - 1) * 100
    if pct < -5:
        highlights.append(
            {
                "kind": "alert",
                "title": f"Revenue {pct:+.1f}% YoY",
                "message": (
                    f"{H.fmt_eur(kpi_new['revenue_eur'])} ggü. "
                    f"{H.fmt_eur(kpi_old['revenue_eur'])} - "
                    f"Δ {H.fmt_eur(kpi_new['revenue_eur'] - kpi_old['revenue_eur'])}."
                ),
            }
        )
    elif pct > 5:
        highlights.append(
            {
                "kind": "success",
                "title": f"Revenue +{pct:.1f}% YoY",
                "message": f"Starker Vergleichszeitraum: {H.fmt_eur(kpi_new['revenue_eur'])}.",
            }
        )

if kpi_old["occupancy_pct"] > 0:
    shift = kpi_new["occupancy_pct"] - kpi_old["occupancy_pct"]
    if shift < -5:
        highlights.append(
            {
                "kind": "warning",
                "title": f"Occupancy {shift:+.1f}pp",
                "message": (
                    f"Von {kpi_old['occupancy_pct']:.1f}% auf {kpi_new['occupancy_pct']:.1f}%."
                ),
            }
        )

c_old = (res_old["is_cancelled"].mean() * 100) if len(res_old) else 0.0
c_new = (res_new["is_cancelled"].mean() * 100) if len(res_new) else 0.0
if c_new - c_old > 5:
    highlights.append(
        {
            "kind": "warning",
            "title": f"Storno-Quote +{c_new - c_old:.1f}pp",
            "message": f"Von {c_old:.1f}% auf {c_new:.1f}%.",
        }
    )

alert_cards(highlights)

# bei später öffnung alter system
_opening = H.opening_date(property_code)
_open_old = H.is_open_in_period(property_code, start_old, end_old)
_open_new = H.is_open_in_period(property_code, start_new, end_new)

_open_str = f"{_opening:%d.%m.%Y}" if _opening else "(kein Eröffnungsdatum hinterlegt)"

if not _open_old and not _open_new:
    alert_card(
        f"{LABEL} wurde erst am {_open_str} eröffnet und war in keiner "
        f"der beiden gewählten Perioden offen. Für diesen Zeitraum gibt es noch "
        f"keine Daten. Wähle in der Sidebar Perioden nach dem Eröffnungsdatum, "
        f"dann läuft die Analyse.",
        kind="warning",
        title=f"{H.city(property_code)} war im gewählten Zeitraum noch nicht offen",
    )
    st.stop()

# Warnung wenn der Standort in der OLD-Periode noch nicht offen war,
# in der NEW-Periode aber schon (später Öffner - YoY nicht aussagekräftig).
if not _open_old and _open_new:
    alert_card(
        f"{LABEL} wurde erst am {_open_str} eröffnet. Fie Vergleichs-"
        f"Periode ({PERIOD_TAG_OLD}) liegt davor. Die OLD-Werte sind daher 0 "
        f"und alle YoY-Vergleiche (Δ, Trend-Linien) sind für diesen Standort nicht "
        f"aussagekräftig. Die NEW-Periode ({PERIOD_TAG_NEW}) wird normal "
        f"ausgewertet. Tipp: OLD auf einen Zeitraum nach Eröffnung setzen für einen "
        f"echten Vergleich.",
        kind="warning",
        title="Vergleichs-Periode liegt vor der Eröffnung - YoY nicht aussagekräftig",
    )
# Warnung wenn die NEW-Periode in der Zukunft liegt (Snapshot kann nicht in
# die Zukunft schauen - Stay-Daten sind 0, Created-Daten nur bis snapshot_date).
if start_new > SNAP_DATE:
    alert_card(
        f"NEW-Periode ({PERIOD_TAG_NEW}) liegt ganz in der Zukunft des "
        f"Snapshots ({SNAP_DATE:%d.%m.%Y}). Realisiertes Revenue = 0, nur "
        f"Forward-Bookings sind sichtbar.",
        kind="warning",
        title="NEW-Periode liegt in der Zukunft",
    )

reset_export(PAGE)
st.divider()


# ===== 1 · Landscape KPIs =================================================
with section(
    1,
    "Landscape KPIs",
    subtitle=f"{LABEL} · {PERIOD_TAG_OLD} vs {PERIOD_TAG_NEW}",
    description="Headline-KPIs - folgen dem Storno/No-Show-Toggle (Default: realized, "
    "d.h. Storno + No-Show ausgeschlossen).",
):
    _plan_active = CD.get_active_plan()
    plan_new_eur = H.plan_revenue(property_code, start_new, end_new, plan=_plan_active)
    delta_plan_eur = kpi_new["revenue_eur"] - plan_new_eur
    delta_plan_pct = (
        (kpi_new["revenue_eur"] / plan_new_eur - 1) * 100 if plan_new_eur > 0 else float("nan")
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(
        "Revenue (€)",
        H.fmt_eur(kpi_new["revenue_eur"]),
        delta=f"{kpi_new['revenue_eur'] - kpi_old['revenue_eur']:+,.0f} €".replace(",", "."),
        help=KPI_REVENUE,
    )
    c2.metric(
        "Δ vs PLAN",
        f"{delta_plan_pct:+.1f} %" if not np.isnan(delta_plan_pct) else "kein PLAN",
        delta=(
            f"{delta_plan_eur:+,.0f} €".replace(",", ".")
            if plan_new_eur > 0
            else f"PLAN {H.fmt_eur(plan_new_eur)}"
        ),
        help=(
            "IST-Revenue der NEW-Periode vs. PLAN aus dem BigQuery-Snapshot "
            "(`ref_tables.plan`). Grau = kein PLAN hinterlegt."
        ),
    )
    c3.metric(
        "ADR (€)",
        H.fmt_eur(kpi_new["adr_eur"]),
        delta=(
            f"{kpi_new['adr_eur'] - kpi_old['adr_eur']:+.2f} €"
            if kpi_old.get("adr_eur") and not np.isnan(kpi_old["adr_eur"])
            else None
        ),
        help=KPI_ADR,
    )
    c4.metric(
        "Occupancy",
        f"{kpi_new['occupancy_pct']:.1f} %",
        delta=f"{kpi_new['occupancy_pct'] - kpi_old['occupancy_pct']:+.1f} pp",
        help=KPI_OCCUPANCY,
    )
    c5.metric(
        "ALOS",
        f"{kpi_new['alos_nights']:.1f} N." if not np.isnan(kpi_new["alos_nights"]) else "–",
        delta=(
            f"{kpi_new['alos_nights'] - kpi_old['alos_nights']:+.2f}"
            if not (np.isnan(kpi_old["alos_nights"]) or np.isnan(kpi_new["alos_nights"]))
            else None
        ),
        help=KPI_ALOS,
    )

    def _f(v, dec=2, suffix=""):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return "–"
        return f"{v:,.{dec}f}{suffix}".replace(",", "X").replace(".", ",").replace("X", ".")

    with st.expander("Berechnungs-Details · ADR / ALOS (Timeslice vs Reservation)", expanded=False):
        st.markdown(
            "Beide Werte sind aus **`timeslices.parquet`** (eine Zeile = eine "
            "genutzte Nacht). Unterschied ist nur der Aggregations-Modus.\n\n"
            "- **Variante A (Timeslice / window-intern):** nur Nights im "
            "Filter-Fenster zählen. Wenn eine 14-Nacht-Buchung 3 Nights im "
            "Window hat, zählen 3.\n"
            "- **Variante B (Reservation-based):** die ganze Booking-LOS zählt "
            "wenn ≥ 1 Nacht im Fenster ist. Dieselbe 14-Nacht-Buchung zählt "
            "als 14.\n\n"
            "In"
            "In den Cards oben:  \n"
            "**ADR** = Variante A \n"
            "**ALOS** = Variante B"
        )
        details = pd.DataFrame(
            {
                "Kennzahl": [
                    "ADR (Variante A · Timeslice)",
                    "ADR (Variante B · Reservation)",
                    "ALOS (Variante A · Timeslice)",
                    "ALOS (Variante B · Reservation)",
                ],
                f"{YEAR_OLD}": [
                    _f(kpi_old["adr_eur"], 2, " €"),
                    _f(kpi_old.get("adr_eur_reservation"), 2, " €"),
                    _f(kpi_old.get("alos_nights_timeslice"), 2, " N."),
                    _f(kpi_old["alos_nights"], 2, " N."),
                ],
                f"{YEAR_NEW}": [
                    _f(kpi_new["adr_eur"], 2, " €"),
                    _f(kpi_new.get("adr_eur_reservation"), 2, " €"),
                    _f(kpi_new.get("alos_nights_timeslice"), 2, " N."),
                    _f(kpi_new["alos_nights"], 2, " N."),
                ],
            }
        )
        st.dataframe(details, hide_index=True, use_container_width=True)
        st.caption(
            "Zahlen können zu existierenden Dashboards abweichen wenn eine andere Variante genutzt wurde."
        )

    monthly_o = H.monthly_landscape(nig_old, units, realized_only=_realized_only)
    monthly_n = H.monthly_landscape(nig_new, units, realized_only=_realized_only)
    show_trend = (
        len(monthly_o) >= 1 and len(monthly_n) >= 1 and max(len(monthly_o), len(monthly_n)) >= 2
    )
    if show_trend:
        png = CD.chart_png(
            _ck("kpis"),
            charts.landscape_kpis_chart,
            kpi_old,
            kpi_new,
            monthly_o,
            monthly_n,
            YEAR_OLD,
            YEAR_NEW,
            LABEL,
        )
        st.image(png, use_container_width=False)
    else:
        st.caption(
            "Trend-Linien werden ausgeblendet da "
            "eine der Perioden keine oder nur einen Monat Daten hat."
        )
        png = None

    kpi_tbl = pd.DataFrame(
        {
            "Metrik": [
                "Revenue (€)",
                "ADR (€)",
                "Occupancy (%)",
                "ALOS (Nächte)",
                "Buchungen",
            ],
            f"{YEAR_OLD}": [
                H.fmt_eur(kpi_old["revenue_eur"]),
                H.fmt_eur(kpi_old["adr_eur"]),
                f"{kpi_old['occupancy_pct']:.1f}",
                f"{kpi_old['alos_nights']:.1f}" if not np.isnan(kpi_old["alos_nights"]) else "–",
                f"{kpi_old['n_bookings']:,}".replace(",", "."),
            ],
            f"{YEAR_NEW}": [
                H.fmt_eur(kpi_new["revenue_eur"]),
                H.fmt_eur(kpi_new["adr_eur"]),
                f"{kpi_new['occupancy_pct']:.1f}",
                f"{kpi_new['alos_nights']:.1f}" if not np.isnan(kpi_new["alos_nights"]) else "–",
                f"{kpi_new['n_bookings']:,}".replace(",", "."),
            ],
        }
    )
    st.dataframe(kpi_tbl, hide_index=True, use_container_width=True)
    register_section("kpis", "1 · Landscape KPIs", chart_png=png, table_df=kpi_tbl, page=PAGE)
    chart_help("kpis")
    push_snippet(
        "1 · Landscape KPIs",
        (
            f"**{LABEL}** · {PERIOD_TAG_NEW} vs {PERIOD_TAG_OLD}\n"
            f"- Revenue: {H.fmt_eur(kpi_new['revenue_eur'])} "
            f"(Δ {H.fmt_eur(kpi_new['revenue_eur'] - kpi_old['revenue_eur'])} YoY)\n"
            f"- vs PLAN: "
            f"{('keine Plan-Daten' if plan_new_eur <= 0 else f'{delta_plan_pct:+.1f} % ({H.fmt_eur(delta_plan_eur)})')}\n"
            f"- ADR: {H.fmt_eur(kpi_new['adr_eur'])}\n"
            f"- Occupancy: {kpi_new['occupancy_pct']:.1f} %\n"
            f"- ALOS: {kpi_new['alos_nights']:.1f} N."
        ),
    )
# ===== 2 · Pace by Month (NEU) ============================================
with section(
    2,
    "Pace by Month",
    subtitle=f"{LABEL} · {YEAR_OLD} vs {YEAR_NEW} · Stand {SNAP_DATE:%d.%m.%Y}",
    description=(
        f"Pro Monat: **{YEAR_OLD}/EoM** = finale Vorjahres-Realität · "
        f"**{YEAR_OLD}/Today** = Stand `{SNAP_DATE:%d.%m.%Y}` "
        f"im Vorjahr (was war on-the-books) · "
        f"**{YEAR_NEW}/Today** = aktueller Stand on-the-books."
    ),
):
    pace_df = H.pace_by_month(nightly, YEAR_OLD, YEAR_NEW, SNAP_DATE, properties=[property_code])
    png = CD.chart_png(_ck("pace"), charts.pace_by_month_chart, pace_df, LABEL, YEAR_OLD, YEAR_NEW)
    st.image(png, use_container_width=False)
    CD.data_table_expander(pace_df, filename=f"{property_code}_pace_by_month")
    register_section("pace_month", "2 · Pace by Month", chart_png=png, table_df=pace_df, page=PAGE)

    chart_help("pace_month")

# ===== 3 · Heatmap Channel × LOS ==========================================
with section(3, "Heatmap Channel × Aufenthaltsdauer"):
    png = CD.chart_png(
        _ck("ch_los"), charts.channel_los_heatmap, nig_old, nig_new, YEAR_OLD, YEAR_NEW, LABEL,
        realized_only=_realized_only,
    )
    st.image(png, use_container_width=False)
    _tbl_chlos = CDT.channel_los_table(nig_old, nig_new, YEAR_OLD, YEAR_NEW, realized_only=_realized_only)
    CD.data_table_expander(_tbl_chlos, filename=f"{property_code}_channel_los")
    register_section(
        "heat_ch_los", "3 · Heatmap Channel × LOS", chart_png=png, table_df=_tbl_chlos, page=PAGE
    )

    chart_help("heat_ch_los")
# ===== 4 · Heatmap Channel × Reisezweck × LOS =============================
with section(4, "Heatmap Channel × Business/Leisure × LOS"):
    png = CD.chart_png(
        _ck("ch_purp_los"),
        charts.channel_purpose_los_heatmap,
        nig_old,
        nig_new,
        YEAR_OLD,
        YEAR_NEW,
        LABEL,
        realized_only=_realized_only,
    )
    st.image(png, use_container_width=False)
    # Channel × Reisezweck × LOS
    _tbl_chpl = CDT.channel_purpose_los_table(nig_old, nig_new, YEAR_OLD, YEAR_NEW, realized_only=_realized_only)
    CD.data_table_expander(
        _tbl_chpl,
        filename=f"{property_code}_channel_purpose_los",
    )
    register_section(
        "heat_ch_purpose_los",
        "4 · Heatmap Channel × Reisezweck × LOS",
        chart_png=png,
        table_df=_tbl_chpl,
        page=PAGE,
    )

    chart_help("heat_ch_purpose_los")
# ===== 5 · LOS Revenue YoY ================================================
with section(5, "Aufenthaltsdauer (LOS) - Revenue YoY"):
    png = CD.chart_png(
        _ck("los_yoy"), charts.los_yoy, nig_old, nig_new, YEAR_OLD, YEAR_NEW, LABEL,
        realized_only=_realized_only,
    )
    st.image(png, use_container_width=False)
    _tbl_los = CDT.los_yoy_table(nig_old, nig_new, YEAR_OLD, YEAR_NEW, realized_only=_realized_only)
    CD.data_table_expander(_tbl_los, filename=f"{property_code}_los_yoy")
    register_section("los_yoy", "5 · LOS Revenue YoY", chart_png=png, table_df=_tbl_los, page=PAGE)

    chart_help("los_yoy")
# ===== 6 · Channel-Mix monatlich & YoY ====================================
if lazy_section(6, "Channel-Mix - monatlich & YoY"):
    png = CD.chart_png(
        _ck("channel_mix"), charts.channel_mix, nig_old, nig_new, nightly, YEAR_OLD, YEAR_NEW, LABEL,
        realized_only=_realized_only,
    )
    st.image(png, use_container_width=False)
    _tbl_chmix = CDT.channel_mix_table(nig_old, nig_new, YEAR_OLD, YEAR_NEW, realized_only=_realized_only)
    CD.data_table_expander(_tbl_chmix, filename=f"{property_code}_channel_mix")
    register_section(
        "channel_mix",
        "6 · Channel-Mix - monatlich & YoY",
        chart_png=png,
        table_df=_tbl_chmix,
        page=PAGE,
    )

    chart_help("channel_mix")
# ===== 7 · ALOS pro Channel ===============================================
if lazy_section(7, "ALOS pro Channel"):
    png = CD.chart_png(
        _ck("alos_ch"), charts.alos_per_channel, nig_old, nig_new, YEAR_OLD, YEAR_NEW, LABEL,
        realized_only=_realized_only,
    )
    st.image(png, use_container_width=False)
    _tbl_aloc = CDT.alos_channel_table(nig_old, nig_new, YEAR_OLD, YEAR_NEW, realized_only=_realized_only)
    CD.data_table_expander(_tbl_aloc, filename=f"{property_code}_alos_channel")
    register_section(
        "alos_channel", "7 · ALOS pro Channel", chart_png=png, table_df=_tbl_aloc, page=PAGE
    )

    chart_help("alos_channel")
# ===== 8 · Wochentag-Pattern Stay =========================================
if lazy_section(8, "Wochentag-Pattern - Stay"):
    png = CD.chart_png(
        _ck("wd_stay"),
        charts.weekday_pattern,
        nig_old,
        nig_new,
        "stay_weekday",
        YEAR_OLD,
        YEAR_NEW,
        LABEL,
        "Revenue je Stay-Wochentag",
        realized_only=_realized_only,
    )
    st.image(png, use_container_width=False)
    _tbl_wds = CDT.weekday_table(nig_old, nig_new, "stay_weekday", YEAR_OLD, YEAR_NEW, realized_only=_realized_only)
    CD.data_table_expander(_tbl_wds, filename=f"{property_code}_weekday_stay")
    register_section(
        "weekday_stay", "8 · Wochentag-Pattern - Stay", chart_png=png, table_df=_tbl_wds, page=PAGE
    )

    chart_help("weekday_stay")
# ===== 9 · Check-in-Pattern Anreise =======================================
if lazy_section(9, "Check-in-Pattern - Anreise"):
    png = CD.chart_png(
        _ck("wd_arr"),
        charts.weekday_pattern,
        nig_old,
        nig_new,
        "check_in_weekday",
        YEAR_OLD,
        YEAR_NEW,
        LABEL,
        "Revenue je Anreise-Wochentag",
        realized_only=_realized_only,
    )
    st.image(png, use_container_width=False)
    _tbl_wda = CDT.weekday_table(nig_old, nig_new, "check_in_weekday", YEAR_OLD, YEAR_NEW, realized_only=_realized_only)
    CD.data_table_expander(_tbl_wda, filename=f"{property_code}_weekday_arrival")
    register_section(
        "weekday_arr", "9 · Check-in-Pattern - Anreise", chart_png=png, table_df=_tbl_wda, page=PAGE
    )

    chart_help("weekday_arr")
# ===== 10 · Gruppen-Größe =================================================
if lazy_section(10, "Gruppen-Größe", subtitle="nach Erstellungsdatum · Stay-Date"):
    png = CD.chart_png(
        _ck("grp"), charts.group_size_yoy, res_old, res_new, YEAR_OLD, YEAR_NEW, LABEL,
        realized_only=_realized_only,
    )
    st.image(png, use_container_width=False)
    _tbl_grp = CDT.group_size_table(res_old, res_new, YEAR_OLD, YEAR_NEW, realized_only=_realized_only)
    CD.data_table_expander(_tbl_grp, filename=f"{property_code}_group_size")
    register_section(
        "group_size", "10 · Gruppen-Größe", chart_png=png, table_df=_tbl_grp, page=PAGE
    )

    chart_help("group_size")
# ===== 11 · Inland vs. Ausland ============================================
if lazy_section(11, "Inland vs. Ausland"):
    png = CD.chart_png(
        _ck("de_intl"), charts.de_vs_international, nig_old, nig_new, YEAR_OLD, YEAR_NEW, LABEL,
        realized_only=_realized_only,
    )
    st.image(png, use_container_width=False)
    _tbl_de = CDT.de_international_table(nig_old, nig_new, YEAR_OLD, YEAR_NEW, realized_only=_realized_only)
    CD.data_table_expander(_tbl_de, filename=f"{property_code}_de_international")
    register_section(
        "de_intl", "11 · Inland vs. Ausland", chart_png=png, table_df=_tbl_de, page=PAGE
    )

    chart_help("de_intl")
# ===== 12 · Top-Herkunftsländer ===========================================
if lazy_section(12, "Top-Herkunftsländer"):
    png = CD.chart_png(
        _ck("countries"), charts.top_countries, nig_old, nig_new, YEAR_OLD, YEAR_NEW, LABEL,
        realized_only=_realized_only,
    )
    st.image(png, use_container_width=False)
    _tbl_ctry = CDT.top_countries_table(nig_old, nig_new, YEAR_OLD, YEAR_NEW, realized_only=_realized_only)
    CD.data_table_expander(_tbl_ctry, filename=f"{property_code}_top_countries")
    register_section(
        "top_countries", "12 · Top-Herkunftsländer", chart_png=png, table_df=_tbl_ctry, page=PAGE
    )

    chart_help("top_countries")
# ===== 13 · Vorlaufzeit & Storno-Risiko ===================================
if lazy_section(
    13,
    "Vorlaufzeit & Storno-Risiko",
    subtitle="nach Erstellungsdatum · Stay-Date · n = Anzahl Buchungen pro Bucket",
):
    png = CD.chart_png(
        _ck("leadtime"), charts.leadtime_storno, res_old, res_new, YEAR_OLD, YEAR_NEW, LABEL
    )
    st.image(png, use_container_width=False)
    _tbl_lt = CDT.leadtime_table(res_old, res_new, YEAR_OLD, YEAR_NEW)
    CD.data_table_expander(_tbl_lt, filename=f"{property_code}_leadtime")
    register_section(
        "leadtime", "13 · Vorlaufzeit & Storno-Risiko", chart_png=png, table_df=_tbl_lt, page=PAGE
    )

    chart_help("leadtime")
# ===== 14 · Daily Occupancy nach LOS ======================================
if lazy_section(14, "Daily Occupancy nach LOS"):
    png = CD.chart_png(
        _ck("daily_occ"), charts.daily_occupancy_los, nightly, units, start_new, end_new, LABEL
    )
    st.image(png, use_container_width=False)
    # Daily-Occupancy-Summary: pro Tag im NEW-Window aggregierte Nights pro LOS-Bucket.
    _daily_mask = (nightly["stay_date"] >= start_new) & (nightly["stay_date"] <= end_new)
    if _realized_only:
        _daily_mask &= nightly["is_realized"]
    _daily = nightly[_daily_mask].copy()
    if not _daily.empty:
        _piv = (
            _daily.groupby(["stay_date", "los_bucket"], observed=True)
            .size()
            .unstack(fill_value=0)
            .sort_index()
        )
        _piv["Sold Nights"] = _piv.sum(axis=1)
        _piv["Occupancy (%)"] = (_piv["Sold Nights"] / max(units, 1) * 100).round(1)
        _occ_tbl = _piv.reset_index().rename(columns={"stay_date": "Datum"})
        _occ_tbl["Datum"] = pd.to_datetime(_occ_tbl["Datum"]).dt.date
        CD.data_table_expander(_occ_tbl, filename=f"{property_code}_daily_occupancy")
        register_section(
            "daily_occ",
            "14 · Daily Occupancy nach LOS",
            chart_png=png,
            table_df=_occ_tbl,
            page=PAGE,
        )
    else:
        register_section("daily_occ", "14 · Daily Occupancy nach LOS", chart_png=png, page=PAGE)

    chart_help("daily_occ")
# ===== 15 · Firmenkunden Überblick & Channel-Split ========================
if lazy_section(
    15,
    "Firmenkunden - Überblick & Channel-Split",
    subtitle="nach Erstellungsdatum · Stay-Date",
):
    png = CD.chart_png(
        _ck("corp_ov"), charts.corporate_overview, res_old, res_new, YEAR_OLD, YEAR_NEW, LABEL,
        realized_only=_realized_only,
    )
    st.image(png, use_container_width=False)

    st.markdown(f"""
#### Was diese Tabelle zeigt und was sie nicht zeigt

**Drin sind:** alle Firmen die in diesem Zeitraum gebucht haben egal über welchen Channel.
**Sortiert nach:** Revenue {YEAR_NEW} (Total über alle Channels) absteigend.
""")

    st.markdown(
        f"### Top-Firmenkunden nach Revenue {YEAR_NEW} (alle Channels)\n\n"
        f"Code-Spalte = `corporateCode` "
        f"Leer = kein Code im Datensatz."
    )
    top_firm_full = charts.top_companies_table(res_old, res_new, YEAR_OLD, YEAR_NEW, realized_only=_realized_only)
    top_firm = top_firm_full.head(12).copy()
    display_firm = top_firm.copy()
    for c in (f"Revenue {YEAR_OLD} (€)", f"Revenue {YEAR_NEW} (€)", "Δ Revenue (€)"):
        display_firm[c] = display_firm[c].map(H.fmt_eur)
    st.dataframe(display_firm, hide_index=True, use_container_width=True)

    register_section(
        "corp_overview",
        "15 · Firmenkunden - Überblick & Channel-Split",
        chart_png=png,
        table_df=top_firm,
        page=PAGE,
    )

    chart_help("corp_overview")
# ===== 16 · Direct Offline - Detail-Segmente ==============================
if lazy_section(
    16,
    "Direct Offline - Detail-Segmente",
    subtitle="nach Erstellungsdatum · Stay-Date",
):
    st.markdown("""
#### Wichtiger Unterschied zur Tabelle weiter oben

**Drin sind hier nur** Firmen die mindestens einmal über Direct Offline gebucht haben.
Sortiert wird nach Total New (Direct_Offline + Direct_Website + OTA zusammen).
""")

    png_wf, extras = CD.chart_png(
        _ck("do_wf"), charts.directoffline_waterfall, res_old, res_new, YEAR_OLD, YEAR_NEW, LABEL,
        realized_only=_realized_only,
    )
    st.image(png_wf, use_container_width=False)
    buckets = extras[0] if extras else None

    if buckets is not None:
        n_lost = len(buckets["lost"])
        n_shrunk = len(buckets["shrunk"])
        n_grown = len(buckets["grown"])
        n_gained = len(buckets["gained"])
        alert_card(
            f"verloren: {n_lost} · geschrumpft: {n_shrunk} · "
            f"gewachsen: {n_grown} · neu: {n_gained}",
            kind="info",
        )

    png_seg = CD.chart_png(
        _ck("do_seg"), charts.directoffline_segments, res_old, res_new, YEAR_OLD, YEAR_NEW, LABEL,
        realized_only=_realized_only,
    )
    st.image(png_seg, use_container_width=False)

    table_for_export = None
    if buckets is not None:
        all_firms = buckets["all"].index
        top_table = charts.build_channel_table(all_firms, res_old, res_new, realized_only=_realized_only)
        top_table_show = top_table.sort_values("Total new (€)", ascending=False).head(12).copy()
        st.markdown(f"### Top-Firmenkunden nach Total-Revenue ({YEAR_NEW})")
        display_top = top_table_show.copy()
        for c in [c for c in display_top.columns if c.endswith("(€)")]:
            display_top[c] = display_top[c].map(H.fmt_eur)
        st.dataframe(display_top, hide_index=True, use_container_width=True)
        table_for_export = top_table_show

        def _show_bucket(title: str, idx, sort_col: str):
            if len(idx) == 0:
                return
            tbl = charts.build_channel_table(idx, res_old, res_new, realized_only=_realized_only)
            tbl_show = tbl.sort_values(sort_col, ascending=False).head(5)
            st.markdown(f"### {title} - Top 5 nach Impact")
            disp = tbl_show.copy()
            for c in [c for c in disp.columns if c.endswith("(€)")]:
                disp[c] = disp[c].map(H.fmt_eur)
            st.dataframe(disp, hide_index=True, use_container_width=True)

        _show_bucket(
            f"Verlorene Firmen ({YEAR_OLD} → {YEAR_NEW})",
            buckets["lost"].index,
            "Direct_Offline old (€)",
        )
        _show_bucket(
            f"Geschrumpfte Firmen ({YEAR_OLD} → {YEAR_NEW})",
            buckets["shrunk"].index,
            "Δ Direct_Offline (€)",
        )
        _show_bucket(
            f"Gewachsene Firmen ({YEAR_OLD} → {YEAR_NEW})",
            buckets["grown"].index,
            "Δ Direct_Offline (€)",
        )
        _show_bucket(f"Neue Firmen ({YEAR_NEW})", buckets["gained"].index, "Direct_Offline new (€)")

    register_section(
        "do_waterfall",
        "16 · Direct Offline - Detail-Segmente",
        chart_png=png_wf,
        table_df=table_for_export,
        page=PAGE,
    )

    chart_help("do_waterfall")
# ===== 17 · Top Vertragscodes =============================================
if lazy_section(
    17,
    "Top Vertragscodes (aktuelle Periode)",
    subtitle="nach Erstellungsdatum · Stay-Date · welche `corporateCode` "
    "haben am meisten Revenue generiert?",
):
    top_codes = charts.top_codes_in_period(res_new, realized_only=_realized_only)
    if top_codes.empty:
        alert_card(
            f"Keine Buchungen mit gefülltem Vertragscode in der aktuellen "
            f"Periode ({PERIOD_TAG_NEW}).",
            kind="info",
        )
        register_section(
            "codes",
            "17 · Top Vertragscodes",
            body_markdown="Keine Vertragscodes in der Periode.",
            page=PAGE,
        )
        chart_help("codes")
    else:
        st.markdown(
            f"**{len(top_codes)} Codes mit Aktivität in {PERIOD_TAG_NEW}** · "
            f"Total-Revenue: **{H.fmt_eur(float(top_codes['Revenue (€)'].sum()))}**"
        )
        show = top_codes.head(15).copy()
        display_codes = show.copy()
        for c in ["Revenue (€)", "ADR (€)"]:
            if c in display_codes.columns:
                display_codes[c] = display_codes[c].map(
                    lambda v: H.fmt_eur(v) if pd.notna(v) else "–"
                )
        st.dataframe(display_codes, hide_index=True, use_container_width=True)
        register_section(
            "codes", "17 · Top Vertragscodes (aktuelle Periode)", table_df=show, page=PAGE
        )


# ===== Export =============================================================
st.divider()
st.subheader("Bericht exportieren")
download_button(
    page_title=f"Standort-Analyse · {LABEL} · {PERIOD_TAG_OLD} vs {PERIOD_TAG_NEW}",
    highlights=highlights,
    filename=f"standort_{property_code}_{start_new:%Y%m%d}.md",
    page=PAGE,
)

CD.collect()
