"""Chart-Funktionen für die Standort-Analyse"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.dates import AutoDateLocator, DateFormatter

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from revenueblindspots import helpers as H
from revenueblindspots.theming import (
    categorical_palette as palette,
)
from revenueblindspots.theming import (
    color,
)

_DE_MONTH = {
    "01": "Jan",
    "02": "Feb",
    "03": "Mär",
    "04": "Apr",
    "05": "Mai",
    "06": "Jun",
    "07": "Jul",
    "08": "Aug",
    "09": "Sep",
    "10": "Okt",
    "11": "Nov",
    "12": "Dez",
}


# =============================================================================
# Pace by Month
# =============================================================================
def pace_by_month_chart(pace_df: pd.DataFrame, label: str, year_old: int, year_new: int):
    """3 Bars je Monat: ``{year_old}/EoM`` (final) · ``{year_old}/Today`` (was war
    zum Stichtag im Vorjahr on-the-books) · ``{year_new}/Today`` (aktueller Stand).

    Erwartet `pace_df` mit Spalten: ``month`` (1-12), ``ist_eom_old``,
    ``ist_asof_old``, ``ist_asof_new``. Siehe ``H.pace_by_month``.
    """
    if pace_df.empty:
        fig, ax = plt.subplots(figsize=(11, 3.4))
        ax.text(0.5, 0.5, "Keine Daten für Pace-Chart", ha="center", va="center")
        ax.set_axis_off()
        return fig

    months = list(range(1, 13))
    month_labels = [_DE_MONTH[f"{m:02d}"] for m in months]
    pace_df = pace_df.set_index("month").reindex(months, fill_value=0.0)
    vals_eom = pace_df["ist_eom_old"].to_numpy()
    vals_old = pace_df["ist_asof_old"].to_numpy()
    vals_new = pace_df["ist_asof_new"].to_numpy()

    fig, ax = plt.subplots(figsize=(14, 4.6))
    x = np.arange(len(months))
    w = 0.27
    ax.bar(
        x - w,
        vals_eom,
        w,
        color=color("yellow"),
        edgecolor=color("black"),
        linewidth=0.4,
        label=f"{year_old}/EoM",
    )
    ax.bar(
        x,
        vals_old,
        w,
        color="#666666",  # Brand-Neutral Grey
        edgecolor=color("black"),
        linewidth=0.4,
        label=f"{year_old}/Today",
    )
    ax.bar(
        x + w,
        vals_new,
        w,
        color=color("blue"),
        edgecolor=color("black"),
        linewidth=0.4,
        label=f"{year_new}/Today",
    )
    ax.set_xticks(x)
    ax.set_xticklabels(month_labels)
    ax.set_ylabel("Revenue (€, netto)")
    ax.set_title(f"{label} - Pace by Month  ({year_new} vs {year_old})", fontsize=13, weight="bold")
    ax.legend(frameon=False, fontsize=9, loc="upper right", ncol=3)
    fig.tight_layout()
    return fig


# =============================================================================
# 1 · Landscape KPIs - 4-Panel Chart (Occupancy · ADR · Revenue · ALOS)
# =============================================================================
def landscape_kpis_chart(kpi_o, kpi_n, monthly_o, monthly_n, year_old, year_new, label):
    pal = palette()
    fig, axes = plt.subplots(2, 2, figsize=(13, 6.8))
    axes = axes.flatten()
    panels = [
        ("Occupancy", "occupancy_pct", "{:.1f} %"),
        ("ADR", "adr_eur", "{:,.0f} €"),
        ("Revenue", "revenue_eur", "{:,.0f} €"),
        ("ALOS", "alos_nights", "{:.2f} N."),
    ]
    months_n = sorted(monthly_n["stay_year_month"].tolist())
    months_o = sorted(monthly_o["stay_year_month"].tolist())
    de_lab = [_DE_MONTH.get(m.split("-")[1], m) for m in months_n]
    x = np.arange(len(months_n))

    for ax, (title, key, fmt) in zip(axes, panels):
        vo, vn = kpi_o[key], kpi_n[key]
        delta = (vn / vo - 1) * 100 if vo else float("nan")
        dcol = "#666666" if np.isnan(delta) else (color("green") if delta >= 0 else color("red"))
        ax.set_title(title, fontsize=12, weight="bold")
        ax.text(
            0.02,
            1.02,
            fmt.format(vn).replace(",", "."),
            transform=ax.transAxes,
            fontsize=24,
            weight="bold",
            color=color("black"),
        )
        ax.text(
            0.02,
            0.92,
            f"YoY {delta:+.1f} %" if not np.isnan(delta) else "YoY n/a",
            transform=ax.transAxes,
            fontsize=11,
            color=dcol,
            weight="bold",
        )
        ax.text(
            0.02,
            0.84,
            fmt.format(vo).replace(",", ".") + f" ({year_old})",
            transform=ax.transAxes,
            fontsize=10,
            color="#666666",
        )
        s_o = monthly_o.set_index("stay_year_month")[key].reindex(months_o)
        s_n = monthly_n.set_index("stay_year_month")[key].reindex(months_n)
        ax.plot(x, s_o.values, marker="o", color=pal[1], label=str(year_old))
        ax.plot(x, s_n.values, marker="o", color=pal[0], label=str(year_new))
        ax.set_xticks(x)
        ax.set_xticklabels(de_lab, fontsize=9)
        ymax_vals = [
            v
            for v in [
                np.nanmax(s_o.values) if len(s_o) else 0,
                np.nanmax(s_n.values) if len(s_n) else 0,
            ]
            if pd.notna(v)
        ]
        ymax = max(ymax_vals) * 1.15 if ymax_vals else 1
        ax.set_ylim(0, ymax if ymax > 0 else 1)
        ax.legend(loc="lower right", frameon=False, fontsize=8)
    fig.suptitle(
        f"{label} - Landscape {year_old} vs {year_new} (Realized, Stay-Date)",
        fontsize=13,
        weight="bold",
        y=1.0,
    )
    fig.tight_layout()
    return fig


# =============================================================================
# 2 · Heatmap Channel × Aufenthaltsdauer
# =============================================================================
def channel_los_heatmap(nig_a, nig_b, year_old, year_new, label):
    pal = palette()
    rows = ["Direct_Website", "Direct_Offline", "OTA"]
    cols = ["short_<=6", "mid_7-28", "long_29+"]

    def agg(nig):
        d = nig[nig["is_realized"]].copy()
        d["row"] = d["channel_combo"].where(
            d["channel_combo"].isin(["Direct_Website", "Direct_Offline"]), "OTA"
        )
        return (
            d.groupby(["row", "los_bucket"], observed=True)["revenue"]
            .sum()
            .unstack(fill_value=0)
            .reindex(index=rows, columns=cols, fill_value=0)
        )

    a, b = agg(nig_a), agg(nig_b)
    rel = ((b / a.replace(0, np.nan)) - 1) * 100
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "rdg", [color("red"), color("white"), color("green")]
    )
    fig, axes = plt.subplots(1, 2, figsize=(15, 4.6), gridspec_kw={"width_ratios": [1, 1.05]})

    ax = axes[0]
    im = ax.imshow(rel.fillna(0).values, aspect="auto", cmap=cmap, vmin=-100, vmax=100)
    ax.set_xticks(range(len(cols)))
    ax.set_yticks(range(len(rows)))
    ax.set_xticklabels(cols, fontsize=10)
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
                fontsize=8.5,
                weight="bold",
                color="black" if not pd.notna(v) or abs(v) < 60 else "white",
            )
    ax.set_title("YoY-Änderung je Zelle")
    fig.colorbar(im, ax=ax, shrink=0.7, label="% YoY")

    ax = axes[1]
    sa, sb = a.values.sum() or 1, b.values.sum() or 1
    pairs = [(r, c) for r in rows for c in cols]
    sh_a = [a.loc[r, c] / sa * 100 for r, c in pairs]
    sh_b = [b.loc[r, c] / sb * 100 for r, c in pairs]
    y = np.arange(len(pairs))
    w = 0.4
    ax.barh(
        y - w / 2,
        sh_a,
        w,
        color=pal[1],
        edgecolor=color("black"),
        linewidth=0.4,
        label=str(year_old),
    )
    ax.barh(
        y + w / 2,
        sh_b,
        w,
        color=pal[0],
        edgecolor=color("black"),
        linewidth=0.4,
        label=str(year_new),
    )
    for i, (va, vb) in enumerate(zip(sh_a, sh_b)):
        ax.text(max(va, vb), i, f"  {vb:.0f}%", va="center", fontsize=8)
    ax.set_yticks(y)
    ax.set_yticklabels([f"{r} · {c}" for r, c in pairs], fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Revenue-Anteil (%)")
    ax.set_title(f"Anteil je Zelle - {year_old} vs {year_new}")
    ax.legend(frameon=False, fontsize=8)
    fig.suptitle(
        f"{label} - Heatmap Channel × Aufenthaltsdauer", fontsize=13, weight="bold", y=1.02
    )
    fig.tight_layout()
    return fig


# =============================================================================
# 3 · Heatmap Channel × Reisezweck × LOS
# =============================================================================
def channel_purpose_los_heatmap(nig_a, nig_b, year_old, year_new, label):
    pal = palette()
    channels = ["Direct_Website", "Direct_Offline", "OTA"]
    purposes = ["Business", "Leisure"]
    cols = ["short_<=6", "mid_7-28", "long_29+"]
    rows = [(c, p) for c in channels for p in purposes]

    def agg(nig):
        d = nig[nig["is_realized"]].copy()
        d["ch"] = d["channel_combo"].where(
            d["channel_combo"].isin(["Direct_Website", "Direct_Offline"]), "OTA"
        )
        d["purpose"] = np.where(
            d["travelPurpose"].astype(str).str.lower().eq("business"),
            "Business",
            "Leisure",
        )
        return d.groupby(["ch", "purpose", "los_bucket"], observed=True)["revenue"].sum()

    a, b = agg(nig_a), agg(nig_b)
    pct = np.full((len(rows), len(cols)), np.nan)
    delta = np.zeros((len(rows), len(cols)))
    for i, (c, p) in enumerate(rows):
        for j, lb in enumerate(cols):
            va = float(a.get((c, p, lb), 0.0))
            vb = float(b.get((c, p, lb), 0.0))
            delta[i, j] = vb - va
            if va > 0:
                pct[i, j] = (vb / va - 1) * 100
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "rdg", [color("red"), color("white"), color("green")]
    )
    fig, axes = plt.subplots(1, 2, figsize=(15, 5.4), gridspec_kw={"width_ratios": [1, 0.85]})

    ax = axes[0]
    im = ax.imshow(np.nan_to_num(pct), aspect="auto", cmap=cmap, vmin=-100, vmax=100)
    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels(cols, fontsize=10)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([f"{c} · {p}" for c, p in rows], fontsize=9)
    for i in range(len(rows)):
        for j in range(len(cols)):
            v = pct[i, j]
            lbl = (f"{v:+.0f} %" if not np.isnan(v) else "neu") + f"\n({H.fmt_eur(delta[i, j])})"
            ax.text(
                j,
                i,
                lbl,
                ha="center",
                va="center",
                fontsize=8,
                weight="bold",
                color="black" if np.isnan(v) or abs(v) < 60 else "white",
            )
    ax.set_title("YoY-Änderung je Zelle")
    fig.colorbar(im, ax=ax, shrink=0.7, label="% YoY")

    ax = axes[1]
    rev_a = np.array([sum(float(a.get((c, p, lb), 0.0)) for lb in cols) for c, p in rows])
    rev_b = np.array([sum(float(b.get((c, p, lb), 0.0)) for lb in cols) for c, p in rows])
    sh_a = rev_a / (rev_a.sum() or 1) * 100
    sh_b = rev_b / (rev_b.sum() or 1) * 100
    y = np.arange(len(rows))
    w = 0.4
    ax.barh(
        y - w / 2,
        sh_a,
        w,
        color=pal[1],
        edgecolor=color("black"),
        linewidth=0.4,
        label=str(year_old),
    )
    ax.barh(
        y + w / 2,
        sh_b,
        w,
        color=pal[0],
        edgecolor=color("black"),
        linewidth=0.4,
        label=str(year_new),
    )
    for i, (va, vb) in enumerate(zip(sh_a, sh_b)):
        ax.text(max(va, vb), i, f"  {vb:.0f}%", va="center", fontsize=8)
    ax.set_yticks(y)
    ax.set_yticklabels([f"{c} · {p}" for c, p in rows], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Revenue-Anteil (%)")
    ax.set_title("Anteil je Channel × Reisezweck")
    ax.legend(frameon=False, fontsize=8)
    fig.suptitle(
        f"{label} - Heatmap Channel × Reisezweck × LOS", fontsize=13, weight="bold", y=1.02
    )
    fig.tight_layout()
    return fig


# =============================================================================
# 4 · LOS Revenue YoY - Two-Panel
# =============================================================================
def los_yoy(nig_a, nig_b, year_old, year_new, label):
    return H.yoy_two_panel(
        nig_a, nig_b, "los_bucket", f"{label} - Aufenthaltsdauer (LOS)", year_old, year_new
    )


# =============================================================================
# 5 · Channel-Mix - Stacked-Bar (Monatlich) + horizontal YoY-Bars (Top-N)
# =============================================================================
def channel_mix(nig_a, nig_b, full_nightly, year_old, year_new, label, top_n=6):
    pal = palette()
    fig, axes = plt.subplots(1, 2, figsize=(15, 5.0), gridspec_kw={"width_ratios": [1.4, 1.6]})

    # Links: Monatlicher Channel-Anteil (stacked bar, Direct vs OTA)
    share = (
        full_nightly[full_nightly["is_realized"]]
        .groupby(["stay_year_month", "channel_group"])["revenue"]
        .sum()
        .unstack(fill_value=0)
    )
    if not share.empty:
        share = (share.div(share.sum(axis=1), axis=0) * 100).round(1)
        ax = axes[0]
        months = share.index.tolist()
        x = np.arange(len(months))
        bot = np.zeros(len(months))
        for i, c_ in enumerate(["Direct", "OTA"]):
            if c_ in share.columns:
                ax.bar(
                    x,
                    share[c_],
                    bottom=bot,
                    color=pal[i + 1],
                    edgecolor=color("white"),
                    linewidth=0.4,
                    label=c_,
                )
                bot += share[c_].values
        ax.set_xticks(x)
        ax.set_xticklabels(months, rotation=45, ha="right", fontsize=8)
        ax.set_ylim(0, 100)
        ax.set_ylabel("% Revenue (Realized)")
        ax.set_title("Monatlicher Channel-Anteil")
        ax.legend(frameon=False, loc="upper right", fontsize=9)

    # Rechts: horizontaler Top-N YoY-Vergleich pro channel_combo
    a = nig_a[nig_a["is_realized"]].groupby("channel_combo", observed=True)["revenue"].sum()
    b = nig_b[nig_b["is_realized"]].groupby("channel_combo", observed=True)["revenue"].sum()
    union = a.index.union(b.index)
    df = pd.DataFrame({"o": a.reindex(union, fill_value=0), "n": b.reindex(union, fill_value=0)})
    df = df.sort_values("n").tail(top_n)
    ax = axes[1]
    y = np.arange(len(df))
    w = 0.4
    ax.barh(
        y - w / 2,
        df["o"],
        w,
        color=pal[1],
        edgecolor=color("black"),
        linewidth=0.4,
        label=str(year_old),
    )
    ax.barh(
        y + w / 2,
        df["n"],
        w,
        color=pal[0],
        edgecolor=color("black"),
        linewidth=0.4,
        label=str(year_new),
    )
    for i, (vo, vn) in enumerate(zip(df["o"], df["n"])):
        pct = (vn / vo - 1) * 100 if vo > 0 else float("nan")
        txt = (
            f"  Δ {H.fmt_eur(vn - vo)} ({pct:+.0f} %)"
            if pd.notna(pct)
            else f"  +{H.fmt_eur(vn)} (neu)"
        )
        ax.text(max(vo, vn), i, txt, va="center", fontsize=8.5)
    ax.set_yticks(y)
    ax.set_yticklabels(df.index, fontsize=9)
    ax.set_xlabel("Revenue (€, netto)")
    ax.set_title(f"YoY je Channel-Detail (Top-{top_n})")
    ax.legend(frameon=False, fontsize=9)
    fig.suptitle(f"{label} - Channel-Mix", fontsize=13, weight="bold", y=1.0)
    fig.tight_layout()
    return fig


# Backward-compatible alias used by older code
channel_mix_monthly = channel_mix


# =============================================================================
# 6 · ALOS pro Channel - granular über alle channel_combo
# =============================================================================
def alos_per_channel(nig_a, nig_b, year_old, year_new, label):
    pal = palette()

    def alos(nig):
        d = nig[nig["is_realized"]]
        nights = d.groupby("channel_combo", observed=True)["revenue"].size()
        books = d.groupby("channel_combo", observed=True)["id"].nunique()
        return nights / books

    a, b = alos(nig_a), alos(nig_b)
    chans = sorted(set(a.index) | set(b.index))
    a = a.reindex(chans).fillna(0)
    b = b.reindex(chans).fillna(0)
    fig, ax = plt.subplots(figsize=(12, max(4, len(chans) * 0.5 + 1)))
    y = np.arange(len(chans))
    w = 0.4
    ax.barh(
        y - w / 2,
        a.values,
        w,
        color=pal[1],
        edgecolor=color("black"),
        linewidth=0.4,
        label=str(year_old),
    )
    ax.barh(
        y + w / 2,
        b.values,
        w,
        color=pal[0],
        edgecolor=color("black"),
        linewidth=0.4,
        label=str(year_new),
    )
    for i, (va, vb) in enumerate(zip(a.values, b.values)):
        ax.text(va, i - w / 2, f" {va:.1f}", va="center", fontsize=8)
        ax.text(vb, i + w / 2, f" {vb:.1f}", va="center", fontsize=8)
    ax.set_yticks(y)
    ax.set_yticklabels(chans, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("ALOS (Ø Nächte je Buchung)")
    ax.set_title(f"{label} - ALOS pro Channel (granular, Realized)", fontsize=13, weight="bold")
    ax.legend(frameon=False, fontsize=9)
    fig.tight_layout()
    return fig


# =============================================================================
# 7 / 8 · Wochentag-Pattern - zwei Stacked-Bar-Charts nebeneinander
# =============================================================================
def weekday_pattern(nig_a, nig_b, weekday_col, year_old, year_new, label, title):
    pal = palette()
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    de = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    chans = ["Direct", "OTA"]

    def pivot(nig):
        return (
            nig[nig["is_realized"]]
            .groupby([weekday_col, "channel_group"], observed=True)["revenue"]
            .sum()
            .unstack(fill_value=0)
            .reindex(order)
            .fillna(0)
        )

    fig, axes = plt.subplots(1, 2, figsize=(15, 5.0), sharey=True)
    for ax, nig, lbl in [(axes[0], nig_a, year_old), (axes[1], nig_b, year_new)]:
        piv = pivot(nig)
        x = np.arange(7)
        bot = np.zeros(7)
        for i, c_ in enumerate(chans):
            if c_ in piv.columns:
                ax.bar(
                    x,
                    piv[c_],
                    bottom=bot,
                    color=pal[i + 1],
                    edgecolor="white",
                    linewidth=0.5,
                    label=c_ if ax is axes[0] else "",
                )
                bot += piv[c_].values
        for i, t in enumerate(bot):
            if t > 0:
                ax.text(i, t * 1.01, H.fmt_eur(t), ha="center", fontsize=8, weight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels(de)
        ax.set_title(f"{lbl}", fontsize=12)
    axes[0].set_ylabel("Revenue (€, netto)")
    fig.legend(loc="upper center", bbox_to_anchor=(0.5, 0.95), ncol=2, frameon=False)
    fig.suptitle(f"{label} - {title}", fontsize=14, weight="bold", y=1.02)
    fig.tight_layout()
    return fig


# =============================================================================
# 9 · Gruppen-Größe
# =============================================================================
def group_size_yoy(res_a, res_b, year_old, year_new, label):
    return H.yoy_two_panel(
        res_a,
        res_b,
        "group_size_bucket",
        f"{label} - Gruppen-Größe (Zimmer je Buchung)",
        year_old,
        year_new,
    )


# =============================================================================
# 10 · Inland vs. Ausland - 3-Panel: Revenue abs · Anteil · Room-Nights (ADR)
# =============================================================================
def de_vs_international(nig_a, nig_b, year_old, year_new, label):
    pal = palette()
    cats = ["DE", "International"]
    x = np.arange(2)
    w = 0.35
    fig, axes = plt.subplots(1, 3, figsize=(17, 4.4))

    def rev(nig):
        g = nig[nig["is_realized"]].groupby("is_international")["revenue"].sum()
        return [float(g.get(False, 0)), float(g.get(True, 0))]

    def nights(nig):
        g = nig[nig["is_realized"]].groupby("is_international")["revenue"].size()
        return [int(g.get(False, 0)), int(g.get(True, 0))]

    ra, rb = rev(nig_a), rev(nig_b)
    na, nb = nights(nig_a), nights(nig_b)

    ax = axes[0]
    ax.bar(
        x - w / 2, ra, w, color=pal[1], edgecolor=color("black"), linewidth=0.4, label=str(year_old)
    )
    ax.bar(
        x + w / 2, rb, w, color=pal[0], edgecolor=color("black"), linewidth=0.4, label=str(year_new)
    )
    for i, (va, vb) in enumerate(zip(ra, rb)):
        ax.text(i - w / 2, va, H.fmt_eur(va), ha="center", va="bottom", fontsize=8)
        ax.text(i + w / 2, vb, H.fmt_eur(vb), ha="center", va="bottom", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(cats)
    ax.set_ylabel("Revenue (€, netto)")
    ax.set_ylim(0, max(max(ra), max(rb), 1) * 1.2)
    ax.set_title("Revenue absolut")
    ax.legend(frameon=False, fontsize=9)

    ax = axes[1]
    sa, sb = sum(ra) or 1, sum(rb) or 1
    sh_a = [v / sa * 100 for v in ra]
    sh_b = [v / sb * 100 for v in rb]
    ax.bar(
        x - w / 2,
        sh_a,
        w,
        color=pal[1],
        edgecolor=color("black"),
        linewidth=0.4,
        label=str(year_old),
    )
    ax.bar(
        x + w / 2,
        sh_b,
        w,
        color=pal[0],
        edgecolor=color("black"),
        linewidth=0.4,
        label=str(year_new),
    )
    for i, (va, vb) in enumerate(zip(sh_a, sh_b)):
        ax.text(i - w / 2, va, f"{va:.1f} %", ha="center", va="bottom", fontsize=8)
        ax.text(i + w / 2, vb, f"{vb:.1f} %", ha="center", va="bottom", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(cats)
    ax.set_ylabel("Anteil (%)")
    ax.set_ylim(0, max(max(sh_a), max(sh_b)) * 1.25 if sh_a or sh_b else 1)
    ax.set_title("Revenue-Anteil")
    ax.legend(frameon=False, fontsize=9)

    ax = axes[2]
    ax.bar(
        x - w / 2, na, w, color=pal[1], edgecolor=color("black"), linewidth=0.4, label=str(year_old)
    )
    ax.bar(
        x + w / 2, nb, w, color=pal[0], edgecolor=color("black"), linewidth=0.4, label=str(year_new)
    )
    for i in range(2):
        adr_o = ra[i] / na[i] if na[i] else 0
        adr_n = rb[i] / nb[i] if nb[i] else 0
        ax.text(
            i - w / 2,
            na[i],
            f"{na[i]:,}".replace(",", ".") + f"\nADR {adr_o:.0f} €",
            ha="center",
            va="bottom",
            fontsize=8,
        )
        ax.text(
            i + w / 2,
            nb[i],
            f"{nb[i]:,}".replace(",", ".") + f"\nADR {adr_n:.0f} €",
            ha="center",
            va="bottom",
            fontsize=8,
        )
    ax.set_xticks(x)
    ax.set_xticklabels(cats)
    ax.set_ylabel("Room-Nights (Realized)")
    ax.set_ylim(0, max(max(na), max(nb), 1) * 1.28)
    ax.set_title("Room-Nights (ADR annotiert)")
    ax.legend(frameon=False, fontsize=9)
    fig.suptitle(f"{label} - Inland vs. Ausland", fontsize=13, weight="bold", y=1.02)
    fig.tight_layout()
    return fig


# =============================================================================
# 12 · Top-Herkunftsländer - zwei Panels (OLD / NEW)
# =============================================================================
def top_countries(nig_a, nig_b, year_old, year_new, label, top_n=10):
    fig, axes = plt.subplots(1, 2, figsize=(15, max(3.5, top_n * 0.35 + 1)))
    for ax, nig, yr in [(axes[0], nig_a, year_old), (axes[1], nig_b, year_new)]:
        counts = (
            nig[nig["is_realized"]]
            .groupby("origin", observed=True)["revenue"]
            .sum()
            .sort_values(ascending=False)
            .head(top_n)
        )
        if counts.empty:
            ax.text(0.5, 0.5, "Keine Daten", ha="center", va="center")
            ax.set_axis_off()
            continue
        ax.barh(
            counts.index.astype(str),
            counts.values,
            color=[color("yellow") if c == "DE" else color("blue") for c in counts.index],
            edgecolor=color("black"),
            linewidth=0.4,
        )
        for i, v in enumerate(counts.values):
            ax.text(v, i, "  " + H.fmt_eur(v), va="center", fontsize=8)
        ax.invert_yaxis()
        ax.set_xlabel("Revenue (€, netto)")
        ax.set_title(str(yr))
    fig.suptitle(f"{label} - Top-{top_n} Herkunftsländer", fontsize=13, weight="bold", y=1.02)
    fig.tight_layout()
    return fig


# =============================================================================
# 13 · Vorlaufzeit & Storno-Risiko
# =============================================================================
def leadtime_storno(res_a, res_b, year_old, year_new, label):
    pal = palette()
    order = list(H.LEAD_LABELS)
    x = np.arange(len(order))
    fig, axes = plt.subplots(1, 2, figsize=(16, 5.0))

    def rev_n(df):
        d = df[df["is_realized"]]
        rev = d.groupby("lead_time_bucket", observed=True)["revenue"].sum().reindex(order).fillna(0)
        n = d.groupby("lead_time_bucket", observed=True)["id"].nunique().reindex(order).fillna(0)
        return rev, n

    ro, no = rev_n(res_a)
    rn, nn = rev_n(res_b)
    ax = axes[0]
    w = 0.38
    ax.bar(
        x - w / 2, ro, w, color=pal[1], edgecolor=color("black"), linewidth=0.4, label=str(year_old)
    )
    ax.bar(
        x + w / 2, rn, w, color=pal[0], edgecolor=color("black"), linewidth=0.4, label=str(year_new)
    )
    ymax = max(ro.max(), rn.max(), 1)
    for i in range(len(order)):
        if no.iloc[i] > 0:
            ax.text(
                x[i] - w / 2,
                ro.iloc[i] + ymax * 0.02,
                f"n={int(no.iloc[i])}",
                ha="center",
                fontsize=7.5,
                color=pal[1],
                weight="bold",
            )
        if nn.iloc[i] > 0:
            ax.text(
                x[i] + w / 2,
                rn.iloc[i] + ymax * 0.02,
                f"n={int(nn.iloc[i])}",
                ha="center",
                fontsize=7.5,
                color=pal[0],
                weight="bold",
            )
    ax.set_xticks(x)
    ax.set_xticklabels(order, rotation=35, ha="right", fontsize=8)
    ax.set_ylabel("Revenue (€, netto)")
    ax.set_title("Vorlaufzeit-Revenue YoY - nur Realized", weight="bold")
    ax.set_ylim(0, ymax * 1.18)
    ax.legend(frameon=False, fontsize=9)

    ax = axes[1]
    g = res_b.groupby("lead_time_bucket", observed=True)
    real = g["is_realized"].sum().reindex(order).fillna(0).values
    canc = g["is_cancelled"].sum().reindex(order).fillna(0).values
    ax.bar(x, real, color=pal[2], edgecolor=color("black"), linewidth=0.4, label="Realized")
    ax.bar(
        x,
        canc,
        bottom=real,
        color=pal[3],
        edgecolor=color("black"),
        linewidth=0.4,
        label="Storniert",
    )
    for i in range(len(order)):
        tot = real[i] + canc[i]
        if tot > 0:
            ax.text(
                i,
                tot,
                f"{canc[i] / tot * 100:.0f}% Storno",
                ha="center",
                va="bottom",
                fontsize=8,
                weight="bold",
            )
    ax.set_xticks(x)
    ax.set_xticklabels(order, rotation=35, ha="right", fontsize=8)
    ax.set_ylabel(f"Buchungen {year_new}")
    ax.set_title(f"Realized vs. Storniert je Vorlaufzeit ({year_new})", weight="bold")
    ax.legend(frameon=False, fontsize=9)
    fig.suptitle(f"{label} - Vorlaufzeit & Storno-Risiko", fontsize=14, weight="bold", y=1.02)
    fig.tight_layout()
    return fig


# =============================================================================
# 14 · Daily Occupancy nach LOS
# =============================================================================
def daily_occupancy_los(full_nightly, units, start_ts, end_ts, label):
    pal = palette()
    nig = full_nightly[full_nightly["is_realized"]].dropna(subset=["stay_date", "los_bucket"])
    nig = nig[(nig["stay_date"] >= start_ts) & (nig["stay_date"] <= end_ts)]
    calendar = pd.date_range(start_ts, end_ts, freq="D")
    los_order = ["long_29+", "mid_7-28", "short_<=6"]
    los_colors = {"long_29+": pal[1], "mid_7-28": pal[2], "short_<=6": pal[0]}
    counts = (
        nig.groupby(["stay_date", "los_bucket"], observed=True)
        .size()
        .unstack(fill_value=0)
        .reindex(index=calendar, columns=los_order, fill_value=0)
    )
    occ = counts / units * 100
    n_days = len(calendar)
    style = "bars" if n_days <= 45 else "area"
    fig, ax = plt.subplots(figsize=(max(11, min(20, n_days * 0.25 + 6)), 5.2))
    if style == "bars":
        bottom = np.zeros(n_days)
        for lb in los_order:
            ax.bar(
                calendar,
                occ[lb].values,
                bottom=bottom,
                width=0.85,
                color=los_colors[lb],
                edgecolor=color("white"),
                linewidth=0.4,
                label=lb,
            )
            bottom += occ[lb].values
    else:
        ax.stackplot(
            calendar,
            [occ[lb].values for lb in los_order],
            labels=los_order,
            colors=[los_colors[lb] for lb in los_order],
            alpha=0.92,
        )
    ax.axhline(100, color=color("red"), linewidth=0.6, linestyle=":", alpha=0.6)
    ax.set_ylim(0, max(110, occ.sum(axis=1).max() * 1.12))
    ax.set_ylabel("Occupancy (%) - gestapelt nach LOS")
    ax.set_xlabel("Stay-Datum")
    ax.set_title(
        f"{label} - Daily Occupancy × LOS  {start_ts:%d.%m.%Y} – {end_ts:%d.%m.%Y} (Realized)",
        fontsize=12,
        weight="bold",
    )
    ax.legend(
        frameon=False,
        fontsize=9,
        ncol=3,
        title="LOS-Bucket",
        loc="upper center",
        bbox_to_anchor=(0.5, -0.18),
    )
    ax.xaxis.set_major_locator(AutoDateLocator(maxticks=min(20, max(7, n_days // 3))))
    ax.xaxis.set_major_formatter(DateFormatter("%d.%m."))
    plt.setp(
        ax.get_xticklabels(),
        rotation=0 if n_days <= 14 else 30,
        ha="center" if n_days <= 14 else "right",
    )
    fig.tight_layout(rect=[0, 0.08, 1, 0.94])
    return fig


# =============================================================================
# 20 · Firmenkunden - Überblick + Channel-Split
# =============================================================================
def corporate_overview(res_a, res_b, year_old, year_new, label):
    pal = palette()
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.6))

    def split(df):
        d = df[df["is_realized"]]
        return (
            float(d[d["has_company"]]["revenue"].sum()),
            float(d[~d["has_company"]]["revenue"].sum()),
        )

    ca, pa = split(res_a)
    cb, pb = split(res_b)
    w = 0.35
    ax = axes[0]
    x = np.arange(2)
    ax.bar(
        x - w / 2,
        [ca, pa],
        w,
        color=pal[1],
        edgecolor=color("black"),
        linewidth=0.4,
        label=str(year_old),
    )
    ax.bar(
        x + w / 2,
        [cb, pb],
        w,
        color=pal[0],
        edgecolor=color("black"),
        linewidth=0.4,
        label=str(year_new),
    )
    for i, (vo, vn) in enumerate([(ca, cb), (pa, pb)]):
        ax.text(i - w / 2, vo, H.fmt_eur(vo), ha="center", va="bottom", fontsize=9)
        ax.text(i + w / 2, vn, H.fmt_eur(vn), ha="center", va="bottom", fontsize=9)
        d = (vn / vo - 1) * 100 if vo else float("nan")
        if not np.isnan(d):
            ax.text(
                i,
                max(vo, vn) * 1.13,
                f"YoY {d:+.0f} %",
                ha="center",
                fontsize=10,
                weight="bold",
                color=color("green") if d >= 0 else color("red"),
            )
    ax.set_xticks(x)
    ax.set_xticklabels(["Firmenkunden", "Privat"])
    ax.set_ylabel("Revenue (€, netto)")
    ax.set_ylim(0, max(ca, cb, pa, pb, 1) * 1.3)
    ax.set_title("Firmenkunden vs. Privat")
    ax.legend(frameon=False, fontsize=9)

    def by_channel(df):
        d = df[df["is_realized"] & df["has_company"]].copy()
        d["ch"] = d["channel_combo"].where(
            d["channel_combo"].isin(["Direct_Website", "Direct_Offline"]), "OTA"
        )
        return d.groupby("ch")["revenue"].sum()

    order = ["Direct_Website", "Direct_Offline", "OTA"]
    a = by_channel(res_a).reindex(order, fill_value=0)
    b = by_channel(res_b).reindex(order, fill_value=0)
    ax = axes[1]
    x = np.arange(len(order))
    ax.bar(
        x - w / 2,
        a.values,
        w,
        color=pal[1],
        edgecolor=color("black"),
        linewidth=0.4,
        label=str(year_old),
    )
    ax.bar(
        x + w / 2,
        b.values,
        w,
        color=pal[0],
        edgecolor=color("black"),
        linewidth=0.4,
        label=str(year_new),
    )
    for i, (vo, vn) in enumerate(zip(a.values, b.values)):
        d = (vn / vo - 1) * 100 if vo else float("nan")
        txt = f"{d:+.0f} %" if not np.isnan(d) else "neu"
        ax.text(
            i,
            max(vo, vn, 1) * 1.04,
            txt,
            ha="center",
            fontsize=9,
            weight="bold",
            color=color("green") if (np.isnan(d) or d >= 0) else color("red"),
        )
    ax.set_xticks(x)
    ax.set_xticklabels(order, fontsize=9)
    ax.set_ylabel("Firmen-Revenue (€, netto)")
    ax.set_ylim(0, max(a.max(), b.max(), 1) * 1.2)
    ax.set_title("Firmenkunden-Revenue nach Channel")
    ax.legend(frameon=False, fontsize=9)
    fig.suptitle(f"{label} - Firmenkunden-Überblick (Realized)", fontsize=13, weight="bold", y=1.02)
    fig.tight_layout()
    return fig


# =============================================================================
# Code-Lookup + Table Builders für Firmenkunden- / Direct-Offline-Tabellen
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
            valid_cc = ~cc.str.lower().isin({"", "nan", "none", "<na>", "null"})
            valid_cp = ~cp.str.lower().isin({"", "nan", "none", "<na>", "null"})
            code_col = cc.where(valid_cc, cp.where(valid_cp))
        sub_df = d.assign(_code=code_col)
        sub = sub_df[
            sub_df["has_company"]
            & sub_df["_code"].notna()
            & sub_df["_code"].astype(str).str.strip().ne("")
        ]
        if not sub.empty:
            parts.append(sub[["company", "_code"]].rename(columns={"_code": "company_code"}))
    if not parts:
        return {}
    cat = pd.concat(parts, ignore_index=True)
    cat["company_code"] = cat["company_code"].astype(str).str.strip()
    out: dict[str, str] = {}
    for firm, g in cat.groupby("company"):
        codes = g["company_code"].value_counts()
        top = list(codes.index[:2])
        out[firm] = " / ".join(top)
    return out


def top_companies_table(res_a, res_b, year_old, year_new) -> pd.DataFrame:
    def by_firm(df):
        d = df[df["is_realized"] & df["has_company"]]
        return d.groupby("company").agg(
            revenue=("revenue", "sum"),
            n_bookings=("id", "nunique"),
            nights=("nights", "sum"),
        )

    a = by_firm(res_a)
    b = by_firm(res_b)
    code_map = _company_code_lookup(res_a, res_b)
    firms = a.index.union(b.index)
    t = pd.DataFrame(
        {
            "Firma": list(firms),
            "Code": [code_map.get(f, "") for f in firms],
            f"Revenue {year_old} (€)": a["revenue"].reindex(firms, fill_value=0.0).values,
            f"Revenue {year_new} (€)": b["revenue"].reindex(firms, fill_value=0.0).values,
            f"Buchungen {year_old}": a["n_bookings"]
            .reindex(firms, fill_value=0)
            .astype(int)
            .values,
            f"Buchungen {year_new}": b["n_bookings"]
            .reindex(firms, fill_value=0)
            .astype(int)
            .values,
            f"Nächte {year_old}": a["nights"].reindex(firms, fill_value=0).astype(int).values,
            f"Nächte {year_new}": b["nights"].reindex(firms, fill_value=0).astype(int).values,
        }
    )
    t["Δ Revenue (€)"] = t[f"Revenue {year_new} (€)"] - t[f"Revenue {year_old} (€)"]
    return t.sort_values(f"Revenue {year_new} (€)", ascending=False).reset_index(drop=True)


# =============================================================================
# Direct-Offline Waterfall + Detail-Segmente
# =============================================================================
def _per_channel_revenue(res_df):
    d = res_df[res_df["is_realized"] & res_df["has_company"]].copy()
    if d.empty:
        return pd.DataFrame(columns=["company", "ch", "revenue"]).set_index(["company", "ch"])[
            "revenue"
        ]
    d["ch"] = np.where(
        d["channel_combo"] == "Direct_Offline",
        "Direct_Offline",
        np.where(d["channel_combo"] == "Direct_Website", "Direct_Website", "OTA"),
    )
    return d.groupby(["company", "ch"])["revenue"].sum()


def build_channel_table(companies, res_a, res_b) -> pd.DataFrame:
    rev_a = _per_channel_revenue(res_a).unstack(fill_value=0.0)
    rev_b = _per_channel_revenue(res_b).unstack(fill_value=0.0)
    for col in ("Direct_Offline", "Direct_Website", "OTA"):
        for src in (rev_a, rev_b):
            if col not in src.columns:
                src[col] = 0.0
    rev_a = rev_a.reindex(companies, fill_value=0.0)
    rev_b = rev_b.reindex(companies, fill_value=0.0)
    code_map = _company_code_lookup(res_a, res_b)
    firms_list = list(companies)
    out = pd.DataFrame(
        {
            "Firma": firms_list,
            "Code": [code_map.get(c, "") for c in firms_list],
            "Direct_Offline old (€)": rev_a["Direct_Offline"].to_numpy(),
            "Direct_Offline new (€)": rev_b["Direct_Offline"].to_numpy(),
            "Direct_Website old (€)": rev_a["Direct_Website"].to_numpy(),
            "Direct_Website new (€)": rev_b["Direct_Website"].to_numpy(),
            "OTA old (€)": rev_a["OTA"].to_numpy(),
            "OTA new (€)": rev_b["OTA"].to_numpy(),
        }
    )
    out["Total old (€)"] = out[
        ["Direct_Offline old (€)", "Direct_Website old (€)", "OTA old (€)"]
    ].sum(axis=1)
    out["Total new (€)"] = out[
        ["Direct_Offline new (€)", "Direct_Website new (€)", "OTA new (€)"]
    ].sum(axis=1)
    out["Δ Direct_Offline (€)"] = out["Direct_Offline new (€)"] - out["Direct_Offline old (€)"]
    out["Δ Total (€)"] = out["Total new (€)"] - out["Total old (€)"]
    drop_do = (-out["Δ Direct_Offline (€)"]).clip(lower=0)
    other_growth = (
        (out["Direct_Website new (€)"] - out["Direct_Website old (€)"])
        + (out["OTA new (€)"] - out["OTA old (€)"])
    ).clip(lower=0)
    out["Channel-Move?"] = np.where(
        (drop_do > 0) & (other_growth >= 0.5 * drop_do),
        "✓ wahrscheinlich",
        "-",
    )
    return out


def directoffline_waterfall(res_a, res_b, year_old, year_new, label):
    pal = palette()

    def by_company(df):
        d = df[(df["channel_combo"] == "Direct_Offline") & df["has_company"] & df["is_realized"]]
        return d.groupby("company")["revenue"].sum()

    comp = pd.DataFrame({"old": by_company(res_a), "new": by_company(res_b)}).fillna(0.0)
    if comp.empty:
        fig, ax = plt.subplots(figsize=(10, 3))
        ax.text(
            0.5, 0.5, "Keine Direct-Offline-Firmenbuchungen im Zeitraum", ha="center", va="center"
        )
        ax.set_axis_off()
        return fig, None
    comp["delta"] = comp["new"] - comp["old"]
    lost = comp[(comp["old"] > 0) & (comp["new"] == 0)]
    gained = comp[(comp["old"] == 0) & (comp["new"] > 0)]
    shrunk = comp[(comp["old"] > 0) & (comp["new"] > 0) & (comp["delta"] < 0)]
    grown = comp[(comp["old"] > 0) & (comp["new"] > 0) & (comp["delta"] > 0)]
    steps = [
        (f"Firmen\n{year_old}", comp["old"].sum(), "base"),
        ("verloren", -lost["old"].sum(), "neg"),
        ("geschrumpft", shrunk["delta"].sum(), "neg"),
        ("gewachsen", grown["delta"].sum(), "pos"),
        ("neu", gained["new"].sum(), "pos"),
        (f"Firmen\n{year_new}", comp["new"].sum(), "base"),
    ]
    fig, ax = plt.subplots(figsize=(11, 4.8))
    running = 0.0
    base = max(comp["old"].sum(), comp["new"].sum(), 1)
    for i, (lbl, val, kind) in enumerate(steps):
        if kind == "base":
            ax.bar(i, val, color=pal[1], edgecolor=color("black"), linewidth=0.4)
            running, top = val, val
        else:
            c = color("green") if val >= 0 else color("red")
            bottom = running if val >= 0 else running + val
            ax.bar(i, abs(val), bottom=bottom, color=c, edgecolor=color("black"), linewidth=0.4)
            running += val
            top = running
        ax.text(i, top + base * 0.02, H.fmt_eur(val), ha="center", fontsize=8, weight="bold")
    ax.set_xticks(range(len(steps)))
    ax.set_xticklabels([s[0] for s in steps], fontsize=9)
    ax.set_ylabel("Revenue (€, netto)")
    ax.set_title(
        f"{label} - Direct Offline Firmen-Revenue: woher kommt die Veränderung?",
        fontsize=12,
        weight="bold",
    )
    fig.tight_layout()
    return fig, {"lost": lost, "gained": gained, "shrunk": shrunk, "grown": grown, "all": comp}


def directoffline_segments(res_a, res_b, year_old, year_new, label):
    pal = palette()
    do_a = res_a[(res_a["channel_combo"] == "Direct_Offline") & res_a["is_realized"]]
    do_b = res_b[(res_b["channel_combo"] == "Direct_Offline") & res_b["is_realized"]]
    w = 0.35
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.4))

    ax = axes[0]
    order = ["short_<=6", "mid_7-28", "long_29+"]
    a = do_a.groupby("los_bucket", observed=True)["revenue"].sum().reindex(order, fill_value=0)
    b = do_b.groupby("los_bucket", observed=True)["revenue"].sum().reindex(order, fill_value=0)
    x = np.arange(len(order))
    ax.bar(
        x - w / 2,
        a.values,
        w,
        color=pal[1],
        edgecolor=color("black"),
        linewidth=0.4,
        label=str(year_old),
    )
    ax.bar(
        x + w / 2,
        b.values,
        w,
        color=pal[0],
        edgecolor=color("black"),
        linewidth=0.4,
        label=str(year_new),
    )
    for i, (vo, vn) in enumerate(zip(a.values, b.values)):
        ax.text(
            i,
            max(vo, vn, 1) * 1.03,
            "Δ " + H.fmt_eur(vn - vo),
            ha="center",
            fontsize=8.5,
            weight="bold",
        )
    ax.set_xticks(x)
    ax.set_xticklabels(order)
    ax.set_ylabel("Revenue (€, netto)")
    ax.set_title("Direct Offline nach Aufenthaltsdauer")
    ax.legend(frameon=False, fontsize=9)

    ax = axes[1]

    def purpose_rev(df):
        p = np.where(
            df["travelPurpose"].astype(str).str.lower().eq("business"), "Business", "Leisure"
        )
        return df.assign(_p=p).groupby("_p")["revenue"].sum()

    pa = purpose_rev(do_a).reindex(["Business", "Leisure"], fill_value=0)
    pb = purpose_rev(do_b).reindex(["Business", "Leisure"], fill_value=0)
    x = np.arange(2)
    ax.bar(
        x - w / 2,
        pa.values,
        w,
        color=pal[1],
        edgecolor=color("black"),
        linewidth=0.4,
        label=str(year_old),
    )
    ax.bar(
        x + w / 2,
        pb.values,
        w,
        color=pal[0],
        edgecolor=color("black"),
        linewidth=0.4,
        label=str(year_new),
    )
    for i, (vo, vn) in enumerate(zip(pa.values, pb.values)):
        ax.text(
            i,
            max(vo, vn, 1) * 1.03,
            "Δ " + H.fmt_eur(vn - vo),
            ha="center",
            fontsize=8.5,
            weight="bold",
        )
    ax.set_xticks(x)
    ax.set_xticklabels(["Business", "Leisure"])
    ax.set_ylabel("Revenue (€, netto)")
    ax.set_title("Direct Offline nach Reisezweck")
    ax.legend(frameon=False, fontsize=9)
    fig.suptitle(
        f"{label} - Direct Offline Detail-Segmente (Realized)", fontsize=13, weight="bold", y=1.02
    )
    fig.tight_layout()
    return fig


# =============================================================================
# 22 · Top Vertragscodes (effective_code)
# =============================================================================
def top_codes_in_period(res_period) -> pd.DataFrame:
    if "effective_code" not in res_period.columns:
        return pd.DataFrame()
    d = res_period[res_period["is_realized"] & res_period["effective_code"].notna()].copy()
    d["effective_code"] = d["effective_code"].astype(str).str.strip()
    d = d[d["effective_code"] != ""]
    if d.empty:
        return pd.DataFrame()

    g = d.groupby("effective_code")
    out = pd.DataFrame(
        {
            "Code": g.size().index,
            "Firma": g["company"]
            .agg(
                lambda s: s.dropna().astype(str).value_counts().index[0] if s.dropna().size else ""
            )
            .values,
            "Buchungen": g["id"].nunique().values,
            "Nächte": g["nights"].sum().astype(int).values,
            "Personen": g["adults"].sum().astype("Int64").values,
            "Revenue (€)": g["revenue"].sum().round(2).values,
        }
    )
    out["ADR (€)"] = (out["Revenue (€)"] / out["Nächte"].replace(0, np.nan)).round(2)
    return out.sort_values("Revenue (€)", ascending=False).reset_index(drop=True)
