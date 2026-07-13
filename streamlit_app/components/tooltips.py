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
    "÷ Anzahl Nächte im Fenster."
    "(1 Zeile = 1 genutzte Nacht). \n\n"
    "Wenn eine 14-Nacht-Buchung nur 3 Nächte im Fenster hat, zählen "
    "nur diese 3."
)
KPI_OCCUPANCY = (
    "Anteil verkaufter Room-Nights an der Kapazität (Units × Periodentage). "
    "100% = ausverkauft. Pro-rata bei Mid-Month-Filter."
)
KPI_ALOS = (
    "**ALOS:** ⌀ Booking-LOS aller "
    "Reservationen die mind. 1 Nacht im Fenster haben. Gemessen wird die "
    "ganze Buchungs-Länge, nicht nur die Nächte im Fenster. \n\n"
    "Alternative: window-saubere Variante steht unten im Expander "
    "*Berechnungs-Details* als 'ALOS (Timeslice)'."
)

# Global Report Exec-Summary KPIs
KPI_GLOBAL_IST_STAY = (
    "IST-Revenue nach Stay-datum. "
    "Die Zahl mit der Plan werte verglichen werden."
)
KPI_GLOBAL_PLAN = (
    "Plan aus dem BigQuery-Snapshot (`ref_tables.plan`), pro-rata pro Monat × Standort. "
    "Wenn kein Plan hinterlegt: 0 €."
)
KPI_GLOBAL_IST_OLD = (
    "Vorjahres-IST im gleichen Stay-datum-Zeitraum (realized only). "
    "Delta-Pfeil = YoY-Veränderung."
)
KPI_GLOBAL_SALES = (
    "Was wurde im Zeitraum tatsächlich gebucht (nach Erstellungs-Datum)? "
    "Netto-Revenue pro Nacht (ohne Services) - "
    "gleiche Revenue-Basis wie die Stay-Sicht. Sales-Sicht: wie viel "
    "Volumen wurde gewonnen durch erstellte Buchungen im Fenster."
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
        "zeigt was nach dem Stichtag noch reinkam im Vorjahr.\n\n"
        "**Storno-Zeitpunkt** für die OTB-Rekonstruktion: `cancellationTime` "
        "(Fallback `modified` als Proxy, falls leer)."
    ),
    "heat_ch_los": (
        "**Links:** YoY-Veränderung je Channel × LOS-Bucket. Rot = Verlust, "
        "Grün = Wachstum. Zahl in Klammern = absolute Δ in EUR.\n\n"
        "**Rechts:** Revenue-Anteil je Zelle, OLD vs NEW nebeneinander - "
        "Mix-Verschiebungen auf einen Blick."
    ),
    "heat_ch_purpose_los": (
        "Wie Heatmap Channel × LOS, aber zusätzlich nach Reisezweck aufgesplittet "
        "(Business links, Leisure rechts). Zeigt ob B oder L-Segmente das YoY-Δ treiben.\n\n"
        "**Achtung:** Fehlender/leerer `travelPurpose` zählt als **Leisure** - "
        "der Leisure-Anteil kann dadurch überzeichnet sein (v.a. bei OTAs, wo der "
        "Reisezweck oft nicht durchgereicht wird; siehe Doku Kap. 11)."
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
        "⌀ Nächte je Buchung, granular pro Channel. Gemessen wird die **volle "
        "Buchungs-LOS** (wie der Headline-ALOS, Variante B) - auch wenn nur ein "
        "Teil der Buchung im Filterfenster liegt, zählt die ganze Länge."
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
        "Revenue nach Anzahl Zimmer je Buchung (single / 2 / 3-4 / 5+). "
        "Single-Room-Buchungen vs Multi-Room-Buchungen zeigen Geschäftsreise- "
        "vs Gruppen-/Familien-Mix.\n\n"
        "**Filter:** nach Erstellungsdatum (created) · Nacht-Netto · Counts = Buchungen."
    ),
    "de_intl": (
        "DE vs International vs **Unbekannt**: Revenue absolut, Anteil in %, "
        "Room-Nights (mit ADR als Annotation). ADR-Unterschied zeigt ob "
        "Internationale teurer/günstiger buchen.\n\n"
        "**Unbekannt** = weder Ländercode noch Sprache erfasst (wird explizit "
        "ausgewiesen statt einem Lager zugeschlagen). Herkunft ist ein "
        "Misch-Feld aus Land + Sprach-Fallback - als Tendenz lesen (Doku Kap. 10b)."
    ),
    "top_countries": (
        "Top 10 Herkunftsländer nach Revenue. Gelb = Deutschland, Blau = Ausland. "
        "OLD links, NEW rechts"
    ),
    "leadtime": (
        "**Links:** Revenue pro Vorlaufzeit-Bucket (wie lange vor Anreise gebucht). "
        "n = Anzahl Buchungen.\n\n"
        "**Rechts:** Realized vs Storniert pro Bucket.\n\n"
        "**Filter:** nach Erstellungsdatum (created) · Nacht-Netto · Counts = Buchungen "
        "(Vorlaufzeit = arrival − created)."
    ),
    "daily_occ": (
        "Daily Occupancy in % der Kapazität, gestapelt nach LOS-Bucket. "
        "100%-Linie (rot gepunktet) = volle Auslastung. Wenn Long-Stays viel "
        "Platz wegnehmen, sieht man's hier zuerst. Chart UND Tabelle folgen "
        "dem Storno/No-Show-Toggle."
    ),
    "corp_overview": (
        "**Links:** Firmen-Revenue vs Privat-Revenue (YoY in % darüber).\n\n"
        "**Rechts:** Firmen-Revenue aufgesplittet nach Channel \n\n"
        "**Filter:** nach Erstellungsdatum (created) · Nacht-Netto."
    ),
    "do_waterfall": (
        "Waterfall-Chart: woher kommt die Direct-Offline-Veränderung?\n"
        "- **verloren** = Firmen die OLD da waren, NEW null\n"
        "- **geschrumpft** = beide da, aber kleiner\n"
        "- **gewachsen** = beide da, aber größer\n"
        "- **neu** = nur NEW da\n\n"
        "Tabellen drunter zeigen die Top-5 pro Bucket.\n\n"
        "**Filter:** nach Erstellungsdatum (created) · Nacht-Netto."
    ),
    "codes": (
        "Welche Vertragscodes (`corporateCode`, fallback auf apaleo "
        "`company_code` wo gepflegt) haben in der aktuellen Periode am meisten "
        "Revenue gemacht. Reine OTA-Privatkunden ohne Code sind hier nicht enthalten.\n\n"
        "**Filter:** Periode nach Erstellungsdatum (created) · Nacht-Netto."
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
        "Netto-Revenue pro Nacht (Timeslices).  "
        "KEIN PLAN-Vergleich (Plan ist immer auf Aufenthalt bezogen)."
    ),
    "chan_created": (
        "Channel-Volumen nach Erstellungs-Datum (Netto-Revenue pro Nacht, "
        "Timeslices) - wie verteilt sich das Sales-Volumen über die Channels. "
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
        "zeitlich schon durch ist (Fortschritt Zeit %)."
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
    "stay_created": (
        "**Doppelt gefilterte Sicht.** Hauptbasis = **Stay-datum** "
        "(Stay-Fenster aus der Sidebar). Zusätzlich wird über den Filter direkt "
        "über der Tabelle nach **Erstellungsdatum** eingeschränkt - also "
        "Buchungen, die *im gewählten Buchungs-Fenster angelegt* wurden und "
        "*ihren Aufenthalt im Stay-Fenster* haben.\n\n"
        "**Jahres-Spiegelung:** Das Creation-Fenster wird pro Vergleichsjahr "
        "verschoben (z.B. 1.–25.06.2026 ↔ 1.–25.06.2025), damit beide Jahre "
        "vergleichbar sind.\n\n"
        "**Storno/No-Show - As-of (point-in-time):** Der Sidebar-Toggle greift "
        "hier wie beim Pace-Chart als **Stichtags-Sicht**, nicht über den "
        "finalen Status. Stichtag = **min(Fensterende, Snapshot)**, je Jahr "
        "gespiegelt.\n"
        "- Toggle **aus** (Default): nur was am Stichtag on-the-books war - "
        "Buchung mit `created ≤ Stichtag` und (nicht storniert *oder* Storno "
        "erst *nach* dem Stichtag). Finale No-Shows raus. So zählen Stornos, die "
        "erst nach dem Stichtag passierten, korrekt noch mit.\n"
        "- Toggle **an**: alle am Stichtag erzeugten Buchungen, inkl. später "
        "stornierter und No-Shows.\n\n"
        "**Hinweis (Zukunfts-Stays):** Liegt das Stay-Fenster in der Zukunft des "
        "Snapshots, sind **No-Shows noch nicht bekannt** (der Aufenthalt war noch "
        "nicht)."
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
