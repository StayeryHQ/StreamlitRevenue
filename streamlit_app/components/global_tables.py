"""Tabellen für den Global Report.

Vier Recap-Tabellen nach Aufenthalt (realized, mit PLAN) und nach
Erstellung (Sales-Sicht, inkl. Storno/No-Show). Alle laufen auf der
Timeslices-/Nightly-Basis (Netto-Revenue pro Nacht, ``baseAmount_netAmount``).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from revenueblindspots import helpers as H

# ============================== Tendency thresholds ========================
GREEN_PCT = 2.0  # ≥ green → 🟢
RED_PCT = -10.0  # ≤ red → 🔴  (between → 🟠)


def tendency_icon(diff_pct: float) -> str:
    """🟢🟠🔴 based on % deviation."""
    if pd.isna(diff_pct):
        return "-"
    if diff_pct >= GREEN_PCT:
        return "🟢"
    if diff_pct <= RED_PCT:
        return "🔴"
    return "🟠"


def tendency_icon_abs(diff_eur: float) -> str:
    """🟢🟠🔴 just by sign + magnitude (for non-relative comparisons)."""
    if pd.isna(diff_eur) or diff_eur == 0:
        return "-"
    return "🟢" if diff_eur > 0 else "🔴"


def with_code_labels(raw: pd.DataFrame) -> pd.DataFrame:
    """Replace the ``Standort`` (city) column with ``property_code``"""
    if "property_code" not in raw.columns:
        return raw
    out = raw.copy()
    out["Standort"] = out["property_code"].where(out["property_code"] != "TOTAL", "Total")
    return out


# ============================== Channel grouping ===========================
_CHANNEL_LOOKUP = {
    "Direct_Website": "IBE",
    "Direct_Offline": "Direct",
    "OTA.BookingCom": "Booking.com",
    "OTA.Booking.com": "Booking.com",
    "OTA.Booking": "Booking.com",
    "OTA.Expedia": "Expedia",
    "OTA.HRS": "HRS",
    "OTA.Airbnb": "Airbnb",
    "OTA.Hotelrez": "Hotelrez / GDS",
    "OTA.GDS": "Hotelrez / GDS",
    "OTA.CRC": "CRC Corporate Rates Club",
    "OTA.Tomas": "Tomas",
    "OTA.feratel": "feratel",
    "OTA.eHotel": "eHotel AG",
}


def _channel_label(combo: str) -> str:
    if combo in _CHANNEL_LOOKUP:
        return _CHANNEL_LOOKUP[combo]
    if isinstance(combo, str) and combo.startswith("OTA."):
        return combo.split(".", 1)[1]
    return str(combo)


# ============================== 3.A · Performance Standorte nach Aufenthalt
@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def performance_by_stay(
    nightly: pd.DataFrame,
    properties: list[str],
    start_new: pd.Timestamp,
    end_new: pd.Timestamp,
    start_old: pd.Timestamp,
    end_old: pd.Timestamp,
    year_old: int,
    year_new: int,
    period_tag_new: str = "",
    period_tag_old: str = "",
    plan: dict | None = None,
    include_cancellations: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Standort-Performance nach Aufenthaltsdatum - IST vs PLAN vs LY.

    ``plan`` = ``{property_code: {"YYYY-MM": eur}}`` aus dem BigQuery-Snapshot
    (``plan_to_dict(load_plan())``).

    include_cancellations=False (default) → realized-only (Storno + No-Show raus).
    include_cancellations=True            → alle Buchungen werden gezählt.
    """
    nig_new = H.filter_period(nightly, start_new, end_new, "stay_date")
    nig_old = H.filter_period(nightly, start_old, end_old, "stay_date")

    if include_cancellations:
        nig_new_r = nig_new
        nig_old_r = nig_old
    else:
        nig_new_r = nig_new[nig_new["is_realized"]]
        nig_old_r = nig_old[nig_old["is_realized"]]

    ist_new = nig_new_r.groupby("property_code", observed=True)["revenue"].sum()
    ist_old = nig_old_r.groupby("property_code", observed=True)["revenue"].sum()

    rows = []
    for pc in properties:
        ic = float(ist_new.get(pc, 0.0))
        ily = float(ist_old.get(pc, 0.0))
        ip = H.plan_revenue(pc, start_new, end_new, plan=plan)
        if ic == 0 and ily == 0 and ip == 0:
            continue
        d_plan = ic - ip
        d_ly = ic - ily
        d_plan_pct = ((ic / ip - 1) * 100) if ip > 0 else float("nan")
        d_ly_pct = ((ic / ily - 1) * 100) if ily > 0 else float("nan")
        rows.append(
            {
                "property_code": pc,
                "Standort": H.city_label(pc),
                "ist_new": ic,
                "plan_new": ip,
                "ist_old": ily,
                "d_plan_eur": d_plan,
                "d_plan_pct": d_plan_pct,
                "d_ly_eur": d_ly,
                "d_ly_pct": d_ly_pct,
            }
        )
    raw = pd.DataFrame(rows)

    if raw.empty:
        return raw, raw

    # Total über GENAU die übergebenen Standorte (= props_pick nach dem
    # Späte-Öffner-Toggle der Seite). KEIN zweiter, versteckter has-both-Filter -
    # sonst folgen die Kacheln (IST/PLAN/LY) dem Toggle nicht und ändern sich
    # beim Ein-/Ausblenden später Öffner gar nicht.
    t_ist = raw["ist_new"].sum()
    t_plan = raw["plan_new"].sum()
    t_ly = raw["ist_old"].sum()
    total = pd.DataFrame(
        [
            {
                "property_code": "TOTAL",
                "Standort": "Total",
                "ist_new": t_ist,
                "plan_new": t_plan,
                "ist_old": t_ly,
                "d_plan_eur": t_ist - t_plan,
                "d_plan_pct": ((t_ist / t_plan - 1) * 100) if t_plan > 0 else float("nan"),
                "d_ly_eur": t_ist - t_ly,
                "d_ly_pct": ((t_ist / t_ly - 1) * 100) if t_ly > 0 else float("nan"),
            }
        ]
    )
    raw = pd.concat([raw, total], ignore_index=True)

    c_ist = f"IST {year_new} (€)"
    c_plan = f"PLAN {year_new} (€)"
    c_ly = f"IST {year_old} (€)"

    disp = pd.DataFrame(
        {
            "Standort": raw["Standort"],
            c_ist: raw["ist_new"].map(H.fmt_eur),
            c_plan: raw["plan_new"].map(H.fmt_eur),
            c_ly: raw["ist_old"].map(lambda v: H.fmt_eur(v) if v > 0 else "-"),
            "DIFF IST vs. PLAN (€)": [
                f"{tendency_icon(p)} {H.fmt_eur(e)}"
                for e, p in zip(raw["d_plan_eur"], raw["d_plan_pct"])
            ],
            "DIFF IST vs. LY (€)": [
                f"{tendency_icon(p)} {H.fmt_eur(e)}" if pd.notna(p) else "-"
                for e, p in zip(raw["d_ly_eur"], raw["d_ly_pct"])
            ],
        }
    )
    return disp, raw


# ============================== 3.B · Buchungskanäle nach Aufenthalt =======
@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def channel_volume_by_stay(
    nightly: pd.DataFrame,
    start_new: pd.Timestamp,
    end_new: pd.Timestamp,
    start_old: pd.Timestamp,
    end_old: pd.Timestamp,
    year_old: int,
    year_new: int,
    include_cancellations: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """3.B - Channel-Volumen nach Aufenthaltsdatum.

    include_cancellations=False (default) → realized-only.
    """
    nig_new = H.filter_period(nightly, start_new, end_new, "stay_date")
    nig_old = H.filter_period(nightly, start_old, end_old, "stay_date")
    return _build_channel_table(
        nig_new, nig_old, year_old, year_new,
        realized_only=not include_cancellations,
    )


# ============================== 2.A · Performance Standorte nach Created ==
@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def performance_by_created(
    nightly: pd.DataFrame,
    properties: list[str],
    start_new: pd.Timestamp,
    end_new: pd.Timestamp,
    start_old: pd.Timestamp,
    end_old: pd.Timestamp,
    year_old: int,
    year_new: int,
    include_cancellations: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Standort-Performance nach Erstellungsdatum - IST vs LY (KEIN PLAN).

    Quelle = Timeslices (nightly): Netto-Revenue pro Nacht (``baseAmount_netAmount``),
    nach ``created`` gebucketet. Damit identische Revenue-Basis wie die
    Aufenthalts-Tabellen - das Reservations-Netto enthielt zusätzlich
    Services/Extras und stimmte deshalb nicht mit der Stay-Sicht überein.

    include_cancellations=True  (default für Created/Sales-Sicht) → alles drin.
    include_cancellations=False → nur realized - gleicher Daten-Scope wie Stay.
    """
    nig_new = H.filter_period(nightly, start_new, end_new, "created")
    nig_old = H.filter_period(nightly, start_old, end_old, "created")

    if not include_cancellations:
        nig_new = nig_new[nig_new["is_realized"]]
        nig_old = nig_old[nig_old["is_realized"]]

    ist_new = nig_new.groupby("property_code", observed=True)["revenue"].sum()
    ist_old = nig_old.groupby("property_code", observed=True)["revenue"].sum()

    rows = []
    for pc in properties:
        ic = float(ist_new.get(pc, 0.0))
        ily = float(ist_old.get(pc, 0.0))
        if ic == 0 and ily == 0:
            continue
        d_eur = ic - ily
        d_pct = ((ic / ily - 1) * 100) if ily > 0 else float("nan")
        rows.append(
            {
                "property_code": pc,
                "Standort": H.city_label(pc),
                "ist_new": ic,
                "ist_old": ily,
                "d_eur": d_eur,
                "d_pct": d_pct,
            }
        )
    raw = pd.DataFrame(rows)
    if raw.empty:
        return raw, raw

    # Total über die übergebenen Standorte (props_pick nach Späte-Öffner-Toggle);
    # kein separater has-both-Filter, damit der Toggle die Kacheln steuert.
    t_new = raw["ist_new"].sum()
    t_old = raw["ist_old"].sum()
    total = pd.DataFrame(
        [
            {
                "property_code": "TOTAL",
                "Standort": "Total",
                "ist_new": t_new,
                "ist_old": t_old,
                "d_eur": t_new - t_old,
                "d_pct": ((t_new / t_old - 1) * 100) if t_old > 0 else float("nan"),
            }
        ]
    )
    raw = pd.concat([raw, total], ignore_index=True)

    c_ist = f"IST {year_new} (€)"
    c_ly = f"IST {year_old} (€)"

    disp = pd.DataFrame(
        {
            "Standort": raw["Standort"],
            c_ist: raw["ist_new"].map(lambda v: H.fmt_eur(v, 2) if v > 0 else "-"),
            c_ly: raw["ist_old"].map(lambda v: H.fmt_eur(v, 2) if v > 0 else "-"),
            f"DIFF {year_new} vs {year_old} (€)": [
                f"{tendency_icon(p)} {H.fmt_eur(e, 2)}" if pd.notna(p) else "-"
                for e, p in zip(raw["d_eur"], raw["d_pct"])
            ],
        }
    )
    return disp, raw


# ============================== 2.B · Channel-Mix nach Created =============
@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def channel_volume_by_created(
    nightly: pd.DataFrame,
    start_new: pd.Timestamp,
    end_new: pd.Timestamp,
    start_old: pd.Timestamp,
    end_old: pd.Timestamp,
    year_old: int,
    year_new: int,
    include_cancellations: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """2.B - Channel-Volumen nach Erstellungsdatum.

    Quelle = Timeslices (nightly): Netto-Revenue pro Nacht, nach ``created``
    gebucketet - gleiche Revenue-Basis wie die Aufenthalts-Tabellen.

    include_cancellations=True (default, Sales-Sicht) → alle Buchungen.
    """
    nig_new = H.filter_period(nightly, start_new, end_new, "created")
    nig_old = H.filter_period(nightly, start_old, end_old, "created")
    return _build_channel_table(
        nig_new, nig_old, year_old, year_new,
        realized_only=not include_cancellations,
    )


# ============================== Helper - channel table builder =============
def _build_channel_table(
    df_new: pd.DataFrame,
    df_old: pd.DataFrame,
    year_old: int,
    year_new: int,
    realized_only: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the channel volume table"""
    if realized_only:
        df_new = df_new[df_new["is_realized"]]
        df_old = df_old[df_old["is_realized"]]

    def agg(df):
        if df.empty:
            return pd.Series(dtype="float64")
        d = df.assign(_ch=df["channel_combo"].map(_channel_label))
        return d.groupby("_ch", observed=True)["revenue"].sum()

    a_new = agg(df_new)
    a_old = agg(df_old)
    all_channels = list((a_new.abs() + a_old.abs()).sort_values(ascending=False).index)

    sum_new = float(a_new.sum()) or 1
    sum_old = float(a_old.sum()) or 1

    rows = []
    for ch in all_channels:
        rn = float(a_new.get(ch, 0.0))
        ro = float(a_old.get(ch, 0.0))
        if rn == 0 and ro == 0:
            continue
        sh_new = rn / sum_new * 100
        sh_old = ro / sum_old * 100
        d_eur = rn - ro
        d_pct = ((rn / ro - 1) * 100) if ro > 0 else float("nan")
        d_share_pp = sh_new - sh_old
        rows.append(
            {
                "Channel": ch,
                "rev_new": rn,
                "share_new": sh_new,
                "rev_old": ro,
                "share_old": sh_old,
                "d_eur": d_eur,
                "d_pct": d_pct,
                "d_share_pp": d_share_pp,
            }
        )
    raw = pd.DataFrame(rows)
    if raw.empty:
        return raw, raw

    # Total row
    total = pd.DataFrame(
        [
            {
                "Channel": "Total",
                "rev_new": float(a_new.sum()),
                "share_new": 100.0,
                "rev_old": float(a_old.sum()),
                "share_old": 100.0,
                "d_eur": float(a_new.sum() - a_old.sum()),
                "d_pct": ((float(a_new.sum()) / float(a_old.sum()) - 1) * 100)
                if a_old.sum() > 0
                else float("nan"),
                "d_share_pp": 0.0,
            }
        ]
    )
    raw = pd.concat([raw, total], ignore_index=True)

    disp = pd.DataFrame(
        {
            "Channel": raw["Channel"],
            f"Revenue {year_new} (€)": raw["rev_new"].map(H.fmt_eur),
            f"Anteil {year_new} (%)": raw["share_new"].map(lambda v: f"{v:.2f}"),
            f"Revenue {year_old} (€)": raw["rev_old"].map(H.fmt_eur),
            f"Anteil {year_old} (%)": raw["share_old"].map(lambda v: f"{v:.2f}"),
            "Δ Anteil (pp)": raw["d_share_pp"].map(lambda v: f"{v:+.2f}"),
            "Tendenz": [tendency_icon(p) for p in raw["d_pct"]],
        }
    )
    return disp, raw


# ============================== Stay × Creation (As-of) ====================
# Kombinierte Sicht: Hauptbasis Aufenthaltsdatum (Sidebar), zusätzlich nach
# Erstellungsdatum gefiltert (Filter über der Tabelle), je Jahr gespiegelt.
# Der Storno/No-Show-Toggle greift hier POINT-IN-TIME (As-of-Stichtag), nicht
# über den finalen Status - identisch über alle drei Tabellen + Liniengrafik.
_SEGMENT_ORDER = ["short_<=6", "mid_7-28", "long_29+"]
_SEGMENT_LABELS = {
    "short_<=6": "kurz (≤6)",
    "mid_7-28": "mittel (7-28)",
    "long_29+": "lang (29+)",
}


def _segment_label(seg: str) -> str:
    return _SEGMENT_LABELS.get(str(seg), str(seg))


def _signed_eur(value: float) -> str:
    """Euro-String mit explizitem Vorzeichen für Delta-Spalten ('+1.234 €')."""
    if pd.isna(value):
        return "-"
    return ("+" if value > 0 else "") + H.fmt_eur(value)


def _sc_volume_disp(
    raw: pd.DataFrame,
    label_src: str,
    label_header: str,
    year_old: int,
    year_new: int,
) -> pd.DataFrame:
    """Anzeige-Tabelle für die Stay×Creation-Volumen-Sichten (Channel + Segment).

    Spalten-Reihenfolge (laut Product-Ownerin): Label · Revenue NEW · Revenue
    OLD · Δ Revenue (€) · Δ Anteil (pp) · Tendenz. Erwartet ein ``raw`` mit den
    Spalten ``rev_new``, ``rev_old``, ``d_eur``, ``d_share_pp``, ``d_pct`` plus
    der Label-Spalte ``label_src``.
    """
    if raw is None or raw.empty:
        return raw
    return pd.DataFrame(
        {
            label_header: raw[label_src],
            f"Revenue {year_new} (€)": raw["rev_new"].map(H.fmt_eur),
            f"Revenue {year_old} (€)": raw["rev_old"].map(H.fmt_eur),
            "Δ Revenue (€)": raw["d_eur"].map(_signed_eur),
            f"Δ Anteil (pp) {year_new}/{year_old}": raw["d_share_pp"].map(
                lambda v: f"{v:+.2f}"
            ),
            "Tendenz": [tendency_icon(p) for p in raw["d_pct"]],
        }
    )


def stay_created_scope(
    nightly: pd.DataFrame,
    start_stay: pd.Timestamp,
    end_stay: pd.Timestamp,
    cre_start: pd.Timestamp,
    cre_end: pd.Timestamp,
    asof: pd.Timestamp,
    include_cancellations: bool,
) -> pd.DataFrame:
    """Stay-Fenster ∩ Creation-Fenster, As-of am ``asof`` gefiltert.

    Reine pandas-Logik (streamlit-frei, testbar): erst nach ``stay_date`` in
    [start_stay, end_stay], dann nach ``created`` in [cre_start, cre_end]
    schneiden, dann die As-of-On-the-books-Maske (``H.asof_on_the_books_mask``)
    anwenden. Gibt eine gefilterte Kopie zurück.

    Die As-of-Maske behandelt Storno UND No-Show point-in-time, je mit eigenem
    Auflösungsdatum: Storno bis ``cancel_time``, No-Show bis ``arrival`` (erst am
    Anreisetag ist das Nicht-Erscheinen bekannt). Ein No-Show mit Anreise NACH
    dem Stichtag zählt also wie eine noch lebende Buchung mit; liegt die Anreise
    am/vor dem Stichtag, fällt er - wie ein Storno - aus der realized-Sicht.

    Args:
        nightly: Timeslices (eine Zeile je Stay-Nacht).
        start_stay: Aufenthalts-Fenster Start (inklusive).
        end_stay: Aufenthalts-Fenster Ende (inklusive).
        cre_start: Erstellungs-Fenster Start (inklusive, schon jahr-gespiegelt).
        cre_end: Erstellungs-Fenster Ende (inklusive, schon jahr-gespiegelt).
        asof: Point-in-time-Stichtag für die Storno-/No-Show-Logik.
        include_cancellations: Toggle - False = realized-only (As-of-Storno raus
            + am Stichtag bereits aufgelöste No-Shows raus), True = alle
            on-the-books am Stichtag.

    Returns:
        Gefilterte Kopie von ``nightly``.
    """
    stay = H.filter_period(nightly, start_stay, end_stay, "stay_date")
    sc = H.filter_period(stay, cre_start, cre_end, "created")
    if sc.empty:
        return sc
    mask = H.asof_on_the_books_mask(sc, asof, include_cancellations=include_cancellations)
    return sc[mask]


@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def performance_by_stay_created(
    nightly: pd.DataFrame,
    properties: list[str],
    start_new: pd.Timestamp,
    end_new: pd.Timestamp,
    start_old: pd.Timestamp,
    end_old: pd.Timestamp,
    cre_start_new: pd.Timestamp,
    cre_end_new: pd.Timestamp,
    cre_start_old: pd.Timestamp,
    cre_end_old: pd.Timestamp,
    asof_new: pd.Timestamp,
    asof_old: pd.Timestamp,
    year_old: int,
    year_new: int,
    include_cancellations: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Standort-Tabelle: Stay-Fenster ∩ Creation-Fenster, As-of, YoY (KEIN PLAN).

    Gleiche Ausgabe-Struktur wie ``performance_by_created`` (Sales-Sicht), nur
    auf der As-of-gefilterten Stay×Creation-Menge. KEIN PLAN-Vergleich - der
    Plan ist monatlich auf das Aufenthaltsdatum bezogen und passt nicht auf
    einen creation-gefilterten Teilausschnitt.
    """
    scope_new = stay_created_scope(
        nightly, start_new, end_new, cre_start_new, cre_end_new, asof_new, include_cancellations
    )
    scope_old = stay_created_scope(
        nightly, start_old, end_old, cre_start_old, cre_end_old, asof_old, include_cancellations
    )

    ist_new = scope_new.groupby("property_code", observed=True)["revenue"].sum()
    ist_old = scope_old.groupby("property_code", observed=True)["revenue"].sum()

    rows = []
    for pc in properties:
        ic = float(ist_new.get(pc, 0.0))
        ily = float(ist_old.get(pc, 0.0))
        if ic == 0 and ily == 0:
            continue
        d_eur = ic - ily
        d_pct = ((ic / ily - 1) * 100) if ily > 0 else float("nan")
        rows.append(
            {
                "property_code": pc,
                "Standort": H.city_label(pc),
                "ist_new": ic,
                "ist_old": ily,
                "d_eur": d_eur,
                "d_pct": d_pct,
            }
        )
    raw = pd.DataFrame(rows)
    if raw.empty:
        return raw, raw

    t_new = raw["ist_new"].sum()
    t_old = raw["ist_old"].sum()
    total = pd.DataFrame(
        [
            {
                "property_code": "TOTAL",
                "Standort": "Total",
                "ist_new": t_new,
                "ist_old": t_old,
                "d_eur": t_new - t_old,
                "d_pct": ((t_new / t_old - 1) * 100) if t_old > 0 else float("nan"),
            }
        ]
    )
    raw = pd.concat([raw, total], ignore_index=True)

    c_ist = f"IST {year_new} (€)"
    c_ly = f"IST {year_old} (€)"
    disp = pd.DataFrame(
        {
            "Standort": raw["Standort"],
            c_ist: raw["ist_new"].map(lambda v: H.fmt_eur(v, 2) if v > 0 else "-"),
            c_ly: raw["ist_old"].map(lambda v: H.fmt_eur(v, 2) if v > 0 else "-"),
            f"DIFF {year_new} vs {year_old} (€)": [
                f"{tendency_icon(p)} {H.fmt_eur(e, 2)}" if pd.notna(p) else "-"
                for e, p in zip(raw["d_eur"], raw["d_pct"], strict=False)
            ],
        }
    )
    return disp, raw


@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def channel_volume_by_stay_created(
    nightly: pd.DataFrame,
    start_new: pd.Timestamp,
    end_new: pd.Timestamp,
    start_old: pd.Timestamp,
    end_old: pd.Timestamp,
    cre_start_new: pd.Timestamp,
    cre_end_new: pd.Timestamp,
    cre_start_old: pd.Timestamp,
    cre_end_old: pd.Timestamp,
    asof_new: pd.Timestamp,
    asof_old: pd.Timestamp,
    year_old: int,
    year_new: int,
    include_cancellations: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Channel-Tabelle auf der As-of-gefilterten Stay×Creation-Menge.

    Die Storno-/No-Show-Logik passiert bereits in ``stay_created_scope``
    (point-in-time), daher ``realized_only=False`` an ``_build_channel_table``:
    KEIN zweiter, finaler ``is_realized``-Filter - sonst stimmen die Totals
    nicht mehr mit der Standort-/Segment-Tabelle überein.
    """
    scope_new = stay_created_scope(
        nightly, start_new, end_new, cre_start_new, cre_end_new, asof_new, include_cancellations
    )
    scope_old = stay_created_scope(
        nightly, start_old, end_old, cre_start_old, cre_end_old, asof_old, include_cancellations
    )
    _, raw = _build_channel_table(scope_new, scope_old, year_old, year_new, realized_only=False)
    return _sc_volume_disp(raw, "Channel", "Channel", year_old, year_new), raw


@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def segment_volume_by_stay_created(
    nightly: pd.DataFrame,
    start_new: pd.Timestamp,
    end_new: pd.Timestamp,
    start_old: pd.Timestamp,
    end_old: pd.Timestamp,
    cre_start_new: pd.Timestamp,
    cre_end_new: pd.Timestamp,
    cre_start_old: pd.Timestamp,
    cre_end_old: pd.Timestamp,
    asof_new: pd.Timestamp,
    asof_old: pd.Timestamp,
    year_old: int,
    year_new: int,
    include_cancellations: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Stay-Segment-Tabelle (``los_bucket``) auf der As-of-Stay×Creation-Menge.

    kurz ``short_<=6`` / mittel ``mid_7-28`` / lang ``long_29+`` - feste
    Reihenfolge, YoY mit Revenue-Anteil. Gleicher Scope + As-of-Filter wie die
    Standort- und Channel-Tabelle (Reconciliation).
    """
    scope_new = stay_created_scope(
        nightly, start_new, end_new, cre_start_new, cre_end_new, asof_new, include_cancellations
    )
    scope_old = stay_created_scope(
        nightly, start_old, end_old, cre_start_old, cre_end_old, asof_old, include_cancellations
    )

    def agg(df: pd.DataFrame) -> pd.Series:
        if df.empty:
            return pd.Series(dtype="float64")
        return df.groupby("los_bucket", observed=True)["revenue"].sum()

    a_new = agg(scope_new)
    a_old = agg(scope_old)
    sum_new = float(a_new.sum()) or 1
    sum_old = float(a_old.sum()) or 1

    rows = []
    for seg in _SEGMENT_ORDER:
        rn = float(a_new.get(seg, 0.0))
        ro = float(a_old.get(seg, 0.0))
        if rn == 0 and ro == 0:
            continue
        rows.append(
            {
                "Segment": _segment_label(seg),
                "rev_new": rn,
                "share_new": rn / sum_new * 100,
                "rev_old": ro,
                "share_old": ro / sum_old * 100,
                "d_eur": rn - ro,
                "d_pct": ((rn / ro - 1) * 100) if ro > 0 else float("nan"),
                "d_share_pp": (rn / sum_new * 100) - (ro / sum_old * 100),
            }
        )
    raw = pd.DataFrame(rows)
    if raw.empty:
        return raw, raw

    total = pd.DataFrame(
        [
            {
                "Segment": "Total",
                "rev_new": float(a_new.sum()),
                "share_new": 100.0,
                "rev_old": float(a_old.sum()),
                "share_old": 100.0,
                "d_eur": float(a_new.sum() - a_old.sum()),
                "d_pct": ((float(a_new.sum()) / float(a_old.sum()) - 1) * 100)
                if a_old.sum() > 0
                else float("nan"),
                "d_share_pp": 0.0,
            }
        ]
    )
    raw = pd.concat([raw, total], ignore_index=True)
    return _sc_volume_disp(raw, "Segment", "Stay-Segment", year_old, year_new), raw


def daily_created_line_data(
    scope_new: pd.DataFrame,
    scope_old: pd.DataFrame,
    cre_start_new: pd.Timestamp,
    cre_start_old: pd.Timestamp,
) -> pd.DataFrame:
    """Revenue je Erstellungs-Tag für NEW und OLD, ausgerichtet am Fenster-Offset.

    X-Achse = Tag im Creation-Fenster (Offset ab ``cre_start``); so liegen NEW
    und OLD trotz Jahres-Spiegelung deckungsgleich übereinander. Beide Reihen
    sind auf die übergebenen (bereits As-of-gefilterten) Scopes berechnet -
    ``sum(rev_new)`` == Total der Standort-/Channel-/Segment-Tabelle (NEW).

    Args:
        scope_new: As-of-gefilterte NEW-Menge (aus ``stay_created_scope``).
        scope_old: As-of-gefilterte OLD-Menge.
        cre_start_new: Creation-Fenster-Start NEW (Offset-Nullpunkt).
        cre_start_old: Creation-Fenster-Start OLD (gespiegelt).

    Returns:
        DataFrame mit ``offset``, ``date_new`` (Kalendertag NEW), ``rev_new``,
        ``rev_old``. Leer (mit Spalten) wenn beide Scopes leer sind.
    """
    cols = ["offset", "date_new", "rev_new", "rev_old"]

    def by_offset(df: pd.DataFrame, cre_start: pd.Timestamp) -> pd.Series:
        if df is None or df.empty:
            return pd.Series(dtype="float64")
        off = (
            pd.to_datetime(df["created"]).dt.normalize() - pd.Timestamp(cre_start).normalize()
        ).dt.days
        s = df.assign(_off=off).groupby("_off")["revenue"].sum()
        return s[s.index >= 0]

    sn = by_offset(scope_new, cre_start_new)
    so = by_offset(scope_old, cre_start_old)
    max_off = int(
        max(
            sn.index.max() if len(sn) else -1,
            so.index.max() if len(so) else -1,
        )
    )
    if max_off < 0:
        return pd.DataFrame(columns=cols)
    offsets = list(range(0, max_off + 1))
    start_new_ts = pd.Timestamp(cre_start_new).normalize()
    return pd.DataFrame(
        {
            "offset": offsets,
            "date_new": [start_new_ts + pd.Timedelta(days=o) for o in offsets],
            "rev_new": [float(sn.get(o, 0.0)) for o in offsets],
            "rev_old": [float(so.get(o, 0.0)) for o in offsets],
        }
    )


# ============================== Automatische Alerts ========================
def auto_alerts(
    raw_stay: pd.DataFrame,
    raw_created: pd.DataFrame,
    year_old: int,
    year_new: int,
    include_cancellations: bool = False,
) -> list[dict]:
    """Generate alert dicts (kind / title / message) from the raw tables.

    Schwellen:
      - alert    < RED_PCT (default -10 %)
      - warning  zwischen RED_PCT und -2 %
      - success  ≥ GREEN_PCT

    include_cancellations wird in den Message-Body geschrieben, damit der User
    sieht ob die Zahl Storno + No-Show enthält oder nicht (realized-only).
    """
    alerts: list[dict] = []
    # Scope-Marker hängt am Ende jeder Message - macht klar woher die Zahl kommt.
    _scope_stay = (
        "alle Buchungen, nach Aufenthalt" if include_cancellations
        else "realized, nach Aufenthalt"
    )
    _scope_created = (
        "alle Buchungen, nach Erstellung" if include_cancellations
        else "realized, nach Erstellung"
    )

    if not raw_stay.empty:
        valid_stay = raw_stay[
            (raw_stay["Standort"] != "Total")
            & (raw_stay["ist_new"] > 0)
            & (raw_stay["ist_old"] > 0)
        ]
        misses = valid_stay[
            (valid_stay["d_plan_pct"].notna()) & (valid_stay["d_plan_pct"] < RED_PCT)
        ]
        for _, r in misses.sort_values("d_plan_pct").head(3).iterrows():
            alerts.append(
                {
                    "kind": "alert",
                    "title": f"{r['Standort']} {r['d_plan_pct']:+.1f}% vs PLAN",
                    "message": (
                        f"Δ IST vs PLAN: **{H.fmt_eur(r['d_plan_eur'])}** "
                        f"(IST {H.fmt_eur(r['ist_new'])} · PLAN "
                        f"{H.fmt_eur(r['plan_new'])}) - _{_scope_stay}_."
                    ),
                }
            )

        # YoY-Misses (Aufenthaltsdatum)
        yoy_misses = valid_stay[
            (valid_stay["d_ly_pct"].notna()) & (valid_stay["d_ly_pct"] < RED_PCT)
        ]
        for _, r in yoy_misses.sort_values("d_ly_pct").head(2).iterrows():
            alerts.append(
                {
                    "kind": "warning",
                    "title": f"{r['Standort']} {r['d_ly_pct']:+.1f}% YoY",
                    "message": (
                        f"Δ IST vs {year_old}: **{H.fmt_eur(r['d_ly_eur'])}** "
                        f"(IST {H.fmt_eur(r['ist_new'])} · {year_old} "
                        f"{H.fmt_eur(r['ist_old'])}) - _{_scope_stay}_."
                    ),
                }
            )

        # Erfolge
        wins = valid_stay[
            (valid_stay["d_plan_pct"].notna()) & (valid_stay["d_plan_pct"] >= GREEN_PCT)
        ]
        for _, r in wins.sort_values("d_plan_pct", ascending=False).head(2).iterrows():
            alerts.append(
                {
                    "kind": "success",
                    "title": f"{r['Standort']} +{r['d_plan_pct']:.1f}% vs PLAN",
                    "message": (
                        f"Δ IST vs PLAN: **+{H.fmt_eur(r['d_plan_eur'])}** "
                        f"(IST {H.fmt_eur(r['ist_new'])} · PLAN "
                        f"{H.fmt_eur(r['plan_new'])}) - _{_scope_stay}_."
                    ),
                }
            )

    # 2. Created-Date (Sales) - YoY-Misses, mit gleichem ist_new>0 + ist_old>0 Guard
    if not raw_created.empty:
        valid_created = raw_created[
            (raw_created["Standort"] != "Total")
            & (raw_created["ist_new"] > 0)
            & (raw_created["ist_old"] > 0)
        ]
        cmisses = valid_created[
            (valid_created["d_pct"].notna()) & (valid_created["d_pct"] < RED_PCT)
        ]
        for _, r in cmisses.sort_values("d_pct").head(2).iterrows():
            alerts.append(
                {
                    "kind": "warning",
                    "title": f"{r['Standort']} {r['d_pct']:+.1f}% YoY (Sales)",
                    "message": (
                        f"Δ Bookings-Volumen: **{H.fmt_eur(r['d_eur'])}** "
                        f"(IST {H.fmt_eur(r['ist_new'])} · {year_old} "
                        f"{H.fmt_eur(r['ist_old'])}) - _{_scope_created}_."
                    ),
                }
            )

    return alerts
