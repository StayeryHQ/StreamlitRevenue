"""Wiederverwendbarer Split-View-Drilldown (kompakter Code-Deep-Dive).

Genutzt von der Promo-Page und vom B2B-Deep-Dive: links eine Tabelle mit
Einfach-Klick-Auswahl, rechts dieser kompakte 360°-Blick für die ausgewählte
Zeile - ohne Seitenwechsel.

Die Layout-Logik (Tabelle full-size, bis etwas ausgewählt ist; danach Split)
liegt bewusst in der jeweiligen Page - dieses Modul liefert nur den robusten
Selektions-Reader und das rechte Panel.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from revenueblindspots import helpers as H
from revenueblindspots import overrides as OV

from . import cached_data as CD
from . import code_deepdive_charts as CC
from .export import register_section


def get_selection_rows(event) -> list[int]:
    """Positionsindizes der ausgewählten Zeilen aus einem ``st.dataframe``-Event.

    Args:
        event: Rückgabe von ``st.dataframe(..., on_select="rerun")``.

    Returns:
        Liste der Zeilen-Positionsindizes (leer wenn nichts ausgewählt ist).
    """
    try:
        return list(event.selection.rows)
    except Exception:
        try:
            return list(event["selection"]["rows"])
        except Exception:
            return []


def compact_deepdive(
    container,
    sub: pd.DataFrame,
    label: str,
    *,
    period_start: pd.Timestamp,
    period_end: pd.Timestamp,
    cache_salt: str = "",
    caption: str | None = None,
    open_code: str | None = None,
    page: str | None = None,
    section_id: str | None = None,
) -> None:
    """Rendere den kompakten Deep-Dive für eine vorgefilterte Buchungs-Teilmenge.

    Args:
        container: Streamlit-Container (z.B. die rechte Spalte).
        sub: Bereits gefilterte Buchungen (eine Zeile = eine Buchung).
        label: Anzeigename (Code oder Firma).
        period_start: Start der Fokus-Periode (nur für die Chart-Schattierung).
        period_end: Ende der Fokus-Periode.
        cache_salt: Zusatz für den Chart-Cache-Key (z.B. Snapshot-Tag).
        caption: Optionaler Untertitel (z.B. Reklassifizierungs-Status).
        open_code: Wenn gesetzt, erscheint ein Button, der diesen Code im vollen
            Code-Deep-Dive öffnet.
        page: Page-Key für ``register_section`` / eindeutige Button-Keys.
        section_id: Wenn gesetzt, wird der Drilldown für den Export registriert.
    """
    if sub is None or sub.empty:
        container.info(f"Keine Buchungen für **{label}**.")
        return

    realized = sub[sub["is_realized"]]
    lifetime_rev = float(realized["revenue"].sum())
    lifetime_nights = int(realized["nights"].fillna(0).sum())
    adr = lifetime_rev / lifetime_nights if lifetime_nights else float("nan")
    n_total = len(sub)
    n_cancelled = int(sub["is_cancelled"].sum())
    cancel_rate = (n_cancelled / n_total * 100) if n_total else 0.0
    first_b, last_b = sub["arrival"].min(), sub["arrival"].max()

    container.markdown(f"### 🔎 {label}")
    if caption:
        container.caption(caption)

    n_real = f"{len(realized):,}".replace(",", ".")
    n_b = f"{n_total:,}".replace(",", ".")
    m1, m2 = container.columns(2)
    m1.metric("Lifetime Revenue", H.fmt_eur(lifetime_rev), delta=f"{n_real} realisiert")
    m2.metric("Cancel-Rate", f"{cancel_rate:.1f} %", delta=f"{n_b} Buchungen")
    m3, m4 = container.columns(2)
    m3.metric(
        "Nächte (real.)", f"{lifetime_nights:,}".replace(",", "."), delta=f"ADR ø {H.fmt_eur(adr)}"
    )
    m4.metric("Erste Buchung", f"{first_b:%d.%m.%y}", delta=f"letzte {last_b:%d.%m.%y}")

    png, _extras = CD.chart_png(
        f"dd::{cache_salt}::{OV.override_signature()}::{label}",
        CC.revenue_timeline,
        sub,
        label,
        period_start,
        period_end,
    )
    container.image(png, use_container_width=True)

    if not realized.empty:
        loc = (
            realized.groupby("property_code")
            .agg(Buchungen=("id", "nunique"), Revenue=("revenue", "sum"))
            .reset_index()
            .rename(columns={"property_code": "Standort", "Revenue": "Revenue (€)"})
            .sort_values("Revenue (€)", ascending=False)
        )
        loc["Revenue (€)"] = loc["Revenue (€)"].round(0)
        container.markdown("**Standort-Aufteilung**")
        container.dataframe(loc, hide_index=True, use_container_width=True, height=180)

    if open_code:
        container.divider()
        if container.button(
            "Im Code Deep-Dive öffnen ↗",
            key=f"_dd_open_{page}_{open_code}",
            use_container_width=True,
        ):
            st.session_state["cd_code_input"] = open_code
            st.switch_page("pages/4_Code_Deepdive.py")

    if section_id and page:
        register_section(
            section_id,
            f"Drilldown · {label}",
            body_markdown=(
                f"**{label}** · Lifetime {H.fmt_eur(lifetime_rev)} · "
                f"{lifetime_nights:,} Nächte · ADR ø {H.fmt_eur(adr)} · "
                f"Cancel {cancel_rate:.1f} % · {n_total} Buchungen"
            ),
            chart_png=png,
            page=page,
        )
