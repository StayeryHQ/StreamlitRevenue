"""Charts für den Code Deep-Dive

- revenue_timeline       (Monatlich + 3M-Rolling + Kumulativ)
- channel_evolution      (Stacked Area + Fokus-vs-Vorperiode-Vergleich)
- stay_patterns          (6-Panel: LOS · Standort · Wochentag · Zimmerkat · Lead · Gruppe)
- storno_view            (Storno-Timing + monatliche Quote)
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.dates import AutoDateLocator, DateFormatter

from revenueblindspots import helpers as H
from revenueblindspots.theming import categorical_palette as _pal
from revenueblindspots.theming import color


# =============================================================================
# 2 · Revenue-Verlauf
# =============================================================================
def revenue_timeline(
    res_df: pd.DataFrame,
    firm_label: str,
    period_start: pd.Timestamp,
    period_end: pd.Timestamp,
):
    """Bar (Monats-Revenue) + Linie (3M-Rolling) + Twin-Axis (Kumulativ)."""
    pal = _pal()
    d = res_df[res_df["is_realized"]].copy()
    if d.empty:
        fig, ax = plt.subplots(figsize=(11, 3))
        ax.text(
            0.5,
            0.5,
            "Keine realisierten Buchungen - kein Verlauf darstellbar.",
            ha="center",
            va="center",
        )
        ax.set_axis_off()
        return fig, None, None
    d["ym"] = d["arrival"].dt.to_period("M").dt.to_timestamp()
    monthly = d.groupby("ym")["revenue"].sum().sort_index()
    full_idx = pd.date_range(monthly.index.min(), monthly.index.max(), freq="MS")
    monthly = monthly.reindex(full_idx, fill_value=0.0)
    rolling = monthly.rolling(3, min_periods=1).mean()
    cum = monthly.cumsum()

    fig, ax = plt.subplots(figsize=(13, 4.6))
    ax.bar(
        monthly.index,
        monthly.values,
        width=22,
        color=pal[1],
        edgecolor=color("black"),
        linewidth=0.3,
        label="Monats-Revenue",
    )
    ax.plot(
        rolling.index,
        rolling.values,
        color=color("red"),
        linewidth=2.0,
        marker="o",
        markersize=4,
        label="3M-rollender Mittelwert",
    )
    ax.axvspan(
        period_start,
        period_end,
        alpha=0.18,
        color=pal[3],
        label=f"Fokus {period_start:%m/%y}–{period_end:%m/%y}",
    )
    ax2 = ax.twinx()
    ax2.plot(
        cum.index,
        cum.values,
        color=color("green"),
        linewidth=1.4,
        linestyle="--",
        alpha=0.7,
        label="kumulativ",
    )
    ax2.set_ylabel("Kumulativ (€)", color=color("green"))
    ax2.tick_params(axis="y", labelcolor=color("green"))
    ax2.grid(False)
    ax.xaxis.set_major_locator(AutoDateLocator(maxticks=10))
    ax.xaxis.set_major_formatter(DateFormatter("%m/%y"))
    ax.set_ylabel("Revenue / Monat (€, netto)")
    ax.set_title(
        f"{firm_label} - Revenue-Verlauf (realisiert) seit {monthly.index.min():%m/%Y}",
        fontsize=12,
        weight="bold",
    )
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, frameon=False, fontsize=9, loc="upper left")
    fig.tight_layout()
    return fig, monthly, cum


# =============================================================================
# 3 · Channel-Evolution
# =============================================================================
def channel_evolution(
    res_df: pd.DataFrame,
    firm_label: str,
    period_start: pd.Timestamp,
    period_end: pd.Timestamp,
    prev_start: pd.Timestamp,
    prev_end: pd.Timestamp,
):
    """Stacked-area über die Lifetime + (wenn beide Perioden Daten) Vergleichs-Panel."""
    pal = _pal()
    d = res_df[res_df["is_realized"]].copy()
    if d.empty:
        fig, ax = plt.subplots(figsize=(11, 3))
        ax.text(
            0.5,
            0.5,
            "Keine realisierten Buchungen - Channel-Evolution nicht darstellbar.",
            ha="center",
            va="center",
        )
        ax.set_axis_off()
        return fig, None, None
    d["ym"] = d["arrival"].dt.to_period("M").dt.to_timestamp()
    d["ch"] = np.where(
        d["channel_combo"] == "Direct_Offline",
        "Direct_Offline",
        np.where(d["channel_combo"] == "Direct_Website", "Direct_Website", "OTA"),
    )
    monthly_ch = d.groupby(["ym", "ch"])["revenue"].sum().unstack(fill_value=0.0).sort_index()
    full_idx = pd.date_range(monthly_ch.index.min(), monthly_ch.index.max(), freq="MS")
    monthly_ch = monthly_ch.reindex(full_idx, fill_value=0.0)
    order = ["Direct_Offline", "Direct_Website", "OTA"]
    monthly_ch = monthly_ch.reindex(columns=order, fill_value=0.0)

    def shares(s, e):
        sub = d[(d["arrival"] >= s) & (d["arrival"] <= e)]
        if sub.empty:
            return pd.Series([0.0] * 3, index=order), 0
        agg = sub.groupby("ch")["revenue"].sum().reindex(order, fill_value=0.0)
        return agg, len(sub)

    cur, cur_n = shares(period_start, period_end)
    prev, prev_n = shares(prev_start, prev_end)
    has_comparison = (cur_n > 0) and (prev_n > 0)

    if has_comparison:
        fig, axes = plt.subplots(1, 2, figsize=(14, 4.6), gridspec_kw={"width_ratios": [2, 1]})
        ax_left = axes[0]
        ax_right = axes[1]
    else:
        fig, ax_left = plt.subplots(figsize=(13, 4.6))
        ax_right = None

    ax_left.stackplot(
        monthly_ch.index,
        monthly_ch["Direct_Offline"],
        monthly_ch["Direct_Website"],
        monthly_ch["OTA"],
        labels=order,
        colors=[pal[1], pal[2], pal[3]],
        edgecolor=color("white"),
        linewidth=0.4,
        alpha=0.92,
    )
    ax_left.axvspan(
        period_start, period_end, alpha=0.18, color=color("yellow"), label="Fokus-Periode"
    )
    ax_left.xaxis.set_major_locator(AutoDateLocator(maxticks=8))
    ax_left.xaxis.set_major_formatter(DateFormatter("%m/%y"))
    ax_left.set_ylabel("Revenue / Monat (€)")
    ax_left.set_title("Channel-Mix über die Zeit")
    ax_left.legend(frameon=False, fontsize=9, loc="upper left")

    if has_comparison:
        cur_pct = cur / cur.sum() * 100
        prev_pct = prev / prev.sum() * 100
        x = np.arange(len(order))
        w = 0.38
        ax_right.bar(
            x - w / 2,
            prev_pct.values,
            w,
            color=pal[2],
            edgecolor=color("black"),
            linewidth=0.4,
            label="Vorperiode",
        )
        ax_right.bar(
            x + w / 2,
            cur_pct.values,
            w,
            color=pal[0],
            edgecolor=color("black"),
            linewidth=0.4,
            label="Fokus-Periode",
        )
        for i, (vp, vc) in enumerate(zip(prev_pct.values, cur_pct.values)):
            shift = vc - vp
            ax_right.text(
                i,
                max(vp, vc, 1) + 2,
                f"{shift:+.0f}pp",
                ha="center",
                fontsize=8,
                weight="bold",
                color=color("green") if shift >= 0 else color("red"),
            )
        ax_right.set_xticks(x)
        ax_right.set_xticklabels(order, rotation=15)
        ax_right.set_ylabel("Anteil (%)")
        ax_right.set_title("Channel-Anteil · Fokus vs. Vorperiode")
        ax_right.legend(frameon=False, fontsize=9)

    fig.suptitle(f"{firm_label} - Channel-Evolution", fontsize=13, weight="bold", y=1.02)
    fig.tight_layout()
    return fig, (cur if has_comparison else None), (prev if has_comparison else None)


# =============================================================================
# 4 · Stay-Patterns
# =============================================================================
def stay_patterns(res_df: pd.DataFrame, firm_label: str):
    pal = _pal()
    d = res_df[res_df["is_realized"]].copy()
    if d.empty:
        fig, ax = plt.subplots(figsize=(11, 3))
        ax.text(0.5, 0.5, "Keine realisierten Buchungen.", ha="center", va="center")
        ax.set_axis_off()
        return fig
    fig, axes = plt.subplots(2, 3, figsize=(16, 8.5))

    def bar(ax, series, title, xrot=0):
        if series.empty:
            ax.text(0.5, 0.5, "keine Daten", ha="center", va="center", transform=ax.transAxes)
        else:
            ax.bar(
                range(len(series)),
                series.values,
                color=pal[1],
                edgecolor=color("black"),
                linewidth=0.4,
            )
            for i, v in enumerate(series.values):
                if pd.isna(v):
                    label_txt = "–"
                elif float(v) == int(v):
                    label_txt = f"{int(v):,}".replace(",", ".")
                else:
                    label_txt = f"{v:.1f}"
                ax.text(
                    i,
                    v if pd.notna(v) else 0,
                    label_txt,
                    ha="center",
                    va="bottom",
                    fontsize=8,
                    weight="bold",
                )
            ax.set_xticks(range(len(series)))
            ax.set_xticklabels(
                series.index.astype(str),
                rotation=xrot,
                ha="right" if xrot else "center",
                fontsize=8,
            )
        ax.set_title(title, fontsize=10, weight="bold")

    los_order = ["short_<=6", "mid_7-28", "long_29+"]
    bar(
        axes[0, 0],
        d["los_bucket"].value_counts().reindex(los_order, fill_value=0),
        "LOS-Bucket (Anzahl Buchungen)",
    )

    by_loc = d.groupby("property_code")["revenue"].sum().sort_values(ascending=False)
    bar(axes[0, 1], by_loc, "Revenue pro Standort (€)", xrot=30)

    weekday_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    weekday_de = {
        "Monday": "Mo",
        "Tuesday": "Di",
        "Wednesday": "Mi",
        "Thursday": "Do",
        "Friday": "Fr",
        "Saturday": "Sa",
        "Sunday": "So",
    }
    if "arrival_weekday" in d.columns:
        wd = d["arrival_weekday"].value_counts().reindex(weekday_order, fill_value=0)
        wd.index = [weekday_de[w] for w in wd.index]
    else:
        wd = pd.Series([], dtype=float)
    bar(axes[0, 2], wd, "Anreise-Wochentag (Anzahl)")

    rc = (
        d["room_category"].value_counts().head(8)
        if "room_category" in d.columns
        else pd.Series([], dtype=float)
    )
    bar(axes[1, 0], rc, "Zimmerkategorie (Top 8)", xrot=25)

    lt_order = list(H.LEAD_LABELS)
    if "lead_time_bucket" in d.columns:
        lt = d["lead_time_bucket"].value_counts().reindex(lt_order, fill_value=0)
    else:
        lt = pd.Series([], dtype=float)
    bar(axes[1, 1], lt, "Vorlaufzeit-Bucket (Anzahl)", xrot=25)

    gs_order = ["single", "2_rooms", "3-4_rooms", "5+_rooms"]
    if "group_size_bucket" in d.columns:
        gs = d["group_size_bucket"].value_counts().reindex(gs_order, fill_value=0)
    else:
        gs = pd.Series([], dtype=float)
    bar(axes[1, 2], gs, "Gruppen-Größe (Anzahl)")

    fig.suptitle(
        f"{firm_label} - Stay-Pattern (alle realisierten Buchungen)",
        fontsize=13,
        weight="bold",
        y=1.00,
    )
    fig.tight_layout()
    return fig


# =============================================================================
# 5 · Storno-View
# =============================================================================
def storno_view(res_df: pd.DataFrame, firm_label: str, alert_cancel_rate_pct: float = 25.0):
    pal = _pal()
    if res_df.empty:
        fig, ax = plt.subplots(figsize=(11, 3))
        ax.text(0.5, 0.5, "Keine Buchungen.", ha="center", va="center")
        ax.set_axis_off()
        return fig
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.4))

    cancelled = res_df[res_df["is_cancelled"] & res_df["cancel_lead_time_days"].notna()].copy()
    if cancelled.empty:
        axes[0].text(
            0.5,
            0.5,
            "Keine Stornos vorhanden",
            ha="center",
            va="center",
            fontsize=11,
            transform=axes[0].transAxes,
        )
        axes[0].set_axis_off()
    else:
        labels = list(H.CANCEL_TIMING_LABELS)
        timing = pd.cut(
            cancelled["cancel_lead_time_days"], bins=H.CANCEL_TIMING_BINS, labels=labels
        )
        tc = timing.value_counts().reindex(labels, fill_value=0)
        axes[0].bar(
            range(len(labels)), tc.values, color=pal[3], edgecolor=color("black"), linewidth=0.4
        )
        for i, v in enumerate(tc.values):
            if v > 0:
                axes[0].text(i, v, str(int(v)), ha="center", va="bottom", fontsize=8, weight="bold")
        axes[0].set_xticks(range(len(labels)))
        axes[0].set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
        axes[0].set_ylabel("Anzahl Stornierungen")
    axes[0].set_title("Storno-Timing vor Anreise")

    d = res_df.copy()
    d["ym"] = d["arrival"].dt.to_period("M").dt.to_timestamp()
    monthly = d.groupby("ym").agg(n=("id", "count"), c=("is_cancelled", "sum"))
    if monthly.empty:
        axes[1].text(
            0.5,
            0.5,
            "Keine Daten für Monatsverlauf",
            ha="center",
            va="center",
            fontsize=11,
            transform=axes[1].transAxes,
        )
        axes[1].set_axis_off()
        fig.suptitle(f"{firm_label} - Storno-Verhalten", fontsize=13, weight="bold", y=1.02)
        fig.tight_layout()
        return fig
    monthly["rate_pct"] = (monthly["c"] / monthly["n"].replace(0, np.nan)) * 100
    full_idx = pd.date_range(monthly.index.min(), monthly.index.max(), freq="MS")
    monthly = monthly.reindex(full_idx, fill_value=0)
    axes[1].plot(monthly.index, monthly["rate_pct"], marker="o", color=pal[3], linewidth=1.6)
    axes[1].axhline(
        alert_cancel_rate_pct,
        color=color("red"),
        linestyle="--",
        linewidth=1,
        label=f"{alert_cancel_rate_pct:.0f}% Alert",
    )
    axes[1].xaxis.set_major_locator(AutoDateLocator(maxticks=8))
    axes[1].xaxis.set_major_formatter(DateFormatter("%m/%y"))
    axes[1].set_ylabel("Storno-Quote (%)")
    axes[1].set_title("Monatliche Storno-Quote")
    axes[1].legend(frameon=False, fontsize=9)

    fig.suptitle(f"{firm_label} - Storno-Verhalten", fontsize=13, weight="bold", y=1.02)
    fig.tight_layout()
    return fig


# =============================================================================
# Resolve identity match code input against corporate code
# =============================================================================
def resolve_codes_to_res(
    res_all: pd.DataFrame,
    codes: list[str],
) -> tuple[pd.DataFrame, list[str], list[str]]:
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
    sub = res_all[mask].copy()
    firm_names_raw = []
    if "company" in sub.columns:
        firm_names_raw = sorted(sub["company"].dropna().astype(str).str.strip().unique())
    firm_names_fuzzy: list[str] = []
    if "firm_by_effective_fuzzy" in sub.columns:
        firm_names_fuzzy = sorted(
            sub["firm_by_effective_fuzzy"].dropna().astype(str).str.strip().unique()
        )
    return sub, firm_names_fuzzy, firm_names_raw
