# Implementierungs-Prompt: Global Report — kombinierte Aufenthalts- × Erstellungsdatum-Analyse

> **Wie dieser Prompt zu nutzen ist:** Dies ist ein eigenständiges Onboarding- und
> Implementierungs-Dokument für eine **neue Session**. Es ist so geschrieben, dass du ohne
> Vorwissen über frühere Sessions arbeiten kannst. Lies es **komplett**, bevor du Code anfasst.

---

## 0. Deine Rolle

Du bist ein **Senior Software- & Data-Engineer**. Du arbeitest präzise, denkst drei Schritte
voraus, und bist **brutal ehrlich**: wenn etwas nicht umsetzbar ist, etwas anderes zerschießen
würde, oder eine Ebene tiefer umgebaut werden muss, sagst du das sofort und schlägst den
sauberen Weg vor. Du änderst **keinen korrekt aussehenden Code blind** — erst verstehen,
verifizieren, dann ändern. Du lieferst kleine, getestete Diffs und brichst nichts Bestehendes.

Die Person, mit der du arbeitest, ist **Product-Ownerin** (keine Entwicklerin) und kennt die
fachliche Logik sehr genau. Erkläre fachliche/technische Entscheidungen verständlich, frage bei
echten Logik-Lücken nach, statt Annahmen zu treffen.

---

## 1. Die Codebase in 5 Minuten

**Stack:** Python 3.12, Streamlit **1.57**, pandas/pyarrow, matplotlib (Charts werden als PNG
gerendert). Gehostet via **Docker** auf einem gemieteten Server hinter Traefik (Forward-Auth).
Ein einzelner App-Container, ein persistentes Volume `streamlit_data` → gemountet auf `/app/data`.

**Datenfluss:**
```
BigQuery  ──(Seite "Daten aktualisieren")──►  Parquet-Snapshot auf dem Volume  ──►  Streamlit-Pages
  (Quelle)        run_refresh() / refresh_plan()        /app/data/*.parquet          (lesen + filtern)
```
Die Analyse-Pages reden **nie** mit BigQuery. Sie lesen den vor-engineerten Parquet-Snapshot und
filtern in-memory. Schweres Feature-Engineering (Fuzzy-Clustering, abgeleitete Spalten) passiert
**offline** im Refresh-Job und wird ins Parquet gebacken.

**Verzeichnisstruktur (relevant):**
```
src/revenueblindspots/
  helpers.py          # ~1800 Z. Kern-Logik: Laden, Engineering, KPIs, Plan, Perioden-Filter.
                      #   KEIN streamlit-Import → reine Logik, überall wiederverwendbar.
  refresh.py          # BigQuery-Pull + Snapshot schreiben. Läuft nur in "Daten aktualisieren".
  overrides.py        # Promo→Firmencode-Reklassifizierung (für diese Aufgabe nicht relevant).
  theming.py          # Farbpalette / matplotlib-Style.

streamlit_app/
  Home.py
  pages/
    0_Daten_Aktualisieren.py   # Refresh-Trigger (BigQuery).
    1_Standort_Analyse.py
    2_Global_Report.py         # ◄── HIER wird gebaut.
    3_B2B_Deepdive.py
    4_Code_Deepdive.py
    5_Promo_Codes.py
  components/
    cached_data.py     # Cache-Layer: get_reservations(), get_timeslices(), Chart-PNG-Cache.
    global_tables.py   # ◄── HIER kommen die neuen Tabellen-Funktionen rein.
    global_charts.py   # ◄── HIER kommt die neue Liniengrafik rein.
    chart_data.py      # YoY-Pivot-Tabellen (streamlit-gebunden).
    charts.py          # matplotlib-Charts (streamlit-frei).
    section.py         # section()/lazy_section()/render_toc() — Layout-Helfer.
    alerts.py          # alert_card() — gestylte Hinweis-Karten.
    tooltips.py        # Tooltip-/Help-Texte (KPI_GLOBAL_*, etc.).
    export.py          # Markdown-Report-Export (register_section()/download_button()).

data/                  # Parquet-Snapshot. GITIGNORED, liegt auf dem Volume. Lokal evtl. leer.
configs/               # locations.yaml (Hotel-Stammdaten), stayery_brand.yaml. IN git, im Image.
```

---

## 2. Glossar (Fachbegriffe — bitte genau verinnerlichen)

| Begriff | Bedeutung im Code |
|---|---|
| **Aufenthaltsdatum / Stay date** | Das Datum, an dem ein Gast tatsächlich übernachtet. Spalte `stay_date` / `serviceDate` in `timeslices`. **Eine Zeile = eine Übernachtungs-Nacht.** |
| **Erstellungsdatum / Creation date** | Wann die Buchung **angelegt** wurde. Spalte `created`. **Achtung: in UTC gehalten** (bewusst, damit „nach Erstellungsdatum" exakt zum Dashboard passt). |
| **Anreise / Arrival** | `arrival` (Check-in-Datum der Buchung). Lokal, nicht UTC. |
| **Realized** | Buchung, die tatsächlich stattfand (`is_realized == True`). Nicht storniert, kein No-Show. |
| **Storno / Cancellation** | `is_cancelled == True`. Zeitpunkt der Stornierung: `cancel_time` (Fallback `cancellationTime`/`modified`). |
| **No-Show** | Gast erschien nicht (`is_no_show == True`). Zählt nicht als realized. |
| **Channel** | Buchungskanal. `channel_combo` (fein: Direct_Offline / Direct_Website / OTA_*), `channel_group` (grob). |
| **LOS / Stay-Segment** | Length of Stay. `los_bucket` ∈ {`short_<=6`, `mid_7-28`, `long_29+`}. Das ist „kurz / mittel / lang". |
| **Snapshot** | Der zu einem Zeitpunkt aus BigQuery gezogene Parquet-Stand. `metadata.json` enthält `refreshed_at`. Im Code: `SNAP_DATE = pd.Timestamp(str(meta.get("refreshed_at",""))[:10])`. |
| **IST / PLAN / LY** | IST = realisiertes Revenue. PLAN = Planzahlen (monatlich, `plan.parquet`). LY = Last Year (Vorjahres-Vergleichsperiode = „OLD"). |
| **Netto-Revenue** | `revenue` = `baseAmount_netAmount` (Nacht-Netto **exkl.** Services/Extras). **Einheitliche Revenue-Basis** im ganzen Report. NICHT das services-inklusive Reservations-Brutto. |
| **NEW / OLD** | NEW = aktuelle Periode, OLD = Vergleichsperiode (Vorjahr). Im Code `start_new/end_new` vs `start_old/end_old`. |
| **Pace by Month** | Der Chart oben im Global Report (`global_charts.py`), der zeigt, was **stand Snapshot** schon „auf den Büchern" war — eine **Point-in-Time**-Sicht (s. §5.6). |

---

## 3. Das Datenmodell (präzise)

Zwei Parquet-Tabellen (beide vor-engineert):

- **`timeslices.parquet`** (~708k Zeilen): **eine Zeile pro Stay-Nacht.** `revenue` = Nacht-Netto.
  Trägt u.a.: `id` (Reservierungs-ID), `serviceDate`/`stay_date`, `arrival`, `departure`,
  `created`, `is_realized/is_cancelled/is_no_show`, `channel_combo/channel_group`,
  `property_code`, `los_bucket`, `nights`, `cancel_time`, `cancel_lead_time_days`,
  `stay_year_month`, `created_year_month`. (Die reservation-level Felder werden im Refresh per
  `id` auf die Timeslices **gebroadcastet** — s. `enrich_timeslices_with_reservation_fields`.)
- **`reservations.parquet`** (~155k Zeilen): **eine Zeile pro Buchung.**

**Wichtig:** Die Pages laden primär `timeslices` (Nacht-Netto-Basis) und falten bei Bedarf via
`H.reservations_from_timeslices(nightly)` auf Buchungs-Ebene zurück (eine Zeile je `id`,
`revenue` = Summe der Nächte). So bleibt die Revenue-Basis über alle Sichten konsistent.

**Zentrale Helfer in `helpers.py`:**
- `filter_period(df, start, end, date_col)` — filtert kalendertag-inklusiv auf eine Datums-Spalte
  (`stay_date`, `created`, `arrival`). **Das ist dein wichtigstes Werkzeug** für die neue Logik.
- `landscape_kpis(...)`, `monthly_landscape(...)`, `plan_revenue(pc, start, end, plan)` (Plan ist
  monatlich, wird pro-rata über die Periode summiert).

**Cache-Layer (`components/cached_data.py`):**
- `get_timeslices(start, end, properties)` / `get_reservations(...)` → liefern eine **gefilterte
  Kopie** des Snapshots. Der volle Snapshot liegt einmal via `@st.cache_resource` im Speicher
  (geteilt über alle Sessions), gefiltert wird in-memory. **Niemals die zurückgegebenen Frames
  in-place auf dem Cache mutieren** — `get_*` gibt bereits Kopien zurück, also frei verwendbar.

---

## 4. Der Global Report heute (Ist-Zustand)

Datei: `streamlit_app/pages/2_Global_Report.py`.

**Sidebar:** Perioden-Modus (Quartal / Freie Periode), Quartal+Jahr bzw. freie Start/Ende-Daten
für NEW und OLD, Standort-Multiselect, Schwellen-Slider, Toggle „Späte Öffner einbeziehen",
Toggle **„Storno + No-Show einbeziehen"** (`global_include_cancellations`, Default = aus →
realized-only).

**Datenladen:** `nightly = CD.get_timeslices(start=pull_start, end=None, properties=props_pick)`,
dann in-memory gefiltert.

**Bestehende Sektionen / Tabellen** (in `components/global_tables.py`):
- §3 **nach Erstellungsdatum** (`created`): `performance_by_created` (3.A, je Standort),
  `channel_volume_by_created` (3.B, je Channel).
- §4 **nach Aufenthaltsdatum** (`stay_date`): `performance_by_stay` (4.A), `channel_volume_by_stay`
  (4.B).
- §5 **IST vs PLAN · Pace** (`global_charts.py`).
- Alle Tabellen-Funktionen nehmen `include_cancellations: bool` und reichen es an
  `_build_channel_table(..., realized_only=not include_cancellations)` bzw. filtern selbst
  `is_realized`. **Dieses Muster ist deine Vorlage.**

`filter_period`, `_build_channel_table`, `_channel_label`, `with_code_labels`,
`tendency_icon` sind wiederverwendbare Bausteine — **nimm sie**, erfinde nichts neu.

---

## 5. ✦ Das zu bauende Feature ✦

### 5.1 Idee in einem Satz
Eine **neue, kombinierte Analyse** im Global Report, deren **Hauptbasis das Aufenthaltsdatum**
(Sidebar-Filter) ist, die aber **zusätzlich nach Erstellungsdatum** gefiltert werden kann — über
einen **zweiten Filter, der NICHT in der Sidebar steht, sondern direkt über der Tabelle/Grafik**.

### 5.2 Die Basis: Aufenthaltsdatum (wie bisher, aus der Sidebar)
Die Stay-Periode (NEW vs OLD, z.B. Juli 2026 vs Juli 2025) kommt **weiterhin aus dem
bestehenden Sidebar-Filter**. Das ist die Hauptmenge: „die Buchungen, die im jeweiligen Monat
ihren Aufenthalt haben".

### 5.3 Der neue Filter: Erstellungsdatum (über der Grafik, nicht in der Sidebar)
Direkt **über** der neuen Tabelle/Grafik kommt ein zusätzlicher **Erstellungsdatum-Filter**
(Start + Ende). Damit schränkt man die Stay-Basis weiter ein auf Buchungen, die **in einem
bestimmten Erstellungs-Fenster** angelegt wurden.

**Konkretes Beispiel der Product-Ownerin (genau so umsetzen):**
> „Heute ist der 25. Juni. Ich will die Buchungen sehen, die ihren **Aufenthalt im Juli** haben
> (Sidebar), aber **nur die, die im Juni vom 1. bis 25. gebucht** wurden (neuer Filter) — und das
> im **Jahresvergleich 2025 vs 2026**."

**Wichtig — Jahres-Spiegelung des Creation-Fensters:** Das Creation-Fenster wird **pro
Vergleichsjahr gespiegelt**: wählt die Userin „1.–25. Juni", dann gilt für NEW `01.–25.06.2026`
und für OLD `01.–25.06.2025` (Fenster um den Jahres-Offset verschoben, analog zur Stay-Periode).
So sind beide Jahre auf gleichem „Buchungs-Reifegrad" vergleichbar. **Das ist der Kern der
Vergleichbarkeit — bitte exakt so.**

### 5.4 Die Deliverables (mehrere Sichten auf dieselbe gefilterte Menge)
Auf der **identisch gefilterten** Menge (Stay-Fenster ∩ Creation-Fenster, je Jahr gespiegelt):
1. **Tabelle nach Standort** (analog `performance_by_*`): IST NEW vs IST OLD (YoY).
2. **Tabelle nach Channel** (analog `channel_volume_by_*`).
3. **NEUE Tabelle nach Stay-Segment** (`los_bucket`: kurz `short_<=6` / mittel `mid_7-28` /
   lang `long_29+`).
4. **Liniengrafik** (wenn machbar): Revenue **pro Erstellungs-Tag** über das gewählte
   Creation-Fenster — aber **nur** für Buchungen, deren Aufenthalt im Stay-Fenster liegt.
   NEW-Linie vs OLD-Linie (zwei Jahre übereinander). X-Achse = Erstellungstag (1..25 Juni),
   Y-Achse = an dem Tag erzeugtes Revenue der relevanten Buchungen.

> **Total-Reconciliation (Akzeptanzkriterium):** Bei identischem Scope/Filter müssen die Totals
> von Standort-Tabelle == Channel-Tabelle == Stay-Segment-Tabelle == Summe der Linien-Punkte
> sein (je Jahr). Das ist ein harter Test (s. §8).

### 5.5 Der Storno/No-Show-Filter hat hier eine **Sonder-Bedingung** (der knifflige Teil)
Der Toggle soll **derselbe** sein wie der Sidebar-Toggle „Storno + No-Show einbeziehen", **aber
er greift anders** — nämlich **point-in-time**, so wie der **„Pace by Month"-Chart** oben im
Report. Begründung der Product-Ownerin:
> „Da gucken wir ja, ob **Stand heute / Stand Datenaktualisierung** die Buchung schon als
> [storniert] markiert war."

**Das fachliche Problem (unbedingt verstehen):** `is_cancelled` ist der **finale** Status zum
Snapshot-Zeitpunkt. Für einen fairen YoY-Vergleich „wie viel war zu einem vergleichbaren
Zeitpunkt auf den Büchern" darf man nicht den finalen Status nehmen (2025 hatte ein ganzes Jahr
Zeit zu stornieren, 2026 nur bis heute). Man braucht eine **As-of-Sicht**: „War die Buchung **bis
zum Stichtag X** schon storniert?" → `is_cancelled AND cancel_time <= X`. Stornos **nach** X
zählen für die As-of-Sicht **nicht**.

**Stichtag-Optionen (DESIGN-ENTSCHEIDUNG — vor dem Bauen mit der Product-Ownerin bestätigen):**
- **(A) Snapshot-Datum** als Stichtag für NEW; für OLD der um 1 Jahr zurückversetzte Stichtag
  (`SNAP_DATE - 1 Jahr`). Spiegelbildlich, an die Realität gekoppelt.
- **(B) Ende des Creation-Fensters** als Stichtag (je Jahr gespiegelt). Symmetrisch, unabhängig
  vom Snapshot, am einfachsten vergleichbar — die Product-Ownerin tendiert hierhin **und** zum
  Snapshot-Datum.
- **Empfehlung zum Vorschlagen:** Stichtag = **min(Creation-Fenster-Ende, Snapshot-Datum)** je
  Jahr gespiegelt. Das ist robust (nie in die Zukunft des Snapshots schauen) und vergleichbar.
  **Aber: erst bestätigen lassen, weil es die Zahlen materiell verändert.**

**Voraussetzung in den Daten:** `cancel_time` ist auf der Timeslices-Basis vorhanden (per Broadcast).
Also ist `is_cancelled & (cancel_time <= stichtag)` berechenbar. Verifiziere die Befüllung von
`cancel_time` (Null-Quote) bevor du darauf baust.

### 5.6 Tooltip + geschriebene Erklärung (Pflicht)
- Ein **Tooltip / Fragezeichen** an genau diesem Storno-Filter, der die As-of-Bedingung erklärt
  (nutze das `help=`-Muster und/oder `components/tooltips.py`).
- Zusätzlich ein **kurzer Erklärtext direkt an der Tabelle** (z.B. via `st.caption`), was „nach
  Erstellungsdatum gefiltert, Stays im Stay-Fenster, As-of-Storno-Logik" bedeutet. Die
  Product-Ownerin legt großen Wert auf solche Inline-Erklärungen — behandle sie als
  First-Class-Deliverable, nicht als Nachgedanke.

---

## 6. Umsetzungs-Leitplanken (wo was hingehört)

- **Neue Tabellen-Logik** → `components/global_tables.py`: neue Funktionen, z.B.
  `performance_by_stay_created(...)`, `channel_volume_by_stay_created(...)`,
  `segment_volume_by_stay_created(...)`. Signatur-Muster von den bestehenden `*_by_stay`-Funktionen
  übernehmen, **plus** Creation-Fenster-Parameter **plus** Stichtag-Parameter für die As-of-Storno.
- **Neue Liniengrafik** → `components/global_charts.py` (matplotlib, via `CD.chart_png(...)`
  gecacht; Cache-Key über `_ck(...)` inkl. aller Filter + Snapshot-Tag).
- **Filter-UI über der Tabelle** (NICHT Sidebar): mit `st.columns`/`st.container` direkt im
  Page-Body, idealerweise in einem `st.form`, damit nicht jeder Tastendruck einen Rerun auslöst.
- **Reine Filter-Logik** (Stay∩Creation, Jahres-Spiegelung, As-of-Storno) gehört in **reine,
  streamlit-freie** Funktionen (in `helpers.py` oder als pure-pandas-Helfer in `global_tables.py`),
  damit sie ohne laufende App testbar ist (s. §8).
- **Mehrere Tabellen, ein Filter:** Achte auf `st.tabs(..., key="_glb_sc_tabs")` (1.57 stateful
  tabs) falls du die drei Tabellen in Tabs legst — sonst springt der aktive Tab bei Rerun zurück.

---

## 7. ⚠ Stolperfallen & Landminen (aus echten Bugs dieser Codebase gelernt)

1. **Caching — zwei Mechanismen, beide leeren.** Die Snapshot-Lader laufen über
   `@st.cache_resource`; Tabellen/Metadaten über `@st.cache_data`. **`st.cache_data.clear()`
   leert `cache_resource` NICHT.** Beide Clear-Stellen (`cache_clear_button` in `cached_data.py`,
   `_clear_caches()` in `0_Daten_Aktualisieren.py`) räumen inzwischen **beide**. Wenn du neue
   Caches einführst, denk an die Invalidierung beim Refresh.
2. **Widget-Key-Persistenz.** `keep_session_state_alive()` re-touched alle Keys mit Persist-Präfix
   (`global_`, `q_old/new`, `go_/gn_`, `standort_`, `b2b_`, `cd_`, `promo_`, …) über
   Seitenwechsel. **Ein Button/Uploader/Selection-Widget darf NICHT mit einem Persist-Präfix
   beginnen** → sonst `StreamlitValueAssignmentNotAllowedError`. Für **transiente** Widgets
   führendes `_` nehmen (z.B. `_glb_sc_apply`). Für **Filter, die persistieren sollen**, das
   Präfix nehmen (z.B. `global_sc_created_start`) — aber **nur** für persistierbare Inputs
   (date_input/selectbox/multiselect), nie für Buttons.
3. **Den geteilten Snapshot nicht mutieren.** `get_*` liefert Kopien — die darfst du verändern.
   Aber wenn du irgendwo den vollen Cache-Frame referenzierst, kopiere vor dem Schreiben.
4. **Revenue-Basis konsistent halten.** Immer `revenue` (= Nacht-Netto `baseAmount_netAmount`)
   verwenden. Nicht das services-inklusive Reservations-Brutto mischen — sonst stimmen Totals
   nicht überein.
5. **`created` ist UTC, Stay/Arrival sind lokal.** Beim Filtern nach `created` keine
   versehentliche Zeitzonen-Verschiebung einbauen. `filter_period` ist kalendertag-normalisiert —
   nutze es.
6. **Den Storno-Toggle KONSISTENT anwenden.** Realer vergangener Bug: `channel_volume_by_created`
   hatte `realized_only=False` **hartkodiert** und ignorierte den Toggle → Totals zwischen
   Standort- und Channel-Tabelle wichen ab. Stelle sicher, dass **jede** deiner neuen Tabellen
   denselben Filter (hier: As-of-Storno) **identisch** anwendet. Teste die Total-Reconciliation.
7. **Leere Slices / Robustheit.** Realer vergangener Bug: `monthly_landscape` warf `KeyError`,
   weil `pd.DataFrame([]).sort_values("spalte")` auf einem leeren Frame crasht. Deine Aggregationen
   müssen **leere Mengen** sauber überstehen (Standort/Periode/Creation-Fenster mit 0 Buchungen,
   späte Öffner ohne OLD-Daten, NEW-Periode in der Zukunft). Gib leere Frames **mit den erwarteten
   Spalten** zurück.
8. **Korrekt aussehenden Code nicht blind ändern.** Realer Fall: die Plan-Quartals-Aggregation
   „funktionierte nicht" — Ursache war **fehlende Plan-Datei**, nicht der Code. Erst reproduzieren
   & verifizieren, dann ändern.
9. **Lint-Konvention.** `ruff` mit `E,F,W,I,B,UP,N,D`, `line-length=100`, Google-Docstrings.
   Pages sind D-exempt; `src/` und `components/` brauchen Docstrings. Die Repo ist **nicht**
   vollständig lint-clean (viel Alt-Schuld) — **füge keine NEUEN Issues hinzu**, aber **räume auch
   keine fremde Alt-Schuld** in Zeilen auf, die du nicht ohnehin anfasst (hält Diffs sauber).
   Konvention im Repo: Module werden als Großbuchstaben-Alias importiert (`as H`, `as CD`, `as GT`)
   — das löst `N812` aus, ist aber gewollt; bleib konsistent.
10. **Streamlit 1.57 Spezifika.** `st.dataframe(..., on_select="rerun",
    selection_mode="single-row")` → `event.selection.rows`. `st.tabs(..., key=...)` für stateful
    Tabs. `@st.fragment` existiert, ist hier aber **nicht** nötig.

---

## 8. ✦ Qualitätssicherung, Code-Verständnis & Best Practices ✦ (groß, bitte ernst nehmen)

### 8.1 Reihenfolge: verstehen → verifizieren → ändern
- **Lies zuerst** `2_Global_Report.py`, `global_tables.py`, `global_charts.py`, die
  `filter_period`/`landscape_kpis`-Helfer und den Cache-Layer. Verstehe das bestehende
  `include_cancellations`-Muster, **bevor** du es erweiterst.
- Bei jeder „das ist kaputt"-Meldung: **erst reproduzieren** (mit echten Daten, kleinem Repro),
  Ursache benennen, dann fixen. Nicht raten.

### 8.2 Daten-Logik OHNE laufende Streamlit-App testen (wichtig!)
Die reinen Funktionen in `helpers.py` und die pandas-Teile sind **streamlit-frei** und damit
direkt testbar. Muster (im Repo-Root, mit dem Snapshot in `data/`):
```bash
PYTHONPATH=src python - <<'PY'
import pandas as pd
from revenueblindspots import helpers as H
nightly = H.load_timeslices()                 # voller Snapshot
prop = nightly[nightly.property_code=="BER_FR"]
# Stay-Fenster ∩ Creation-Fenster nachbauen und Totals prüfen:
stay = H.filter_period(prop, pd.Timestamp("2026-07-01"), pd.Timestamp("2026-07-31"), "stay_date")
sc   = H.filter_period(stay, pd.Timestamp("2026-06-01"), pd.Timestamp("2026-06-25"), "created")
asof = pd.Timestamp("2026-06-25")
realized_asof = sc[~(sc.is_cancelled & (sc.cancel_time <= asof))]   # As-of-Storno-Logik
print("Total realized-asof:", round(realized_asof.revenue.sum(), 2))
print("== Summe je Channel:", round(realized_asof.groupby('channel_combo').revenue.sum().sum(),2))
print("== Summe je Segment:", round(realized_asof.groupby('los_bucket', observed=True).revenue.sum().sum(),2))
PY
```
Streamlit-gebundene Module (`chart_data.py`, `cached_data.py`) lassen sich im Sandbox-Python ohne
streamlit-Installation **nicht** importieren — teste deren **reine Logik** separat oder ziehe sie
in streamlit-freie Helfer.

### 8.3 Pflicht-Tests vor „fertig"
- **Total-Reconciliation:** Standort-Summe == Channel-Summe == Stay-Segment-Summe == Summe der
  Linien-Tagespunkte, je Jahr, in **beiden** Toggle-Stellungen.
- **Toggle-Wirkung:** Storno-Toggle an vs aus liefert **unterschiedliche** Zahlen (sonst greift er
  nicht) — und in „aus"-Stellung exakt die As-of-realized-Menge.
- **Jahres-Spiegelung:** OLD-Creation-Fenster = NEW-Fenster minus 1 Jahr (per Test verifizieren).
- **Edge-Cases ohne Crash:** leeres Creation-Fenster, Standort ohne OLD-Daten (später Öffner),
  NEW-Periode komplett in der Zukunft, ein einzelner Standort, kein Plan vorhanden.
- **Vorher/Nachher-Gleichheit:** wenn du Bestehendes anfasst, beweise mit einem Skript, dass sich
  bestehende Tabellen-Totals **nicht** verändern (Regressionsschutz).
- **Gates:** `python -m py_compile <files>` und `python -m ruff check <files>` (nur deine Dateien;
  keine neuen Issue-Typen).

### 8.4 Code-Best-Practices in dieser Codebase
- **Kleine, fokussierte Diffs.** Eine Sache pro Änderung. Bestehende „fertige" Pages nicht
  nebenbei umbauen.
- **Wiederverwenden statt neu erfinden:** `filter_period`, `_build_channel_table`, `_channel_label`,
  `with_code_labels`, `section()/lazy_section()`, `alert_card()`, `CD.chart_png()`.
- **Reine Logik von UI trennen:** Aggregation/Filterung in streamlit-freie Funktionen, damit
  testbar; die Page macht nur Layout + ruft die Logik.
- **Cache-Keys vollständig:** jeder gecachte Wert/Chart muss über **alle** Filter + `snapshot_tag()`
  invalidiert werden (sonst Stale-Cache).
- **Defensiv bei leeren/None-Werten** (s. §7.7).
- **Performance:** Es sind nur ~155k/708k Zeilen — in-memory-Filter auf dem gecachten Snapshot ist
  schnell. Keine erneuten Disk-Reads, keine BigQuery-Calls in den Pages.
- **Inline-Erklärungen & Tooltips** sind hier Teil der Definition-of-Done, nicht optional.

### 8.5 Definition of Done (Akzeptanzkriterien)
- [ ] Stichtag-/As-of-Logik mit der Product-Ownerin bestätigt (§5.5).
- [ ] Neuer Creation-Filter über (nicht in) der Tabelle, persistiert sinnvoll, kein Key-Crash.
- [ ] Drei Tabellen (Standort, Channel, Stay-Segment) + Liniengrafik, YoY 2025 vs 2026, mit
      Jahres-gespiegeltem Creation-Fenster.
- [ ] Storno-Toggle wirkt point-in-time (As-of), identisch über alle vier Sichten.
- [ ] Tooltip + Inline-Erklärung vorhanden.
- [ ] Total-Reconciliation & alle Edge-Cases getestet, keine Crashes.
- [ ] `py_compile` + `ruff` sauber (keine neuen Issues), kein Regress bei bestehenden Tabellen.

---

## 9. Erste Schritte (Vorschlag)
1. Snapshot lokal sicherstellen (`data/*.parquet`); sonst Logik-Tests auf Beispiel-Frames.
2. `cancel_time`-Befüllung prüfen (Null-Quote), As-of-Storno-Logik in einem reinen Helfer
   prototypen und per §8.2-Skript gegen die Reconciliation testen.
3. Stichtag-Entscheidung (§5.5) klären.
4. Tabellen-Funktionen in `global_tables.py` bauen (Muster: bestehende `*_by_*`), dann die
   Liniengrafik in `global_charts.py`.
5. Filter-UI + Sektionen in `2_Global_Report.py` verdrahten, Tooltip + Erklärtext, Export
   registrieren (`register_section`).
6. Voll testen (§8.3), Diffs klein halten, ehrlich melden, falls etwas tiefer umgebaut werden muss.

---

*Ende des Prompts. Bei echten Logik-Lücken: nachfragen statt annehmen. Viel Erfolg.*
