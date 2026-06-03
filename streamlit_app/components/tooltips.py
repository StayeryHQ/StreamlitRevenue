"""Tooltips + Methodik-Erklärungen für KPIs und Charts.

Zentrale Sammlung. Diese Texte tauchen nicht im Markdown-Export auf.
"""

from __future__ import annotations

import streamlit as st

# ============================== KPI-Tooltips ==============================
# Standort-Analyse Headline-KPIs (Sektion 1)
KPI_REVENUE = (
    "Netto-Revenue über alle realisierten Nächte im Filter-Zeitraum. "
    "Storno + No-Show ausgeschlossen. Anzeige in Euro netto."
)
KPI_ADR = (
    "**ADR (Timeslice-Berechnung):** Revenue der Nächte im Filter-Fenster "
    "÷ Anzahl Nächte IM Fenster. Datenquelle: `timeslices.parquet` "
    "(1 Zeile = 1 genutzte Nacht). \n\n"
    "Wenn eine 14-Nacht-Buchung nur 3 Nächte im Fenster hat, zählen "
    "nur diese 3. Beide Werte stehen "
    "unten im Expander *Berechnungs-Details* nebeneinander."
)
KPI_OCCUPANCY = (
    "Anteil verkaufter Room-Nights an der Kapazität (Units × Periodentage). "
    "100% = ausverkauft. Pro-rata bei Mid-Month-Filter."
)
KPI_ALOS = (
    "**ALOS:** ⌀ Booking-LOS aller "
    "Reservationen die mind. 1 Nacht im Fenster haben - gemessen wird die "
    "ganze Buchungs-Länge, nicht nur die Nächte im Fenster. Datenquelle: "
    "`timeslices.parquet`, dedupliziert auf `id`, dann `mean(nights)`.\n\n"
    "Alternative: window-saubere Variante steht unten im Expander "
    "*Berechnungs-Details* als 'ALOS (Timeslice)'."
)

# Global Report Exec-Summary KPIs
KPI_GLOBAL_IST_STAY = (
    "IST-Revenue nach Aufenthaltsdatum (realized only = Storno + No-Show raus). "
    "Die Zahl mit der Plan werte verglichen werden."
)
KPI_GLOBAL_PLAN = (
    "Hochgeladener Plan aus der Plan-Upload-Page, pro-rata pro Monat × Standort. "
    "Wenn kein Plan hinterlegt: 0 €."
)
KPI_GLOBAL_IST_OLD = (
    "Vorjahres-IST im gleichen Aufenthaltsdatum-Zeitraum (realized only). "
    "Delta-Pfeil = YoY-Veränderung."
)
KPI_GLOBAL_SALES = (
    "Was wurde im Zeitraum tatsächlich gebucht (alle Reservations nach "
    "Erstellungs-Datum, inkl. später stornierter). Das ist die Sales-Sicht: "
    "wie viel Volumen wurde gewonnen unabhängig "
    "davon ob die Gäste später anreisen oder stornieren."
)

KPI_LIFETIME_REVENUE = (
    "Summe aller realisierten Revenue dieser Firma über die gesamte Historie im Snapshot."
)
KPI_CANCEL_RATE = (
    "Anzahl stornierter Buchungen ÷ Gesamt-Buchungen × 100. Schwelle aus dem Sidebar-Slider."
)


# ============================== Chart-Tooltips ============================
# Pro Sektion eine kurze Lesehilfe. Wird via chart_help() als Expander
# unter dem Chart gerendert.
CHART_TOOLTIPS: dict[str, str] = {
    # Standort-Analyse
    "kpis": (
        "**Was du siehst:** Big-Number = Total der NEW-Periode. Drunter "
        "YoY-Δ in % (grün/rot). Untertitel = OLD-Wert mit Jahreszahl. "
        "Linien = Monatswerte (NEW oben, OLD darunter).\n\n"
        "**Filter:** realized only - Storno + No-Show fallen raus."
    ),
    "pace_month": (
        "**3 Bars pro Monat:**\n"
        "- 🟡 `Jahr/EoM` = finale Realität im Vorjahr (alle Buchungen)\n"
        "- ⚪ `Jahr/Today` = was war zum gleichen Snapshot-Tag im Vorjahr on-the-books\n"
        "- 🔵 `aktJahr/Today` = aktueller Stand on-the-books\n\n"
        "**Pacing-Logik:** Vergleich Grau vs Blau zeigt ob wir besser/schlechter "
        "stehen als zum gleichen Zeitpunkt letztes Jahr. Vergleich Grau vs Gelb "
        "zeigt was nach dem Stichtag noch reinkam im Vorjahr."
    ),
    "heat_ch_los": (
        "**Links:** YoY-Veränderung je Channel × LOS-Bucket. Rot = Verlust, "
        "Grün = Wachstum. Zahl in Klammern = absolute Δ in EUR.\n\n"
        "**Rechts:** Revenue-Anteil je Zelle, OLD vs NEW nebeneinander - "
        "Mix-Verschiebungen auf einen Blick."
    ),
    "heat_ch_purpose_los": (
        "Wie Heatmap Channel × LOS, aber zusätzlich nach Reisezweck aufgesplittet "
        "(Business links, Leisure rechts). Zeigt ob B oder L-Segmente das YoY-Δ treiben."
    ),
    "los_yoy": (
        "Revenue pro LOS-Bucket (short ≤6 / mid 7-28 / long 29+). "
        "Links: Balken-Vergleich OLD vs NEW. Rechts: Share-Verschiebung in pp."
    ),
    "channel_mix": (
        "**Links:** Monatsverlauf gestapelt nach Channel (Top-6) - zeigt "
        "Saisonalität pro Channel.\n\n"
        "**Rechts:** YoY-Vergleich pro Channel mit %-Veränderung als Label."
    ),
    "alos_channel": (
        "⌀ Nächte je Buchung, granular pro Channel - wer bringt die langen "
        "Aufenthalte (Corporate-Stays vs OTA-Kurztrips)."
    ),
    "weekday_stay": (
        "Revenue je Wochentag (gestapelt nach Channel-Gruppe), OLD vs NEW "
        "nebeneinander. Stay-Wochentag = der Tag an dem der Gast tatsächlich da ist."
    ),
    "weekday_arr": (
        "Wie Stay-Pattern, aber Check-in-Tag statt Stay-Tag. Wichtig für "
        "Front-Desk-Staffing und Channel-spezifische An-/Abreise-Muster."
    ),
    "group_size": (
        "Revenue nach Anzahl Zimmer je Buchung (1 / 2 / 3+). Single-Room-Buchungen "
        "vs Multi-Room-Buchungen zeigen Geschäftsreise- vs Gruppen-/Familien-Mix."
    ),
    "de_intl": (
        "DE vs International - drei Sichten: Revenue absolut, Anteil in %, "
        "Room-Nights (mit ADR als Annotation). ADR-Unterschied zeigt ob "
        "Internationale teurer/günstiger buchen."
    ),
    "top_countries": (
        "Top 10 Herkunftsländer nach Revenue. Gelb = Deutschland, Blau = Ausland. "
        "OLD links, NEW rechts - neue Märkte werden sichtbar wenn Länder im "
        "NEW-Panel auftauchen die im OLD nicht da waren."
    ),
    "leadtime": (
        "**Links:** Revenue pro Vorlaufzeit-Bucket (wie lange vor Anreise gebucht). "
        "n = Anzahl Buchungen.\n\n"
        "**Rechts:** Realized vs Storniert pro Bucket - Risiko-Sicht: Werden "
        "späte Buchungen häufiger storniert als frühe?"
    ),
    "daily_occ": (
        "Daily Occupancy in % der Kapazität, gestapelt nach LOS-Bucket. "
        "100%-Linie (rot gepunktet) = volle Auslastung. Wenn Long-Stays viel "
        "Platz wegnehmen, sieht man's hier zuerst."
    ),
    "corp_overview": (
        "**Links:** Firmen-Revenue vs Privat-Revenue (YoY in % darüber).\n\n"
        "**Rechts:** Firmen-Revenue aufgesplittet nach Channel - sieht man "
        "ob Direct-Offline-Firmen auf OTA gewechselt sind."
    ),
    "do_waterfall": (
        "Waterfall-Chart: woher kommt die Direct-Offline-Veränderung?\n"
        "- **verloren** = Firmen die OLD da waren, NEW null\n"
        "- **geschrumpft** = beide da, aber kleiner\n"
        "- **gewachsen** = beide da, aber größer\n"
        "- **neu** = nur NEW da\n\n"
        "Tabellen drunter zeigen die Top-5 pro Bucket."
    ),
    "codes": (
        "Welche Vertragscodes (`corporateCode`, fallback auf apaleo "
        "`company_code` wo gepflegt) haben in der aktuellen Periode am meisten "
        "Revenue gemacht. Reine OTA-Privatkunden ohne Code sind hier NICHT enthalten."
    ),
    # Global Report
    "scorecard": (
        "**Bar-Länge** = IST-Revenue je Standort (sortiert nach Δ vs PLAN). "
        "**Schwarzer Tick** = PLAN, **gestrichelte Linie** = Vorjahres-IST. "
        "**Farbe:**\n"
        "- 🟢 grün = IST ≥ PLAN + Schwelle (Slider in Sidebar)\n"
        "- 🟠 orange = im Korridor\n"
        "- 🔴 rot = IST ≤ PLAN - Schwelle (Slider in Sidebar)\n"
        "- ⚪ grau = kein PLAN hinterlegt für diesen Standort"
    ),
    "perf_created": (
        "Performance pro Standort nach **Erstellungs-Datum** der Buchung. "
        "Sales-Sicht: alles was im Zeitraum gebucht wurde, inkl. später "
        "stornierter. KEIN PLAN-Vergleich (Plan ist immer auf Aufenthalt bezogen)."
    ),
    "chan_created": (
        "Channel-Volumen nach Erstellungs-Datum - wie verteilt sich das "
        "Sales-Volumen über die Channels. Inkl. später stornierter Buchungen."
    ),
    "perf_stay": (
        "Performance pro Standort nach **Aufenthalts-Datum**. Nur realisierte "
        "Nächte (Storno + No-Show raus). Das ist die Sicht für PLAN-Vergleich."
    ),
    "chan_stay": (
        "Channel-Volumen nach Aufenthalts-Datum (realized only). "
        "Vergleich mit Channel-Mix nach Erstellung zeigt: stornieren OTAs mehr?"
    ),
    "pace_plan": (
        "**Was du siehst:** je Standort die bisherige IST-Revenue der Periode, "
        "der PLAN-Wert, das Verhältnis IST/PLAN (%) und wie weit die Periode "
        "zeitlich schon durch ist (Fortschritt Zeit %).\n\n"
        "**Lese-Faustregel:** bei 30 % verstrichener Periode sind ~30 % vom "
        "PLAN ein 'on-pace'-Signal. Deutlich weniger = hinterher, deutlich mehr "
        "= voraus. Keine lineare Forecast-Hochrechnung mehr — die war für "
        "Hospitality-Saisonalität ohnehin zu naiv."
    ),
    "channel_detail": (
        "**Donuts:** Channel-Anteile am Total - OLD vs NEW nebeneinander.\n"
        "**Bars darunter:** Top-Channels mit YoY-Δ in % je Channel."
    ),
    "heat_loc_month": (
        "Heatmap Revenue je Standort × Monat - visualisiert Saisonalität und "
        "Standort-Skew. Dunkler = mehr Revenue."
    ),
    "heat_chan_loc": (
        "Anteil je Channel × Standort in % - welcher Channel dominiert wo. "
        "Hilft Channel-Strategie pro Standort zu kalibrieren."
    ),
    "top_movers": (
        "Best/Worst-Bewegungen YoY in absoluten EUR. Diverging-Bars: rot = Verlust, "
        "grün = Wachstum. Sortiert nach Δ Revenue ↑."
    ),
    "heat_ch_los_granular": (
        "**Links:** YoY-Veränderung pro Channel × LOS-Bucket. Granulare Channel-"
        "Sicht (Booking.com, Expedia, HRS, IBE, Direct Offline, …) - Top 8 "
        "nach Revenue.\n\n"
        "**Rechts:** Revenue-Anteil je Zelle, OLD vs NEW nebeneinander - "
        "wo wandert Volumen zwischen Channels und Aufenthaltsdauern."
    ),
}


# ============================== Render-Helper =============================
def chart_help(key: str) -> None:
    """Render an expander with the methodology for a chart key. UI-only."""
    txt = CHART_TOOLTIPS.get(key)
    if not txt:
        return
    with st.expander("ℹ Was zeigt diese Grafik?", expanded=False):
        st.markdown(txt)
