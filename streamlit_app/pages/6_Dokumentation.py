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

> **Dashboard = Übernachtung, Netto.** Services und Brutto musst du bewusst
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

**§8 Schritt für Schritt (`stay_created_scope`):**

1. **Stay-Filter:** `serviceDate` ∈ [Stay-Start, Stay-Ende] (Sidebar).
2. **Creation-Filter:** `created` ∈ [Erstellung-von, Erstellung-bis]; fürs Vorjahr per
   `mirror_years` gespiegelt (gleicher Monat/Tag, 1 Jahr früher).
3. **As-of-Maske:** `created ≤ Stichtag` UND (nicht storniert ODER `cancel_time > Stichtag`)
   UND (kein No-Show ODER `arrival > Stichtag`). Stichtag = `min(Erstellung-bis, Snapshot)`,
   fürs Vorjahr gespiegelt.

**Rechenbeispiel (NEW):** Stay = Juli 2026, Erstellung 01.–10.06.2026, Snapshot 23.06.2026
→ Stichtag = min(10.06., 23.06.) = **10.06.2026**.

- Buchung gebucht 03.06., Anreise 14.07., **nicht** storniert → zählt (created ≤ 10.06., lebt).
- Storno am **07.07.** (nach Stichtag) → zählt trotzdem (am 10.06. war sie noch aktiv).
- Storno am **05.06.** (vor Stichtag) → fällt raus (realized); erscheint nur mit Toggle „an".
- No-Show, Anreise 20.07. (> Stichtag) → zählt (am 10.06. noch nicht als No-Show bekannt).

> Genau diese Nicht-Additivität ist die Ursache, dass „01.01.–30.05." + „01.06.–30.06."
> ≠ „01.01.–30.06." ergibt: jedes Fenster hat einen **anderen Stichtag**.
"""
    )

# ============================================================================
with st.expander("8 · Channels (Buchungskanäle)"):
    st.markdown(
        """
`channel_combo` entsteht aus `channelCode` + `source` (`classify_channel`). **Exakte Regel:**

1. Ist `channelCode` ∈ **CHANNEL_COMBO_MAP** → fester Wert:
   - `Ibe` → **`Direct_Website`** (= IBE, eigene Website / Booking-Engine)
   - `Direct` → **`Direct_Offline`** (Direktbuchung offline, z.B. Telefon/Mail/Walk-in)
2. Sonst → **`OTA_<source>`** (die `source` angehängt), z.B. `OTA_Booking.com`,
   `OTA_Airbnb`, `OTA_HRS`, `OTA_Expedia`, `OTA_Synxis`, `OTA_GDS`,
   `OTA_CRC Corporate Rates Club`, …; fehlt die `source`, dann `OTA_<channelCode oder 'Other'>`.

> Hinweis: Das Präfix ist **`OTA_`** (Unterstrich), nicht `OTA.` – relevant beim Filtern in Roh-Exports.

`channel_group` fasst zusammen: beginnt `channel_combo` mit `Direct` → **Direct**,
mit `OTA` → **OTA**, sonst **Other**. Aktueller Snapshot grob: ~Direct 53 % / OTA 47 %;
größte Einzelkanäle: Booking.com, Direct_Offline, Direct_Website (IBE), Airbnb, HRS, Expedia.

Für die **Anzeige** mappt `_channel_label` (in `global_tables.py`) die internen Combos auf
lesbare Labels (z.B. `Direct_Website` → „IBE", `Direct_Offline` → „Direct",
`OTA_Booking.com` → „Booking.com").
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

**Fuzzy-Clustering im Detail (`cluster_companies`, rapidfuzz):** Freitext-Firmennamen
werden zu einem kanonischen Namen zusammengeführt, damit Schreibvarianten nicht als
verschiedene Firmen zählen.

1. **Normalisieren:** klein, Akzente/Sonderzeichen weg, Rechtsformen entfernt (`GmbH`,
   `AG`, `GmbH & Co. KG`, `Ltd`, `Inc`, `SE`, …) und Segment-/Region-Suffixe
   (`… Segment X`, `… Region Y`, `… - …`) abgeschnitten.
2. **Blocking:** Kandidaten werden nach Token-Präfix (erste 3 Zeichen) gruppiert –
   nur innerhalb eines Blocks wird verglichen (Performance).
3. **Ähnlichkeit:** `token_sort_ratio` ≥ **85** (Default-Schwelle) → gilt als „gleich".
4. **Union-Find** bündelt Treffer zu Clustern; ein **Anti-Chaining**-Schritt wirft
   transitiv „durchgereichte" Mitglieder wieder raus (A~B, B~C, aber A≁C).
5. **Repräsentant** je Cluster = die **häufigste** Schreibvariante.

Ist `rapidfuzz` nicht installiert, fällt die Funktion auf **Identität** zurück (keine
Cluster) – mit Warnung. Das Clustering läuft **einmal beim Refresh** und wird per `id`
auf die Nächte gebroadcastet.
"""
    )

# ============================================================================
with st.expander("10 · Segmente & weitere abgeleitete Spalten"):
    st.markdown(
        """
**Exakte Schwellen (aus `helpers.py`):**

`los_bucket` (`LOS_BINS = [-0.1, 6, 28, ∞]`):

| Label | Nächte |
|---|---|
| `short_<=6` | 1–6 |
| `mid_7-28` | 7–28 |
| `long_29+` | 29+ |

`group_size_bucket` (`GROUP_BINS = [0, 1, 2, 4, ∞]`, Zimmer/`id` je `bookingId`):
`single` (1) · `2_rooms` (2) · `3-4_rooms` (3–4) · `5+_rooms` (5+).

`lead_time_bucket` (`arrival − created`, `LEAD_BINS`):
`same_day` (0) · `1-3 T` · `4-7 T` · `8-10 T` · `11-13 T` · `14-16 T` · `17-19 T` ·
`20-22 T` · `23-25 T` · `26-28 T` · `29+ T`.

Storno-Timing (`cancel_lead_time_days`) nutzt **dasselbe Raster**, zusätzlich
`nach Anreise` (Storno nach Check-in) und `Anreisetag`.

**Weitere abgeleitete Spalten:**

| Spalte | Logik |
|---|---|
| `nights` | `departure − arrival` (ganze Nächte, Mitternacht-normalisiert) |
| `room_category` | bereinigte `unitGroup_name` (z.B. `BIE_HB`: „ AIRCON" entfernt) |
| `is_flex` | `ratePlan_name` enthält „flex" |
| `is_corporate_rate` | `ratePlan_name` enthält „firmen/corporate/business/hrs" |
| `has_promo` | `promoCode` nicht leer |
| `stay_weekday` / `check_in_weekday` | Wochentag der Nacht / der Anreise |
| `adr_per_night` | `revenue / nights` (nur Reservations-Frame) |
| `origin` / `is_international` | Herkunft (eigene Logik, siehe Kap. 10b) |
"""
    )

# ============================================================================
with st.expander(" 10b · Herkunft: Inland/Ausland & Top-Länder (Fallback-Logik – WICHTIG)"):
    st.markdown(
        """
Das ist eines der **am leichtesten misszuverstehenden** Felder. Es gibt hier **zwei**
getrennte Themen: (A) die **fachliche Herleitung** der Herkunft (Fallback-Kette) und
(B) ein **technischer Bug** in den zugehörigen Daten-Tabellen.

#### A) Wie `origin` / `is_international` entsteht (`_add_origin`)

```
origin = primaryGuest_address_countryCode
         └─ wenn leer ──► Fallback: primaryGuest_preferredLanguage (groß)
is_international = (origin bekannt) UND (origin ≠ "DE")
```

Im Klartext:

- Liegt ein **Gast-Ländercode** (`primaryGuest_address_countryCode`) vor, wird der genutzt.
- Fehlt er, fällt die Logik auf die **bevorzugte Sprache**
  (`primaryGuest_preferredLanguage`) zurück und behandelt sie wie eine Herkunft.
- `is_international` ist **WAHR**, wenn die Herkunft bekannt **und ungleich `DE`** ist.

**Das hat mehrere Konsequenzen, die man kennen sollte:**

1. **`origin` ist ein Misch-Feld aus Länder- UND Sprachcodes.** In „Top-Herkunftsländer"
   steht dann z.B. `FR` (Land) neben `EN` (Sprache) – nicht sauber vergleichbar.
2. **Sprache ≠ Land.** Ein englischsprachiger Gast aus Deutschland (ohne Ländercode,
   Sprache `EN`) wird als **international** gezählt; ein deutschsprachiger Gast aus
   Österreich/Schweiz (Sprache `DE`) als **Inland**. Die Quote ist also eine sehr ungenaue
   Näherung, keine exakte Nationalität.
3. **Datenverfügbarkeit hängt stark vom Channel ab.** OTAs geben die Gast-Adresse /
   den Ländercode oft **nicht** durch → dort greift fast immer der Sprach-Fallback oder
   die Herkunft bleibt unbekannt. Direkt/IBE erfasst andere Felder – und **was IBE
   erfasst, hat sich über die Zeit geändert**. Dadurch ist ein Anstieg/Rückgang der
   International-Quote über die Zeit oder zwischen Channels oft ein **Daten-Artefakt**
   (anderes Erfassungsverhalten), nicht zwingend echtes Gästeverhalten.
4. **Fallback-Spalte nicht immer vorhanden.** `primaryGuest_preferredLanguage` wird
   defensiv per `df.get(...)` geholt – fehlt sie (ältere Snapshots/Quellen), gibt es
   gar keinen Fallback und die Herkunft bleibt unbekannt.
5. **Unbekannte Herkunft zählt als „Inland".** `is_international` ist bei leerer/unbekannter
   Herkunft **FALSE** – diese Buchungen landen also im **DE-/Inland**-Balken, nicht in einem
   eigenen „unbekannt"-Topf. Fehlende Daten verschieben die Quote damit systematisch
   Richtung Inland.

> **Lesehilfe:** International-Quote als **Tendenz** lesen, nicht als exakte Herkunft.
> Vergleiche über Zeit oder zwischen Channels (v.a. IBE) mit Vorsicht – sie spiegeln
> teils nur, wie vollständig Länder-/Sprachdaten erfasst wurden.

"""
    )

# ============================================================================
with st.expander("11 · Bekannte Datenqualitäts-Themen"):
    st.markdown(
        """
- **Herkunft/International (Kap. 10b):** Sprach-Fallback, Misch-Feld Land+Sprache,
  channel-/zeitabhängige Erfassung (v.a. IBE), unbekannt→Inland. Quote als Tendenz lesen.
- **„country_code"-Bug:** die **Daten-Tabellen** hinter §11/§12 suchen die nicht
  existierende Spalte `country_code` (richtig wäre `origin`) → diese Tabellen bleiben
  **leer**; die Charts funktionieren. Offener, rein technischer Fix.
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
**Plan (`plan_revenue`, pro-rata):** `plan.parquet` (aus `ref_tables.plan`) liefert
**Monats**-Planzahlen je Standort (`{property_code: {"YYYY-MM": EUR}}`). Für eine
beliebige Periode wird je Monat anteilig gerechnet:

```
Plan(Periode) = Σ_Monat  Monatsplan × (überlappende Tage im Monat / Tage des Monats)
```

Beispiel: Periode 15.07.–31.07. → 17/31 des Juli-Plans. **PLAN gibt es nur in den
Aufenthalts-Sichten** (Standort-KPIs, §4 Global), **nicht** in Erstellungs-/§8-Sichten
(Plan ist monatlich aufs Aufenthaltsdatum bezogen, passt nicht auf einen created-Teilausschnitt).

**Promo→Firmencode-Overrides (`apply_code_overrides`):** Für jede Buchung, deren
`promoCode` im Store (`code_overrides.json`) steht, werden – nur wo noch leer –
`corporateCode`, `effective_code`, `firm_by_code` mit dem Code gefüllt, `has_code=True`
gesetzt und (falls ein Firmenname hinterlegt ist) `company`/`firm_by_effective`/
`firm_by_effective_fuzzy` ergänzt; Marker `is_reclassified_promo=True`. Idempotent,
nur vorhandene Spalten werden angefasst. Speicherort: env `STAYERY_OVERRIDES_FILE` →
Snapshot-Ordner → `data/` → `configs/`.

**Caching:** Tabellen/Charts mit `st.cache_data` (TTL 1 h). Chart-PNG-Cache-Keys
enthalten Snapshot-Stand, Standorte, Perioden **und den Storno/No-Show-Toggle** – damit
beim Umschalten nichts „hängen bleibt". Der Override-Store invalidiert den Cache über
seine Signatur (Dateizeit + Größe). Lazy-Sections (Standort 6–17, Global 4–7) rendern
erst auf Klick; Sidebar-Buttons „Alle laden" / „Cache leeren".

**Snapshot aktualisieren:** über die Seite *Daten aktualisieren* (oder
`scripts/refresh_snapshot.py`). Erst danach sind neue BigQuery-Daten im Dashboard.
"""
    )

# ============================================================================
with st.expander("12b · Seiten & Sektionen im Detail"):
    st.markdown(
        """
**Standort-Analyse (Einzelstandort, YoY)** – 17 Sektionen. Datumsbasis je Sektion:

| # | Sektion | Basis |
|---|---|---|
| 1 | Landscape KPIs (Revenue, ADR, Occupancy, ALOS) + Monatstrend | Aufenthalt |
| 2 | Pace by Month (OTB-Rekonstruktion zum Stichtag) | Aufenthalt (eigene As-of-Logik) |
| 3 | Heatmap Channel × LOS | Aufenthalt |
| 4 | Heatmap Channel × Reisezweck × LOS | Aufenthalt |
| 5 | LOS-Revenue YoY | Aufenthalt |
| 6 | Channel-Mix monatlich & YoY | Aufenthalt |
| 7 | ALOS pro Channel | Aufenthalt |
| 8 / 9 | Wochentag (Stay) / (Anreise) | Aufenthalt |
| 10 | Gruppen-Größe | **Erstellung** |
| 11 | Inland vs. Ausland | Aufenthalt (Herkunft, Kap. 10b) |
| 12 | Top-Herkunftsländer | Aufenthalt (Herkunft, Kap. 10b) |
| 13 | Vorlaufzeit & Storno-Risiko | **Erstellung** (eigene Storno-Logik) |
| 14 | Daily Occupancy nach LOS | Aufenthalt |
| 15 | Firmenkunden | **Erstellung** |
| 16 | Direct Offline | **Erstellung** |
| 17 | Top Vertragscodes | **Erstellung** |

**Global Report (Portfolio)** – 8 Sektionen:

| # | Sektion | Basis |
|---|---|---|
| 1 | Visual Scorecard (IST vs PLAN je Standort) | Aufenthalt + PLAN |
| 2 | Pace by Month | Aufenthalt (As-of) |
| 3.A/3.B | Performance / Channels **nach Erstellung** | **Erstellung** |
| 4.A/4.B | Performance / Channels **nach Aufenthalt** (mit PLAN) | Aufenthalt |
| 5 | IST vs PLAN · Pace-Fortschritt | Aufenthalt |
| 6 | Channel-Mix Detail | Aufenthalt |
| 7.A–7.D | Heatmaps (Standort×Monat, Channel×Standort, Top-Movers, Channel×LOS) | Aufenthalt |
| 8 | **Stay × Creation (As-of)** + Download | Doppelfilter (Kap. 7) |

**Weitere Seiten:** *Daten aktualisieren* (BigQuery-Refresh), *B2B Deep-Dive*
(company_code / corporateCode / fuzzy-Firmen + Excel), *Code Deep-Dive* (eine Firma 360°),
*Promo-Codes* (Promo→Firmencode-Reklassifizierung), *Plan-Upload*.

**Querschnitt:** Der Sidebar-Toggle „Storno + No-Show einbeziehen" wirkt in allen
„normalen" Sektionen (Default realized-only). Eigene Logik behalten: Pace (§2 beide
Seiten), Storno-Risiko (Standort §13) und die As-of-Sicht (Global §8).
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
    "Stand: 30.06.2026 Bei Logik-Änderungen (Filter, Spalten, "
    "Engineering) diese Seite mit aktualisieren."
)
