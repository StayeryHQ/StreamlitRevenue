# dash_app/pages/doku.py
# Dokumentation - data basis, revenue logic, filters, channels and B2B, ported
# from the 7_Dokumentation page into a dmc.Accordion (one dcc.Markdown
# per chapter). Content is verbatim except: framework-specific phrasing is fixed
# ("Sidebar" -> "Filterleiste"), the caching chapter now describes the lru_cache
# snapshot layer in dash_app/backend/data.py, and page/section references follow
# the current tabbed-hub structure (Revenue / Sales hubs; the B2B page holds the
# former Standort sections 11-13). IDs: doku-. One file.

from __future__ import annotations

import dash
import dash_mantine_components as dmc
from dash import dcc

dash.register_page(__name__, path="/doku", name="Doku", order=8,
                   title="STAYERY · Doku")


# (value, title, markdown) - each markdown renders verbatim inside an accordion panel.
_CHAPTERS = [
    ("c1", "1 · Überblick, Zugriff & Tech-Stack", """
**Was ist das?** Ein Dash-Dashboard für den Revenue-Recap
(Global-Report, Pickup/Vorlauf-Analyse, Standort-Analyse, B2B-, Code- und Promo-Deepdives).

**Zugriff / Code:** Der Quellcode liegt im GitHub-Repo **`StreamlitRevenue`**.
Sprache ist **Python (3.12)**. Wichtigste Bausteine:

| Bereich | Modul / Ordner | Zweck |
|---|---|---|
| Kern-Logik | `src/revenueblindspots/helpers.py` | Feature-Engineering, Filter, Revenue-Logik |
| Daten-Refresh | `src/revenueblindspots/refresh.py` | BigQuery-Pull → Snapshot |
| Promo-Overrides | `src/revenueblindspots/overrides.py` | Promo-Codes als Firmencodes reklassifizieren |
| Seiten & Views | `dash_app/pages/` + `dash_app/views/` | Nav-Seiten (Home, Revenue-Hub, Sales-Hub, Daten, Doku) + die Revenue-Views |
| Backend | `dash_app/backend/` | Snapshot-Cache (`data.py`), Job-Runner (`jobs.py`), Tabellen- & Chart-Daten |
| Komponenten | `dash_app/components/` | UI-Bausteine (`ui.py`), Plotly-Charts, Tooltips |
| Konfiguration | `configs/` | `locations.yaml` (Hotels), `code_overrides.json` |
| Daten-Snapshot | `data/` | `*.parquet` + `metadata.json` |

**Bibliotheken:** Dash + dash-mantine-components (UI), pandas/numpy (Daten), Plotly (Charts),
pyarrow (Parquet), openpyxl (Excel), rapidfuzz (Firmen-Fuzzy-Matching),
google-cloud-bigquery (nur beim Refresh).

Das Dashboard rechnet **nicht** live auf BigQuery, sondern auf
einem **Snapshot** (lokale Parquet-Dateien). Nur die Seite *Daten aktualisieren*
spricht mit BigQuery.
"""),

    ("c2", "2 · Datenfluss: von BigQuery zum Dashboard", """
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
"""),

    ("c3", "3 · Die zwei Quell-Tabellen (wichtig: unterschiedlicher Grain & Revenue)", """
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
"""),

    ("c4", "4 · Revenue-Grundprinzip: Netto vs. Brutto, mit/ohne Services", """
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
"""),

    ("c5", "5 · Datum & Zeitzone: Aufenthalt vs. Erstellung", """
Drei Datums-Achsen:

- **Aufenthalt** = `stay_date` / `serviceDate` (der Tag der Übernachtung). Basis der
  „nach Aufenthalt"-Sichten (KPIs, Occupancy, Pace, Channels …).
- **Erstellung** = `created` (wann gebucht wurde). Basis der „nach Erstellungsdatum"-Sichten
  (Sales/Pickup, Gruppen-Größe, Lead-Time, Firmen, Pickup-Analyse).
- **Anreise** = `arrival`. U.a. Auflösungs-Zeitpunkt für No-Shows (siehe Kap. 7).

**Zeitzone:** Alle Zeitstempel werden nach **Europe/Berlin** normalisiert (inkl.
`created` – früher war `created` ein UTC-Sonderfall, das ist behoben). `serviceDate`
ist ein reines Datum. Dadurch fällt eine abends gebuchte Reservierung nicht mehr in
einen anderen Kalendertag als der Rest der Spalten.
Es gibt auch noch zusätzlich CancellationDateTime und Abreise natürlich. Für no-shows wird
als „no-show" Datum das Anreisedatum genutzt.
"""),

    ("c6", "6 · Status, Storno & No-Show", """
Der apaleo-`status` wird in drei Flags übersetzt:

- `is_realized` = Status ∈ {Confirmed, InHouse, CheckedOut}
- `is_cancelled` = Status == Canceled
- `is_no_show` = Status == NoShow

**`realized_only`** (Default in fast allen Sichten) = nur `is_realized`, also
**Storno + No-Show raus**. Der Schalter in der Filterleiste **„Storno + No-Show einbeziehen"**
schaltet auf „alle Buchungen".

Weitere Storno-Spalten (auf Buchungs-Ebene):
- `cancel_time` = `cancellationTime`, Fallback `modified`. **Stolperfalle:** bei
  *nicht* stornierten Buchungen ist `cancel_time` mit `modified` gefüllt – als echtes
  Stornodatum nur lesen, wenn `is_cancelled` = WAHR (siehe Kap. 11).
- `kept_revenue` / `lost_revenue` = bei Storno/No-Show die einbehaltene Fee
  (gedeckelt aufs Buchungs-Netto) vs. der verlorene Rest.
"""),

    ("c7", "7 · Filter-Logik: realized-only, As-of (point-in-time) & Doppelfilterung (Pickup)", """
**a) Der Storno/No-Show-Schalter greift in fast allen Charts/Tabellen** der Revenue-Views
(Standort + Global). Default = realized-only; eingeschaltet = alle Buchungen.
**Ausnahmen mit eigener Logik:** die **Pace-by-Month**-Sicht (point-in-time-
Rekonstruktion, No-Shows immer raus) und die **Storno-Risiko/Vorlaufzeit**-Sektion
(braucht Stornos, um die Storno-Quote zu zeigen).

**b) As-of / point-in-time (Pickup-Analyse):** Hier wird gefragt *„War die Buchung am
Stichtag schon storniert / als No-Show aufgelöst?"* – nicht der heutige Endstatus.

- **Storno** löst zum `cancel_time` auf: ein Storno **nach** dem Stichtag zählt am
  Stichtag noch mit; ein Storno **am/vor** dem Stichtag fällt raus.
- **No-Show** löst zur **`arrival`** auf (erst am Anreisetag ist das Nicht-Erscheinen
  bekannt): No-Show mit Anreise **nach** dem Stichtag zählt noch mit.
- **Stichtag** = auf der Pickup-Seite **frei wählbar** (Default = Snapshot); fürs
  Vorjahr um ganze Jahre gespiegelt. Zähler (Erstellt) und Nenner (OTB) nutzen
  **denselben** Stichtag → Pickup-Anteil ≤ 100 %.
- **Storno-Modus 3-fach:** *All in* (alle), *All out* (nur realisierte, finaler
  Status) und *As-of* (die obige point-in-time-Logik). Für vergangene Monate
  fallen As-of und All out zusammen.

**c) Doppelfilterung „Stay × Creation" (Pickup-Analyse):** Die Menge ist der Schnitt
aus **Aufenthalts-Fenster** (serviceDate) **und** **Erstellungs-Fenster** (created),
danach die As-of-Maske. Das Erstellungs-Fenster wird fürs Vorjahr per `mirror_years`
gespiegelt (gleicher Monat/Tag, ein Jahr früher). Creation-Fenster-Modi: *festes
Fenster* (von–bis) oder *alles bis Stichtag*.

> **Hinweis:** Der frühere Global-§8-Stichtag war `min(Ende Erstellungs-Fenster,
> Snapshot)`. Auf der Pickup-Seite ist der Stichtag ein eigener Filter, damit der
> OTB-Nenner sauber definiert ist und der Pickup-Anteil ≤ 100 % bleibt.

**Schritt für Schritt (`stay_created_scope`, Pickup-Analyse):**

1. **Stay-Filter:** `serviceDate` ∈ [Stay-Start, Stay-Ende] (Filterleiste).
2. **Creation-Filter:** `created` ∈ [Erstellung-von, Erstellung-bis]; fürs Vorjahr per
   `mirror_years` gespiegelt (gleicher Monat/Tag, 1 Jahr früher).
3. **As-of-Maske:** `created ≤ Stichtag` UND (nicht storniert ODER `cancel_time > Stichtag`)
   UND (kein No-Show ODER `arrival > Stichtag`). Stichtag = `min(Erstellung-bis, Snapshot)`,
   fürs Vorjahr gespiegelt.

**Rechenbeispiel (NEW):** Stay = Juli 2026, Erstellung 01.–10.06.2026, Snapshot 23.06.2026
→ Stichtag = min(10.06., 23.06.) = **10.06.2026**.

- Buchung gebucht 03.06., Anreise 14.07., **nicht** storniert → zählt (created ≤ 10.06., lebt).
- Storno am **07.07.** (nach Stichtag) → zählt trotzdem (am 10.06. war sie noch aktiv).
- Storno am **05.06.** (vor Stichtag) → fällt raus (realized); erscheint nur mit Schalter „an".
- No-Show, Anreise 20.07. (> Stichtag) → zählt (am 10.06. noch nicht als No-Show bekannt).

> Genau diese Nicht-Additivität ist die Ursache, dass „01.01.–30.05." + „01.06.–30.06."
> ≠ „01.01.–30.06." ergibt: jedes Fenster hat einen **anderen Stichtag**.
"""),

    ("c8", "8 · Channels (Buchungskanäle)", """
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
"""),

    ("c9", "9 · B2B / Firmen: Codes, Company-Walk, Fuzzy & Promo-Overrides", """
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
"""),

    ("c10", "10 · Segmente & weitere abgeleitete Spalten", """
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
"""),

    ("c10b", "10b · Herkunft: Inland/Ausland & Top-Länder (Fallback-Logik – WICHTIG)", """
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
"""),

    ("c11", "11 · Bekannte Datenqualitäts-Themen", """
- **Herkunft/International (Kap. 10b):** Sprach-Fallback, Misch-Feld Land+Sprache,
  channel-/zeitabhängige Erfassung (v.a. IBE), unbekannt→Inland. Quote als Tendenz lesen.
- **„country_code"-Bug:** die **Daten-Tabellen** hinter den Herkunfts-Sektionen suchen die
  nicht existierende Spalte `country_code` (richtig wäre `origin`) → diese Tabellen bleiben
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
"""),

    ("c12", "12 · Plan-Vergleich, Caching & Snapshot", """
**Plan (`plan_revenue`, pro-rata):** `plan.parquet` (aus `ref_tables.plan`) liefert
**Monats**-Planzahlen je Standort (`{property_code: {"YYYY-MM": EUR}}`). Für eine
beliebige Periode wird je Monat anteilig gerechnet:

```
Plan(Periode) = Σ_Monat  Monatsplan × (überlappende Tage im Monat / Tage des Monats)
```

Beispiel: Periode 15.07.–31.07. → 17/31 des Juli-Plans. **PLAN gibt es nur in den
Aufenthalts-Sichten** (Standort-KPIs, §4 Global), **nicht** in Erstellungs-/Pickup-Sichten
(Plan ist monatlich aufs Aufenthaltsdatum bezogen, passt nicht auf einen created-Teilausschnitt).

**Promo→Firmencode-Overrides (`apply_code_overrides`):** Für jede Buchung, deren
`promoCode` im Store (`code_overrides.json`) steht, werden – nur wo noch leer –
`corporateCode`, `effective_code`, `firm_by_code` mit dem Code gefüllt, `has_code=True`
gesetzt und (falls ein Firmenname hinterlegt ist) `company`/`firm_by_effective`/
`firm_by_effective_fuzzy` ergänzt; Marker `is_reclassified_promo=True`. Idempotent,
nur vorhandene Spalten werden angefasst. Speicherort: env `STAYERY_OVERRIDES_FILE` →
Snapshot-Ordner → `data/` → `configs/`.

**Caching:** Der Snapshot-Cache liegt in `dash_app/backend/data.py`. `@lru_cache`-Loader
halten Reservations-, Timeslices-, Plan- und Metadata-Frames im RAM, gekeyed auf eine
**Snapshot-Signatur** (Pfad + mtime der Parquets) und die **Override-Signatur**; das
Filtern nach Zeitraum/Standort passiert danach in-memory mit `.copy()`. Nach einem
Refresh-Job leert `data.clear_caches()` alle Frames **einmal** und ein `*-version`
`dcc.Store` wird hochgezählt, sodass jede Seite sofort den neuen Snapshot liest. Der
Override-Store invalidiert den Cache über seine Signatur (Dateizeit + Größe). Die Filter
wirken **direkt** – es gibt keinen „Übernehmen"-Button mehr; die Sektionen sind in
thematische Tabs gruppiert statt lazy per Klick nachzuladen.

**Snapshot aktualisieren:** über die Seite *Daten aktualisieren* (oder
`scripts/refresh_snapshot.py`). Erst danach sind neue BigQuery-Daten im Dashboard.
"""),

    ("c12b", "12b · Seiten & Sektionen im Detail", """
Die Analysen liegen in zwei getabbten **Hubs**: **Revenue** (Global Report · Pickup ·
Standort) und **Sales** (B2B · Code · Promo). Dazu die System-Seiten *Home*,
*Daten aktualisieren* und *Dokumentation*.

**Standort-Analyse (Einzelstandort, YoY)** – 10 Sektionen, je Sektion ein
Datumsbasis-Badge (Aufenthalt / Erstellung):

| # | Sektion | Basis |
|---|---|---|
| 1 | Landscape KPIs + Monatstrend | Aufenthalt |
| 2 | Channel-Mix monatlich & YoY | Aufenthalt |
| 3 | Heatmap Channel × LOS | Aufenthalt |
| 4 | Heatmap Channel × Reisezweck × LOS | Aufenthalt |
| 5 | LOS-Revenue YoY | Aufenthalt |
| 6 / 7 | Wochentag (Stay) / (Anreise) | Aufenthalt |
| 8 | Inland vs. Ausland (inkl. Unbekannt) | Aufenthalt |
| 9 | Top-Herkunftsländer | Aufenthalt |
| 10 | Gruppen-Größe | **Erstellung** |

Die früheren Standort-Sektionen **11 Firmenkunden**, **12 Direct Offline** und
**13 Top Vertragscodes** (alle nach Erstellung) leben jetzt auf der **B2B-Seite**
im Sales-Hub. (Pace by Month, ALOS je Channel, Vorlaufzeit/Storno und Daily Occupancy
sind hier entfernt – Pace lebt auf der Pickup-Seite §2; Vorlaufzeit/Storno und Daily
Occupancy ziehen ins Overbooking-Tool um.)

**Global Report (Portfolio)** – 6 Sektionen:

| # | Sektion | Basis |
|---|---|---|
| 1 | Visual Scorecard (IST vs PLAN je Standort) | Aufenthalt + PLAN |
| 2.A/2.B | Performance / Channels **nach Erstellung** | **Erstellung** |
| 3.A/3.B | Performance / Channels **nach Aufenthalt** (mit PLAN) | Aufenthalt |
| 4 | IST vs PLAN · Pace-Fortschritt → Verweis Pickup-Seite | - |
| 5 | Channel-Mix Detail | Aufenthalt |
| 6.A-6.D | Heatmaps (Standort×Monat, Channel×Standort, Top-Movers, Channel×LOS) | Aufenthalt |

**Pickup / Vorlauf-Analyse** – 7 Sektionen:

| # | Block | Inhalt |
|---|---|---|
| 1 | Headline | Pickup kumuliert NEW/OLD (+ Fenster) · OTB Δ heute · OTB gesamt |
| 2 | **Pace by Month** | EIGENE Einstellungen: aktuelles Jahr vs Vorjahr, Stichtag = Snapshot, Storno immer As-of; Standorte = Filterleiste (inkl. Späte-Öffner-Ausschluss). Grafik: EoM-final / Vorjahr-Stichtag / aktuell-Stichtag je Monat. Darunter **Stichtagsblick** auf den aktuellen Monat: eine Zeile = ein As-of-Stichtag (Tagesende); vergangene Zeilen ändern sich bei einem Refresh nicht mehr |
| 3 | Buchungskurve | kumulierter Pickup-Anteil je Erstellungs-Tag / Lead-Time |
| 4 | Kategorie-Balken | Pickup-Anteil je Standort/Kanal/Segment |
| 5 | Tabellen | Erstellt · OTB · Pickup-Anteil · Δ Pickup, je Kategorie |
| 6 | Pace-to-PLAN | OTB vs. Ziel + Zeit-Fortschritt |
| 7 | Downloads | Tabellen-Excel, Roh-Timeslices, Kurven-CSV |

**Stichtag-Konvention (überall):** Stichtag = ganzer Kalendertag, d.h.
Tagesende 24:00 Europe/Berlin. Am Stichtag erstellte Buchungen zählen mit;
ein Storno mit Zeitstempel am Stichtag zählt raus. Ein As-of-Tag ist erst
final, wenn der Snapshot nach diesem Tag gezogen wurde.

**Sales-Hub:** *B2B Deep-Dive* (Firmenkunden, Direct-Offline & Vertragscodes über die
Historie, fuzzy-geclustert, Excel-Export), *Code Deep-Dive* (eine Firma im 360°-Blick)
und *Promo-Codes* (Promo→Firmencode-Reklassifizierung).

**Querschnitt:** Der Filterleisten-Schalter „Storno + No-Show einbeziehen" wirkt in
allen „normalen" Sektionen (Default realized-only, binär). Eigene Logik:
Pace by Month (Pickup §2, immer As-of) und die As-of-/3-fach-Sicht der
übrigen Pickup-Blöcke. Der Späte-Öffner-Ausschluss (Toggle + Warnbanner)
existiert im Global Report UND in der Pickup-Analyse. Filter wirken direkt (kein
„Übernehmen"-Button); der frühere Notepad- und Markdown-Export ist entfernt – Tabellen
lassen sich weiterhin als CSV/Excel herunterladen.
"""),

    ("c13", "13 · Spalten-Glossar (Kurzreferenz)", """
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
"""),
]


def layout(**_kwargs):
    header = dmc.Stack([
        dmc.Group([
            dmc.Title("Dokumentation", order=3),
            dmc.Badge("Datenbasis & Logik", color="yellow", variant="light", radius="sm"),
        ], gap="sm", align="center"),
        dmc.Text("Woher die Daten kommen, welche Tabellen/Spalten genutzt werden und wie "
                 "die wichtigsten Logiken (Netto/Brutto, Storno/No-Show, Filter, Channels, "
                 "B2B) funktionieren. Die Kapitel sind aufklappbar.",
                 size="sm", c="dimmed", style={"maxWidth": "820px"}),
    ], gap=4, mb="xs")

    items = [
        dmc.AccordionItem([
            dmc.AccordionControl(title),
            dmc.AccordionPanel(dcc.Markdown(md, className="doku-markdown")),
        ], value=value)
        for value, title, md in _CHAPTERS
    ]

    return dmc.Stack([
        header,
        dmc.Accordion(items, multiple=True, value=["c1"], variant="separated",
                      radius="md", chevronPosition="left"),
        dmc.Text("Bei Logik-Änderungen (Filter, Spalten, Engineering) diese Seite "
                 "mit aktualisieren.", size="xs", c="dimmed", mt="sm"),
    ], gap="md")
