# RevenueBlindSpots

Stayery Revenue-Analytics als Streamlit-App. Standort-Deep-Dives, Global
Recap (IST vs. PLAN vs. Vorjahr), B2B-Outreach-Tabellen und Firmen-360°-
Profile laufen über einem täglich refreshbaren Parquet-Snapshot der
BigQuery-Daten.

---

## Quickstart

```bash
# 1. Dependencies + venv (einmalig)
uv sync

# 2. App starten
uv run streamlit run streamlit_app/Home.py
```

Beim ersten Start ist noch kein Snapshot da. **Refresh-Snapshot**-Page
öffnen, BigQuery-Auth erledigen (drei Wege, siehe Page), „Refresh starten"
klicken - danach laufen alle Analyse-Pages.

---

## Architektur

```
              ┌───────────────────┐
              │  BigQuery (live)  │   stayery-analytics.reporting.*
              └─────────┬─────────┘
                        │  Pull manuell via Refresh-Snapshot-Page
                        ▼
              ┌──────────────────────┐
              │  data/*.parquet      │   ~25 MB total
              │  metadata.json       │   (local oder gs:// via env-var)
              │  plan_override.json  │   persistierter Plan-Upload
              └─────────┬────────────┘
                        │  read once, cached
                        ▼
              ┌───────────────────┐
              │  Streamlit-App    │   alle Pages, alle Charts
              └───────────────────┘
```

Single Source of Truth ist der Parquet-Snapshot. Filter-Änderungen in der
App kosten **keine** BigQuery-Calls - alles in-memory pandas.

---

## Pages

| Page | Was sie tut |
|---|---|
| **Refresh-Snapshot** | BigQuery-Pull + Engineering + Fuzzy-Cluster → Parquet schreiben. Caches werden danach automatisch geleert, neue Standorte erscheinen sofort. |
| **Standort-Analyse** | Tiefer Einzelblick auf einen Standort - 17 Sektionen mit dynamischem TOC und Methodik-Tooltips. |
| **Global Report** | Standortübergreifend, Quartal oder freie Periode. Visual Scorecard, Pace-by-Month, Channel-Mix, Heatmaps. Hotel-Codes in Charts, Stadt-Namen in Tabellen. |
| **B2B Deep-Dive** | Drei Tabellen: alle `company_code`, `corporateCode`, fuzzy-geclusterte Firmen. Multi-Sheet Excel-Export. |
| **Code Deep-Dive** | Eine Firma im 360°-Blick - Revenue-Verlauf, Channel-Evolution, Stay-Pattern, Storno, Future Pipeline. |
| **Plan-Upload** | Wide-Format Excel hochladen → persistiert in `<snapshot_dir>/plan_override.json` (überlebt App-Restart, bei GCS für alle User gleich). |

---

## Repo-Struktur

```
.
├── streamlit_app/         # die App
│   ├── Home.py            # Entry-Point + Standort-Verwaltung
│   ├── pages/             # 6 Analyse-Pages
│   └── components/        # cache, charts, tabellen, layout, export, tooltips
├── src/revenueblindspots/ # data layer
│   ├── helpers.py         # BigQuery-Cols, Engineering, KPIs, Snapshot-IO, Plan-Persistenz
│   └── theming.py         # Stayery-Branding für matplotlib
├── configs/
│   ├── locations.yaml     # Hotel-Codes + Units + Stadt + opening_date (SoT)
│   └── stayery_brand.yaml # Farben, Typografie
├── data/                  # Parquet-Snapshot + plan_override.json (gitignored)
├── .streamlit/config.toml # Theme + Performance-Settings
└── pyproject.toml         # uv-managed
```

---

## Performance

- **Parquet-Snapshot in `@st.cache_data`** - Slider-Drag triggert kein Disk-IO.
- **Chart-PNG-Cache in `st.session_state`** - matplotlib-Renders werden
  einmal gemacht, dann bytes-cached. Cache-Key enthält Snapshot-Signatur
  (Refresh → automatische Invalidierung) und Filter-Werte (Slider-Änderung
  → frischer Render).
- **Lazy-Sections** - Sektionen 6–17 (Standort) und 4–7 (Global) werden
  erst auf Klick gerendert. Sidebar-Button „🚀 Alle laden" für volles Bild.
- **Tabellen-Builder gecacht** - `performance_by_stay` etc. laufen pro
  Filter-Kombination genau einmal.

Falls etwas hakt: Sidebar → „🔄 Cache leeren".

---

## Snapshot-Speicherort

Default: `data/` im Repo. Override via Environment-Variable:

```bash
# Lokal anderswo
export STAYERY_SNAPSHOT_DIR=/abs/path/to/data

# GCS-Bucket (zentral, alle teilen denselben Snapshot + Plan)
export STAYERY_SNAPSHOT_DIR=gs://stayery-analytics-snapshots
```

In der Refresh-Page kannst du den Pfad auch interaktiv setzen - wird in
Session-State + Env-Var geschrieben.

---

## Plan pflegen

Plan-Upload-Page öffnen, Wide-Format Excel hochladen, „Plan aktivieren
+ speichern" klicken. Der Plan wird als JSON neben dem Snapshot
persistiert (`data/plan_override.json` bzw. im GCS-Bucket) - überlebt
also App-Restarts, und bei GCS sehen alle User denselben Plan.

**Excel-Format (Wide):**
- 1. Spalte: `PLAN:<Stadt>` (z.B. `PLAN:Berlin`) oder
  `PLAN:<Stadt Neighborhood>` (z.B. `PLAN:Köln Sülz` wenn mehrere Hotels
  in der Stadt) oder `PLAN:<HOTEL_CODE>` (z.B. `PLAN:CGN_WS`).
- weitere Spalten: `MM-YY` (z.B. `01-25`, `12-26`).
- Werte: PLAN in EUR (netto).

Template-Download in der Plan-Upload-Page selbst.

---

## Neuen Standort hinzufügen

`configs/locations.yaml` ist die **Single Source of Truth** für
Hotel-Metadaten (`hotel_code`, `city`, `neighborhood`, `bundesland`,
`units_total`, `opening_date`). BigQuery liefert nur die nackten
`property_code` - alles andere wohnt in der YAML.

Workflow:

1. Home-Page öffnen → Sektion **„Standorte"** → Expander **„➕ Neuen
   Standort hinzufügen"** → Form ausfüllen → erzeugt YAML-Snippet.
2. Snippet ans Ende von `locations:` in `configs/locations.yaml` einfügen.
3. **Refresh-Snapshot** ausführen → BigQuery zieht den neuen Code mit,
   Caches werden geleert, Standort erscheint überall in den Sidebars.

`opening_date` ist wichtig: ist gesetzt, warnt die App auf der Standort-
und Global-Page wenn der Standort in der OLD-Vergleichsperiode noch nicht
offen war (kein crash, klar markierter Hinweis).

---

## Tooltips & Methodik

Jeder Headline-KPI (Revenue, ADR, Occupancy, ALOS, IST/PLAN/YoY/Sales-
Volumen im Global Report) hat einen ⓘ-Tooltip mit kurzer Erklärung.
Unter jedem Chart gibt es einen „ℹ Was zeigt diese Grafik?"-Expander mit
Lesehilfe (Methodik, Storno-Konvention, Farb-Logik).

Alle Tooltip-Texte zentral in `streamlit_app/components/tooltips.py` -
einmal editieren, überall sichtbar. Die Tooltips landen **nicht** im
Markdown-Export für Notion (UI-only).

---

## Entwicklung

```bash
# Dev-Tools (ruff, pre-commit, nbstripout)
uv sync --extra dev

# Pre-commit-Hooks aktivieren (einmalig)
uv run pre-commit install

# Manuell laufen lassen
uv run pre-commit run --all-files
```

Code-Style: ruff (line-length 100), Google-Docstrings.

---

## Troubleshooting

**„Kein Snapshot gefunden"** → Refresh-Snapshot-Page öffnen, einmal pullen.

**Neuer Standort nicht in Sidebar nach Refresh** → Sidebar → „🔄 Cache
leeren". Sollte seit dem letzten Refresh-Fix automatisch passieren.

**App ist langsam** → Sidebar → „🔄 Cache leeren". Wenn das nicht hilft,
liegt's vermutlich an matplotlib-Charts mit sehr viel Daten - Periode
einschränken.

**BigQuery-Auth schlägt fehl** → Der Refresh-Klick scheitert mit klarer
Fehlermeldung. Lokal: `gcloud auth application-default login`. Streamlit Cloud:
`st.secrets`-TOML.

**„403 … Permission denied while getting Drive credentials" beim Plan-Pull** →
`ref_tables.plan` ist eine Drive-backed External Table (Google Sheet); das Token
braucht zusätzlich den **Drive-Scope**. Lokal einmalig mit Drive-Scope einloggen:

```bash
gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/bigquery,https://www.googleapis.com/auth/drive.readonly,https://www.googleapis.com/auth/cloud-platform
```

Voraussetzung: dein Google-Account (bzw. die Service-Account-Mail) hat Leserecht
auf das Sheet. Der Voll-Refresh läuft inzwischen auch ohne Plan durch (Plan wird
übersprungen, ein bestehender `plan.parquet` bleibt erhalten); der separate
Button „Nur Planzahlen aktualisieren" zeigt den Drive-Hinweis direkt an.

**„−100 % YoY"-Alert für einen Standort, der absurd aussieht** → meistens
ein Standort der in der OLD-Periode noch nicht offen war. Die Auto-Alert-
Logik filtert solche Fälle inzwischen raus; oben auf der Page erscheint
stattdessen ein gelber Banner „Standorte ohne Daten in {old_period}".

**Plan-Werte stimmen nicht** → Plan-Upload-Page → „Aktiver Plan" prüfen.
„Plan löschen" entfernt den Override (Disk + Session).

**Filter springen beim Tab-Wechsel zurück** → sollte nicht mehr passieren
seit alle Widgets einen `key=` haben. Falls doch: Browser-Cache leeren.

---

## Lizenz

Proprietär - Stayery internal.
