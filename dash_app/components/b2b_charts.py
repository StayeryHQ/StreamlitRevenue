# dash_app/components/b2b_charts.py
# Pure Plotly builders + table helpers for the B2B view's Standort-Sektionen
# 11-13 (Firmenkunden-Uebersicht, Direct-Offline, Top-Vertragscodes). Straight
# port of the matplotlib builders in the charts module
# (corporate_overview, top_companies_table, build_channel_table,
# directoffline_waterfall, directoffline_segments, top_codes_in_period) to
# Plotly + plain display DataFrames the view feeds into ui.df_grid / an Excel
# export. Colours come only from theme. No matplotlib, no BigQuery.

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dash_app import theme
from revenueblindspots import helpers as H

_LOS_ORDER = ["short_<=6", "mid_7-28", "long_29+"]
_CHANNEL_ORDER = ["Direct_Website", "Direct_Offline", "OTA"]
_NULLISH = {"", "nan", "none", "<na>", "null"}


def _empty(msg: str) -> go.Figure:
    """Placeholder figure for empty inputs (mirrors the mpl 'Keine Daten' axes)."""
    fig = go.Figure()
    fig.add_annotation(text=msg, x=0.5, y=0.5, xref="paper", yref="paper",
                       showarrow=False, font=dict(size=14, color=theme.GREY))
    theme.brand_figure(fig)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return fig


def _has_company(df: pd.DataFrame) -> pd.Series:
    """has_company as a clean boolean mask (nullable/NA -> False)."""
    if "has_company" not in df.columns:
        return pd.Series(False, index=df.index)
    return df["has_company"].fillna(False).astype(bool)


# =============================================================================
# 11 · Firmenkunden-Ueberblick: Firmen vs. Privat + Firmen-Revenue nach Channel
# =============================================================================
def corporate_overview(res_a, res_b, year_old, year_new, label,
                       realized_only: bool = True) -> go.Figure:
    def split(df):
        hc = _has_company(df)
        real = df["is_realized"] if realized_only else pd.Series(True, index=df.index)
        return (float(df.loc[hc & real, "revenue"].sum()),
                float(df.loc[~hc & real, "revenue"].sum()))

    ca, pa = split(res_a)
    cb, pb = split(res_b)

    def by_channel(df):
        mask = _has_company(df)
        if realized_only:
            mask = mask & df["is_realized"]
        d = df[mask].copy()
        if d.empty:
            return pd.Series(0.0, index=_CHANNEL_ORDER)
        d["ch"] = H.channel_bucket(d["channel_combo"])
        return d.groupby("ch")["revenue"].sum().reindex(_CHANNEL_ORDER, fill_value=0.0)

    a = by_channel(res_a)
    b = by_channel(res_b)

    fig = make_subplots(rows=1, cols=2, horizontal_spacing=0.12,
                        subplot_titles=("Firmenkunden vs. Privat",
                                        "Firmenkunden-Revenue nach Channel"))
    cats = ["Firmenkunden", "Privat"]
    fig.add_trace(go.Bar(x=cats, y=[ca, pa], name=str(year_old),
                         marker=dict(color=theme.GREY, line=dict(color=theme.BLACK, width=0.4)),
                         hovertemplate="%{x}: %{y:,.0f} €<extra>" + str(year_old) + "</extra>"),
                  row=1, col=1)
    fig.add_trace(go.Bar(x=cats, y=[cb, pb], name=str(year_new),
                         marker=dict(color=theme.YELLOW, line=dict(color=theme.BLACK, width=0.4)),
                         hovertemplate="%{x}: %{y:,.0f} €<extra>" + str(year_new) + "</extra>"),
                  row=1, col=1)
    anns = []
    for i, (vo, vn) in enumerate([(ca, cb), (pa, pb)]):
        d = (vn / vo - 1) * 100 if vo else float("nan")
        if not np.isnan(d):
            anns.append(dict(x=cats[i], y=max(vo, vn, 1) * 1.12, xref="x", yref="y",
                             text=f"YoY {d:+.0f} %", showarrow=False,
                             font=dict(size=11, color=theme.GREEN if d >= 0 else theme.RED)))

    fig.add_trace(go.Bar(x=_CHANNEL_ORDER, y=a.values, name=str(year_old), showlegend=False,
                         marker=dict(color=theme.GREY, line=dict(color=theme.BLACK, width=0.4)),
                         hovertemplate="%{x}: %{y:,.0f} €<extra>" + str(year_old) + "</extra>"),
                  row=1, col=2)
    fig.add_trace(go.Bar(x=_CHANNEL_ORDER, y=b.values, name=str(year_new), showlegend=False,
                         marker=dict(color=theme.YELLOW, line=dict(color=theme.BLACK, width=0.4)),
                         hovertemplate="%{x}: %{y:,.0f} €<extra>" + str(year_new) + "</extra>"),
                  row=1, col=2)
    for i, (vo, vn) in enumerate(zip(a.values, b.values)):
        d = (vn / vo - 1) * 100 if vo else float("nan")
        txt = f"{d:+.0f} %" if not np.isnan(d) else "neu"
        good = np.isnan(d) or d >= 0
        anns.append(dict(x=_CHANNEL_ORDER[i], y=max(vo, vn, 1) * 1.05, xref="x2", yref="y2",
                         text=txt, showarrow=False,
                         font=dict(size=10, color=theme.GREEN if good else theme.RED)))
    theme.add_annotations(fig, anns)

    theme.brand_figure(fig)
    fig.update_yaxes(title_text="Revenue (€, netto)", row=1, col=1)
    fig.update_yaxes(title_text="Firmen-Revenue (€, netto)", row=1, col=2)
    fig.update_layout(barmode="group")
    return fig


# =============================================================================
# Code-Lookup + Table-Builder fuer Firmenkunden- / Direct-Offline-Tabellen
# =============================================================================
def _company_code_lookup(*res_dfs) -> dict[str, str]:
    parts = []
    for d in res_dfs:
        if "effective_code" in d.columns:
            code_col = d["effective_code"]
        else:
            cc = d["company_code"].astype(str).str.strip()
            cp = d.get("corporateCode", pd.Series([""] * len(d), index=d.index))
            cp = cp.astype(str).str.strip()
            valid_cc = ~cc.str.lower().isin(_NULLISH)
            valid_cp = ~cp.str.lower().isin(_NULLISH)
            code_col = cc.where(valid_cc, cp.where(valid_cp))
        sub_df = d.assign(_code=code_col)
        sub = sub_df[_has_company(sub_df)
                     & sub_df["_code"].notna()
                     & sub_df["_code"].astype(str).str.strip().ne("")]
        if not sub.empty:
            parts.append(sub[["company", "_code"]].rename(columns={"_code": "company_code"}))
    if not parts:
        return {}
    cat = pd.concat(parts, ignore_index=True)
    cat["company_code"] = cat["company_code"].astype(str).str.strip()
    out: dict[str, str] = {}
    for firm, g in cat.groupby("company"):
        codes = g["company_code"].value_counts()
        out[firm] = " / ".join(list(codes.index[:2]))
    return out


def top_companies_table(res_a, res_b, year_old, year_new,
                        realized_only: bool = True) -> pd.DataFrame:
    """§11 Top-Firmenkunden nach Revenue (alle Channels) - Roh-Frame."""
    def by_firm(df):
        mask = _has_company(df)
        if realized_only:
            mask = mask & df["is_realized"]
        d = df[mask]
        return d.groupby("company").agg(revenue=("revenue", "sum"),
                                        n_bookings=("id", "nunique"),
                                        nights=("nights", "sum"))

    a = by_firm(res_a)
    b = by_firm(res_b)
    code_map = _company_code_lookup(res_a, res_b)
    firms = a.index.union(b.index)
    if len(firms) == 0:
        return pd.DataFrame()
    t = pd.DataFrame({
        "Firma": list(firms),
        "Code": [code_map.get(f, "") for f in firms],
        f"Revenue {year_old} (€)": a["revenue"].reindex(firms, fill_value=0.0).values,
        f"Revenue {year_new} (€)": b["revenue"].reindex(firms, fill_value=0.0).values,
        f"Buchungen {year_old}": a["n_bookings"].reindex(firms, fill_value=0).astype(int).values,
        f"Buchungen {year_new}": b["n_bookings"].reindex(firms, fill_value=0).astype(int).values,
        f"Nächte {year_old}": a["nights"].reindex(firms, fill_value=0).astype(int).values,
        f"Nächte {year_new}": b["nights"].reindex(firms, fill_value=0).astype(int).values,
    })
    t["Δ Revenue (€)"] = t[f"Revenue {year_new} (€)"] - t[f"Revenue {year_old} (€)"]
    return t.sort_values(f"Revenue {year_new} (€)", ascending=False).reset_index(drop=True)


# =============================================================================
# 12 · Direct-Offline: Waterfall + Detail-Segmente + Channel-Tabelle
# =============================================================================
def _per_channel_revenue(res_df, realized_only: bool = True):
    mask = _has_company(res_df)
    if realized_only:
        mask = mask & res_df["is_realized"]
    d = res_df[mask].copy()
    if d.empty:
        idx = pd.MultiIndex.from_arrays([[], []], names=["company", "ch"])
        return pd.Series([], index=idx, dtype=float, name="revenue")
    d["ch"] = H.channel_bucket(d["channel_combo"])
    return d.groupby(["company", "ch"])["revenue"].sum()


def build_channel_table(companies, res_a, res_b, realized_only: bool = True) -> pd.DataFrame:
    """§12 Channel-Aufschlüsselung je Firma (old vs new) - Roh-Frame."""
    rev_a = _per_channel_revenue(res_a, realized_only=realized_only).unstack(fill_value=0.0)
    rev_b = _per_channel_revenue(res_b, realized_only=realized_only).unstack(fill_value=0.0)
    for col in ("Direct_Offline", "Direct_Website", "OTA"):
        for src in (rev_a, rev_b):
            if col not in src.columns:
                src[col] = 0.0
    rev_a = rev_a.reindex(companies, fill_value=0.0)
    rev_b = rev_b.reindex(companies, fill_value=0.0)
    code_map = _company_code_lookup(res_a, res_b)
    firms_list = list(companies)
    out = pd.DataFrame({
        "Firma": firms_list,
        "Code": [code_map.get(c, "") for c in firms_list],
        "Direct_Offline old (€)": rev_a["Direct_Offline"].to_numpy(),
        "Direct_Offline new (€)": rev_b["Direct_Offline"].to_numpy(),
        "Direct_Website old (€)": rev_a["Direct_Website"].to_numpy(),
        "Direct_Website new (€)": rev_b["Direct_Website"].to_numpy(),
        "OTA old (€)": rev_a["OTA"].to_numpy(),
        "OTA new (€)": rev_b["OTA"].to_numpy(),
    })
    out["Total old (€)"] = out[["Direct_Offline old (€)", "Direct_Website old (€)",
                                "OTA old (€)"]].sum(axis=1)
    out["Total new (€)"] = out[["Direct_Offline new (€)", "Direct_Website new (€)",
                                "OTA new (€)"]].sum(axis=1)
    out["Δ Direct_Offline (€)"] = out["Direct_Offline new (€)"] - out["Direct_Offline old (€)"]
    out["Δ Total (€)"] = out["Total new (€)"] - out["Total old (€)"]
    drop_do = (-out["Δ Direct_Offline (€)"]).clip(lower=0)
    other_growth = ((out["Direct_Website new (€)"] - out["Direct_Website old (€)"])
                    + (out["OTA new (€)"] - out["OTA old (€)"])).clip(lower=0)
    out["Channel-Move?"] = np.where((drop_do > 0) & (other_growth >= 0.5 * drop_do),
                                    "✓ wahrscheinlich", "-")
    return out


def directoffline_waterfall(res_a, res_b, year_old, year_new, label,
                            realized_only: bool = True):
    """§12 Waterfall + Buckets. Returns (fig, buckets|None)."""
    def by_company(df):
        mask = (df["channel_combo"] == "Direct_Offline") & _has_company(df)
        if realized_only:
            mask = mask & df["is_realized"]
        return df[mask].groupby("company")["revenue"].sum()

    comp = pd.DataFrame({"old": by_company(res_a), "new": by_company(res_b)}).fillna(0.0)
    if comp.empty:
        return _empty("Keine Direct-Offline-Firmenbuchungen im Zeitraum."), None
    comp["delta"] = comp["new"] - comp["old"]
    lost = comp[(comp["old"] > 0) & (comp["new"] == 0)]
    gained = comp[(comp["old"] == 0) & (comp["new"] > 0)]
    shrunk = comp[(comp["old"] > 0) & (comp["new"] > 0) & (comp["delta"] < 0)]
    grown = comp[(comp["old"] > 0) & (comp["new"] > 0) & (comp["delta"] > 0)]

    labels = [f"Firmen {year_old}", "verloren", "geschrumpft", "gewachsen", "neu",
              f"Firmen {year_new}"]
    values = [comp["old"].sum(), -lost["old"].sum(), shrunk["delta"].sum(),
              grown["delta"].sum(), gained["new"].sum(), comp["new"].sum()]
    measure = ["absolute", "relative", "relative", "relative", "relative", "total"]

    fig = go.Figure(go.Waterfall(
        x=labels, measure=measure, y=values,
        text=[H.fmt_eur(v) for v in values], textposition="outside",
        connector=dict(line=dict(color=theme.GREY, width=1)),
        increasing=dict(marker=dict(color=theme.GREEN)),
        decreasing=dict(marker=dict(color=theme.RED)),
        totals=dict(marker=dict(color=theme.YELLOW, line=dict(color=theme.BLACK, width=0.4))),
    ))
    theme.brand_figure(fig)
    fig.update_yaxes(title_text="Revenue (€, netto)")
    fig.update_layout(showlegend=False)
    return fig, {"lost": lost, "gained": gained, "shrunk": shrunk, "grown": grown, "all": comp}


def directoffline_segments(res_a, res_b, year_old, year_new, label,
                           realized_only: bool = True) -> go.Figure:
    """§12 Direct-Offline nach Aufenthaltsdauer + Reisezweck (old vs new)."""
    mask_a = res_a["channel_combo"] == "Direct_Offline"
    mask_b = res_b["channel_combo"] == "Direct_Offline"
    if realized_only:
        mask_a = mask_a & res_a["is_realized"]
        mask_b = mask_b & res_b["is_realized"]
    do_a = res_a[mask_a]
    do_b = res_b[mask_b]

    fig = make_subplots(rows=1, cols=2, horizontal_spacing=0.12,
                        subplot_titles=("Direct Offline nach Aufenthaltsdauer",
                                        "Direct Offline nach Reisezweck"))

    a = do_a.groupby("los_bucket", observed=True)["revenue"].sum().reindex(_LOS_ORDER, fill_value=0)
    b = do_b.groupby("los_bucket", observed=True)["revenue"].sum().reindex(_LOS_ORDER, fill_value=0)
    fig.add_trace(go.Bar(x=_LOS_ORDER, y=a.values, name=str(year_old),
                         marker=dict(color=theme.GREY, line=dict(color=theme.BLACK, width=0.4)),
                         hovertemplate="%{x}: %{y:,.0f} €<extra>" + str(year_old) + "</extra>"),
                  row=1, col=1)
    fig.add_trace(go.Bar(x=_LOS_ORDER, y=b.values, name=str(year_new),
                         marker=dict(color=theme.YELLOW, line=dict(color=theme.BLACK, width=0.4)),
                         hovertemplate="%{x}: %{y:,.0f} €<extra>" + str(year_new) + "</extra>"),
                  row=1, col=1)
    anns = []
    for i, (vo, vn) in enumerate(zip(a.values, b.values)):
        anns.append(dict(x=_LOS_ORDER[i], y=max(vo, vn, 1) * 1.04, xref="x", yref="y",
                         text="Δ " + H.fmt_eur(vn - vo), showarrow=False, font=dict(size=9)))

    def purpose_rev(df):
        p = np.where(df["travelPurpose"].astype(str).str.lower().eq("business"),
                     "Business", "Leisure")
        return df.assign(_p=p).groupby("_p")["revenue"].sum()

    order = ["Business", "Leisure"]
    pa = purpose_rev(do_a).reindex(order, fill_value=0)
    pb = purpose_rev(do_b).reindex(order, fill_value=0)
    fig.add_trace(go.Bar(x=order, y=pa.values, name=str(year_old), showlegend=False,
                         marker=dict(color=theme.GREY, line=dict(color=theme.BLACK, width=0.4)),
                         hovertemplate="%{x}: %{y:,.0f} €<extra>" + str(year_old) + "</extra>"),
                  row=1, col=2)
    fig.add_trace(go.Bar(x=order, y=pb.values, name=str(year_new), showlegend=False,
                         marker=dict(color=theme.YELLOW, line=dict(color=theme.BLACK, width=0.4)),
                         hovertemplate="%{x}: %{y:,.0f} €<extra>" + str(year_new) + "</extra>"),
                  row=1, col=2)
    for i, (vo, vn) in enumerate(zip(pa.values, pb.values)):
        anns.append(dict(x=order[i], y=max(vo, vn, 1) * 1.04, xref="x2", yref="y2",
                         text="Δ " + H.fmt_eur(vn - vo), showarrow=False, font=dict(size=9)))
    theme.add_annotations(fig, anns)

    theme.brand_figure(fig)
    fig.update_yaxes(title_text="Revenue (€, netto)", row=1, col=1)
    fig.update_yaxes(title_text="Revenue (€, netto)", row=1, col=2)
    fig.update_layout(barmode="group")
    return fig


# =============================================================================
# 13 · Top-Vertragscodes (effective_code) in der Periode
# =============================================================================
def top_codes_in_period(res_period, realized_only: bool = True) -> pd.DataFrame:
    """§13 Top-Vertragscodes nach Revenue in der aktuellen Periode - Roh-Frame."""
    if "effective_code" not in res_period.columns:
        return pd.DataFrame()
    mask = res_period["effective_code"].notna()
    if realized_only:
        mask = mask & res_period["is_realized"]
    d = res_period[mask].copy()
    d["effective_code"] = d["effective_code"].astype(str).str.strip()
    d = d[d["effective_code"] != ""]
    if d.empty:
        return pd.DataFrame()

    g = d.groupby("effective_code")
    out = pd.DataFrame({
        "Code": g.size().index,
        "Firma": g["company"].agg(
            lambda s: s.dropna().astype(str).value_counts().index[0] if s.dropna().size else ""
        ).values,
        "Buchungen": g["id"].nunique().values,
        "Nächte": g["nights"].sum().astype(int).values,
        "Personen": g["adults"].sum().astype("Int64").values,
        "Revenue (€)": g["revenue"].sum().round(2).values,
    })
    out["ADR (€)"] = (out["Revenue (€)"] / out["Nächte"].replace(0, np.nan)).round(2)
    return out.sort_values("Revenue (€)", ascending=False).reset_index(drop=True)
