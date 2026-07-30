# dash_app/components/global_report_charts.py
# Pure Plotly builders for the Global Report page - a straight port of the old
# matplotlib builders in the global_charts module. Every builder
# takes DataFrames in and returns a brand_figure'd go.Figure; axes, ordering and
# annotations mirror the matplotlib originals. Colours come only from theme:
# HEAT_SCALE for magnitude heatmaps, DIVERGING_SCALE for YoY-delta heatmaps,
# GREY for the prior-year (Vorjahr) series.

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dash_app import theme
from dash_app.backend.global_tables import _channel_label
from revenueblindspots import helpers as H

_LOS_COLS = ["short_<=6", "mid_7-28", "long_29+"]


def _empty(msg: str) -> go.Figure:
    """Placeholder figure for empty inputs (mirrors the mpl 'Keine Daten' axes)."""
    fig = go.Figure()
    fig.add_annotation(text=msg, x=0.5, y=0.5, xref="paper", yref="paper",
                       showarrow=False, font=dict(size=14, color=theme.GREY))
    theme.brand_figure(fig)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return fig


# =============================================================================
# 1 · Visual Scorecard - IST-Revenue je Standort, sortiert nach Δ vs PLAN
# =============================================================================
def visual_scorecard(raw_stay: pd.DataFrame, year_old: int, year_new: int,
                     period_tag: str, green_pct: float = 2.0,
                     red_pct: float = -10.0) -> go.Figure:
    score = raw_stay[raw_stay["Standort"] != "Total"].copy()
    if score.empty:
        return _empty("Keine Standortdaten für Scorecard")
    score = score.sort_values("d_plan_pct", ascending=True, na_position="first")
    order = score["Standort"].tolist()

    colors = [
        theme.GREY if pd.isna(d)
        else theme.GREEN if d >= green_pct
        else theme.RED if d <= red_pct
        else theme.ORANGE
        for d in score["d_plan_pct"]
    ]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=order, x=score["ist_new"], orientation="h",
        marker=dict(color=colors, line=dict(color=theme.BLACK, width=0.4)),
        showlegend=False, name=f"IST {year_new}",
        hovertemplate="%{y}: %{x:,.0f} €<extra></extra>",
    ))

    plan_rows = score[score["plan_new"] > 0]
    if len(plan_rows):
        fig.add_trace(go.Scatter(
            x=plan_rows["plan_new"], y=plan_rows["Standort"], mode="markers",
            marker=dict(symbol="line-ns", size=22, color=theme.BLACK,
                        line=dict(color=theme.BLACK, width=2.5)),
            name="PLAN", hovertemplate="PLAN %{x:,.0f} €<extra></extra>",
        ))
    ly_rows = score[score["ist_old"] > 0]
    if len(ly_rows):
        fig.add_trace(go.Scatter(
            x=ly_rows["ist_old"], y=ly_rows["Standort"], mode="markers",
            marker=dict(symbol="line-ns", size=18, color=theme.GREY,
                        line=dict(color=theme.GREY, width=1.8)),
            name=f"IST {year_old}", hovertemplate=f"IST {year_old} %{{x:,.0f}} €<extra></extra>",
        ))

    anns = []
    for _, r in score.iterrows():
        d = r["d_plan_pct"]
        if pd.notna(d):
            anns.append(dict(
                x=max(r["ist_new"], r["plan_new"]) * 1.01, y=r["Standort"],
                text=f"{d:+.1f} %", showarrow=False, xanchor="left", yanchor="middle",
                font=dict(size=10, color=theme.GREEN if d >= 0 else theme.RED)))
    theme.add_annotations(fig, anns)

    # Legend-only swatches for the colour thresholds (x=None => not drawn).
    for col, lbl in [
        (theme.GREEN, f"IST ≥ PLAN {green_pct:+g} %"),
        (theme.ORANGE, "IST im Korridor"),
        (theme.RED, f"IST ≤ PLAN {red_pct:+g} %"),
        (theme.GREY, "kein PLAN hinterlegt"),
    ]:
        fig.add_trace(go.Scatter(
            x=[None], y=[order[0]], mode="markers",
            marker=dict(symbol="square", size=12, color=col), name=lbl,
        ))

    fig.update_layout(
        title=f"Scorecard · {period_tag} · sortiert nach Δ vs. PLAN",
        xaxis_title="Revenue (€, netto)", barmode="overlay",
    )
    fig.update_yaxes(categoryorder="array", categoryarray=order)
    return theme.brand_figure(fig)


# =============================================================================
# 5 · Channel-Mix Donuts - Anteil je Channel OLD vs NEW (Top-7 + Andere)
# =============================================================================
def channel_mix_donuts(raw_channel: pd.DataFrame, year_old: int,
                       year_new: int) -> go.Figure:
    df = raw_channel[raw_channel["Channel"] != "Total"].copy()
    if df.empty:
        return _empty("Keine Channel-Daten")

    df_sorted = df.sort_values("rev_new", ascending=False)
    top = df_sorted.head(7)
    rest = df_sorted.iloc[7:]
    if len(rest):
        other = pd.DataFrame([{
            "Channel": "Andere",
            "rev_new": rest["rev_new"].sum(), "rev_old": rest["rev_old"].sum(),
        }])
        top = pd.concat([top[["Channel", "rev_new", "rev_old"]], other], ignore_index=True)

    labels = top["Channel"].tolist()
    # Brand categorical order + neutral GREY overflow so "Andere" reads as grey.
    palette = (theme.CATEGORICAL + [theme.GREY])[: len(labels)]
    sum_old = float(top["rev_old"].sum()) or 1.0
    sum_new = float(top["rev_new"].sum()) or 1.0

    fig = go.Figure()
    fig.add_trace(go.Pie(
        labels=labels, values=top["rev_old"], hole=0.45, sort=False,
        direction="clockwise", domain=dict(x=[0.0, 0.46], y=[0.0, 0.9]),
        marker=dict(colors=palette, line=dict(color=theme.WHITE, width=2)),
        textinfo="percent", name=str(year_old),
    ))
    fig.add_trace(go.Pie(
        labels=labels, values=top["rev_new"], hole=0.45, sort=False,
        direction="clockwise", domain=dict(x=[0.54, 1.0], y=[0.0, 0.9]),
        marker=dict(colors=palette, line=dict(color=theme.WHITE, width=2)),
        textinfo="percent", name=str(year_new),
    ))
    theme.add_annotations(fig, [dict(
        x=x_c, y=0.45, xref="paper", yref="paper", showarrow=False,
        text=f"<b>{yr}</b><br>{H.fmt_eur(tot)}", font=dict(size=13))
        for x_c, yr, tot in [(0.23, year_old, sum_old), (0.77, year_new, sum_new)]])
    return theme.brand_figure(fig)


# =============================================================================
# 5 · Channel-Mix Bars - Top-N Channels horizontal, OLD vs NEW, YoY-Δ als Label
# =============================================================================
def channel_mix_bars(raw_channel: pd.DataFrame, year_old: int, year_new: int,
                     top_n: int = 8) -> go.Figure:
    df = raw_channel[raw_channel["Channel"] != "Total"].copy()
    if df.empty:
        return _empty("Keine Channel-Daten")
    df = df.sort_values("rev_new", ascending=False).head(top_n).iloc[::-1]
    order = df["Channel"].tolist()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=order, x=df["rev_old"], orientation="h", name=str(year_old),
        marker=dict(color=theme.GREY, line=dict(color=theme.BLACK, width=0.4)),
    ))
    fig.add_trace(go.Bar(
        y=order, x=df["rev_new"], orientation="h", name=str(year_new),
        marker=dict(color=theme.YELLOW, line=dict(color=theme.BLACK, width=0.4)),
    ))
    anns = []
    for _, r in df.iterrows():
        vo, vn, pct = r["rev_old"], r["rev_new"], r["d_pct"]
        txt = (f"  Δ {H.fmt_eur(vn - vo)} ({pct:+.1f} %)"
               if pd.notna(pct) else f"  +{H.fmt_eur(vn)} (neu)")
        anns.append(dict(
            x=max(vo, vn), y=r["Channel"], text=txt, showarrow=False,
            xanchor="left", yanchor="middle",
            font=dict(size=10, color=theme.GREEN if (pd.isna(pct) or pct >= 0) else theme.RED)))
    theme.add_annotations(fig, anns)
    fig.update_layout(title=f"Top-{top_n} Channels YoY", xaxis_title="Revenue (€, netto)",
                      barmode="group", bargap=0.25)
    fig.update_yaxes(categoryorder="array", categoryarray=order)
    return theme.brand_figure(fig)


# =============================================================================
# 6.A · Revenue-Heatmap Standort × Monat (Magnitude -> HEAT_SCALE)
# =============================================================================
def location_revenue_heatmap(nightly: pd.DataFrame, start_ts: pd.Timestamp,
                             end_ts: pd.Timestamp, realized_only: bool = True,
                             title_suffix: str = "") -> go.Figure:
    d = nightly[(nightly["stay_date"] >= start_ts) & (nightly["stay_date"] <= end_ts)].copy()
    if realized_only:
        d = d[d["is_realized"]]
    if d.empty:
        return _empty("Keine Daten")
    d["ym"] = d["stay_date"].dt.to_period("M").astype(str)
    piv = d.groupby(["property_code", "ym"], observed=True)["revenue"].sum().unstack(fill_value=0)
    piv = piv.reindex(sorted(piv.columns), axis=1).sort_index()

    x, y, z = list(piv.columns), list(piv.index), piv.values
    zmax = float(z.max()) if z.size else 0.0

    fig = go.Figure(go.Heatmap(
        z=z, x=x, y=y, colorscale=theme.HEAT_SCALE,
        colorbar=dict(title="Revenue (€)"),
        hovertemplate="%{y} · %{x}: %{z:,.0f} €<extra></extra>",
    ))
    theme.add_annotations(fig, [
        dict(x=col, y=row, text=H.fmt_eur(z[i, j]), showarrow=False,
             font=dict(size=8, color="white" if z[i, j] > zmax * 0.55 else theme.BLACK))
        for i, row in enumerate(y) for j, col in enumerate(x) if z[i, j] > 0])
    fig.update_layout(title=f"Revenue-Heatmap · Standort × Monat{title_suffix}")
    fig.update_xaxes(tickangle=-45, showgrid=False)
    fig.update_yaxes(autorange="reversed", showgrid=False)
    return theme.brand_figure(fig)


# =============================================================================
# 6.B · Channel-Mix je Standort (%-Anteil, Magnitude -> HEAT_SCALE)
# =============================================================================
def channel_x_location_heatmap(nightly: pd.DataFrame, start_ts: pd.Timestamp,
                               end_ts: pd.Timestamp, realized_only: bool = True) -> go.Figure:
    d = nightly[(nightly["stay_date"] >= start_ts) & (nightly["stay_date"] <= end_ts)].copy()
    if realized_only:
        d = d[d["is_realized"]]
    if d.empty:
        return _empty("Keine Daten")
    d["ch"] = d["channel_combo"].map(_channel_label)
    piv = d.groupby(["property_code", "ch"], observed=True)["revenue"].sum().unstack(fill_value=0)
    piv_pct = piv.div(piv.sum(axis=1).replace(0, 1), axis=0) * 100
    order = piv.sum(axis=0).sort_values(ascending=False).index.tolist()
    piv_pct = piv_pct.reindex(columns=order, fill_value=0).sort_index()

    x, y, z = list(piv_pct.columns), list(piv_pct.index), piv_pct.values
    fig = go.Figure(go.Heatmap(
        z=z, x=x, y=y, colorscale=theme.HEAT_SCALE, zmin=0, zmax=80,
        colorbar=dict(title="% Revenue je Standort"),
        hovertemplate="%{y} · %{x}: %{z:.0f} %<extra></extra>",
    ))
    theme.add_annotations(fig, [
        dict(x=col, y=row, text=f"{z[i, j]:.0f}%", showarrow=False,
             font=dict(size=8, color="white" if z[i, j] > 40 else theme.BLACK))
        for i, row in enumerate(y) for j, col in enumerate(x) if z[i, j] >= 1])
    fig.update_layout(title="Channel-Mix je Standort (Anteil %)")
    fig.update_xaxes(tickangle=-35, showgrid=False)
    fig.update_yaxes(autorange="reversed", showgrid=False)
    return theme.brand_figure(fig)


# =============================================================================
# 6.C · Top-Movers - diverging Bars, best/worst YoY-Δ in EUR
# =============================================================================
def top_movers(raw_stay: pd.DataFrame, year_old: int, year_new: int) -> go.Figure:
    df = raw_stay[raw_stay["Standort"] != "Total"].copy()
    if df.empty:
        return _empty("Keine Daten")
    df = df.sort_values("d_ly_eur", ascending=True)
    order = df["Standort"].tolist()
    colors = [theme.GREEN if v >= 0 else theme.RED for v in df["d_ly_eur"]]

    fig = go.Figure(go.Bar(
        y=order, x=df["d_ly_eur"], orientation="h",
        marker=dict(color=colors, line=dict(color=theme.BLACK, width=0.4)),
        showlegend=False, hovertemplate="%{y}: %{x:,.0f} €<extra></extra>",
    ))
    theme.add_annotations(fig, [
        dict(x=r["d_ly_eur"], y=r["Standort"], text="  " + H.fmt_eur(r["d_ly_eur"]),
             showarrow=False, xanchor="left" if r["d_ly_eur"] >= 0 else "right",
             yanchor="middle",
             font=dict(size=10, color=theme.GREEN if r["d_ly_eur"] >= 0 else theme.RED))
        for _, r in df.iterrows()])
    fig.add_vline(x=0, line_color=theme.BLACK, line_width=0.8)
    fig.update_layout(title="Top-Movers · Δ Revenue YoY (nach Aufenthalt)",
                      xaxis_title=f"Δ Revenue (€)  ·  {year_new} vs {year_old}")
    fig.update_yaxes(categoryorder="array", categoryarray=order)
    return theme.brand_figure(fig)


# =============================================================================
# 6.D · Channel × LOS granular - links YoY-Heatmap (DIVERGING), rechts Anteil-Bars
# =============================================================================
def channel_los_heatmap_granular(nightly: pd.DataFrame,
                                 start_old: pd.Timestamp, end_old: pd.Timestamp,
                                 start_new: pd.Timestamp, end_new: pd.Timestamp,
                                 year_old: int, year_new: int,
                                 top_n_channels: int = 8,
                                 realized_only: bool = True) -> go.Figure:
    def agg(start, end):
        d = nightly[(nightly["stay_date"] >= start) & (nightly["stay_date"] <= end)]
        if realized_only:
            d = d[d["is_realized"]]
        if d.empty:
            return pd.DataFrame(columns=_LOS_COLS)
        d = d.assign(_ch=d["channel_combo"].map(_channel_label))
        return (d.groupby(["_ch", "los_bucket"], observed=True)["revenue"].sum()
                .unstack(fill_value=0).reindex(columns=_LOS_COLS, fill_value=0))

    a = agg(start_old, end_old)
    b = agg(start_new, end_new)
    totals = (a.sum(axis=1) + b.sum(axis=1)).sort_values(ascending=False)
    rows = totals.head(top_n_channels).index.tolist()
    if not rows:
        return _empty("Keine Channel-Daten")
    a = a.reindex(index=rows, columns=_LOS_COLS, fill_value=0)
    b = b.reindex(index=rows, columns=_LOS_COLS, fill_value=0)
    rel = ((b / a.replace(0, np.nan)) - 1) * 100

    fig = make_subplots(rows=1, cols=2, column_widths=[0.42, 0.58],
                        horizontal_spacing=0.2,
                        subplot_titles=(f"YoY je Channel × LOS · {year_old} → {year_new}",
                                        f"Anteil je Zelle · {year_old} vs {year_new}"))

    # Links: YoY-Heatmap (rows[0] oben via reversed y-axis).
    fig.add_trace(go.Heatmap(
        z=rel.fillna(0).values, x=_LOS_COLS, y=rows, colorscale=theme.DIVERGING_SCALE,
        zmin=-100, zmax=100, colorbar=dict(title="% YoY", x=0.37, len=0.9, thickness=10),
        hovertemplate="%{y} · %{x}: %{z:+.0f} %<extra></extra>",
    ), row=1, col=1)
    anns = []
    for i, ch in enumerate(rows):
        for j, los in enumerate(_LOS_COLS):
            v = rel.iloc[i, j]
            delta = b.iloc[i, j] - a.iloc[i, j]
            txt = (f"{v:+.0f} %" if pd.notna(v) else "neu") + f"<br>({H.fmt_eur(delta)})"
            anns.append(dict(
                x=los, y=ch, text=txt, showarrow=False, xref="x", yref="y",
                font=dict(size=8,
                          color="white" if (pd.notna(v) and abs(v) >= 60) else theme.BLACK)))

    # Rechts: Revenue-Anteil je Zelle OLD vs NEW.
    sa = float(a.values.sum()) or 1.0
    sb = float(b.values.sum()) or 1.0
    pairs = [(r, c) for r in rows for c in _LOS_COLS]
    pair_labels = [f"{r} · {c}" for r, c in pairs]
    sh_a = [a.loc[r, c] / sa * 100 for r, c in pairs]
    sh_b = [b.loc[r, c] / sb * 100 for r, c in pairs]
    fig.add_trace(go.Bar(
        y=pair_labels, x=sh_a, orientation="h", name=str(year_old),
        marker=dict(color=theme.GREY, line=dict(color=theme.BLACK, width=0.4)),
    ), row=1, col=2)
    fig.add_trace(go.Bar(
        y=pair_labels, x=sh_b, orientation="h", name=str(year_new),
        marker=dict(color=theme.YELLOW, line=dict(color=theme.BLACK, width=0.4)),
    ), row=1, col=2)
    for lbl, va, vb in zip(pair_labels, sh_a, sh_b):
        if vb >= 0.5:
            anns.append(dict(x=max(va, vb), y=lbl, text=f"  {vb:.1f}%", showarrow=False,
                             xanchor="left", yanchor="middle", font=dict(size=8),
                             xref="x2", yref="y2"))
    theme.add_annotations(fig, anns)

    fig.update_layout(barmode="group", bargap=0.2)
    fig.update_xaxes(showgrid=False, row=1, col=1)
    fig.update_yaxes(autorange="reversed", showgrid=False, row=1, col=1)
    fig.update_xaxes(title_text="Revenue-Anteil (%)", row=1, col=2)
    fig.update_yaxes(autorange="reversed", row=1, col=2)
    return theme.brand_figure(fig)
