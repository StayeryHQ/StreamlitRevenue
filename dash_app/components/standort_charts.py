# dash_app/components/standort_charts.py
# Pure Plotly builders for the Standort-Analyse page (sections 1-10) - a straight
# port of the old matplotlib builders in the charts module. Every
# builder takes the same DataFrames the source page passed and returns a
# brand_figure'd go.Figure; axes, ordering and annotations mirror the matplotlib
# originals. Colours come only from theme: YELLOW = current (NEW) series, GREY =
# previous-period (OLD) series, DIVERGING_SCALE for YoY-delta heatmaps.

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dash_app import theme
from revenueblindspots import helpers as H

_LOS_COLS = ["short_<=6", "mid_7-28", "long_29+"]

_DE_MONTH = {
    "01": "Jan", "02": "Feb", "03": "Mär", "04": "Apr", "05": "Mai", "06": "Jun",
    "07": "Jul", "08": "Aug", "09": "Sep", "10": "Okt", "11": "Nov", "12": "Dez",
}

_WEEKDAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                  "Saturday", "Sunday"]
_WEEKDAY_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


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
# 1 · Landscape KPIs - 4-Panel Chart (Occupancy · ADR · Revenue · ALOS)
# =============================================================================
def landscape_kpis_chart(kpi_o: dict, kpi_n: dict, monthly_o: pd.DataFrame,
                         monthly_n: pd.DataFrame, year_old: int, year_new: int,
                         label: str) -> go.Figure:
    panels = [
        ("Occupancy", "occupancy_pct", lambda v: f"{v:.1f} %"),
        ("ADR", "adr_eur", H.fmt_eur),
        ("Revenue", "revenue_eur", H.fmt_eur),
        ("ALOS", "alos_nights", lambda v: f"{v:.2f} N."),
    ]
    # YoY-Overlay nach Monat-des-Jahres ausrichten. OLD und NEW koennen
    # unterschiedlich viele Monate mit Daten haben - gemeinsame Achse = Vereinigung
    # der Monatsnummern (01-12).
    _mn = {m.split("-")[1]: m for m in sorted(monthly_n["stay_year_month"].tolist())}
    _mo = {m.split("-")[1]: m for m in sorted(monthly_o["stay_year_month"].tolist())}
    months_axis = sorted(set(_mn) | set(_mo))
    de_lab = [_DE_MONTH.get(mm, mm) for mm in months_axis]

    fig = make_subplots(rows=2, cols=2, subplot_titles=[p[0] for p in panels],
                        vertical_spacing=0.16, horizontal_spacing=0.09)
    positions = [(1, 1), (1, 2), (2, 1), (2, 2)]
    axis_refs = [("x domain", "y domain"), ("x2 domain", "y2 domain"),
                 ("x3 domain", "y3 domain"), ("x4 domain", "y4 domain")]

    anns = []
    for idx, (title, key, fmt) in enumerate(panels):
        r, c = positions[idx]
        xref, yref = axis_refs[idx]
        vo, vn = kpi_o.get(key), kpi_n.get(key)
        delta = ((vn / vo - 1) * 100) if (vo and pd.notna(vo) and pd.notna(vn)) else float("nan")
        dcol = theme.GREY if np.isnan(delta) else (theme.GREEN if delta >= 0 else theme.RED)

        _so = monthly_o.set_index("stay_year_month")[key]
        _sn = monthly_n.set_index("stay_year_month")[key]
        s_o = [float(_so.get(_mo[mm])) if mm in _mo else None for mm in months_axis]
        s_n = [float(_sn.get(_mn[mm])) if mm in _mn else None for mm in months_axis]

        show_legend = idx == 0
        fig.add_trace(go.Scatter(
            x=de_lab, y=s_o, mode="lines+markers", name=str(year_old),
            legendgroup="old", showlegend=show_legend,
            line=dict(color=theme.GREY), marker=dict(color=theme.GREY),
            connectgaps=True,
            hovertemplate="%{x}: %{y:,.1f}<extra>" + str(year_old) + "</extra>",
        ), row=r, col=c)
        fig.add_trace(go.Scatter(
            x=de_lab, y=s_n, mode="lines+markers", name=str(year_new),
            legendgroup="new", showlegend=show_legend,
            line=dict(color=theme.YELLOW), marker=dict(color=theme.YELLOW),
            connectgaps=True,
            hovertemplate="%{x}: %{y:,.1f}<extra>" + str(year_new) + "</extra>",
        ), row=r, col=c)

        big = fmt(vn) if pd.notna(vn) else "–"
        anns.append(dict(x=0.02, y=0.95, xref=xref, yref=yref, showarrow=False,
                         text=f"<b>{big}</b>", xanchor="left", yanchor="top",
                         font=dict(size=19, color=theme.BLACK)))
        anns.append(dict(x=0.02, y=0.78, xref=xref, yref=yref, showarrow=False,
                         text=f"YoY {delta:+.1f} %" if not np.isnan(delta) else "YoY n/a",
                         xanchor="left", yanchor="top",
                         font=dict(size=11, color=dcol)))
        old_txt = fmt(vo) if pd.notna(vo) else "–"
        anns.append(dict(x=0.02, y=0.66, xref=xref, yref=yref, showarrow=False,
                         text=f"{old_txt} ({year_old})", xanchor="left", yanchor="top",
                         font=dict(size=10, color=theme.GREY)))

        vals = [v for v in (s_o + s_n) if v is not None]
        ymax = max(vals) * 1.15 if vals else 1.0
        fig.update_yaxes(range=[0, ymax if ymax > 0 else 1], row=r, col=c)

    theme.add_annotations(fig, anns)
    fig.update_layout(
        title=f"{label} - Landscape {year_old} vs {year_new} (Realized, Stay-Date)",
        margin=dict(l=50, r=20, t=90, b=40),
    )
    return theme.brand_figure(fig)


# =============================================================================
# 2 · Channel-Mix - Monatlicher Anteil (stacked) + Top-N YoY-Bars
# =============================================================================
def channel_mix(nig_old: pd.DataFrame, nig_new: pd.DataFrame,
                full_nightly: pd.DataFrame, year_old: int, year_new: int,
                label: str, top_n: int = 6, realized_only: bool = True) -> go.Figure:
    fig = make_subplots(rows=1, cols=2, column_widths=[0.44, 0.56],
                        horizontal_spacing=0.12,
                        subplot_titles=("Monatlicher Channel-Anteil",
                                        f"YoY je Channel-Detail (Top-{top_n})"))

    # Links: monatlicher Channel-Anteil (stacked bar, Direct vs OTA).
    base_df = full_nightly[full_nightly["is_realized"]] if realized_only else full_nightly
    share = (base_df.groupby(["stay_year_month", "channel_group"], observed=True)["revenue"]
             .sum().unstack(fill_value=0))
    if not share.empty:
        share = (share.div(share.sum(axis=1).replace(0, 1), axis=0) * 100).round(1)
        months = share.index.tolist()
        colors = {"Direct": theme.YELLOW, "OTA": theme.BLUE}
        base = np.zeros(len(months))
        for grp in ["Direct", "OTA"]:
            if grp in share.columns:
                fig.add_trace(go.Bar(
                    x=months, y=share[grp], base=base.copy(), offsetgroup="mix",
                    name=grp, legendgroup=grp,
                    marker=dict(color=colors[grp], line=dict(color=theme.WHITE, width=0.4)),
                    hovertemplate="%{x} · " + grp + ": %{y:.1f} %<extra></extra>",
                ), row=1, col=1)
                base = base + share[grp].to_numpy()

    # Rechts: horizontaler Top-N YoY-Vergleich pro channel_combo.
    a = (nig_old[nig_old["is_realized"]] if realized_only else nig_old
         ).groupby("channel_combo", observed=True)["revenue"].sum()
    b = (nig_new[nig_new["is_realized"]] if realized_only else nig_new
         ).groupby("channel_combo", observed=True)["revenue"].sum()
    union = a.index.union(b.index)
    df = pd.DataFrame({"o": a.reindex(union, fill_value=0),
                       "n": b.reindex(union, fill_value=0)}).sort_values("n").tail(top_n)
    order = df.index.astype(str).tolist()
    if order:
        fig.add_trace(go.Bar(
            y=order, x=df["o"], orientation="h", offsetgroup="old", name=str(year_old),
            legendgroup="old",
            marker=dict(color=theme.GREY, line=dict(color=theme.BLACK, width=0.4)),
        ), row=1, col=2)
        fig.add_trace(go.Bar(
            y=order, x=df["n"], orientation="h", offsetgroup="new", name=str(year_new),
            legendgroup="new",
            marker=dict(color=theme.YELLOW, line=dict(color=theme.BLACK, width=0.4)),
        ), row=1, col=2)
        anns = []
        for ch, vo, vn in zip(order, df["o"], df["n"]):
            pct = (vn / vo - 1) * 100 if vo > 0 else float("nan")
            txt = (f"  Δ {H.fmt_eur(vn - vo)} ({pct:+.0f} %)" if pd.notna(pct)
                   else f"  +{H.fmt_eur(vn)} (neu)")
            anns.append(dict(x=max(vo, vn), y=ch, text=txt, showarrow=False,
                             xanchor="left", yanchor="middle", font=dict(size=9),
                             xref="x2", yref="y2"))
        theme.add_annotations(fig, anns)
        fig.update_yaxes(categoryorder="array", categoryarray=order, row=1, col=2)

    fig.update_layout(title=f"{label} - Channel-Mix", barmode="group")
    fig.update_yaxes(title_text="% Revenue (Realized)", range=[0, 100], row=1, col=1)
    fig.update_xaxes(tickangle=-45, row=1, col=1)
    fig.update_xaxes(title_text="Revenue (€, netto)", row=1, col=2)
    return theme.brand_figure(fig)


# =============================================================================
# Shared: links YoY-Heatmap (DIVERGING) + rechts Revenue-Anteil-Bars je Zelle.
# =============================================================================
def _heat_and_share(a: pd.DataFrame, b: pd.DataFrame, super_title: str,
                    year_old: int, year_new: int, left_title: str,
                    *, share_rows: bool = False) -> go.Figure:
    # share_rows=False -> right panel shows the revenue share of each CELL
    # (row x LOS). share_rows=True -> share of each ROW (LOS summed), e.g. §4
    # channel x purpose, matching the original per-Channel-x-Reisezweck panel.
    rows = list(a.index)
    rel = ((b / a.replace(0, np.nan)) - 1) * 100

    share_title = "Anteil je Channel × Reisezweck" if share_rows else "Anteil je Zelle"
    fig = make_subplots(rows=1, cols=2, column_widths=[0.42, 0.58],
                        horizontal_spacing=0.22,
                        subplot_titles=(left_title,
                                        f"{share_title} · {year_old} vs {year_new}"))

    fig.add_trace(go.Heatmap(
        z=rel.fillna(0).values, x=_LOS_COLS, y=rows, colorscale=theme.DIVERGING_SCALE,
        zmin=-100, zmax=100, colorbar=dict(title="% YoY", x=0.37, len=0.9, thickness=10),
        hovertemplate="%{y} · %{x}: %{z:+.0f} %<extra></extra>",
    ), row=1, col=1)
    anns = []
    for i, rlab in enumerate(rows):
        for j, los in enumerate(_LOS_COLS):
            v = rel.iloc[i, j]
            delta = b.iloc[i, j] - a.iloc[i, j]
            txt = (f"{v:+.0f} %" if pd.notna(v) else "neu") + f"<br>({H.fmt_eur(delta)})"
            anns.append(dict(
                x=los, y=rlab, text=txt, showarrow=False, xref="x", yref="y",
                font=dict(size=8, color="white" if (pd.notna(v) and abs(v) >= 60)
                          else theme.BLACK)))

    sa = float(a.values.sum()) or 1.0
    sb = float(b.values.sum()) or 1.0
    if share_rows:
        ra, rb = a.sum(axis=1), b.sum(axis=1)
        pair_labels = list(rows)
        sh_a = [float(ra[r]) / sa * 100 for r in rows]
        sh_b = [float(rb[r]) / sb * 100 for r in rows]
    else:
        pairs = [(r, c) for r in rows for c in _LOS_COLS]
        pair_labels = [f"{r} · {c}" for r, c in pairs]
        sh_a = [a.loc[r, c] / sa * 100 for r, c in pairs]
        sh_b = [b.loc[r, c] / sb * 100 for r, c in pairs]
    fig.add_trace(go.Bar(
        y=pair_labels, x=sh_a, orientation="h", offsetgroup="old", name=str(year_old),
        legendgroup="old",
        marker=dict(color=theme.GREY, line=dict(color=theme.BLACK, width=0.4)),
    ), row=1, col=2)
    fig.add_trace(go.Bar(
        y=pair_labels, x=sh_b, orientation="h", offsetgroup="new", name=str(year_new),
        legendgroup="new",
        marker=dict(color=theme.YELLOW, line=dict(color=theme.BLACK, width=0.4)),
    ), row=1, col=2)
    for lbl, va, vb in zip(pair_labels, sh_a, sh_b):
        anns.append(dict(x=max(va, vb), y=lbl, text=f"  {vb:.0f}%", showarrow=False,
                         xanchor="left", yanchor="middle", font=dict(size=8),
                         xref="x2", yref="y2"))
    theme.add_annotations(fig, anns)

    fig.update_layout(title=super_title, barmode="group", bargap=0.2)
    fig.update_xaxes(showgrid=False, row=1, col=1)
    fig.update_yaxes(autorange="reversed", showgrid=False, row=1, col=1)
    fig.update_xaxes(title_text="Revenue-Anteil (%)", row=1, col=2)
    fig.update_yaxes(autorange="reversed", row=1, col=2)
    return theme.brand_figure(fig)


# =============================================================================
# 3 · Heatmap Channel × Aufenthaltsdauer
# =============================================================================
def channel_los_heatmap(nig_old: pd.DataFrame, nig_new: pd.DataFrame,
                        year_old: int, year_new: int, label: str,
                        realized_only: bool = True) -> go.Figure:
    rows = list(H.CHANNEL_BUCKETS)

    def agg(nig):
        d = H.filter_realized(nig, realized_only).copy()
        if d.empty:
            return pd.DataFrame(0.0, index=rows, columns=_LOS_COLS)
        d["row"] = H.channel_bucket(d["channel_combo"])
        return (d.groupby(["row", "los_bucket"], observed=True)["revenue"].sum()
                .unstack(fill_value=0).reindex(index=rows, columns=_LOS_COLS, fill_value=0))

    a, b = agg(nig_old), agg(nig_new)
    return _heat_and_share(a, b, f"{label} - Heatmap Channel × Aufenthaltsdauer",
                           year_old, year_new, "YoY-Änderung je Zelle")


# =============================================================================
# 4 · Heatmap Channel × Reisezweck × LOS
# =============================================================================
def channel_purpose_los_heatmap(nig_old: pd.DataFrame, nig_new: pd.DataFrame,
                                year_old: int, year_new: int, label: str,
                                realized_only: bool = True) -> go.Figure:
    channels = ["Direct_Website", "Direct_Offline", "OTA"]
    purposes = ["Business", "Leisure"]
    row_keys = [(c, p) for c in channels for p in purposes]
    row_labels = [f"{c} · {p}" for c, p in row_keys]

    def agg(nig):
        d = H.filter_realized(nig, realized_only).copy()
        out = pd.DataFrame(0.0, index=row_labels, columns=_LOS_COLS)
        if d.empty:
            return out
        d["ch"] = H.channel_bucket(d["channel_combo"])
        # Unbekannter/leerer Reisezweck zaehlt als Leisure (siehe Tooltip/Doku).
        d["purpose"] = np.where(
            d["travelPurpose"].astype(str).str.lower().eq("business"), "Business", "Leisure")
        g = d.groupby(["ch", "purpose", "los_bucket"], observed=True)["revenue"].sum()
        for (c, p), rlab in zip(row_keys, row_labels):
            for los in _LOS_COLS:
                out.loc[rlab, los] = float(g.get((c, p, los), 0.0))
        return out

    a, b = agg(nig_old), agg(nig_new)
    return _heat_and_share(a, b, f"{label} - Heatmap Channel × Reisezweck × LOS",
                           year_old, year_new, "YoY-Änderung je Zelle")


# =============================================================================
# Shared: Two-panel YoY - Revenue-Bars (links) + Anteils-Verschiebung pp (rechts)
# =============================================================================
def _yoy_two_panel(nig_old: pd.DataFrame, nig_new: pd.DataFrame, dim: str,
                   super_title: str, year_old: int, year_new: int,
                   realized_only: bool = True) -> go.Figure:
    yoy = H.yoy_by(nig_old, nig_new, dim, realized_only=realized_only).reset_index()
    if yoy.empty:
        return _empty("Keine Daten")
    yoy[dim] = yoy[dim].astype(str)
    order = yoy[dim].tolist()

    fig = make_subplots(rows=1, cols=2, horizontal_spacing=0.16,
                        subplot_titles=("Revenue YoY", "Anteils-Verschiebung"))

    fig.add_trace(go.Bar(
        y=order, x=yoy["revenue_eur_old"], orientation="h", offsetgroup="old",
        name=str(year_old), legendgroup="old",
        marker=dict(color=theme.GREY, line=dict(color=theme.BLACK, width=0.4)),
    ), row=1, col=1)
    fig.add_trace(go.Bar(
        y=order, x=yoy["revenue_eur_new"], orientation="h", offsetgroup="new",
        name=str(year_new), legendgroup="new",
        marker=dict(color=theme.YELLOW, line=dict(color=theme.BLACK, width=0.4)),
    ), row=1, col=1)
    anns = []
    for lab, vo, vn in zip(order, yoy["revenue_eur_old"], yoy["revenue_eur_new"]):
        anns.append(dict(x=max(vo, vn), y=lab, text="  Δ " + H.fmt_eur(vn - vo),
                         showarrow=False, xanchor="left", yanchor="middle",
                         font=dict(size=9), xref="x", yref="y"))

    pp = yoy["share_delta_pp"]
    fig.add_trace(go.Bar(
        y=order, x=pp, orientation="h", showlegend=False,
        marker=dict(color=[theme.GREEN if v >= 0 else theme.RED for v in pp],
                    line=dict(color=theme.BLACK, width=0.4)),
    ), row=1, col=2)
    for lab, v in zip(order, pp):
        anns.append(dict(x=v, y=lab, text=f"  {v:+.1f} pp", showarrow=False,
                         xanchor="left" if v >= 0 else "right", yanchor="middle",
                         font=dict(size=9), xref="x2", yref="y2"))
    theme.add_annotations(fig, anns)
    fig.add_vline(x=0, line_color=theme.BLACK, line_width=0.6, row=1, col=2)

    fig.update_layout(title=super_title, barmode="group")
    fig.update_xaxes(title_text="Revenue (€, netto)", row=1, col=1)
    fig.update_xaxes(title_text="Anteils-Verschiebung (pp)", row=1, col=2)
    fig.update_yaxes(categoryorder="array", categoryarray=order, row=1, col=1)
    fig.update_yaxes(categoryorder="array", categoryarray=order, row=1, col=2)
    return theme.brand_figure(fig)


# =============================================================================
# 5 · LOS Revenue YoY
# =============================================================================
def los_yoy(nig_old: pd.DataFrame, nig_new: pd.DataFrame, year_old: int,
            year_new: int, label: str, realized_only: bool = True) -> go.Figure:
    return _yoy_two_panel(nig_old, nig_new, "los_bucket",
                          f"{label} - Aufenthaltsdauer (LOS)", year_old, year_new,
                          realized_only=realized_only)


# =============================================================================
# 6 / 7 · Wochentag-Pattern - zwei Stacked-Bar-Panels (OLD | NEW)
# =============================================================================
def weekday_pattern(nig_old: pd.DataFrame, nig_new: pd.DataFrame, weekday_col: str,
                    year_old: int, year_new: int, label: str, title: str,
                    realized_only: bool = True) -> go.Figure:
    colors = {"Direct": theme.YELLOW, "OTA": theme.BLUE}

    def pivot(nig):
        return ((nig[nig["is_realized"]] if realized_only else nig)
                .groupby([weekday_col, "channel_group"], observed=True)["revenue"].sum()
                .unstack(fill_value=0).reindex(_WEEKDAY_ORDER).fillna(0))

    fig = make_subplots(rows=1, cols=2, shared_yaxes=True, horizontal_spacing=0.06,
                        subplot_titles=(str(year_old), str(year_new)))
    anns = []
    for col, nig in [(1, nig_old), (2, nig_new)]:
        piv = pivot(nig)
        total = np.zeros(7)
        for grp in ["Direct", "OTA"]:
            if grp in piv.columns:
                fig.add_trace(go.Bar(
                    x=_WEEKDAY_DE, y=piv[grp], name=grp, legendgroup=grp,
                    showlegend=(col == 1),
                    marker=dict(color=colors[grp], line=dict(color=theme.WHITE, width=0.5)),
                    hovertemplate="%{x} · " + grp + ": %{y:,.0f} €<extra></extra>",
                ), row=1, col=col)
                total = total + piv[grp].to_numpy()
        xr, yr = ("x", "y") if col == 1 else ("x2", "y2")
        for i, t in enumerate(total):
            if t > 0:
                anns.append(dict(x=_WEEKDAY_DE[i], y=t, text=H.fmt_eur(t),
                                 showarrow=False, yanchor="bottom",
                                 font=dict(size=8, color=theme.BLACK), xref=xr, yref=yr))
    theme.add_annotations(fig, anns)

    fig.update_layout(title=f"{label} - {title}", barmode="stack")
    fig.update_yaxes(title_text="Revenue (€, netto)", row=1, col=1)
    return theme.brand_figure(fig)


# =============================================================================
# 8 · Inland vs. Ausland - 3-Panel: Revenue abs · Anteil · Room-Nights (ADR)
# =============================================================================
def de_vs_international(nig_old: pd.DataFrame, nig_new: pd.DataFrame, year_old: int,
                       year_new: int, label: str,
                       realized_only: bool = True) -> go.Figure:
    def agg(nig):
        d = H.filter_realized(nig, realized_only)
        if d.empty or "origin" not in d.columns:
            return pd.Series(dtype=float), pd.Series(dtype=float)
        g = d.groupby(H.origin_bucket(d), observed=True)
        return g["revenue"].sum(), g["revenue"].size()

    rev_a, n_a = agg(nig_old)
    rev_b, n_b = agg(nig_new)
    cats = [c for c in H.ORIGIN_BUCKETS
            if not (c == "Unbekannt" and int(n_a.get(c, 0)) == 0 and int(n_b.get(c, 0)) == 0)]
    if not cats:
        return _empty("Keine Daten")
    ra = [float(rev_a.get(c, 0.0)) for c in cats]
    rb = [float(rev_b.get(c, 0.0)) for c in cats]
    na = [int(n_a.get(c, 0)) for c in cats]
    nb = [int(n_b.get(c, 0)) for c in cats]

    fig = make_subplots(rows=1, cols=3, horizontal_spacing=0.07,
                        subplot_titles=("Revenue absolut", "Revenue-Anteil",
                                        "Room-Nights (ADR annotiert)"))

    def grouped(col, y_old, y_new, text_old, text_new, show_legend):
        fig.add_trace(go.Bar(
            x=cats, y=y_old, offsetgroup="old", name=str(year_old), legendgroup="old",
            showlegend=show_legend, text=text_old, textposition="outside",
            marker=dict(color=theme.GREY, line=dict(color=theme.BLACK, width=0.4)),
        ), row=1, col=col)
        fig.add_trace(go.Bar(
            x=cats, y=y_new, offsetgroup="new", name=str(year_new), legendgroup="new",
            showlegend=show_legend, text=text_new, textposition="outside",
            marker=dict(color=theme.YELLOW, line=dict(color=theme.BLACK, width=0.4)),
        ), row=1, col=col)

    # Panel 1: Revenue absolut
    grouped(1, ra, rb, [H.fmt_eur(v) for v in ra], [H.fmt_eur(v) for v in rb], True)
    # Panel 2: Revenue-Anteil
    sa, sb = sum(ra) or 1, sum(rb) or 1
    sh_a = [v / sa * 100 for v in ra]
    sh_b = [v / sb * 100 for v in rb]
    grouped(2, sh_a, sh_b, [f"{v:.1f} %" for v in sh_a], [f"{v:.1f} %" for v in sh_b], False)
    # Panel 3: Room-Nights + ADR-Annotation
    txt_na = [f"{na[i]:,}".replace(",", ".") + f"<br>ADR {(ra[i]/na[i] if na[i] else 0):.0f} €"
              for i in range(len(cats))]
    txt_nb = [f"{nb[i]:,}".replace(",", ".") + f"<br>ADR {(rb[i]/nb[i] if nb[i] else 0):.0f} €"
              for i in range(len(cats))]
    grouped(3, na, nb, txt_na, txt_nb, False)

    fig.update_layout(title=f"{label} - Inland vs. Ausland", barmode="group")
    fig.update_yaxes(title_text="Revenue (€, netto)", row=1, col=1)
    fig.update_yaxes(title_text="Anteil (%)", row=1, col=2)
    fig.update_yaxes(title_text="Room-Nights" + (" (Realized)" if realized_only else ""),
                     row=1, col=3)
    return theme.brand_figure(fig)


# =============================================================================
# 9 · Top-Herkunftsländer - zwei Panels (OLD / NEW)
# =============================================================================
def top_countries(nig_old: pd.DataFrame, nig_new: pd.DataFrame, year_old: int,
                  year_new: int, label: str, top_n: int = 10,
                  realized_only: bool = True) -> go.Figure:
    fig = make_subplots(rows=1, cols=2, horizontal_spacing=0.12,
                        subplot_titles=(str(year_old), str(year_new)))
    for col, nig in [(1, nig_old), (2, nig_new)]:
        counts = ((nig[nig["is_realized"]] if realized_only else nig)
                  .groupby("origin", observed=True)["revenue"].sum()
                  .sort_values(ascending=False).head(top_n))
        if counts.empty:
            fig.add_annotation(text="Keine Daten", x=0.5, y=0.5,
                               xref="x domain", yref="y domain",
                               showarrow=False, font=dict(color=theme.GREY), row=1, col=col)
            continue
        labels = counts.index.astype(str).tolist()
        bar_colors = [theme.YELLOW if c == "DE" else theme.BLUE for c in labels]
        fig.add_trace(go.Bar(
            y=labels, x=counts.values, orientation="h", showlegend=False,
            marker=dict(color=bar_colors, line=dict(color=theme.BLACK, width=0.4)),
            text=["  " + H.fmt_eur(v) for v in counts.values], textposition="outside",
            hovertemplate="%{y}: %{x:,.0f} €<extra></extra>",
        ), row=1, col=col)
        fig.update_yaxes(categoryorder="array", categoryarray=labels[::-1], row=1, col=col)
        fig.update_xaxes(title_text="Revenue (€, netto)", row=1, col=col)

    fig.update_layout(title=f"{label} - Top-{top_n} Herkunftsländer")
    return theme.brand_figure(fig)


# =============================================================================
# 10 · Gruppen-Größe (basis=created, res_old/res_new)
# =============================================================================
def group_size_yoy(res_old: pd.DataFrame, res_new: pd.DataFrame, year_old: int,
                   year_new: int, label: str, realized_only: bool = True) -> go.Figure:
    return _yoy_two_panel(res_old, res_new, "group_size_bucket",
                          f"{label} - Gruppen-Größe (Zimmer je Buchung)",
                          year_old, year_new, realized_only=realized_only)
