# dash_app/components/pickup_charts.py
# Plotly-Builder + Pace-Tabellen-Logik der Pickup / Vorlauf-Analyse.
# Portiert aus streamlit_app/pages/2_Pickup_Analyse.py (Pace-Balken, Stichtags-
# Tabelle) und streamlit_app/components/global_charts.py (build_pace_table,
# pace_to_plan_chart als Matplotlib -> hier Plotly). Alle Grafiken laufen durch
# theme.brand_figure; Vorjahres-Serien in GREY (Brand-Neutral-Grey).

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from dash_app import theme
from revenueblindspots import helpers as H

# Deutsche Monats-/Wochentag-Labels (aus der Streamlit-Seite übernommen).
MONTH_ABBR_DE = ("Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
                 "Jul", "Aug", "Sep", "Okt", "Nov", "Dez")
MONTH_NAMES_DE = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
                  "August", "September", "Oktober", "November", "Dezember")
WD_DE = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


def empty_fig(message: str, *, height: int = 300) -> go.Figure:
    """Leerer Brand-Chart mit zentrierter Hinweis-Nachricht."""
    fig = go.Figure()
    fig.add_annotation(text=message, xref="paper", yref="paper", x=0.5, y=0.5,
                       showarrow=False, font=dict(size=13, color=theme.GREY))
    theme.brand_figure(fig)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.update_layout(height=height)
    return fig


# ============================== 2 · Pace by Month ==========================
def pace_fig(pace_df: pd.DataFrame, year: int) -> go.Figure:
    """3 Balken je Übernachtungs-Monat (EoM Vorjahr / Stichtag Vorjahr / Stichtag
    aktuell). Near-verbatim aus der Streamlit-Seite, Farben/Layout identisch."""
    months = list(range(1, 13))
    if pace_df is None or pace_df.empty or "month" not in pace_df.columns:
        return empty_fig("Keine Pace-Daten im gewählten Fenster.", height=420)
    d = pace_df.set_index("month").reindex(months, fill_value=0.0)
    x = [MONTH_ABBR_DE[m - 1] for m in months]
    fig = go.Figure()
    fig.add_bar(x=x, y=d["ist_eom_old"], name=f"{year - 1}/EoM (final)",
                marker_color=theme.YELLOW, marker_line=dict(color=theme.BLACK, width=0.4),
                hovertemplate="%{y:,.0f} €<extra>" + f"{year - 1}/EoM" + "</extra>")
    fig.add_bar(x=x, y=d["ist_asof_old"], name=f"{year - 1}/Stichtag",
                marker_color=theme.GREY, marker_line=dict(color=theme.BLACK, width=0.4),
                hovertemplate="%{y:,.0f} €<extra>" + f"{year - 1}/Stichtag" + "</extra>")
    fig.add_bar(x=x, y=d["ist_asof_new"], name=f"{year}/Stichtag",
                marker_color=theme.BLUE, marker_line=dict(color=theme.BLACK, width=0.4),
                hovertemplate="%{y:,.0f} €<extra>" + f"{year}/Stichtag" + "</extra>")
    theme.brand_figure(fig)
    fig.update_layout(barmode="group", height=420, hovermode="x unified",
                      yaxis_title="Revenue (€, netto)")
    return fig


def pace_stichtag_table(year: int, month_: int, snap: pd.Timestamp,
                        props: list[str], nightly: pd.DataFrame) -> pd.DataFrame:
    """Stichtagsblick auf den aktuellen Monat: eine Zeile = ein As-of-Stichtag.

    Rohe Zahlen (gerundet); die Seite formatiert sie fürs Grid. Logik 1:1 aus
    ``_pace_stichtag_table`` der Streamlit-Seite (ohne den st.cache-Dekorator).
    """
    df = nightly
    if props:
        df = df[df["property_code"].isin(list(props))]
    if "is_no_show" in df.columns:
        df = df[~df["is_no_show"].astype(bool)]
    if df.empty:
        return pd.DataFrame()
    stay = pd.to_datetime(df["stay_date"]).dt.normalize()
    sub_new = df[(stay.dt.year == year) & (stay.dt.month == month_)]
    sub_old = df[(stay.dt.year == year - 1) & (stay.dt.month == month_)]

    realized_old = (sub_old["is_realized"].astype(bool)
                    if "is_realized" in sub_old.columns
                    else ~sub_old["is_cancelled"].astype(bool))
    eom_old = float(sub_old.loc[realized_old, "revenue"].sum()) if len(sub_old) else 0.0

    month_start = pd.Timestamp(year=year, month=month_, day=1)
    month_end = month_start + pd.offsets.MonthEnd(0)
    last_day = min(month_end, pd.Timestamp(snap).normalize())
    if last_day < month_start:
        return pd.DataFrame()  # Snapshot älter als Monatsbeginn

    rows = []
    for d in pd.date_range(month_start, last_day, freq="D"):
        d_old = H.mirror_years(d, 1)
        v_new = (float(sub_new.loc[
            H.asof_on_the_books_mask(sub_new, d, include_cancellations=False),
            "revenue"].sum()) if len(sub_new) else 0.0)
        v_old = (float(sub_old.loc[
            H.asof_on_the_books_mask(sub_old, d_old, include_cancellations=False),
            "revenue"].sum()) if len(sub_old) else 0.0)
        rows.append({
            "Stichtag": f"{WD_DE[d.weekday()]} {d:%d.%m.}",
            f"OTB {year - 1} (€)": round(v_old, 0),
            f"OTB {year} (€)": round(v_new, 0),
            "Δ (€)": round(v_new - v_old, 0),
            "Δ (%)": round((v_new / v_old - 1) * 100.0, 1) if v_old > 0 else None,
            f"IST {year - 1} final (€)": round(eom_old, 0),
        })
    return pd.DataFrame(rows)


# ============================== 3 · Buchungskurve ==========================
def booking_curve_fig(curve_df: pd.DataFrame, year_new: int, year_old: int,
                      x_title: str, y_title: str) -> go.Figure:
    """Linien-Chart aus einer (Index = X, Spalten = Jahre)-Tabelle.

    Aktuelles Jahr GELB, Vorjahr GREY, weitere Serien in CATEGORICAL - ersetzt
    das frühere ``st.line_chart``.
    """
    if curve_df is None or curve_df.empty:
        return empty_fig("Keine Daten für die Buchungskurve.", height=360)
    x = list(curve_df.index)
    fig = go.Figure()
    others = 0
    for col in curve_df.columns:
        c = str(col)
        if c == str(year_new):
            line = dict(color=theme.YELLOW, width=2.4)
        elif c == str(year_old):
            line = dict(color=theme.GREY, width=1.8)
        else:
            line = dict(color=theme.CATEGORICAL[others % len(theme.CATEGORICAL)], width=1.8)
            others += 1
        fig.add_scatter(x=x, y=curve_df[col].to_numpy(), mode="lines", name=c,
                        line=line, connectgaps=False,
                        hovertemplate="%{y:.1f} %<extra>" + c + "</extra>")
    theme.brand_figure(fig)
    fig.update_layout(height=360, hovermode="x unified",
                      xaxis_title=x_title, yaxis_title=y_title)
    return fig


# ============================== 4 · Pickup-Balken ==========================
def pickup_bars_fig(bars_df: pd.DataFrame, year_new: int, year_old: int,
                    y_title: str) -> go.Figure:
    """Gruppierte Balken je Kategorie: aktuelles Jahr GELB, Vorjahr GREY."""
    if bars_df is None or bars_df.empty:
        return empty_fig("Keine Kategorie-Daten für die Balken.", height=360)
    x = list(bars_df.index)
    fig = go.Figure()
    for col in bars_df.columns:
        c = str(col)
        color = theme.YELLOW if c == str(year_new) else (
            theme.GREY if c == str(year_old) else theme.BLUE)
        fig.add_bar(x=x, y=bars_df[col].to_numpy(), name=c, marker_color=color,
                    marker_line=dict(color=theme.BLACK, width=0.4),
                    hovertemplate="%{y:.1f} %<extra>" + c + "</extra>")
    theme.brand_figure(fig)
    fig.update_layout(barmode="group", height=360, yaxis_title=y_title)
    return fig


# ============================== 6 · Pace-to-PLAN ===========================
def pace_to_plan_fig(pace_df: pd.DataFrame, year_new: int, period_tag: str) -> go.Figure:
    """Horizontale IST-Balken je Standort mit PLAN-Tick (Plotly-Rewrite der
    Matplotlib-``pace_to_plan_chart``). Sortierung nach IST/PLAN-%."""
    if pace_df is None or pace_df.empty:
        return empty_fig("Keine Pace-Daten (kein PLAN für dieses Stay-Fenster).")
    df = pace_df[pace_df["Standort"] != "Gesamt"].copy()
    if df.empty:
        return empty_fig("Keine Pace-Daten (kein PLAN für dieses Stay-Fenster).")
    # Sortierung nach Fortschritt-% (IST/PLAN). Standorte ohne PLAN landen unten.
    df["_pct"] = (df["IST (€)"] / df["PLAN (€)"].replace(0, np.nan) * 100).fillna(-1)
    df = df.sort_values("_pct", ascending=True)
    names = df["Standort"].tolist()
    ist = df["IST (€)"].to_numpy(dtype=float)
    plan = df["PLAN (€)"].to_numpy(dtype=float)

    fig = go.Figure()
    fig.add_bar(x=ist, y=names, orientation="h", name="IST bisher",
                marker_color=theme.YELLOW, marker_line=dict(color=theme.BLACK, width=0.4),
                hovertemplate="IST %{x:,.0f} €<extra></extra>")
    plan_mask = plan > 0
    if plan_mask.any():
        fig.add_scatter(
            x=plan[plan_mask], y=[n for n, m in zip(names, plan_mask) if m],
            mode="markers", name="PLAN",
            marker=dict(symbol="line-ns-open", size=22, color=theme.BLACK,
                        line=dict(width=2.5, color=theme.BLACK)),
            hovertemplate="PLAN %{x:,.0f} €<extra></extra>")
    for i, n in enumerate(names):
        p, it = plan[i], ist[i]
        if p > 0:
            pct = it / p * 100
            fig.add_annotation(x=max(it, p), y=n, text=f"{pct:.0f} % vom PLAN",
                               showarrow=False, xanchor="left", xshift=6,
                               font=dict(size=11, color=theme.GREEN if pct >= 100 else theme.RED))
    theme.brand_figure(fig)
    xmax = max(float(ist.max(initial=0.0)), float(plan.max(initial=0.0))) or 1.0
    fig.update_xaxes(range=[0, xmax * 1.22])
    fig.update_layout(height=max(320, 42 * len(df) + 120),
                      xaxis_title="Revenue (€, netto)", showlegend=True)
    return fig


# ============================== Pace-to-PLAN Tabelle =======================
def build_pace_table(
    raw_stay: pd.DataFrame,
    start_new: pd.Timestamp,
    end_new: pd.Timestamp,
    today: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """IST vs PLAN + Zeit-Fortschritt je Standort + Gesamt-Zeile.

    Reine pandas-Logik, 1:1 aus ``global_charts.build_pace_table`` portiert.
    """
    today = pd.Timestamp(today) if today is not None else pd.Timestamp.today().normalize()

    # Periodweite Werte (gleich für alle Hotels, daher außerhalb der Schleife).
    period_pace = H.pace_to_plan(start_new, end_new, today=today)
    period_status = {
        "completed": "abgeschlossen",
        "in_progress": "laufend",
        "future": "zukünftig",
    }.get(period_pace["status"], period_pace["status"])
    period_progress = period_pace["elapsed_pct"]

    rows = []
    for _, r in raw_stay[raw_stay["Standort"] != "Total"].iterrows():
        ist = r["ist_new"]
        plan = r["plan_new"]
        if ist == 0 and plan == 0:
            continue
        rows.append(
            {
                "Standort": r["Standort"],
                "IST (€)": ist,
                "PLAN (€)": plan,
                "IST / PLAN (%)": (ist / plan * 100) if plan > 0 else float("nan"),
                "Fortschritt Zeit (%)": period_progress,
                "Status": period_status,
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    total_ist = df["IST (€)"].sum()
    total_plan = df["PLAN (€)"].sum()
    total_row = pd.DataFrame(
        [
            {
                "Standort": "Gesamt",
                "IST (€)": total_ist,
                "PLAN (€)": total_plan,
                "IST / PLAN (%)": (total_ist / total_plan * 100)
                if total_plan > 0 else float("nan"),
                "Fortschritt Zeit (%)": period_progress,
                "Status": period_status,
            }
        ]
    )
    df = pd.concat([df, total_row], ignore_index=True)
    return df
