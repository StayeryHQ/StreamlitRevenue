"""Dokumentation - Datenbasis, Logik & Spalten des Dashboards."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT / "streamlit_app"))

import streamlit as st

from components import cached_data as CD
from components import inject_brand_css
from components.brand import hero

st.set_page_config(page_title="Dokumentation · Stayery", page_icon="📚", layout="wide")
inject_brand_css()
CD.apply_stayery_style_once()

hero(
    eyebrow="Dokumentation · Datenbasis & Logik",
    title="Dokumentation",
    subtitle="Woher die Daten kommen, welche Tabellen/Spalten genutzt werden und "
    "wie die wichtigsten Logiken (Netto/Brutto, Storno/No-Show, Filter, Channels, "
    "B2B) funktionieren.",
)

st.info(
    "Die Kapitel sind aufklappbar.",
    icon="ℹ️",
)

# ============================================================================
with st.expander("1 · Überblick, Zugriff & Tech-Stack", expanded=True):
    st.markdown(
        """
**Was ist das?** Ein Streamlit-Dashboard für den Revenue-Recap
(Standort-Analyse, Portfolio/Global-Report, B2B-, Code- und Promo-Deepdives).

**Zugriff / Code:** Der Quellcode liegt im GitHub-Repo **`StreamlitRevenue`**.
Sprache ist **Python (3.12)**. Wichtigste Bausteine:

| Bereich | Modul / Ordner | Zweck |
|---|---|---|
| Kern-Logik | `src/revenueblindspots/helpers.py` | Feature-Engineering, Filter, Revenue-Logik |
| Daten-Refresh | `src/revenueblindspots/refresh.py` | BigQuery-Pull → Snapshot |
| Promo-Overrides | `src/revenueblindspots/overrides.py` | Promo-Codes als Firmencodes reklassifizieren |
| Seiten | `streamlit_app/pages/` | die einzelnen Dashboard-Seiten |
| Komponenten | `streamlit_app/components/` | Charts, Tabellen, Caching, Alerts |
| Konfiguration | `configs/` | `locations.yaml` (Hotels), `code_overrides.json` |
| Daten-Snapshot | `data/` | `*.parquet` + `metadata.json` |

**Bibliotheken:** Streamlit (UI), pandas/numpy (Daten), matplotlib (Charts),
pyarrow (Parquet), openpyxl (Excel), rapidfuzz (Firmen-Fuzzy-Matching),
google-cloud-bigquery (nur beim Refresh).

Das Dashboard rechnet **nicht** live auf BigQuery, sondern auf
einem **Snapshot** (lokale Parquet-Dateien). Nur die Seite *Daten aktualisieren*
spricht mit BigQuery.
"""
    )

# ============================================================================
with st.expander("2 · Datenfluss: von BigQuery zum Dashboard"):
    st.markdown(
        """
```
BigQuery  ──(Refresh)──►  Engineering  ──►  Snapshot (data/)  ──►  Dashboard
reservations              + abgeleitete       reservations.parquet   (liest nur
reservations_timeslices   Spalten            timeslices.parquet      den Snapshot)
ref_tables.plan           + Fuzzy-Cluster    plan.parquet
                                             metadata.json
```

**Ablauf (`refresh.run_refresh`):**

1. **Auth** gegen BigQuery (Service-Account oder lokaler gcloud-Login).
2. **Pull** der Roh-Tabellen ab einem **Lookback-Startdatum** =
   `heute − lookback_years` (Default **3 Jahre**); gefiltert auf `DATE(arrival) ≥ Start`
   bzw. `serviceDate ≥ Start`. Zukunfts-Buchungen (Forward-Bookings) werden voll mitgezogen.
3. **Engineering** (`engineer_reservations`, `engineer_timeslices`): abgeleitete Spalten anlegen.
4. **Fuzzy-Cluster** der Firmennamen (rapidfuzz).
5. **Broadcast**: buchungsweite Felder (Firmen, Lead-Time, cancel_time …) auf die
   Nächte verteilen.
6. **Save**: `reservations.parquet`, `timeslices.parquet`, `metadata.json` (+ ggf. `plan.parquet`).

**`metadata.json`** hält u.a. `refreshed_at`, `lookback_years`, Row-Counts und die
**Datenspanne** (`timeslices.earliest/latest`). Letztere ist die Grundlage der Warnung
„Periode reicht vor den verfügbaren Datenbestand zurück".
"""
    )

# ============================================================================
with st.expander("3 · Die zwei Quell-Tabellen (wichtig: unterschiedlicher Grain & Revenue)"):
    st.markdown(
        """
Es gibt **zwei** BigQuery-Quelltabellen mit **unterschiedlicher Körnung (Grain)**
und **unterschiedlicher Revenue-Definition**:

| | `reservations` | `reservations_timeslices` |
|---|---|---|
| **Grain** | 1 Zeile = **1 Buchung** | 1 Zeile = **1 Übernachtung (Nacht)** |
| **Revenue-Feld** | `totalGrossAmount_amount` | `baseAmount_netAmount` |
| **Enthält Services?** | **JA** (Frühstück, Parkplatz, Extras …) | **NEIN** – nur der Übernachtungs-Grundpreis |
| **Datum** | `arrival`, `departure`, `created` | zusätzlich `serviceDate` (= der Nacht-Tag) |

**Konsequenz:** Eine 3-Nächte-Buchung erscheint in
`reservations_timeslices` als **3 Zeilen**. Die Summe dieser drei Nacht-Netto-Werte
ist **kleiner** als der Buchungs-Gesamtbetrag aus `reservations`, weil in den
Timeslices **keine Services** stecken.

**Das Dashboard nutzt überall die Timeslices** (eine Nacht je Zeile,
`baseAmount_netAmount`). Für „nach Erstellungsdatum"-Sichten werden die Timeslices
per `reservations_from_timeslices()` auf **Buchungs-Ebene zurückgefaltet**
(Revenue = Summe der Nacht-Netto je Buchung) – damit ist die Revenue-Basis
durchgängig dieselbe (Nacht-Netto, **ohne** Services).
"""
    )

# ============================================================================
with st.expander("4 · Revenue-Grundprinzip: Netto vs. Brutto, mit/ohne Services"):
    st.markdown(
        """
**Wir rechnen in NETTO.** Die Hauptkennzahl `revenue` = `baseAmount_netAmount`
(Nacht-Netto, ohne Services).

- **Brutto = Netto × 1,07** (deutsche Beherbergungs-MwSt. **7 %**, `to_net = gross / 1,07`).
- `revenue_gross` (= `baseAmount_grossAmount`) liegt zusätzlich vor und entspricht
  praktisch `revenue × 1,07`.
- **Achtung Abgleich mit externen Brutto-Listen:** Selbst nach ×1,07 fehlen die
  **Extras** (Frühstück/Parkplatz), weil die Timeslices nur den Übernachtungs-Grundpreis
  führen. Eine Brutto-Excel inkl. Services ist daher **höher** als die Dashboard-Zahl
  ×1,07. Die Differenz = Services + ggf. abweichende MwSt. auf Extras (19 %).

> Merksatz: **Dashboard = Übernachtung, Netto.** Services und Brutto musst du bewusst
> dazudenken.
"""
    )

# ============================================================================
with st.expander("5 · Datum & Zeitzone: Aufenthalt vs. Erstellung"):
    st.markdown(
        """
Drei Datums-Achsen:

- **Aufenthalt** = `stay_date` / `serviceDate` (der Tag der Übernachtung). Basis der
  „nach Aufenthalt"-Sichten (KPIs, Occupancy, Pace, Channels …).
- **Erstellung** = `created` (wann gebucht wurde). Basis der „nach Erstellungsdatum"-Sichten
  (Sales/Pickup, Gruppen-Größe, Lead-Time, Firmen, §8).
- **Anreise** = `arrival`. U.a. Auflösungs-Zeitpunkt für No-Shows (siehe Kap. 7).

**Zeitzone:** Alle Zeitstempel werden nach **Europe/Berlin** normalisiert (inkl.
`created` – früher war `created` ein UTC-Sonderfall, das ist behoben). `serviceDate`
ist ein reines Datum. Dadurch fällt eine abends gebuchte Reservierung nicht mehr in
einen anderen Kalendertag als der Rest der Spalten.
Es gibt auch noch zusätzlich CancellationDateTime und Abreise natürlich. Für no-shows wird
als "no-show" Datum das Anreisedatum genutzt.
"""
    )

# ============================================================================
with st.expander("6 · Status, Storno & No-Show"):
    st.markdown(
        """
Der apaleo-`status` wird in drei Flags übersetzt:

- `is_realized` = Status ∈ {Confirmed, InHouse, CheckedOut}
- `is_cancelled` = Status == Canceled
- `is_no_show` = Status == NoShow

**`realized_only`** (Default in fast allen Sichten) = nur `is_realized`, also
**Storno + No-Show raus**. Der Sidebar-Toggle **„Storno + No-Show einbeziehen"**
schaltet auf „alle Buchungen".

Weitere Storno-Spalten (auf Buchungs-Ebene):
- `cancel_time` = `cancellationTime`, Fallback `modified`. **Stolperfalle:** bei
  *nicht* stornierten Buchungen ist `cancel_time` mit `modified` gefüllt – als echtes
  Stornodatum nur lesen, wenn `is_cancelled` = WAHR (siehe Kap. 11).
- `kept_revenue` / `lost_revenue` = bei Storno/No-Show die einbehaltene Fee
  (gedeckelt aufs Buchungs-Netto) vs. der verlorene Rest.
"""
    )

# ============================================================================
with st.expander("7 · Filter-Logik: realized-only, As-of (point-in-time) & Doppelfilterung §8"):
    st.markdown(
        """
**a) Der Storno/No-Show-Toggle greift in fast allen Charts/Tabellen** beider Seiten
(Standort + Global). Default = realized-only; eingeschaltet = alle Buchungen.
**Ausnahmen mit eigener Logik:** die **Pace-by-Month**-Sicht (point-in-time-
Rekonstruktion, No-Shows immer raus) und die **Storno-Risiko/Vorlaufzeit**-Sektion
(braucht Stornos, um die Storno-Quote zu zeigen).

**b) As-of / point-in-time (Global §8):** Hier wird gefragt *„War die Buchung am
Stichtag schon storniert / als No-Show aufgelöst?"* – nicht der heutige Endstatus.

- **Storno** löst zum `cancel_time` auf: ein Storno **nach** dem Stichtag zählt am
  Stichtag noch mit; ein Storno **am/vor** dem Stichtag fällt raus.
- **No-Show** löst zur **`arrival`** auf (erst am Anreisetag ist das Nicht-Erscheinen
  bekannt): No-Show mit Anreise **nach** dem Stichtag zählt noch mit.
- **Stichtag** = `min(Ende Erstellungs-Fenster, Snapshot-Datum)`

**c) Doppelfilterung §8 „Stay × Creation":** Die Menge ist der Schnitt aus
**Aufenthalts-Fenster** (serviceDate) **und** **Erstellungs-Fenster** (created),
danach die As-of-Maske. Das Erstellungs-Fenster wird fürs Vorjahr per `mirror_years`
gespiegelt (gleicher Monat/Tag, ein Jahr früher).

> **Wichtige Konsequenz:** Weil der Stichtag = Ende des Erstellungs-Fensters ist,
> sind Erstellungs-Teilfenster **nicht additiv** – änderst du das Fensterende,
> verschiebt sich auch der Bewertungs-Zeitpunkt für Storno/No-Show.
"""
    )

# ============================================================================
with st.expander("8 · Channels (Buchungskanäle)"):
    st.markdown(
        """
`channel_combo` entsteht aus `channelCode` + `source` (`classify_channel`):

- `Ibe` → **Direct_Website** (= IBE, eigene Website)
- `Direct` → **Direct_Offline** (Direktbuchung offline)
- alles andere → OTA (z.B. `OTA.Booking.com`, `OTA.Expedia`, `OTA.HRS` …)

`channel_group` fasst zu **Direct / OTA / Other** zusammen. Für die Anzeige gibt es
lesbare Labels (z.B. `OTA.Booking.com` → „Booking.com", `Direct_Website` → „IBE").
"""
    )

# ============================================================================
with st.expander("9 · B2B / Firmen: Codes, Company-Walk, Fuzzy & Promo-Overrides"):
    st.markdown(
        """
**Vertragscode** (`effective_code`): bevorzugt `company_code` (harter apaleo-Link),
sonst `corporateCode` (OTA-/Firmen-Code). So werden beide Felder erfasst – wer nur
`company_code` betrachtet, unterzählt B2B deutlich.

**Firmenname** (`company`): Priority-Walk
`company_name → booker_company_name → primaryGuest_company_name → effective_code`.

**Vier Firmen-Definitionen** (für Vergleich nebeneinander):

| Spalte | Bedeutung |
|---|---|
| `firm_by_code` | nur Vertragscode (hart) |
| `firm_by_effective` | Priority-Walk (s.o.) |
| `firm_by_effective_fuzzy` | + Fuzzy-Clustering ähnlicher Schreibweisen (rapidfuzz, Schwelle 85) |
| `firm_by_business_purpose` | `firm_by_effective`, gefiltert auf `travelPurpose == Business` |

**Promo-Code-Overrides** (`overrides.py` + `configs/code_overrides.json`): Manche
Marketing-Promocodes sind eigentlich Firmencodes. Im Store hinterlegte Codes werden
beim Laden als Vertragsbuchung **reklassifiziert** (füllt `corporateCode`/`effective_code`/
`firm_by_*`, Marker `is_reclassified_promo`). Änderungen am Store invalidieren den Cache automatisch.
Zusatzinfo: company_code ist momentan all NAs, aber an sich die stärkere Spalte falls sie in Zukunft
befüllt wird.
"""
    )

# ============================================================================
with st.expander("10 · Segmente & weitere abgeleitete Spalten"):
    st.markdown(
        """
| Spalte | Logik |
|---|---|
| `los_bucket` | Aufenthaltsdauer: **kurz ≤6**, **mittel 7–28**, **lang 29+** Nächte |
| `nights` | `departure − arrival` (ganze Nächte) |
| `group_size_bucket` | Zimmer je `bookingId`: single / 2 / 3–4 / 5+ |
| `lead_time_days` / `lead_time_bucket` | `arrival − created` (Vorlaufzeit) |
| `room_category` | bereinigte `unitGroup_name` |
| `is_flex` / `is_corporate_rate` | aus `ratePlan_name` (flex / firmen·corporate·business·hrs) |
| `stay_weekday` / `check_in_weekday` | Wochentag der Nacht / der Anreise |
| `origin` / `is_international` | Herkunft (siehe Kap. 11) |
"""
    )

# ============================================================================
with st.expander("11 · Bekannte Datenqualitäts-Themen"):
    st.markdown(
        """
- **„country_code"-Bug → leere Länder-Tabellen:** Die DE-vs-International- und
  Top-Länder-**Tabellen** suchen eine Spalte `country_code`, die Spalte heißt aber
  **`origin`**. Folge: diese beiden Tabellen bleiben **leer**. (Die Charts nutzen
  korrekt `is_international`/`origin`.) → offener Fix.
- **`cancel_time` bei Nicht-Stornierten:** ist mit `modified` vorbelegt; nur bei
  `is_cancelled = WAHR` als Stornodatum interpretieren. Die Filter selbst sind davon
  nicht betroffen (sie prüfen `cancel_time` nur, wenn `is_cancelled`).
- **`travelPurpose`:** fehlender/leerer Wert zählt als **Privat** – kann den
  Privat-Anteil überzeichnen. Außerdem ist der Reisezweck oft erst **nach Check-in**
  verlässlich, also bei jungen Buchungstagen mit Vorsicht lesen.
- **Services fehlen in den Timeslices** (Kap. 3/4) – Brutto-Abgleiche scheitern sonst.
- **Snapshot-Lookback:** Perioden vor `timeslices.earliest` sind leer → es erscheint
  die Warnung „Periode reicht vor den verfügbaren Datenbestand zurück".
- **Späte Öffner:** Standorte, die im Vorjahres-Zeitraum noch nicht offen waren,
  zeigen dort 0 € (eigene Warnung).
"""
    )

# ============================================================================
with st.expander("12 · Plan-Vergleich, Caching & Snapshot"):
    st.markdown(
        """
**Plan:** `plan.parquet` (aus `ref_tables.plan`) liefert Monats-Planzahlen je
Standort. `plan_revenue()` rechnet pro-rata auf die Periode. **PLAN gibt es nur in
den Aufenthalts-Sichten** (z.B. §4 / Standort-KPIs), nicht in den Erstellungs-/§8-Sichten
(Plan ist monatlich aufs Aufenthaltsdatum bezogen).

**Caching:** Tabellen/Charts sind mit `st.cache_data` gecacht. Chart-PNG-Cache-Keys
enthalten u.a. Snapshot-Stand, Standorte, Perioden **und den Storno/No-Show-Toggle** –
damit beim Umschalten nichts „hängen bleibt". Der Override-Store invalidiert den Cache
über seine Signatur (Dateizeit + Größe).

**Snapshot aktualisieren:** über die Seite *Daten aktualisieren* (oder
`scripts/refresh_snapshot.py`). Erst danach sind neue BigQuery-Daten im Dashboard.
"""
    )

# ============================================================================
with st.expander("13 · Spalten-Glossar (Kurzreferenz)"):
    st.markdown(
        """
| Spalte | Bedeutung |
|---|---|
| `id` | Reservierungs-ID (eindeutig je Buchungs-Leg) |
| `bookingId` | Buchungs-ID (kann mehrere `id` umfassen = Gruppe) |
| `serviceDate` / `stay_date` | Tag der Übernachtung |
| `created` | Erstellzeitpunkt der Buchung (Europe/Berlin) |
| `arrival` / `departure` | An-/Abreise |
| `cancel_time` | Storno-Zeit (nur valide bei `is_cancelled`) |
| `revenue` | **Nacht-Netto** (`baseAmount_netAmount`), ohne Services |
| `revenue_gross` | Nacht-Brutto (`baseAmount_grossAmount`) ≈ `revenue × 1,07` |
| `is_realized / is_cancelled / is_no_show` | Status-Flags |
| `channel_combo / channel_group` | Buchungskanal / Gruppe (Direct/OTA) |
| `origin / is_international` | Herkunftsland / international? |
| `los_bucket` | Aufenthaltsdauer-Segment |
| `lead_time_days / _bucket` | Vorlaufzeit |
| `effective_code / company / firm_by_*` | B2B-Vertragscode / Firma / Firmendefinitionen |
| `travelPurpose` | Business vs. Privat (fehlend → Privat) |
| `kept_revenue / lost_revenue` | bei Storno/No-Show behaltene Fee vs. Verlust |
"""
    )

st.divider()
st.caption(
    "Stand: generiert aus dem aktuellen Code. Bei Logik-Änderungen (Filter, Spalten, "
    "Engineering) diese Seite mit aktualisieren."
)
