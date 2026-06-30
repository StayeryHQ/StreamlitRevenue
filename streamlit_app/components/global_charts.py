"""Charts für den Global Report

Storno/No-Show Konvention:
  - "_stay" charts 
  - "_created" charts      
"""

from __future__ import annotations

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from revenueblindspots import helpers as H
from revenueblindspots.theming import categorical_palette as _pal
from revenueblindspots.theming import color


# =============================================================================
# Visual Scorecard
# =============================================================================
def visual_scorecard(
    raw_stay: pd.DataFrame,
    year_old: int,
    year_new: int,
    period_tag: str,
    green_pct: float = 2.0,
    red_pct: float = -10.0,
):
    """Horizontaler Bar-Chart: IST-Revenue je Standort, sortiert nach Δ vs PLAN.

    Farb-Logik nutzt die User-konfigurierbaren Schwellen (Slider in Sidebar):
      🟢 Δ ≥ green_pct   🟠 Korridor   🔴 Δ ≤ red_pct
    """
    score = raw_stay[raw_stay["Standort"] != "Total"].copy()
    if score.empty:
        fig, ax = plt.subplots(figsize=(10, 3))
        ax.text(0.5, 0.5, "Keine Standortdaten für Scorecard", ha="center", va="center")
        ax.set_axis_off()
        return fig
    score = score.sort_values("d_plan_pct", ascending=True, na_position="first")

    fig, ax = plt.subplots(figsize=(11, max(3.2, 0.42 * len(score) + 1.4)))
    y = np.arange(len(score))
    GREY = "#666666"  # Brand-Neutral Grey
    bar_colors = [
        GREY
        if pd.isna(d)
        else color("green")
        if d >= green_pct
        else color("red")
        if d <= red_pct
        else color("orange")
        for d in score["d_plan_pct"].values
    ]
    ax.barh(
        y,
        score["ist_new"],
        color=bar_colors,
        edgecolor=color("black"),
        linewidth=0.4,
        label=f"IST {year_new}",
    )

    for i in range(len(score)):
        ist = score["ist_new"].iloc[i]
        plan = score["plan_new"].iloc[i]
        if plan > 0:
            ax.plot(
                [plan, plan],
                [i - 0.38, i + 0.38],
                color=color("black"),
                linewidth=2.2,
                solid_capstyle="butt",
            )
        ly = score["ist_old"].iloc[i]
        if ly > 0:
            ax.plot([ly, ly], [i - 0.30, i + 0.30], color="#666666", linewidth=1.6, linestyle="--")
        d = score["d_plan_pct"].iloc[i]
        if pd.notna(d):
            ax.text(
                max(ist, plan) * 1.01,
                i,
                f"{d:+.1f} %",
                va="center",
                fontsize=9,
                weight="bold",
                color=color("green") if d >= 0 else color("red"),
            )

    ax.set_yticks(y)
    ax.set_yticklabels(score["Standort"])
    ax.set_xlabel("Revenue (€, netto)")
    ax.set_title(f"Scorecard · {period_tag} · sortiert nach Δ vs. PLAN", fontsize=12, weight="bold")
    handles = [
        Patch(facecolor=color("green"), label=f"IST ≥ PLAN {green_pct:+g} %"),
        Patch(facecolor=color("orange"), label="IST im Korridor"),
        Patch(facecolor=color("red"), label=f"IST ≤ PLAN {red_pct:+g} %"),
        Patch(facecolor=GREY, label="kein PLAN hinterlegt"),
        Line2D([0], [0], color=color("black"), linewidth=2.2, label="PLAN"),
        Line2D([0], [0], color="#666666", linewidth=1.6, linestyle="--", label=f"IST {year_old}"),
    ]
    ax.legend(handles=handles, frameon=False, fontsize=9, loc="lower right")
    ax.set_xlim(0, max(score["ist_new"].max(), score["plan_new"].max()) * 1.15)
    fig.tight_layout()
    return fig


# =============================================================================
# Channel-Mix Donuts
# =============================================================================
def channel_mix_donuts(raw_channel: pd.DataFrame, year_old: int, year_new: int):
    """Anteil je Channel OLD vs NEW."""
    df = raw_channel[raw_channel["Channel"] != "Total"].copy()
    if df.empty:
        fig, ax = plt.subplots(figsize=(10, 3))
        ax.text(0.5, 0.5, "Keine Channel-Daten", ha="center", va="center")
        ax.set_axis_off()
        return fig

    # Top-7 + "Andere"
    df_sorted = df.sort_values("rev_new", ascending=False)
    top = df_sorted.head(7)
    rest = df_sorted.iloc[7:]
    if len(rest):
        other = pd.DataFrame(
            [
                {
                    "Channel": "Andere",
                    "rev_new": rest["rev_new"].sum(),
                    "rev_old": rest["rev_old"].sum(),
                    "share_new": rest["share_new"].sum(),
                    "share_old": rest["share_old"].sum(),
                    "d_eur": 0,
                    "d_pct": 0,
                    "d_share_pp": 0,
                }
            ]
        )
        top = pd.concat([top, other], ignore_index=True)

    pal = _pal() + ["#666666", "#CCCCCC"]  # Overflow: Neutral Grey + Tint
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.0))
    for ax, vals, lbl in [
        (axes[0], top["rev_old"].values, year_old),
        (axes[1], top["rev_new"].values, year_new),
    ]:
        sum_v = vals.sum() or 1
        wedges, _ = ax.pie(
            vals,
            colors=pal[: len(vals)],
            wedgeprops=dict(width=0.42, edgecolor="white", linewidth=2),
        )
        ax.set_title(f"{lbl} · {H.fmt_eur(float(sum_v))}", fontsize=12, weight="bold")
        # Donut-center text
        ax.text(0, 0, f"{lbl}", ha="center", va="center", fontsize=14, weight="bold")
    # Geteilte Legende mit Anteilen
    legend_labels = [
        f"{ch} ({sn:.1f}% / {so:.1f}%)"
        for ch, sn, so in zip(top["Channel"], top["share_new"], top["share_old"])
    ]
    handles = [Patch(facecolor=pal[i], label=lbl) for i, lbl in enumerate(legend_labels)]
    fig.legend(
        handles=handles,
        loc="center",
        bbox_to_anchor=(0.5, -0.02),
        frameon=False,
        ncol=min(4, len(handles)),
        fontsize=9,
    )
    fig.suptitle(
        f"Channel-Mix · {year_old} vs {year_new} (Anteil + Δ)", fontsize=13, weight="bold", y=1.02
    )
    fig.tight_layout(rect=[0, 0.05, 1, 0.97])
    return fig


# =============================================================================
# Channel-Mix
# =============================================================================
def channel_mix_bars(raw_channel: pd.DataFrame, year_old: int, year_new: int, top_n: int = 8):
    """Top-N Channel horizontal, OLD vs NEW, mit YoY-Δ als Label."""
    df = raw_channel[raw_channel["Channel"] != "Total"].copy()
    if df.empty:
        fig, ax = plt.subplots(figsize=(10, 3))
        ax.text(0.5, 0.5, "Keine Channel-Daten", ha="center", va="center")
        ax.set_axis_off()
        return fig
    df = df.sort_values("rev_new", ascending=False).head(top_n)
    df = df.iloc[::-1]  # damit Top oben rauskommt
    pal = _pal()
    fig, ax = plt.subplots(figsize=(13, max(4, 0.5 * len(df) + 1.5)))
    y = np.arange(len(df))
    w = 0.38
    ax.barh(
        y - w / 2,
        df["rev_old"],
        w,
        color=pal[1],
        edgecolor=color("black"),
        linewidth=0.4,
        label=str(year_old),
    )
    ax.barh(
        y + w / 2,
        df["rev_new"],
        w,
        color=pal[0],
        edgecolor=color("black"),
        linewidth=0.4,
        label=str(year_new),
    )
    for i, (vo, vn, pct) in enumerate(zip(df["rev_old"], df["rev_new"], df["d_pct"])):
        txt = (
            f"  Δ {H.fmt_eur(vn - vo)}  ({pct:+.1f} %)"
            if pd.notna(pct)
            else f"  +{H.fmt_eur(vn)} (neu)"
        )
        ax.text(
            max(vo, vn),
            i,
            txt,
            va="center",
            fontsize=9,
            color=color("green") if (pd.isna(pct) or pct >= 0) else color("red"),
        )
    ax.set_yticks(y)
    ax.set_yticklabels(df["Channel"])
    ax.set_xlabel("Revenue (€, netto)")
    ax.set_title(f"Top-{top_n} Channels YoY", fontsize=12, weight="bold")
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    fig.tight_layout()
    return fig


# =============================================================================
# Location-Revenue-Heatmap
# =============================================================================
def location_revenue_heatmap(
    nightly: pd.DataFrame,
    properties: list[str],
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    realized_only: bool = True,
    title_suffix: str = "",
):
    """Heatmap: Standort × Monat - Revenue je Standort, monatlich.

    realized_only=True für "nach Aufenthalt"-Sicht (Storno + No-Show RAUS).
    """
    d = nightly[(nightly["stay_date"] >= start_ts) & (nightly["stay_date"] <= end_ts)].copy()
    if realized_only:
        d = d[d["is_realized"]]
    if d.empty:
        fig, ax = plt.subplots(figsize=(10, 3))
        ax.text(0.5, 0.5, "Keine Daten", ha="center", va="center")
        ax.set_axis_off()
        return fig
    d["ym"] = d["stay_date"].dt.to_period("M").astype(str)
    piv = d.groupby(["property_code", "ym"], observed=True)["revenue"].sum().unstack(fill_value=0)
    # y-Labels: Hotel-Codes (kompakter im Chart als Stadt-Namen).
    piv = piv.reindex(sorted(piv.columns), axis=1)
    piv = piv.sort_index()

    fig, ax = plt.subplots(
        figsize=(max(10, 1 + 1.0 * piv.shape[1]), max(3.5, 0.45 * piv.shape[0] + 1.5))
    )
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "yel", [color("white"), color("yellow"), color("orange")]
    )
    im = ax.imshow(piv.values, cmap=cmap, aspect="auto")
    ax.set_xticks(range(len(piv.columns)))
    ax.set_xticklabels(piv.columns, rotation=45, ha="right", fontsize=9)
    ax.set_yticks(range(len(piv.index)))
    ax.set_yticklabels(piv.index, fontsize=9)
    for i in range(piv.shape[0]):
        for j in range(piv.shape[1]):
            v = piv.values[i, j]
            if v > 0:
                ax.text(
                    j,
                    i,
                    H.fmt_eur(v),
                    ha="center",
                    va="center",
                    fontsize=7.5,
                    color="white" if v > piv.values.max() * 0.55 else "black",
                )
    fig.colorbar(im, ax=ax, shrink=0.7, label="Revenue (€)")
    ax.set_title(f"Revenue-Heatmap · Standort × Monat{title_suffix}", fontsize=12, weight="bold")
    fig.tight_layout()
    return fig


# =============================================================================
# Channel × Location Heatmap
# =============================================================================
def channel_x_location_heatmap(
    nightly: pd.DataFrame,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    realized_only: bool = True,
):
    """Heatmap Standort × Sales-Channel - %-Anteil je Standort."""
    d = nightly[(nightly["stay_date"] >= start_ts) & (nightly["stay_date"] <= end_ts)].copy()
    if realized_only:
        d = d[d["is_realized"]]
    if d.empty:
        fig, ax = plt.subplots(figsize=(10, 3))
        ax.text(0.5, 0.5, "Keine Daten", ha="center", va="center")
        ax.set_axis_off()
        return fig
    try:
        from .global_tables import _channel_label
    except ImportError:
        from global_tables import _channel_label  # type: ignore
    d["ch"] = d["channel_combo"].map(_channel_label)
    piv = d.groupby(["property_code", "ch"], observed=True)["revenue"].sum().unstack(fill_value=0)
    # %-Anteile je Standort
    piv_pct = piv.div(piv.sum(axis=1).replace(0, 1), axis=0) * 100

    # Channel-Reihenfolge: nach Total-Revenue absteigend
    order = piv.sum(axis=0).sort_values(ascending=False).index.tolist()
    piv_pct = piv_pct.reindex(columns=order, fill_value=0)
    # Standort-Reihenfolge: alphabetisch nach Hotel-Code (= y-Label im Chart).
    piv_pct = piv_pct.sort_index()

    fig, ax = plt.subplots(
        figsize=(max(10, 1.0 + 1.0 * piv_pct.shape[1]), max(3.5, 0.45 * piv_pct.shape[0] + 1.5))
    )
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "yelgrn", [color("white"), color("yellow"), color("green")]
    )
    im = ax.imshow(piv_pct.values, cmap=cmap, aspect="auto", vmin=0, vmax=80)
    ax.set_xticks(range(len(piv_pct.columns)))
    ax.set_xticklabels(piv_pct.columns, rotation=35, ha="right", fontsize=9)
    ax.set_yticks(range(len(piv_pct.index)))
    ax.set_yticklabels(piv_pct.index, fontsize=9)
    for i in range(piv_pct.shape[0]):
        for j in range(piv_pct.shape[1]):
            v = piv_pct.values[i, j]
            if v >= 1:
                ax.text(
                    j,
                    i,
                    f"{v:.0f}%",
                    ha="center",
                    va="center",
                    fontsize=8,
                    color="white" if v > 40 else "black",
                )
    fig.colorbar(im, ax=ax, shrink=0.7, label="% Revenue je Standort")
    ax.set_title("Channel-Mix je Standort (Anteil %)", fontsize=12, weight="bold")
    fig.tight_layout()
    return fig


# =============================================================================
# Heatmap Channel × LOS
# =============================================================================
def channel_los_heatmap_granular(
    nightly: pd.DataFrame,
    start_old: pd.Timestamp,
    end_old: pd.Timestamp,
    start_new: pd.Timestamp,
    end_new: pd.Timestamp,
    year_old: int,
    year_new: int,
    top_n_channels: int = 8,
    realized_only: bool = True,
):
    """Globaler Channel × LOS-Vergleich auf granularer Channel-Ebene.

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
        return (
            d.groupby(["_ch", "los_bucket"], observed=True)["revenue"]
            .sum()
            .unstack(fill_value=0)
            .reindex(columns=cols, fill_value=0)
        )

    a = agg(start_old, end_old)
    b = agg(start_new, end_new)

    # Channel-Reihenfolge: Top-N nach Total-Revenue (OLD + NEW)
    totals = (a.sum(axis=1) + b.sum(axis=1)).sort_values(ascending=False)
    rows = totals.head(top_n_channels).index.tolist()
    if not rows:
        fig, ax = plt.subplots(figsize=(10, 3))
        ax.text(0.5, 0.5, "Keine Channel-Daten", ha="center", va="center")
        ax.set_axis_off()
        return fig
    a = a.reindex(index=rows, columns=cols, fill_value=0)
    b = b.reindex(index=rows, columns=cols, fill_value=0)

    rel = ((b / a.replace(0, np.nan)) - 1) * 100
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "rdg", [color("red"), color("white"), color("green")]
    )

    fig, axes = plt.subplots(
        1,
        2,
        figsize=(15, max(3.6, 0.42 * len(rows) + 1.6)),
        gridspec_kw={"width_ratios": [1, 1.1]},
    )

    # Links - YoY-Heatmap je Channel × LOS-Bucket
    ax = axes[0]
    im = ax.imshow(rel.fillna(0).values, aspect="auto", cmap=cmap, vmin=-100, vmax=100)
    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels(cols, fontsize=10)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(rows, fontsize=10)
    for i in range(len(rows)):
        for j in range(len(cols)):
            v = rel.iloc[i, j]
            delta = b.iloc[i, j] - a.iloc[i, j]
            txt = (f"{v:+.0f} %" if pd.notna(v) else "neu") + f"\n({H.fmt_eur(delta)})"
            ax.text(
                j,
                i,
                txt,
                ha="center",
                va="center",
                fontsize=8,
                weight="bold",
                color="black" if not pd.notna(v) or abs(v) < 60 else "white",
            )
    ax.set_title(f"YoY je Channel × LOS · {year_old} → {year_new}", fontsize=11, weight="bold")
    fig.colorbar(im, ax=ax, shrink=0.7, label="% YoY")

    # Rechts - Anteil OLD vs NEW pro Zelle (Channel × LOS)
    ax = axes[1]
    sa = a.values.sum() or 1
    sb = b.values.sum() or 1
    pairs = [(r, c) for r in rows for c in cols]
    sh_a = [a.loc[r, c] / sa * 100 for r, c in pairs]
    sh_b = [b.loc[r, c] / sb * 100 for r, c in pairs]
    y = np.arange(len(pairs))
    w = 0.4
    pal_colors = _pal()
    ax.barh(
        y - w / 2,
        sh_a,
        w,
        color=pal_colors[1],
        edgecolor=color("black"),
        linewidth=0.4,
        label=str(year_old),
    )
    ax.barh(
        y + w / 2,
        sh_b,
        w,
        color=pal_colors[0],
        edgecolor=color("black"),
        linewidth=0.4,
        label=str(year_new),
    )
    for i, (va, vb) in enumerate(zip(sh_a, sh_b)):
        if vb >= 0.5:
            ax.text(max(va, vb), i, f"  {vb:.1f}%", va="center", fontsize=7.5)
    ax.set_yticks(y)
    ax.set_yticklabels([f"{r} · {c}" for r, c in pairs], fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Revenue-Anteil (%)")
    ax.set_title(f"Anteil je Zelle · {year_old} vs {year_new}", fontsize=11, weight="bold")
    ax.legend(frameon=False, fontsize=8)

    fig.suptitle(
        f"Channel × LOS - granular (Top {min(top_n_channels, len(rows))} Channels, realized)",
        fontsize=13,
        weight="bold",
        y=1.02,
    )
    fig.tight_layout()
    return fig


# =============================================================================
# Pace-to-Plan Chart
# =============================================================================
def pace_to_plan_chart(pace_df: pd.DataFrame, year_new: int, period_tag: str):
    """Horizontaler Bar: IST je Standort vs PLAN-Tick"""
    df = pace_df[pace_df["Standort"] != "Gesamt"].copy()
    if df.empty:
        fig, ax = plt.subplots(figsize=(10, 3))
        ax.text(0.5, 0.5, "Keine Pace-Daten", ha="center", va="center")
        ax.set_axis_off()
        return fig
    # Sortierung nach Fortschritt-% (IST/PLAN). Standorte ohne PLAN landen unten.
    df["_pct"] = (df["IST (€)"] / df["PLAN (€)"].replace(0, np.nan) * 100).fillna(-1)
    df = df.sort_values("_pct", ascending=True)

    pal = _pal()
    fig, ax = plt.subplots(figsize=(11, max(3.2, 0.42 * len(df) + 1.4)))
    y = np.arange(len(df))
    ax.barh(
        y, df["IST (€)"], color=pal[0], edgecolor=color("black"), linewidth=0.4, label="IST bisher"
    )
    for i in range(len(df)):
        plan = df["PLAN (€)"].iloc[i]
        ist = df["IST (€)"].iloc[i]
        if plan > 0:
            ax.plot(
                [plan, plan],
                [i - 0.38, i + 0.38],
                color=color("black"),
                linewidth=2.2,
                solid_capstyle="butt",
            )
            pct = ist / plan * 100
            ax.text(
                max(ist, plan) * 1.01,
                i,
                f"{pct:.0f} % vom PLAN",
                va="center",
                fontsize=9,
                weight="bold",
                color=color("green") if pct >= 100 else color("red"),
            )
    ax.set_yticks(y)
    ax.set_yticklabels(df["Standort"])
    ax.set_xlabel("Revenue (€, netto)")
    ax.set_title(f"IST vs PLAN · {period_tag}", fontsize=12, weight="bold")
    handles = [
        Patch(facecolor=pal[0], label="IST bisher"),
        Line2D([0], [0], color=color("black"), linewidth=2.2, label="PLAN"),
    ]
    ax.legend(handles=handles, frameon=False, fontsize=9, loc="lower right")
    fig.tight_layout()
    return fig


# =============================================================================
# Top-Movers
# =============================================================================
def top_movers(raw_stay: pd.DataFrame, year_old: int, year_new: int):
    """Diverging Bars: best/worst YoY-Veränderungen."""
    df = raw_stay[raw_stay["Standort"] != "Total"].copy()
    if df.empty:
        fig, ax = plt.subplots(figsize=(10, 3))
        ax.text(0.5, 0.5, "Keine Daten", ha="center", va="center")
        ax.set_axis_off()
        return fig
    df = df.sort_values("d_ly_eur", ascending=True)
    fig, ax = plt.subplots(figsize=(11, max(3.2, 0.42 * len(df) + 1.2)))
    y = np.arange(len(df))
    colors = [color("green") if v >= 0 else color("red") for v in df["d_ly_eur"]]
    ax.barh(y, df["d_ly_eur"], color=colors, edgecolor=color("black"), linewidth=0.4)
    for i, v in enumerate(df["d_ly_eur"]):
        ax.text(
            v,
            i,
            "  " + H.fmt_eur(v),
            va="center",
            fontsize=9,
            weight="bold",
            color=color("green") if v >= 0 else color("red"),
        )
    ax.axvline(0, color=color("black"), linewidth=0.8)
    ax.set_yticks(y)
    ax.set_yticklabels(df["Standort"])
    ax.set_xlabel(f"Δ Revenue (€)  ·  {year_new} vs {year_old}")
    ax.set_title("Top-Movers · Δ Revenue YoY (nach Aufenthalt)", fontsize=12, weight="bold")
    fig.tight_layout()
    return fig


# =============================================================================
# Stay × Creation - Revenue je Erstellungs-Tag (As-of, YoY)
# =============================================================================
def stay_created_daily_chart(
    line_df: pd.DataFrame,
    year_old: int,
    year_new: int,
    period_label: str = "",
):
    """Liniengrafik: an jedem Erstellungs-Tag erzeugtes Revenue, NEW vs OLD.

    Erwartet ``line_df`` aus ``global_tables.daily_created_line_data`` mit den
    Spalten ``offset``, ``date_new``, ``rev_new``, ``rev_old``. X-Achse =
    Kalendertag des Creation-Fensters (NEW-Datierung, OLD liegt per
    Jahres-Offset deckungsgleich darüber). Nur Buchungen, deren Aufenthalt im
    Stay-Fenster liegt; Storno-/No-Show-Logik steckt bereits im Scope.
    """
    if line_df is None or line_df.empty:
        fig, ax = plt.subplots(figsize=(11, 3.4))
        ax.text(0.5, 0.5, "Keine Buchungen im gewählten Fenster", ha="center", va="center")
        ax.set_axis_off()
        return fig

    x = line_df["offset"].to_numpy()
    rev_new = line_df["rev_new"].to_numpy()
    rev_old = line_df["rev_old"].to_numpy()
    day_labels = [pd.Timestamp(d).strftime("%d.%m.") for d in line_df["date_new"]]

    pal = _pal()
    fig, ax = plt.subplots(figsize=(13, 4.6))
    ax.plot(
        x, rev_old, marker="o", markersize=3.5, linewidth=1.6,
        color="#666666", label=str(year_old),
    )
    ax.plot(
        x, rev_new, marker="o", markersize=3.5, linewidth=2.0,
        color=pal[0], label=str(year_new),
    )
    ax.fill_between(x, rev_new, rev_old, where=(rev_new >= rev_old),
                    color=pal[0], alpha=0.10, interpolate=True)

    # X-Ticks ausdünnen, damit lange Fenster lesbar bleiben.
    n = len(x)
    step = max(1, n // 12)
    tick_pos = list(range(0, n, step))
    ax.set_xticks([x[i] for i in tick_pos])
    ax.set_xticklabels([day_labels[i] for i in tick_pos], rotation=45, ha="right", fontsize=9)
    ax.set_xlabel("Erstellungs-Tag (Buchungsdatum)")
    ax.set_ylabel("Revenue (€, netto)")
    ax.set_title(
        f"Revenue je Erstellungs-Tag (Aufenthalt im Stay-Fenster) · {year_new} vs {year_old}"
        + (f" · {period_label}" if period_label else ""),
        fontsize=12,
        weight="bold",
    )
    # Summen in die Legende (= Total der Tabellen, As-of).
    handles = [
        Line2D([0], [0], color=pal[0], linewidth=2.0, marker="o", markersize=4,
               label=f"{year_new} · Summe {H.fmt_eur(float(rev_new.sum()))}"),
        Line2D([0], [0], color="#666666", linewidth=1.6, marker="o", markersize=4,
               label=f"{year_old} · Summe {H.fmt_eur(float(rev_old.sum()))}"),
    ]
    ax.legend(handles=handles, frameon=False, fontsize=9, loc="upper left")
    fig.tight_layout()
    return fig


def purpose_composition_area_chart(
    area_df: pd.DataFrame,
    year_old: int,
    year_new: int,
    period_label: str = "",
):
    """Gestapelte Flächen: Business vs Privat je Erstellungs-Tag, OLD vs NEW.

    Zwei Panels nebeneinander (links OLD, rechts NEW) mit **gemeinsamer
    Y-Achse**, damit die absoluten Revenue-Niveaus direkt vergleichbar sind.
    In jedem Panel ist das Revenue je Erstellungs-Tag in Business (unten) und
    Privat (oben) gestapelt - die Flächenhöhe zeigt die absolute Entwicklung,
    der Titel je Panel nennt die Summe und den Business/Privat-Anteil (in %).

    Erwartet ``area_df`` aus ``global_tables.purpose_daily_area_data`` mit den
    Spalten ``offset``, ``date_new``, ``biz_new``, ``priv_new``, ``biz_old``,
    ``priv_old``. X-Achse = Kalendertag des Creation-Fensters (NEW-Datierung,
    OLD liegt per Jahres-Offset deckungsgleich darüber).
    """
    if area_df is None or area_df.empty:
        fig, ax = plt.subplots(figsize=(11, 3.4))
        ax.text(0.5, 0.5, "Keine Buchungen im gewählten Fenster", ha="center", va="center")
        ax.set_axis_off()
        return fig

    x = area_df["offset"].to_numpy()
    day_labels = [pd.Timestamp(d).strftime("%d.%m.") for d in area_df["date_new"]]

    c_biz = color("blue")
    c_priv = color("orange")

    fig, axes = plt.subplots(1, 2, figsize=(13, 4.6), sharey=True)
    panels = [
        (axes[0], area_df["biz_old"].to_numpy(), area_df["priv_old"].to_numpy(), year_old),
        (axes[1], area_df["biz_new"].to_numpy(), area_df["priv_new"].to_numpy(), year_new),
    ]
    for ax, biz, priv, yr in panels:
        ax.stackplot(
            x, biz, priv,
            colors=[c_biz, c_priv],
            labels=["Business", "Privat"],
            edgecolor="white", linewidth=0.3, alpha=0.92,
        )
        tot = float(biz.sum() + priv.sum())
        biz_sum, priv_sum = float(biz.sum()), float(priv.sum())
        sh_biz = (biz_sum / tot * 100) if tot > 0 else 0.0
        sh_priv = (priv_sum / tot * 100) if tot > 0 else 0.0
        ax.set_title(
            f"{yr} · Summe {H.fmt_eur(tot)}\n"
            f"Business {sh_biz:.0f}% ({H.fmt_eur(biz_sum)}) · "
            f"Privat {sh_priv:.0f}% ({H.fmt_eur(priv_sum)})",
            fontsize=10.5, weight="bold",
        )
        n = len(x)
        step = max(1, n // 10)
        tick_pos = list(range(0, n, step))
        ax.set_xticks([x[i] for i in tick_pos])
        ax.set_xticklabels(
            [day_labels[i] for i in tick_pos], rotation=45, ha="right", fontsize=8
        )
        ax.set_xlabel("Erstellungs-Tag (Buchungsdatum)")
    axes[0].set_ylabel("Revenue (€, netto)")

    handles = [
        Patch(facecolor=c_biz, label="Business"),
        Patch(facecolor=c_priv, label="Privat (inkl. unbekannter Reisezweck)"),
    ]
    fig.legend(
        handles=handles, loc="upper center", bbox_to_anchor=(0.5, 0.02),
        frameon=False, ncol=2, fontsize=9,
    )
    fig.suptitle(
        f"Composition Business vs Privat je Erstellungs-Tag · {year_new} vs {year_old}"
        + (f" · {period_label}" if period_label else ""),
        fontsize=12, weight="bold", y=1.02,
    )
    fig.tight_layout(rect=[0, 0.04, 1, 0.99])
    return fig


def purpose_booking_count_chart(
    count_df: pd.DataFrame,
    year_old: int,
    year_new: int,
    period_label: str = "",
):
    """Gruppierte Balken: Anzahl Buchungen je Reisezweck, OLD vs NEW.

    Anders als 8.E (Revenue) zählt diese Grafik **Buchungen** (eindeutige
    Reservierungen). X-Achse = Reisezweck (Business / Privat), je Gruppe zwei
    Balken (OLD vs NEW) - damit beide Jahre direkt vergleichbar sind. Über
    jedem Balken: absolute Anzahl + Anteil (%) am jeweiligen Jahr.

    Erwartet ``count_df`` aus ``global_tables.purpose_booking_counts`` mit den
    Spalten ``Reisezweck``, ``n_new``, ``n_old``, ``share_new``, ``share_old``.
    """
    if count_df is None or count_df.empty:
        fig, ax = plt.subplots(figsize=(11, 3.4))
        ax.text(0.5, 0.5, "Keine Buchungen im gewählten Fenster", ha="center", va="center")
        ax.set_axis_off()
        return fig

    purposes = count_df["Reisezweck"].tolist()
    n_old = count_df["n_old"].to_numpy()
    n_new = count_df["n_new"].to_numpy()
    sh_old = count_df["share_old"].to_numpy()
    sh_new = count_df["share_new"].to_numpy()

    x = np.arange(len(purposes))
    w = 0.38
    c_old, c_new = "#666666", _pal()[0]

    fig, ax = plt.subplots(figsize=(9, 4.6))
    bars_old = ax.bar(x - w / 2, n_old, w, color=c_old, label=str(year_old))
    bars_new = ax.bar(x + w / 2, n_new, w, color=c_new, label=str(year_new))

    def _annotate(bars, counts, shares):
        for rect, cnt, sh in zip(bars, counts, shares, strict=False):
            ax.annotate(
                f"{int(cnt):,}".replace(",", ".") + f"\n{sh:.0f}%",
                xy=(rect.get_x() + rect.get_width() / 2, rect.get_height()),
                xytext=(0, 3), textcoords="offset points",
                ha="center", va="bottom", fontsize=9,
            )

    _annotate(bars_old, n_old, sh_old)
    _annotate(bars_new, n_new, sh_new)

    ax.set_xticks(x)
    ax.set_xticklabels(purposes)
    ax.set_ylabel("Anzahl Buchungen")
    ax.set_ylim(0, max(float(n_old.max(initial=0)), float(n_new.max(initial=0))) * 1.18 + 1)
    tot_old, tot_new = int(n_old.sum()), int(n_new.sum())
    handles = [
        Patch(facecolor=c_new, label=f"{year_new} · Summe {tot_new:,}".replace(",", ".")),
        Patch(facecolor=c_old, label=f"{year_old} · Summe {tot_old:,}".replace(",", ".")),
    ]
    ax.legend(handles=handles, frameon=False, fontsize=9, loc="upper left")
    ax.set_title(
        f"Anzahl Buchungen je Reisezweck · {year_new} vs {year_old}"
        + (f" · {period_label}" if period_label else ""),
        fontsize=12, weight="bold",
    )
    fig.tight_layout()
    return fig


# =============================================================================
# Pace-to-Plan helper
# =============================================================================
def build_pace_table(
    raw_stay: pd.DataFrame,
    start_new: pd.Timestamp,
    end_new: pd.Timestamp,
    today: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Sammelt IST vs PLAN + Zeit-Fortschritt je Standort + Gesamt-Zeile.
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

    # Gesamt-Zeile: IST + PLAN summieren, Fortschritt + Status sind periodweit
    # gleich (kommen aus period_pace oben), IST/PLAN-% aus der Total-Summe.
    total_ist = df["IST (€)"].sum()
    total_plan = df["PLAN (€)"].sum()
    total_row = pd.DataFrame(
        [
            {
                "Standort": "Gesamt",
                "IST (€)": total_ist,
                "PLAN (€)": total_plan,
                "IST / PLAN (%)": (total_ist / total_plan * 100) if total_plan > 0 else float("nan"),
                "Fortschritt Zeit (%)": period_progress,
                "Status": period_status,
            }
        ]
    )
    df = pd.concat([df, total_row], ignore_index=True)
    return df
