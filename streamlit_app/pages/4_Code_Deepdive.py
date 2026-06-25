"""Code Deep-Dive - eine Firma im 360°-Blick."""

from __future__ import annotations

import io
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT / "streamlit_app"))

import numpy as np
import pandas as pd
import streamlit as st

from components import cached_data as CD
from components import code_deepdive_charts as CC
from components import (
    download_button,
    inject_brand_css,
    lazy_section,
    preload_all_button,
    render_notepad,
    section,
    sync_snapshot_override,
)
from components.alerts import alert_card
from components.brand import hero
from components.export import register_section, reset_export
from revenueblindspots import helpers as H
from revenueblindspots import overrides as OV

st.set_page_config(
    page_title="Code Deep-Dive · Stayery",
    page_icon="🔍",
    layout="wide",
)
inject_brand_css()
CD.apply_stayery_style_once()
sync_snapshot_override()
CD.keep_session_state_alive()  # MUST run before any widget renders this page

PAGE = "code"
st.session_state["__page"] = PAGE

hero(
    eyebrow="Firma · 360°-Blick",
    title="Code Deep-Dive",
    subtitle="Code(s) eingeben - Revenue-Verlauf, Channel-Evolution, "
    "Stay-Pattern, Storno-Verhalten, Future Pipeline, "
    "Reservations-Excel-Export.",
)


# ============================== Sidebar filter =============================
with st.sidebar:
    st.header("Filter")

    meta = CD.get_metadata()
    if not meta:
        st.error("Kein Snapshot - bitte erst `Daten aktualisieren` ausführen.")
        st.stop()

    all_props = meta.get("properties") or H.all_properties()

    code_input = st.text_input(
        "Code(s)",
        value="",
        placeholder="z.B. GBG10 oder mehrere komma-getrennt",
        help="Wird gegen `corporateCode`, `company_code`, `effective_code` und "
        "(wenn aktiviert) `promoCode` gematcht.",
        key="cd_code_input",
    )
    props_pick = st.multiselect("Standorte", options=all_props, default=all_props, key="cd_props")
    include_promo = st.checkbox(
        "Promocodes einbeziehen",
        value=True,
        key="cd_include_promo",
        help="Matcht den/die Code(s) zusätzlich gegen `promoCode` - so lassen sich "
        "auch reine Promocodes hier ansehen (z.B. via Link aus der Promo-Page). "
        "Aus = strikt nur Corporate-/Company-/Effective-Code.",
    )

    # Default-Fokus = aktueller Monat (Anfang bis Ende). Ändert der User die Werte,
    # bleiben sie über Seitenwechsel erhalten (cd_*-Keys laufen über
    # keep_session_state_alive); der Default greift nur beim ersten Aufruf.
    _today = pd.Timestamp.today().normalize()
    _month_start = _today.replace(day=1).date()
    _month_end = (_today.replace(day=1) + pd.offsets.MonthEnd(1)).date()

    with st.form("code_dates", clear_on_submit=False, border=False):
        st.caption("Fokus-Periode")
        c1, c2 = st.columns(2)
        with c1:
            ps = st.date_input("Start", value=_month_start, key="cd_ps")
        with c2:
            pe = st.date_input("Ende", value=_month_end, key="cd_pe")
        lookback_years = st.slider(
            "Lookback-Jahre", min_value=1, max_value=7, value=3, key="cd_lookback_years"
        )
        alert_rate = st.slider(
            "Alert-Schwelle Storno-Quote (%)",
            min_value=10.0,
            max_value=50.0,
            value=25.0,
            step=5.0,
            key="cd_alert_rate",
        )
        st.form_submit_button("Periode anwenden", use_container_width=True)

    st.caption("Sektionen 3-7 laden erst auf Klick.")
    preload_all_button([3, 4, 5, 6, 7], label="Alle Sektionen laden")

    codes = [c.strip() for c in code_input.split(",") if c.strip()]
    if not codes:
        st.info("Mindestens einen Code eingeben.")
        st.stop()
    if not props_pick:
        st.warning("Bitte mindestens einen Standort wählen.")
        st.stop()
    period_start = pd.Timestamp(ps)
    period_end = pd.Timestamp(pe)

    st.divider()
    CD.cache_clear_button()
    st.caption(f"Snapshot vom **{str(meta.get('refreshed_at', '?'))[:10]}**")

render_notepad(PAGE)


window_days = (period_end - period_start).days + 1
prev_period_end = period_start - pd.Timedelta(days=1)
prev_period_start = prev_period_end - pd.Timedelta(days=window_days - 1)
lookback_start = (period_start - pd.DateOffset(years=lookback_years)).normalize()
lookback_end = max(pd.Timestamp.today().normalize(), period_end + pd.Timedelta(days=180))

codes_tag = "+".join(sorted(codes))


def _ck(section: str) -> str:
    return (
        f"code::{codes_tag}::{period_start.date()}::{period_end.date()}"
        f"::{lookback_years}::{section}"
    )


st.markdown(f"""
**Analyse-Setup:**
- Code(s): **{", ".join(f"`{c}`" for c in codes)}**
- Fokus-Periode: **{period_start:%d.%m.%Y} – {period_end:%d.%m.%Y}** ({window_days} Tage)
- Vorperiode (auto): **{prev_period_start:%d.%m.%Y} – {prev_period_end:%d.%m.%Y}**
- Lookback: **{lookback_start:%d.%m.%Y} – {lookback_end:%d.%m.%Y}**
""")

st.caption(
    "**Datenbasis & Filter:** Nacht-Netto (Counts = Buchungen). Lookback-Fenster "
    "über **Aufenthalt** (serviceDate); Fokus-/Vorperiode & **Future-Pipeline** nach "
    "**Anreise** (arrival). Revenue-Charts (Verlauf, Channel, Storno) nach "
    "Anreise-Monat. Lost-Revenue = einbehaltene Netto-Fee, gedeckelt aufs Nacht-Netto."
)


# ============================== Data load ==================================
# Revenue-Konsistenz: Code-/Firmen-Revenue läuft auf der Nacht-Netto-Basis -
# nightly auf Buchungs-Ebene zurückfalten (revenue = Summe der Nacht-Netto je
# Buchung, inkl. kept/lost). Perioden/Future bleiben arrival-basiert. Solange
# der Snapshot die gebroadcasteten Felder noch nicht trägt Fallback auf die
# services-inklusive Reservations + Hinweis-Banner.
with st.spinner("Lade Daten aus dem Parquet-Snapshot …"):
    nightly = CD.get_timeslices(start=lookback_start, end=lookback_end, properties=props_pick)
    _enriched = H.timeslices_are_enriched(nightly)
    if _enriched:
        res_all = H.reservations_from_timeslices(nightly)
    else:
        res_all = CD.get_reservations(start=lookback_start, end=lookback_end, properties=props_pick)
if res_all.empty:
    st.warning("Keine Reservierungen im Lookback-Zeitraum.")
    st.stop()
if not _enriched:
    alert_card(
        "Code-/Firmen-Revenue läuft noch auf der services-inklusiven "
        "Reservations-Basis. Für die konsistente Nacht-Netto-Sicht einmal "
        "Voll-Refresh ziehen (Daten aktualisieren).",
        kind="info",
    )

# promoCode lebt (vor dem Foundation-Refresh) nur in den Reservations - im
# Timeslices-Snapshot fehlt die Spalte noch. Damit reine Promocodes auch auf der
# Nacht-Netto-Basis auflösbar sind, joinen wir promoCode hier per `id` nach.
# Nach dem Refresh trägt der Timeslices-Snapshot promoCode selbst -> die Spalte
# ist dann schon da und dieser Schritt entfällt automatisch.
if include_promo and "promoCode" not in res_all.columns and "id" in res_all.columns:
    _pmap = CD.get_reservations(start=lookback_start, end=lookback_end, properties=props_pick)
    if {"id", "promoCode"}.issubset(_pmap.columns):
        res_all = res_all.merge(
            _pmap[["id", "promoCode"]].drop_duplicates("id"), on="id", how="left"
        )

res, firm_names_fuzzy, firm_names_raw = CC.resolve_codes_to_res(
    res_all, codes, include_promo=include_promo
)

if res.empty:
    st.error(f"Keine Buchungen für Code(s) **{', '.join(codes)}** im Lookback gefunden.")
    st.stop()

# "Code"-Anzeige robust machen: für reine Promo-Buchungen ist effective_code
# (= company_code ?? corporateCode) leer -> sonst bleibt die Code-Spalte in den
# Tabellen unten leer. Fallback auf den promoCode, damit immer ein Code steht.
if "effective_code" in res.columns and "promoCode" in res.columns:
    _eff = res["effective_code"].astype("string").str.strip()
    _empty = _eff.isna() | _eff.str.lower().isin(["", "nan", "none", "<na>", "null"])
    res.loc[_empty, "effective_code"] = res.loc[_empty, "promoCode"].astype("string").str.strip()

reset_export(PAGE)


# ===== 1 · Identity Card ==================================================
firm_label = firm_names_fuzzy[0] if firm_names_fuzzy else ", ".join(codes)
all_variants = " · ".join(firm_names_raw[:5]) + (" …" if len(firm_names_raw) > 5 else "")

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

in_period = res[(res["arrival"] >= period_start) & (res["arrival"] <= period_end)]
in_period_real = in_period[in_period["is_realized"]]
period_has_data = not in_period_real.empty
period_revenue = float(in_period_real["revenue"].sum())
period_nights = int(in_period_real["nights"].fillna(0).sum())
period_bookings = len(in_period)

prev_period = res[(res["arrival"] >= prev_period_start) & (res["arrival"] <= prev_period_end)]
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

# Code-Typ bestimmen: Corporate / Promo / beides / reklassifizierter Promo.
# corporateCode ist roh (apply_code_overrides setzt es nur für gelistete Codes,
# die hier zuerst als "reklassifiziert" abgefangen werden).
_codes_up = {c.upper() for c in codes}
_reclassified = set(OV.promo_overrides().keys())
_as_promo = (
    res["promoCode"].astype("string").str.strip().str.upper().isin(_codes_up).any()
    if "promoCode" in res.columns
    else False
)
_as_corp = (
    res["corporateCode"].astype("string").str.strip().str.upper().isin(_codes_up).any()
    if "corporateCode" in res.columns
    else False
)
if _codes_up & _reclassified:
    code_type = "Promo → reklass. Firmencode"
elif _as_corp and _as_promo:
    code_type = "Corporate & Promo"
elif _as_corp:
    code_type = "Corporatecode"
elif _as_promo:
    code_type = "Promocode"
else:
    code_type = "—"

st.markdown(f"## 1 · {firm_label}")
st.markdown(
    f"Code(s): **{', '.join(codes)}**  ·  Firmennamen-Varianten (raw): {all_variants or '-'}"
)

warns = []
if not period_has_data:
    warns.append(
        f"Fokus-Periode {period_start:%d.%m.%Y}–{period_end:%d.%m.%Y}: keine realisierten Buchungen"
    )
if not prev_has_data:
    warns.append(
        f"Vorperiode {prev_period_start:%d.%m.%Y}–{prev_period_end:%d.%m.%Y}: keine realisierten Buchungen"
    )
if warns:
    alert_card(
        "<br>".join(warns)
        + '<br>Periode-spezifische Werte als „-"; Lifetime + Charts zeigen volle Historie.',
        kind="warning",
        title="Hinweis zur Datenabdeckung",
    )

c1, c2, c3, c4, c_type = st.columns(5)
c1.metric(
    "Lifetime Revenue",
    H.fmt_eur(lifetime_revenue),
    delta=f"{n_realized:,} realisiert".replace(",", "."),
)
c2.metric(
    "Lifetime Nights",
    f"{lifetime_nights:,}".replace(",", "."),
    delta=f"ADR ø {H.fmt_eur(adr_lifetime)}",
)
c3.metric("Erste Buchung", f"{first_booking:%d.%m.%Y}", delta=f"letzte {last_booking:%d.%m.%Y}")
c_type.metric("Code-Typ", code_type)
c4.metric(
    "Cancel-Rate",
    f"{cancel_rate:.1f} %",
    delta=("⚠ über Alert" if cancel_rate > alert_rate else "im Korridor"),
    delta_color=("inverse" if cancel_rate > alert_rate else "normal"),
)

st.markdown(" ")

c5, c6, c7 = st.columns(3)
c5.metric(
    f"Period Revenue ({period_start:%d.%m}–{period_end:%d.%m})",
    H.fmt_eur(period_revenue) if period_has_data else "-",
    delta=(f"{period_bookings} B. · {period_nights} N." if period_has_data else None),
)
c6.metric(
    "vs. Vorperiode",
    f"{period_yoy_pct:+.1f} %" if pd.notna(period_yoy_pct) else "-",
    delta=(f"Vorperiode {H.fmt_eur(prev_revenue)} · {prev_bookings} B." if prev_has_data else None),
)
c7.metric(
    "Future Pipeline",
    H.fmt_eur(future_revenue),
    delta=f"{future_bookings} offene Buchungen",
)

register_section(
    "identity",
    f"1 · {firm_label}",
    body_markdown=(
        f"**Code(s):** {', '.join(codes)}  \n"
        f"**Firmennamen-Varianten:** {all_variants or '-'}  \n"
        f"**Lifetime:** {H.fmt_eur(lifetime_revenue)} · {lifetime_nights:,} Nächte"
        f" · ADR ø {H.fmt_eur(adr_lifetime)}  \n"
        f"**Cancel-Rate:** {cancel_rate:.1f} %  \n"
        f"**Erste/Letzte Buchung:** {first_booking:%d.%m.%Y} / {last_booking:%d.%m.%Y}\n\n"
        f"**Periode:** {'-' if not period_has_data else H.fmt_eur(period_revenue)}  \n"
        f"**vs. Vorperiode:** {'-' if pd.isna(period_yoy_pct) else f'{period_yoy_pct:+.1f} %'}  \n"
        f"**Future Pipeline:** {H.fmt_eur(future_revenue)} ({future_bookings} offene Buchungen)"
    ),
    page=PAGE,
)
st.divider()


# ===== 2 · Revenue-Verlauf ================================================
with section(
    2, "Revenue-Verlauf", subtitle="Monatlich · 3M-Rolling · Kumulativ · Fokus-Periode markiert"
):
    png, extras = CD.chart_png(
        _ck("rev_tl"), CC.revenue_timeline, res, firm_label, period_start, period_end
    )
    st.image(png, use_container_width=False)
    monthly, cum = extras if extras else (None, None)
    if monthly is not None and len(monthly):
        monthly_tbl = (
            pd.DataFrame(
                {
                    "Monat": monthly.index.strftime("%Y-%m"),
                    "Revenue (€)": monthly.values.round(2),
                    "Kumulativ (€)": cum.values.round(2),
                    "Δ vs. Vormonat (€)": monthly.diff().fillna(0).values.round(2),
                }
            )
            .sort_values("Monat", ascending=False)
            .reset_index(drop=True)
        )
        with st.expander(f"Monats-Tabelle ({len(monthly_tbl)} Monate)"):
            st.dataframe(monthly_tbl, hide_index=True, use_container_width=True, height=320)
        register_section(
            "revenue_timeline",
            "2 · Revenue-Verlauf",
            chart_png=png,
            table_df=monthly_tbl.head(24),
            page=PAGE,
        )
    else:
        register_section("revenue_timeline", "2 · Revenue-Verlauf", chart_png=png, page=PAGE)


# ===== 3 · Channel-Evolution ==============================================
if lazy_section(3, "Channel-Evolution"):
    png, extras = CD.chart_png(
        _ck("ch_evo"),
        CC.channel_evolution,
        res,
        firm_label,
        period_start,
        period_end,
        prev_period_start,
        prev_period_end,
    )
    st.image(png, use_container_width=False)
    cur_ch, prev_ch = extras if extras else (None, None)

    if cur_ch is not None and prev_ch is not None:
        shift = pd.DataFrame(
            {
                "Channel": cur_ch.index,
                "Vorperiode (€)": prev_ch.values.round(2),
                "Fokus-Periode (€)": cur_ch.values.round(2),
                "Δ (€)": (cur_ch.values - prev_ch.values).round(2),
                "Anteil vor (%)": (prev_ch / max(prev_ch.sum(), 1) * 100).round(1).values,
                "Anteil aktuell (%)": (cur_ch / max(cur_ch.sum(), 1) * 100).round(1).values,
            }
        )
        st.markdown("**Channel-Tabelle · Periode-Vergleich**")
        st.dataframe(shift, hide_index=True, use_container_width=True)
        register_section(
            "channel_evo", "3 · Channel-Evolution", chart_png=png, table_df=shift, page=PAGE
        )
    else:
        alert_card(
            "Channel-Vergleich übersprungen - mindestens eine Periode hat keine "
            "realisierten Buchungen.",
            kind="info",
        )
        register_section("channel_evo", "3 · Channel-Evolution", chart_png=png, page=PAGE)


# ===== 4 · Stay-Pattern ===================================================
if lazy_section(
    4,
    "Stay-Pattern",
    subtitle="6 Panels: LOS · Standort · Wochentag · Zimmerkategorie · Vorlauf · Gruppen-Größe",
):
    png = CD.chart_png(_ck("stay_pat"), CC.stay_patterns, res, firm_label)
    st.image(png, use_container_width=False)

    realized_for_loc = res[res["is_realized"]]
    if not realized_for_loc.empty:
        loc_tbl = (
            realized_for_loc.groupby("property_code")
            .agg(
                Buchungen=("id", "nunique"),
                Nächte=("nights", "sum"),
                Revenue=("revenue", "sum"),
            )
            .reset_index()
            .rename(columns={"property_code": "Standort", "Revenue": "Revenue (€)"})
        )
        loc_tbl["ADR (€)"] = (loc_tbl["Revenue (€)"] / loc_tbl["Nächte"].replace(0, np.nan)).round(
            2
        )
        loc_tbl["Revenue (€)"] = loc_tbl["Revenue (€)"].round(2)
        loc_tbl = loc_tbl.sort_values("Revenue (€)", ascending=False).reset_index(drop=True)
        st.markdown(f"**Standort-Aufteilung · {firm_label}**")
        st.dataframe(loc_tbl, hide_index=True, use_container_width=True)
        register_section(
            "stay_pattern", "4 · Stay-Pattern", chart_png=png, table_df=loc_tbl, page=PAGE
        )
    else:
        register_section("stay_pattern", "4 · Stay-Pattern", chart_png=png, page=PAGE)


# ===== 5 · Storno-View ====================================================
if lazy_section(
    5, "Storno-Verhalten", subtitle="Storno-Timing vor Anreise + monatliche Storno-Quote"
):
    png = CD.chart_png(
        _ck("storno"), CC.storno_view, res, firm_label, alert_cancel_rate_pct=alert_rate
    )
    st.image(png, use_container_width=False)

    lost_revenue_total = float(res["lost_revenue"].sum()) if "lost_revenue" in res.columns else 0.0
    realized_revenue = float(res[res["is_realized"]]["revenue"].sum())
    st.markdown(
        f"**Storno-Ökonomie über die Lifetime:**  \n"
        f"- realisierter Revenue: **{H.fmt_eur(realized_revenue)}**  \n"
        f"- verlorener Revenue: **{H.fmt_eur(lost_revenue_total)}**"
    )
    st.caption(
        "Verlorener Revenue = Nacht-Netto der Stornos/No-Shows MINUS einbehaltene "
        "Netto-Fee (nicht die volle Buchung). Storno-Timing über `cancellationTime` "
        "(Fallback `modified` als Proxy)."
    )
    # Datentabelle: monatliche Storno-Quote
    _stor = res.copy()
    _stor["ym"] = _stor["arrival"].dt.to_period("M").astype(str)
    _stor_tbl = (
        _stor.groupby("ym")
        .agg(
            Buchungen=("id", "count"),
            Storniert=("is_cancelled", "sum"),
            No_Show=("is_no_show", "sum"),
            Realisiert=("is_realized", "sum"),
            Revenue=("revenue", "sum"),
        )
        .reset_index()
    )
    _stor_tbl["Storno-Quote (%)"] = (
        _stor_tbl["Storniert"] / _stor_tbl["Buchungen"].replace(0, np.nan) * 100
    ).round(1)
    _stor_tbl["Revenue"] = _stor_tbl["Revenue"].round(2)
    _stor_tbl = _stor_tbl.rename(columns={"ym": "Monat", "Revenue": "Revenue (€)"})
    _stor_tbl = _stor_tbl.sort_values("Monat", ascending=False)
    CD.data_table_expander(_stor_tbl, filename=f"code_{codes[0]}_storno_monthly")
    register_section(
        "storno", "5 · Storno-Verhalten", chart_png=png, table_df=_stor_tbl.head(24), page=PAGE
    )


# ===== 6 · Future Pipeline ================================================
pipeline_df: pd.DataFrame | None = None
if lazy_section(6, "Future Pipeline", subtitle="Offene Buchungen mit Anreise > heute"):
    future_table = res[(res["arrival"] > today) & ~res["is_cancelled"]].copy()
    if future_table.empty:
        alert_card("Keine offenen Buchungen mit Anreise in der Zukunft.", kind="info")
        register_section(
            "pipeline", "6 · Future Pipeline", body_markdown="Keine offenen Buchungen.", page=PAGE
        )
    else:
        pipe_cols = {
            "id": "Buchungs-ID",
            "arrival": "Anreise",
            "departure": "Abreise",
            "nights": "Nächte",
            "adults": "Personen",
            "property_code": "Standort",
            "channel_combo": "Channel",
            "effective_code": "Code",
            "promoCode": "Promocode",
            "ratePlan_name": "Rate-Plan",
            "status": "Status",
            "revenue": "Revenue (€)",
        }
        present = {k: v for k, v in pipe_cols.items() if k in future_table.columns}
        pipe = future_table[list(present.keys())].copy().rename(columns=present)
        if "Anreise" in pipe.columns:
            pipe["Anreise"] = pd.to_datetime(pipe["Anreise"]).dt.date
        if "Abreise" in pipe.columns:
            pipe["Abreise"] = pd.to_datetime(pipe["Abreise"]).dt.date
        if "Revenue (€)" in pipe.columns:
            pipe["Revenue (€)"] = pipe["Revenue (€)"].astype(float).round(2)
        if "Nächte" in pipe.columns:
            pipe["Nächte"] = pipe["Nächte"].astype(int)
        pipe = pipe.sort_values(["Anreise", "Standort"], na_position="last").reset_index(drop=True)
        pipeline_df = pipe

        st.markdown(
            f"**{len(pipe)} offene Buchungen** · erwarteter Revenue: "
            f"**{H.fmt_eur(float(pipe['Revenue (€)'].sum())) if 'Revenue (€)' in pipe.columns else '-'}**"
        )
        st.dataframe(pipe, hide_index=True, use_container_width=True, height=420)
        register_section("pipeline", "6 · Future Pipeline", table_df=pipe.head(50), page=PAGE)


# ===== 7 · Reservations-Download ==========================================
reservations_df: pd.DataFrame | None = None
if lazy_section(7, "Reservations-Tabelle", subtitle="Alle Buchungen für diese Code(s) - Lifetime"):
    download_cols = [
        "id",
        "bookingId",
        "status",
        "arrival",
        "departure",
        "created",
        "property_code",
        "channel_combo",
        "effective_code",
        "corporateCode",
        "promoCode",
        "company",
        "firm_by_effective_fuzzy",
        "travelPurpose",
        "ratePlan_code",
        "ratePlan_name",
        "unitGroup_name",
        "nights",
        "adults",
        "los_bucket",
        "lead_time_days",
        "lead_time_bucket",
        "revenue",
        "kept_revenue",
        "lost_revenue",
        "is_realized",
        "is_cancelled",
        "is_no_show",
        "cancel_lead_time_days",
    ]
    present = [c for c in download_cols if c in res.columns]
    res_dl = (
        res[present]
        .copy()
        .sort_values(["arrival", "id"] if "id" in present else ["arrival"])
        .reset_index(drop=True)
    )
    rename = {
        "id": "Reservation-ID",
        "bookingId": "Booking-ID",
        "status": "Status",
        "arrival": "Anreise",
        "departure": "Abreise",
        "created": "Erstellt",
        "property_code": "Standort",
        "channel_combo": "Channel",
        "effective_code": "Code (effektiv)",
        "promoCode": "Promocode",
        "company": "Firma (Priority)",
        "firm_by_effective_fuzzy": "Firma (Fuzzy)",
        "travelPurpose": "Reisezweck",
        "nights": "Nächte",
        "adults": "Personen",
        "revenue": "Revenue (€)",
        "kept_revenue": "Behaltener Revenue (€)",
        "lost_revenue": "Verlorener Revenue (€)",
        "is_realized": "Realisiert?",
        "is_cancelled": "Storniert?",
        "is_no_show": "No-Show?",
        "cancel_lead_time_days": "Cancel-Vorlauf (Tage)",
        "lead_time_days": "Vorlaufzeit (Tage)",
        "lead_time_bucket": "Vorlauf-Bucket",
        "los_bucket": "LOS-Bucket",
        "ratePlan_code": "Rate-Plan-Code",
        "ratePlan_name": "Rate-Plan",
        "unitGroup_name": "Zimmerkategorie",
    }
    res_dl = res_dl.rename(columns={k: v for k, v in rename.items() if k in res_dl.columns})
    reservations_df = res_dl

    st.markdown(
        f"**{len(res_dl):,} Reservierungen** - Lifetime-Schnitt für die Codes.".replace(",", ".")
    )
    st.dataframe(res_dl.head(10), hide_index=True, use_container_width=True)


# ===== Sammel-Export =======================================================
st.divider()
st.subheader("Bericht exportieren")

if pipeline_df is not None or reservations_df is not None:
    bundle_buf = io.BytesIO()
    with pd.ExcelWriter(bundle_buf, engine="openpyxl") as w:
        if reservations_df is not None:
            reservations_df.to_excel(w, sheet_name="reservations", index=False)
        if pipeline_df is not None:
            pipeline_df.to_excel(w, sheet_name="pipeline", index=False)
    st.download_button(
        "Alle Daten als Excel",
        data=bundle_buf.getvalue(),
        file_name=f"code_{codes[0]}_export.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="dl_code_all",
    )

download_button(
    page_title=f"Code Deep-Dive · {firm_label}",
    filename=f"code_{codes[0]}_recap.md",
    page=PAGE,
)

CD.collect()
