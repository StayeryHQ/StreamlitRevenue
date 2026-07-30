# dash_app/components/code_charts.py
# Pure Plotly builders + table helpers for the Code-Deepdive view. Straight port
# of the code_deepdive_charts module (matplotlib -> Plotly) plus
# resolve_codes_to_res and the display-table builders the page inlined.
# Every builder returns a brand_figure'd go.Figure; the table helpers return plain
# display DataFrames the view feeds into ui.df_grid / an Excel export.,
# no BigQuery - colours come only from theme.

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dash_app import theme
from revenueblindspots import helpers as H

_CHANNEL_ORDER = ["Direct_Offline", "Direct_Website", "OTA"]
_CHANNEL_COLORS = [theme.BLUE, theme.GREEN, theme.ORANGE]
_LOS_ORDER = ["short_<=6", "mid_7-28", "long_29+"]
_GROUP_ORDER = ["single", "2_rooms", "3-4_rooms", "5+_rooms"]
_WEEKDAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                  "Saturday", "Sunday"]
_WEEKDAY_DE = {"Monday": "Mo", "Tuesday": "Di", "Wednesday": "Mi",
               "Thursday": "Do", "Friday": "Fr", "Saturday": "Sa", "Sunday": "So"}


def _empty(msg: str) -> go.Figure:
    """Placeholder figure for empty inputs (mirrors the mpl 'Keine Daten' axes)."""
    fig = go.Figure()
    fig.add_annotation(text=msg, x=0.5, y=0.5, xref="paper", yref="paper",
                       showarrow=False, font=dict(size=14, color=theme.GREY))
    theme.brand_figure(fig)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return fig


def _count_label(v) -> str:
    """Integer counts with '.'-thousands; 1-decimal for fractional values."""
    if pd.isna(v):
        return "–"
    v = float(v)
    if v == int(v):
        return f"{int(v):,}".replace(",", ".")
    return f"{v:.1f}"


# =============================================================================
# 2 · Revenue-Verlauf: Monats-Bars + 3M-Rolling + kumulative Linie (2. Y-Achse)
# =============================================================================
def revenue_timeline(res_df: pd.DataFrame, firm_label: str,
                     period_start: pd.Timestamp, period_end: pd.Timestamp):
    """Bar (Monats-Revenue) + Linie (3M-Rolling) + Sekundärachse (kumulativ).

    Returns (fig, monthly, cum): monthly/cum are month-indexed Series (or None
    when there are no realized bookings)."""
    d = res_df[res_df["is_realized"]].copy()
    if d.empty:
        return _empty("Keine realisierten Buchungen - kein Verlauf darstellbar."), None, None
    d["ym"] = d["arrival"].dt.to_period("M").dt.to_timestamp()
    monthly = d.groupby("ym")["revenue"].sum().sort_index()
    full_idx = pd.date_range(monthly.index.min(), monthly.index.max(), freq="MS")
    monthly = monthly.reindex(full_idx, fill_value=0.0)
    rolling = monthly.rolling(3, min_periods=1).mean()
    cum = monthly.cumsum()

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(
        x=monthly.index, y=monthly.values, name="Monats-Revenue",
        marker=dict(color=theme.YELLOW, line=dict(color=theme.BLACK, width=0.3)),
        hovertemplate="%{x|%m/%Y}: %{y:,.0f} €<extra>Monats-Revenue</extra>",
    ), secondary_y=False)
    fig.add_trace(go.Scatter(
        x=rolling.index, y=rolling.values, name="3M-rollender Mittelwert",
        mode="lines+markers", line=dict(color=theme.RED, width=2.0),
        marker=dict(size=5),
        hovertemplate="%{x|%m/%Y}: %{y:,.0f} €<extra>3M-Rolling</extra>",
    ), secondary_y=False)
    fig.add_trace(go.Scatter(
        x=cum.index, y=cum.values, name="kumulativ", mode="lines",
        line=dict(color=theme.GREEN, width=1.6, dash="dash"), opacity=0.8,
        hovertemplate="%{x|%m/%Y}: %{y:,.0f} €<extra>kumulativ</extra>",
    ), secondary_y=True)
    fig.add_vrect(x0=period_start, x1=period_end, fillcolor=theme.ORANGE,
                  opacity=0.15, line_width=0,
                  annotation_text=f"Fokus {period_start:%m/%y}–{period_end:%m/%y}",
                  annotation_position="top left")

    theme.brand_figure(fig)
    fig.update_yaxes(title_text="Revenue / Monat (€, netto)", secondary_y=False)
    fig.update_yaxes(title_text="Kumulativ (€)", secondary_y=True, showgrid=False,
                     color=theme.GREEN)
    fig.update_xaxes(title_text="Anreise-Monat")
    return fig, monthly, cum


# =============================================================================
# 3 · Channel-Evolution: Stacked Area (Lifetime) + Fokus-vs-Vorperiode-Vergleich
# =============================================================================
def channel_evolution(res_df: pd.DataFrame, firm_label: str,
                      period_start: pd.Timestamp, period_end: pd.Timestamp,
                      prev_start: pd.Timestamp, prev_end: pd.Timestamp):
    """Stacked-Area über die Lifetime + (wenn beide Perioden Daten) Vergleichs-Panel.

    Returns (fig, cur, prev): cur/prev are channel-indexed Series for the focus
    vs. previous period (both None when no comparison is possible)."""
    d = res_df[res_df["is_realized"]].copy()
    if d.empty:
        return _empty("Keine realisierten Buchungen - Channel-Evolution nicht darstellbar."), None, None
    d["ym"] = d["arrival"].dt.to_period("M").dt.to_timestamp()
    d["ch"] = H.channel_bucket(d["channel_combo"])
    monthly_ch = (d.groupby(["ym", "ch"])["revenue"].sum()
                  .unstack(fill_value=0.0).sort_index())
    full_idx = pd.date_range(monthly_ch.index.min(), monthly_ch.index.max(), freq="MS")
    monthly_ch = monthly_ch.reindex(full_idx, fill_value=0.0)
    monthly_ch = monthly_ch.reindex(columns=_CHANNEL_ORDER, fill_value=0.0)

    def shares(s, e):
        sub = d[(d["arrival"] >= s) & (d["arrival"] <= e)]
        if sub.empty:
            return pd.Series([0.0] * 3, index=_CHANNEL_ORDER), 0
        agg = sub.groupby("ch")["revenue"].sum().reindex(_CHANNEL_ORDER, fill_value=0.0)
        return agg, len(sub)

    cur, cur_n = shares(period_start, period_end)
    prev, prev_n = shares(prev_start, prev_end)
    has_comparison = (cur_n > 0) and (prev_n > 0)

    if has_comparison:
        fig = make_subplots(
            rows=1, cols=2, column_widths=[0.66, 0.34], horizontal_spacing=0.1,
            subplot_titles=("Channel-Mix über die Zeit",
                            "Channel-Anteil · Fokus vs. Vorperiode"))
    else:
        fig = make_subplots(rows=1, cols=1, subplot_titles=("Channel-Mix über die Zeit",))

    for name, col in zip(_CHANNEL_ORDER, _CHANNEL_COLORS):
        fig.add_trace(go.Scatter(
            x=monthly_ch.index, y=monthly_ch[name], name=name, mode="lines",
            stackgroup="ch", line=dict(color=col, width=0.5), fillcolor=col,
            hovertemplate="%{x|%m/%Y}: %{y:,.0f} €<extra>" + name + "</extra>",
        ), row=1, col=1)
    fig.add_vrect(x0=period_start, x1=period_end, fillcolor=theme.YELLOW,
                  opacity=0.18, line_width=0, row=1, col=1,
                  annotation_text="Fokus", annotation_position="top left")

    if has_comparison:
        cur_pct = cur / cur.sum() * 100
        prev_pct = prev / prev.sum() * 100
        fig.add_trace(go.Bar(
            x=_CHANNEL_ORDER, y=prev_pct.values, name="Vorperiode",
            marker=dict(color=theme.GREY, line=dict(color=theme.BLACK, width=0.4)),
            hovertemplate="%{x}: %{y:.0f} %<extra>Vorperiode</extra>",
        ), row=1, col=2)
        fig.add_trace(go.Bar(
            x=_CHANNEL_ORDER, y=cur_pct.values, name="Fokus-Periode",
            marker=dict(color=theme.YELLOW, line=dict(color=theme.BLACK, width=0.4)),
            hovertemplate="%{x}: %{y:.0f} %<extra>Fokus-Periode</extra>",
        ), row=1, col=2)
        anns = []
        for i, (vp, vc) in enumerate(zip(prev_pct.values, cur_pct.values)):
            shift = vc - vp
            anns.append(dict(
                x=_CHANNEL_ORDER[i], y=max(vp, vc, 1) + 2, xref="x2", yref="y2",
                text=f"{shift:+.0f}pp", showarrow=False,
                font=dict(size=10, color=theme.GREEN if shift >= 0 else theme.RED)))
        theme.add_annotations(fig, anns)
        fig.update_yaxes(title_text="Anteil (%)", row=1, col=2)

    theme.brand_figure(fig)
    fig.update_yaxes(title_text="Revenue / Monat (€)", row=1, col=1)
    fig.update_layout(barmode="group")
    return fig, (cur if has_comparison else None), (prev if has_comparison else None)


# =============================================================================
# 4 · Stay-Patterns: 6-Panel (LOS · Standort · Wochentag · Zimmerkat · Lead · Gruppe)
# =============================================================================
def stay_patterns(res_df: pd.DataFrame, firm_label: str) -> go.Figure:
    d = res_df[res_df["is_realized"]].copy()
    if d.empty:
        return _empty("Keine realisierten Buchungen.")

    by_loc = d.groupby("property_code")["revenue"].sum().sort_values(ascending=False)
    if "arrival_weekday" in d.columns:
        wd = d["arrival_weekday"].value_counts().reindex(_WEEKDAY_ORDER, fill_value=0)
        wd.index = [_WEEKDAY_DE[w] for w in wd.index]
    else:
        wd = pd.Series([], dtype=float)
    rc = (d["room_category"].value_counts().head(8)
          if "room_category" in d.columns else pd.Series([], dtype=float))
    lt = (d["lead_time_bucket"].value_counts().reindex(list(H.LEAD_LABELS), fill_value=0)
          if "lead_time_bucket" in d.columns else pd.Series([], dtype=float))
    gs = (d["group_size_bucket"].value_counts().reindex(_GROUP_ORDER, fill_value=0)
          if "group_size_bucket" in d.columns else pd.Series([], dtype=float))

    panels = [
        (d["los_bucket"].value_counts().reindex(_LOS_ORDER, fill_value=0),
         "LOS-Bucket (Anzahl Buchungen)"),
        (by_loc, "Revenue pro Standort (€)"),
        (wd, "Anreise-Wochentag (Anzahl)"),
        (rc, "Zimmerkategorie (Top 8)"),
        (lt, "Vorlaufzeit-Bucket (Anzahl)"),
        (gs, "Gruppen-Größe (Anzahl)"),
    ]
    fig = make_subplots(rows=2, cols=3, subplot_titles=[p[1] for p in panels],
                        vertical_spacing=0.16, horizontal_spacing=0.07)
    for idx, (series, _title) in enumerate(panels):
        r, c = idx // 3 + 1, idx % 3 + 1
        if series is None or series.empty:
            fig.add_annotation(text="keine Daten", x=0.5, y=0.5, showarrow=False,
                               xref=f"x{idx + 1} domain", yref=f"y{idx + 1} domain",
                               font=dict(size=11, color=theme.GREY))
            continue
        labels = [str(x) for x in series.index]
        fig.add_trace(go.Bar(
            x=labels, y=series.values, showlegend=False,
            marker=dict(color=theme.YELLOW, line=dict(color=theme.BLACK, width=0.4)),
            text=[_count_label(v) for v in series.values], textposition="outside",
            cliponaxis=False, hovertemplate="%{x}: %{y}<extra></extra>",
        ), row=r, col=c)

    theme.brand_figure(fig)
    fig.update_layout(showlegend=False)
    return fig


# =============================================================================
# 5 · Storno-View: Storno-Timing vor Anreise + monatliche Storno-Quote
# =============================================================================
def storno_view(res_df: pd.DataFrame, firm_label: str,
                alert_cancel_rate_pct: float = 25.0) -> go.Figure:
    if res_df.empty:
        return _empty("Keine Buchungen.")
    fig = make_subplots(rows=1, cols=2, horizontal_spacing=0.1,
                        subplot_titles=("Storno-Timing vor Anreise",
                                        "Monatliche Storno-Quote"))

    cancelled = res_df[res_df["is_cancelled"]
                       & res_df["cancel_lead_time_days"].notna()].copy()
    if cancelled.empty:
        fig.add_annotation(text="Keine Stornos vorhanden", x=0.5, y=0.5,
                           showarrow=False, xref="x domain", yref="y domain",
                           font=dict(size=11, color=theme.GREY))
    else:
        labels = list(H.CANCEL_TIMING_LABELS)
        timing = pd.cut(cancelled["cancel_lead_time_days"],
                        bins=H.CANCEL_TIMING_BINS, labels=labels)
        tc = timing.value_counts().reindex(labels, fill_value=0)
        fig.add_trace(go.Bar(
            x=labels, y=tc.values, showlegend=False,
            marker=dict(color=theme.ORANGE, line=dict(color=theme.BLACK, width=0.4)),
            text=[str(int(v)) if v > 0 else "" for v in tc.values],
            textposition="outside", cliponaxis=False,
            hovertemplate="%{x}: %{y}<extra></extra>",
        ), row=1, col=1)
        fig.update_yaxes(title_text="Anzahl Stornierungen", row=1, col=1)

    d = res_df.copy()
    d["ym"] = d["arrival"].dt.to_period("M").dt.to_timestamp()
    monthly = d.groupby("ym").agg(n=("id", "count"), c=("is_cancelled", "sum"))
    if monthly.empty:
        fig.add_annotation(text="Keine Daten für Monatsverlauf", x=0.5, y=0.5,
                           showarrow=False, xref="x2 domain", yref="y2 domain",
                           font=dict(size=11, color=theme.GREY))
    else:
        monthly["rate_pct"] = (monthly["c"] / monthly["n"].replace(0, np.nan)) * 100
        full_idx = pd.date_range(monthly.index.min(), monthly.index.max(), freq="MS")
        monthly = monthly.reindex(full_idx, fill_value=0)
        fig.add_trace(go.Scatter(
            x=monthly.index, y=monthly["rate_pct"], mode="lines+markers",
            showlegend=False, line=dict(color=theme.ORANGE, width=1.8),
            hovertemplate="%{x|%m/%Y}: %{y:.1f} %<extra>Storno-Quote</extra>",
        ), row=1, col=2)
        fig.add_hline(y=alert_cancel_rate_pct, line=dict(color=theme.RED, dash="dash",
                                                         width=1), row=1, col=2,
                      annotation_text=f"{alert_cancel_rate_pct:.0f}% Alert",
                      annotation_position="top right")
        fig.update_yaxes(title_text="Storno-Quote (%)", row=1, col=2)

    theme.brand_figure(fig)
    return fig


# =============================================================================
# Resolve identity: match code input against corporate/company/effective/promo code
# =============================================================================
def resolve_codes_to_res(
    res_all: pd.DataFrame,
    codes: list[str],
    include_promo: bool = True,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """(subset, firm_names_fuzzy, firm_names_raw) for the given codes. Vectorised
    match on company_code / corporateCode / effective_code (+ promoCode when the
    toggle is on)."""
    if not codes:
        return res_all.iloc[0:0].copy(), [], []
    codes_clean = [str(c).strip().lower() for c in codes if str(c).strip()]
    if not codes_clean:
        return res_all.iloc[0:0].copy(), [], []

    def _norm(col):
        if col not in res_all.columns:
            return pd.Series(False, index=res_all.index)
        return res_all[col].astype(str).str.strip().str.lower().isin(codes_clean)

    mask = _norm("company_code") | _norm("corporateCode") | _norm("effective_code")
    if include_promo:
        mask = mask | _norm("promoCode")
    sub = res_all[mask].copy()
    firm_names_raw = []
    if "company" in sub.columns:
        firm_names_raw = sorted(sub["company"].dropna().astype(str).str.strip().unique())
    firm_names_fuzzy: list[str] = []
    if "firm_by_effective_fuzzy" in sub.columns:
        firm_names_fuzzy = sorted(
            sub["firm_by_effective_fuzzy"].dropna().astype(str).str.strip().unique())
    return sub, firm_names_fuzzy, firm_names_raw


# =============================================================================
# Pure display-table builders (used by the view for grids + the Excel export)
# =============================================================================
def monthly_revenue_table(monthly: pd.Series, cum: pd.Series) -> pd.DataFrame:
    """§2 Monats-Tabelle (Revenue · kumulativ · Δ vs. Vormonat), neueste zuerst."""
    if monthly is None or len(monthly) == 0:
        return pd.DataFrame()
    return (pd.DataFrame({
        "Monat": monthly.index.strftime("%Y-%m"),
        "Revenue (€)": monthly.values.round(2),
        "Kumulativ (€)": cum.values.round(2),
        "Δ vs. Vormonat (€)": monthly.diff().fillna(0).values.round(2),
    }).sort_values("Monat", ascending=False).reset_index(drop=True))


def channel_shift_table(cur: pd.Series, prev: pd.Series) -> pd.DataFrame:
    """§3 Channel-Tabelle · Periode-Vergleich (leer wenn kein Vergleich möglich)."""
    if cur is None or prev is None:
        return pd.DataFrame()
    return pd.DataFrame({
        "Channel": cur.index,
        "Vorperiode (€)": prev.values.round(2),
        "Fokus-Periode (€)": cur.values.round(2),
        "Δ (€)": (cur.values - prev.values).round(2),
        "Anteil vor (%)": (prev / max(prev.sum(), 1) * 100).round(1).values,
        "Anteil aktuell (%)": (cur / max(cur.sum(), 1) * 100).round(1).values,
    })


def location_table(res: pd.DataFrame) -> pd.DataFrame:
    """§4 Standort-Aufteilung (realisierte Buchungen)."""
    realized = res[res["is_realized"]]
    if realized.empty:
        return pd.DataFrame()
    loc = (realized.groupby("property_code")
           .agg(Buchungen=("id", "nunique"), Nächte=("nights", "sum"),
                Revenue=("revenue", "sum"))
           .reset_index()
           .rename(columns={"property_code": "Standort", "Revenue": "Revenue (€)"}))
    loc["ADR (€)"] = (loc["Revenue (€)"] / loc["Nächte"].replace(0, np.nan)).round(2)
    loc["Revenue (€)"] = loc["Revenue (€)"].round(2)
    return loc.sort_values("Revenue (€)", ascending=False).reset_index(drop=True)


def storno_monthly_table(res: pd.DataFrame) -> pd.DataFrame:
    """§5 monatliche Storno-Quote, neueste zuerst."""
    if res.empty:
        return pd.DataFrame()
    d = res.copy()
    d["ym"] = d["arrival"].dt.to_period("M").astype(str)
    tbl = (d.groupby("ym")
           .agg(Buchungen=("id", "count"), Storniert=("is_cancelled", "sum"),
                No_Show=("is_no_show", "sum"), Realisiert=("is_realized", "sum"),
                Revenue=("revenue", "sum"))
           .reset_index())
    tbl["Storno-Quote (%)"] = (
        tbl["Storniert"] / tbl["Buchungen"].replace(0, np.nan) * 100).round(1)
    tbl["Revenue"] = tbl["Revenue"].round(2)
    tbl = tbl.rename(columns={"ym": "Monat", "Revenue": "Revenue (€)"})
    return tbl.sort_values("Monat", ascending=False).reset_index(drop=True)


_PIPE_COLS = {
    "id": "Buchungs-ID", "arrival": "Anreise", "departure": "Abreise",
    "nights": "Nächte", "adults": "Personen", "property_code": "Standort",
    "channel_combo": "Channel", "effective_code": "Code", "promoCode": "Promocode",
    "ratePlan_name": "Rate-Plan", "status": "Status", "revenue": "Revenue (€)",
}


def pipeline_table(res: pd.DataFrame, today: pd.Timestamp) -> pd.DataFrame:
    """§6 Future-Pipeline: offene Buchungen mit Anreise > heute (nicht storniert)."""
    future = res[(res["arrival"] > today) & ~res["is_cancelled"]].copy()
    if future.empty:
        return pd.DataFrame()
    present = {k: v for k, v in _PIPE_COLS.items() if k in future.columns}
    pipe = future[list(present.keys())].copy().rename(columns=present)
    if "Anreise" in pipe.columns:
        pipe["Anreise"] = pd.to_datetime(pipe["Anreise"]).dt.date
    if "Abreise" in pipe.columns:
        pipe["Abreise"] = pd.to_datetime(pipe["Abreise"]).dt.date
    if "Revenue (€)" in pipe.columns:
        pipe["Revenue (€)"] = pipe["Revenue (€)"].astype(float).round(2)
    if "Nächte" in pipe.columns:
        pipe["Nächte"] = pipe["Nächte"].astype(int)
    return pipe.sort_values(["Anreise", "Standort"], na_position="last").reset_index(drop=True)


_RES_COLS = [
    "id", "bookingId", "status", "arrival", "departure", "created", "property_code",
    "channel_combo", "effective_code", "corporateCode", "promoCode", "company",
    "firm_by_effective_fuzzy", "travelPurpose", "ratePlan_code", "ratePlan_name",
    "unitGroup_name", "nights", "adults", "los_bucket", "lead_time_days",
    "lead_time_bucket", "revenue", "kept_revenue", "lost_revenue", "is_realized",
    "is_cancelled", "is_no_show", "cancel_lead_time_days",
]
_RES_RENAME = {
    "id": "Reservation-ID", "bookingId": "Booking-ID", "status": "Status",
    "arrival": "Anreise", "departure": "Abreise", "created": "Erstellt",
    "property_code": "Standort", "channel_combo": "Channel",
    "effective_code": "Code (effektiv)", "corporateCode": "Corporate-Code",
    "promoCode": "Promocode", "company": "Firma (Priority)",
    "firm_by_effective_fuzzy": "Firma (Fuzzy)", "travelPurpose": "Reisezweck",
    "nights": "Nächte", "adults": "Personen", "revenue": "Revenue (€)",
    "kept_revenue": "Behaltener Revenue (€)", "lost_revenue": "Verlorener Revenue (€)",
    "is_realized": "Realisiert?", "is_cancelled": "Storniert?",
    "is_no_show": "No-Show?", "cancel_lead_time_days": "Cancel-Vorlauf (Tage)",
    "lead_time_days": "Vorlaufzeit (Tage)", "lead_time_bucket": "Vorlauf-Bucket",
    "los_bucket": "LOS-Bucket", "ratePlan_code": "Rate-Plan-Code",
    "ratePlan_name": "Rate-Plan", "unitGroup_name": "Zimmerkategorie",
}


def reservations_table(res: pd.DataFrame) -> pd.DataFrame:
    """§7 Reservations-Tabelle: Lifetime-Schnitt für die Codes (Excel-ready)."""
    if res.empty:
        return pd.DataFrame()
    present = [c for c in _RES_COLS if c in res.columns]
    sort_by = ["arrival", "id"] if "id" in present else ["arrival"]
    out = res[present].copy().sort_values(sort_by).reset_index(drop=True)
    return out.rename(columns={k: v for k, v in _RES_RENAME.items() if k in out.columns})
