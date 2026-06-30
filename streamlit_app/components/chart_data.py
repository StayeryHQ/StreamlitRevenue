"""Daten-Tabellen für die Charts.

Konvention:
  - Eingabe spiegelt die Chart-Funktion (dieselben DataFrames + Perioden).
  - Rückgabe = formatierter DataFrame
  - ``@st.cache_data`` für Reuse zwischen Chart-Render und Expander-Render.
  - Storno-Konventionen identisch zu den jeweiligen Charts
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from revenueblindspots import helpers as H


# =========================================================================
# Standort-Analyse
# =========================================================================
@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def channel_los_table(nig_old: pd.DataFrame, nig_new: pd.DataFrame,
                       year_old: int, year_new: int, realized_only: bool = True) -> pd.DataFrame:
    """Sektion 3 - Channel × LOS-Bucket Pivot (Revenue + YoY-%)."""
    cols = ["short_<=6", "mid_7-28", "long_29+"]

    def piv(df):
        r = df[df["is_realized"]] if realized_only else df
        if r.empty:
            return pd.DataFrame(0.0, index=["Direct", "OTA"], columns=cols)
        ch = np.where(r["channel_combo"].str.startswith("Direct"), "Direct", "OTA")
        out = (pd.DataFrame({"ch": ch, "los": r["los_bucket"], "rev": r["revenue"]})
                 .groupby(["ch", "los"], observed=True)["rev"].sum()
                 .unstack(fill_value=0.0))
        return out.reindex(index=["Direct", "OTA"], columns=cols, fill_value=0.0)

    a, b = piv(nig_old), piv(nig_new)
    rows = []
    for ch in ["Direct", "OTA"]:
        for los in cols:
            ro = float(a.loc[ch, los])
            rn = float(b.loc[ch, los])
            d_pct = ((rn / ro - 1) * 100) if ro > 0 else float("nan")
            rows.append({
                "Channel": ch,
                "LOS-Bucket": los,
                f"Revenue {year_old} (€)": round(ro, 2),
                f"Revenue {year_new} (€)": round(rn, 2),
                "Δ (€)": round(rn - ro, 2),
                "Δ (%)": round(d_pct, 1) if pd.notna(d_pct) else None,
            })
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def channel_purpose_los_table(nig_old: pd.DataFrame, nig_new: pd.DataFrame,
                                year_old: int, year_new: int, realized_only: bool = True) -> pd.DataFrame:
    """Sektion 4 - Channel × Reisezweck (Business / Leisure) × LOS-Bucket"""
    channels = ["Direct_Website", "Direct_Offline", "OTA"]
    purposes = ["Business", "Leisure"]
    cols = ["short_<=6", "mid_7-28", "long_29+"]

    def agg(nig):
        d = (nig[nig["is_realized"]] if realized_only else nig).copy()
        if d.empty:
            return {}
        d["ch"] = d["channel_combo"].where(
            d["channel_combo"].isin(["Direct_Website", "Direct_Offline"]), "OTA")
        d["purpose"] = np.where(
            d["travelPurpose"].astype(str).str.lower().eq("business"),
            "Business", "Leisure",
        )
        return d.groupby(["ch", "purpose", "los_bucket"], observed=True)["revenue"].sum().to_dict()

    a, b = agg(nig_old), agg(nig_new)
    rows = []
    for ch in channels:
        for p in purposes:
            for los in cols:
                ro = float(a.get((ch, p, los), 0.0))
                rn = float(b.get((ch, p, los), 0.0))
                d_pct = ((rn / ro - 1) * 100) if ro > 0 else float("nan")
                rows.append({
                    "Channel": ch,
                    "Reisezweck": p,
                    "LOS-Bucket": los,
                    f"Revenue {year_old} (€)": round(ro, 2),
                    f"Revenue {year_new} (€)": round(rn, 2),
                    "Δ (€)": round(rn - ro, 2),
                    "Δ (%)": round(d_pct, 1) if pd.notna(d_pct) else None,
                })
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def los_yoy_table(nig_old: pd.DataFrame, nig_new: pd.DataFrame,
                    year_old: int, year_new: int, realized_only: bool = True) -> pd.DataFrame:
    """Sektion 5 - LOS-Bucket × Revenue YoY."""
    order = ["short_<=6", "mid_7-28", "long_29+"]

    def agg(df):
        r = df[df["is_realized"]] if realized_only else df
        if r.empty:
            return pd.Series(0.0, index=order)
        return r.groupby("los_bucket", observed=True)["revenue"].sum().reindex(order, fill_value=0.0)

    a, b = agg(nig_old), agg(nig_new)
    sum_a = a.sum() or 1
    sum_b = b.sum() or 1
    rows = []
    for los in order:
        rows.append({
            "LOS-Bucket": los,
            f"Revenue {year_old} (€)": round(float(a[los]), 2),
            f"Revenue {year_new} (€)": round(float(b[los]), 2),
            f"Anteil {year_old} (%)": round(float(a[los] / sum_a * 100), 1),
            f"Anteil {year_new} (%)": round(float(b[los] / sum_b * 100), 1),
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def channel_mix_table(nig_old: pd.DataFrame, nig_new: pd.DataFrame,
                       year_old: int, year_new: int, realized_only: bool = True) -> pd.DataFrame:
    """Sektion 6 - Channel × Total-Revenue YoY (realized)."""

    def agg(df):
        r = df[df["is_realized"]] if realized_only else df
        if r.empty:
            return pd.Series(dtype=float)
        return r.groupby("channel_combo", observed=True)["revenue"].sum()

    a, b = agg(nig_old), agg(nig_new)
    chans = sorted(set(a.index) | set(b.index))
    sum_a = a.sum() or 1
    sum_b = b.sum() or 1
    rows = []
    for ch in chans:
        ro = float(a.get(ch, 0.0))
        rn = float(b.get(ch, 0.0))
        d_pct = ((rn / ro - 1) * 100) if ro > 0 else float("nan")
        rows.append({
            "Channel": ch,
            f"Revenue {year_old} (€)": round(ro, 2),
            f"Revenue {year_new} (€)": round(rn, 2),
            f"Anteil {year_old} (%)": round(ro / sum_a * 100, 1),
            f"Anteil {year_new} (%)": round(rn / sum_b * 100, 1),
            "Δ (%)": round(d_pct, 1) if pd.notna(d_pct) else None,
        })
    return pd.DataFrame(rows).sort_values(f"Revenue {year_new} (€)", ascending=False)


@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def alos_channel_table(nig_old: pd.DataFrame, nig_new: pd.DataFrame,
                        year_old: int, year_new: int, realized_only: bool = True) -> pd.DataFrame:
    """Sektion 7 - ⌀ Nächte / Buchung pro Channel."""

    def agg(df):
        r = df[df["is_realized"]] if realized_only else df
        if r.empty:
            return pd.Series(dtype=float)
        per_booking = r.groupby(["channel_combo", "id"], observed=True)["nights"].count()
        return per_booking.groupby("channel_combo").mean()

    a, b = agg(nig_old), agg(nig_new)
    chans = sorted(set(a.index) | set(b.index))
    rows = []
    for ch in chans:
        va = float(a.get(ch, float("nan")))
        vb = float(b.get(ch, float("nan")))
        rows.append({
            "Channel": ch,
            f"ALOS {year_old} (Nächte)": round(va, 2) if pd.notna(va) else None,
            f"ALOS {year_new} (Nächte)": round(vb, 2) if pd.notna(vb) else None,
            "Δ (Nächte)": round(vb - va, 2) if pd.notna(va) and pd.notna(vb) else None,
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def weekday_table(nig_old: pd.DataFrame, nig_new: pd.DataFrame,
                    weekday_col: str, year_old: int, year_new: int, realized_only: bool = True) -> pd.DataFrame:
    """Sektionen 8 / 9 - Revenue je Wochentag (Stay oder Anreise)."""
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    de = {"Monday": "Mo", "Tuesday": "Di", "Wednesday": "Mi", "Thursday": "Do",
          "Friday": "Fr", "Saturday": "Sa", "Sunday": "So"}

    def agg(df):
        r = df[df["is_realized"]] if realized_only else df
        if r.empty or weekday_col not in r.columns:
            return pd.Series(0.0, index=order)
        return r.groupby(weekday_col, observed=True)["revenue"].sum().reindex(order, fill_value=0.0)

    a, b = agg(nig_old), agg(nig_new)
    rows = []
    for wd in order:
        rows.append({
            "Wochentag": de[wd],
            f"Revenue {year_old} (€)": round(float(a[wd]), 2),
            f"Revenue {year_new} (€)": round(float(b[wd]), 2),
            "Δ (€)": round(float(b[wd] - a[wd]), 2),
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def group_size_table(res_old: pd.DataFrame, res_new: pd.DataFrame,
                      year_old: int, year_new: int, realized_only: bool = True) -> pd.DataFrame:
    """Sektion 10 - Revenue nach Gruppen-Größe."""
    order = ["single", "2_rooms", "3-4_rooms", "5+_rooms"]

    def agg(df):
        r = df[df["is_realized"]] if (realized_only and "is_realized" in df.columns) else df
        if r.empty or "group_size_bucket" not in r.columns:
            return pd.Series(0.0, index=order)
        return r.groupby("group_size_bucket", observed=True)["revenue"].sum().reindex(order, fill_value=0.0)

    a, b = agg(res_old), agg(res_new)
    rows = []
    for gs in order:
        rows.append({
            "Gruppen-Größe": gs,
            f"Revenue {year_old} (€)": round(float(a[gs]), 2),
            f"Revenue {year_new} (€)": round(float(b[gs]), 2),
            "Δ (€)": round(float(b[gs] - a[gs]), 2),
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def de_international_table(nig_old: pd.DataFrame, nig_new: pd.DataFrame,
                            year_old: int, year_new: int, realized_only: bool = True) -> pd.DataFrame:
    """Sektion 11 - DE vs International (Revenue + Nights + ADR)."""

    def agg(df):
        r = df[df["is_realized"]] if realized_only else df
        if r.empty or "origin" not in r.columns:
            return pd.DataFrame()
        r = r.copy()
        r["bucket"] = np.where(r["origin"].astype(str).str.upper() == "DE",
                                 "Deutschland", "International")
        out = r.groupby("bucket", observed=True).agg(
            revenue=("revenue", "sum"),
            nights=("nights", "sum"),
        ).reset_index()
        return out

    a, b = agg(nig_old), agg(nig_new)
    rows = []
    for bucket in ["Deutschland", "International"]:
        sa = a[a["bucket"] == bucket]
        sb = b[b["bucket"] == bucket]
        ra = float(sa["revenue"].iloc[0]) if len(sa) else 0.0
        na = float(sa["nights"].iloc[0]) if len(sa) else 0.0
        rb = float(sb["revenue"].iloc[0]) if len(sb) else 0.0
        nb = float(sb["nights"].iloc[0]) if len(sb) else 0.0
        rows.append({
            "Markt": bucket,
            f"Revenue {year_old} (€)": round(ra, 2),
            f"Revenue {year_new} (€)": round(rb, 2),
            f"Nights {year_old}": int(na),
            f"Nights {year_new}": int(nb),
            f"ADR {year_old} (€)": round(ra / na, 2) if na > 0 else None,
            f"ADR {year_new} (€)": round(rb / nb, 2) if nb > 0 else None,
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def top_countries_table(nig_old: pd.DataFrame, nig_new: pd.DataFrame,
                          year_old: int, year_new: int, top_n: int = 12, realized_only: bool = True) -> pd.DataFrame:
    """Sektion 12 - Top-Herkunftsländer Revenue YoY."""

    def agg(df):
        r = df[df["is_realized"]] if realized_only else df
        if r.empty or "origin" not in r.columns:
            return pd.Series(dtype=float)
        return r.groupby("origin", observed=True)["revenue"].sum()

    a, b = agg(nig_old), agg(nig_new)
    countries = (a.add(b, fill_value=0).sort_values(ascending=False).head(top_n).index.tolist())
    rows = []
    for c in countries:
        ra = float(a.get(c, 0.0))
        rb = float(b.get(c, 0.0))
        d_pct = ((rb / ra - 1) * 100) if ra > 0 else float("nan")
        rows.append({
            "Land": c,
            f"Revenue {year_old} (€)": round(ra, 2),
            f"Revenue {year_new} (€)": round(rb, 2),
            "Δ (€)": round(rb - ra, 2),
            "Δ (%)": round(d_pct, 1) if pd.notna(d_pct) else None,
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def leadtime_table(res_old: pd.DataFrame, res_new: pd.DataFrame,
                    year_old: int, year_new: int) -> pd.DataFrame:
    """Sektion 13 - Revenue + Storno-Quote pro Lead-Time-Bucket."""
    order = list(getattr(H, "LEAD_LABELS", []) or [])

    def agg(df):
        if df.empty or "lead_time_bucket" not in df.columns:
            return pd.DataFrame()
        return df.groupby("lead_time_bucket", observed=True).agg(
            buchungen=("id", "count"),
            realisiert=("is_realized", "sum") if "is_realized" in df.columns else ("id", "count"),
            storniert=("is_cancelled", "sum") if "is_cancelled" in df.columns else ("id", "count"),
            revenue=("revenue", "sum"),
        ).reindex(order, fill_value=0).reset_index()

    a, b = agg(res_old), agg(res_new)
    if a.empty and b.empty:
        return pd.DataFrame()
    rows = []
    for lt in order:
        ra = a[a["lead_time_bucket"] == lt]
        rb = b[b["lead_time_bucket"] == lt]

        def get(df, col, default=0.0):
            if df.empty:
                return default
            return float(df[col].iloc[0])
        n_a, n_b = int(get(ra, "buchungen")), int(get(rb, "buchungen"))
        s_a, s_b = int(get(ra, "storniert")), int(get(rb, "storniert"))
        rows.append({
            "Lead-Bucket": lt,
            f"Buchungen {year_old}": n_a,
            f"Buchungen {year_new}": n_b,
            f"Storno-Quote {year_old} (%)": round(s_a / n_a * 100, 1) if n_a else None,
            f"Storno-Quote {year_new} (%)": round(s_b / n_b * 100, 1) if n_b else None,
            f"Revenue {year_old} (€)": round(get(ra, "revenue"), 2),
            f"Revenue {year_new} (€)": round(get(rb, "revenue"), 2),
        })
    return pd.DataFrame(rows)


# =========================================================================
# Global Report
# =========================================================================
@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def location_revenue_table(nightly: pd.DataFrame, start_ts: pd.Timestamp,
                             end_ts: pd.Timestamp, realized_only: bool = True) -> pd.DataFrame:
    """Sektion 7.A - Revenue je Standort × Monat (long-format)."""
    d = nightly[(nightly["stay_date"] >= start_ts) & (nightly["stay_date"] <= end_ts)]
    if realized_only:
        d = d[d["is_realized"]]
    if d.empty:
        return pd.DataFrame()
    d = d.copy()
    d["ym"] = d["stay_date"].dt.to_period("M").astype(str)
    piv = (d.groupby(["property_code", "ym"], observed=True)["revenue"].sum()
            .unstack(fill_value=0.0).round(2))
    piv = piv.reindex(sorted(piv.columns), axis=1).sort_index()
    out = piv.reset_index().rename(columns={"property_code": "Standort"})
    return out


@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def channel_x_location_table(nightly: pd.DataFrame, start_ts: pd.Timestamp,
                               end_ts: pd.Timestamp, realized_only: bool = True) -> pd.DataFrame:
    """Sektion 7.B - Channel-Mix je Standort (% Anteile)."""
    try:
        from .global_tables import _channel_label
    except ImportError:
        from global_tables import _channel_label  # type: ignore
    d = nightly[(nightly["stay_date"] >= start_ts) & (nightly["stay_date"] <= end_ts)]
    if realized_only:
        d = d[d["is_realized"]]
    if d.empty:
        return pd.DataFrame()
    d = d.copy()
    d["ch"] = d["channel_combo"].map(_channel_label)
    piv = (d.groupby(["property_code", "ch"], observed=True)["revenue"].sum()
            .unstack(fill_value=0.0))
    piv_pct = piv.div(piv.sum(axis=1).replace(0, 1), axis=0) * 100
    piv_pct = piv_pct.round(1).sort_index()
    return piv_pct.reset_index().rename(columns={"property_code": "Standort"})


@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def channel_los_granular_table(nightly: pd.DataFrame,
                                 start_old: pd.Timestamp, end_old: pd.Timestamp,
                                 start_new: pd.Timestamp, end_new: pd.Timestamp,
                                 year_old: int, year_new: int,
                                 top_n_channels: int = 8,
                                 realized_only: bool = True) -> pd.DataFrame:
    """Sektion 7.D - Channel × LOS YoY (granulare Channel-Liste).

    realized_only=True (default) → Storno + No-Show raus; False → alle Buchungen
    (folgt dem Sidebar-Toggle „Storno + No-Show einbeziehen").
    """
    try:
        from .global_tables import _channel_label
    except ImportError:
        from global_tables import _channel_label  # type: ignore
    cols = ["short_<=6", "mid_7-28", "long_29+"]

    def agg(start, end):
        d = nightly[(nightly["stay_date"] >= start) & (nightly["stay_date"] <= end)]
        if realized_only:
            d = d[d["is_realized"]]
        if d.empty:
            return pd.DataFrame(columns=cols)
        d = d.assign(_ch=d["channel_combo"].map(_channel_label))
        return (d.groupby(["_ch", "los_bucket"], observed=True)["revenue"].sum()
                  .unstack(fill_value=0)
                  .reindex(columns=cols, fill_value=0))

    a, b = agg(start_old, end_old), agg(start_new, end_new)
    totals = (a.sum(axis=1) + b.sum(axis=1)).sort_values(ascending=False)
    rows_idx = totals.head(top_n_channels).index.tolist()
    a = a.reindex(index=rows_idx, columns=cols, fill_value=0)
    b = b.reindex(index=rows_idx, columns=cols, fill_value=0)
    rows = []
    for ch in rows_idx:
        for los in cols:
            ro, rn = float(a.loc[ch, los]), float(b.loc[ch, los])
            d_pct = ((rn / ro - 1) * 100) if ro > 0 else float("nan")
            rows.append({
                "Channel": ch,
                "LOS-Bucket": los,
                f"Revenue {year_old} (€)": round(ro, 2),
                f"Revenue {year_new} (€)": round(rn, 2),
                "Δ (€)": round(rn - ro, 2),
                "Δ (%)": round(d_pct, 1) if pd.notna(d_pct) else None,
            })
    return pd.DataFrame(rows)
