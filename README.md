# RevenueBlindSpots

Stayery Revenue-Analytics als **Dash-App**. Standort-Deep-Dives, Global Recap
(IST vs. PLAN vs. Vorjahr), Pickup/Vorlauf, B2B-Outreach und Firmen-360°-Profile
laufen über einem refreshbaren Parquet-Snapshot der BigQuery-Daten.

---

## Quickstart

```bash
# 1. Dependencies (einmalig)
uv sync            # oder: pip install -r requirements.txt

# 2. App starten (lokal, mit Hot-Reload)
uv run python -m dash_app.app      # http://localhost:8050
```

Ist noch kein Snapshot da, unter **Daten** einmal „Voll-Refresh starten"
(BigQuery-Auth nötig, siehe Troubleshooting) — danach laufen alle Analysen.

Produktiv läuft die App per gunicorn (`gunicorn dash_app.app:server`, siehe
`Dockerfile`).

---

## Architektur

```
        ┌───────────────────┐
        │  BigQuery (live)  │   stayery-analytics.reporting.*
        └─────────┬─────────┘
                  │  Pull nur beim Refresh-Job (Seite „Daten")
                  ▼
        ┌──────────────────────┐
        │  data/*.parquet      │   reservations + timeslices (+ plan)
        │  metadata.json       │   local oder gs:// via STAYERY_SNAPSHOT_DIR
        └─────────┬────────────┘
                  │  einmal geladen, lru_cache (backend/data.py)
                  ▼
        ┌───────────────────┐
        │  Dash-App          │   Plotly-Charts + dash-ag-grid
        └───────────────────┘
```

Single Source of Truth ist der Parquet-Snapshot. **Filter-Interaktionen kosten
keine BigQuery-Calls** — alles in-memory pandas. BigQuery wird ausschließlich
vom Refresh-Job berührt.

---

## Navigation (Tabbed Hubs)

| Nav | Inhalt |
|---|---|
| **Home** | Freshness, Kennzahlen, Schnellzugriffe, Standort-Verwaltung (YAML-Snippet-Generator). |
| **Revenue** | Tabs: **Global Report** (IST/PLAN/Vorjahr, Channel-Mix, Heatmaps), **Pickup** (Stay × Creation Booking-Pace), **Standort** (Einzel-Deep-Dive, 10 Sektionen). |
| **Sales** | Tabs: **B2B** (Corporate-Codes, Fuzzy-Firmen, Firmenkunden/Direct-Offline/Vertragscodes), **Code-Deepdive** (Firma/Code im 360°-Blick), **Promo-Codes** (Roster + Reklassifizierungs-Tool). |
| **Daten** | Voll-/Plan-Refresh als Hintergrund-Job (Ring-Progress, abbrechbar) + Plan-Einsicht. |
| **Doku** | In-App-Methodik (KPIs, Storno-Konventionen, Datenfluss). |

Jede Seite hat eine **sticky Filterleiste** (Primärfilter + „Erweitert"-Popover),
gruppiert Sektionen in **Tabs** und zeigt die aktiven Filter als Chips.
Deep-Links: `/revenue?tab=pickup`, `/sales?tab=code&code=<CODE>`.

---

## Repo-Struktur

```
.
├── dash_app/
│   ├── app.py            # App-Factory, Navbar, MantineProvider, React-18.2-Pin
│   ├── theme.py          # Farben/Fonts aus stayery_brand.yaml, brand_figure()
│   ├── assets/           # brand.css + Fonts (Dash serviert /assets automatisch)
│   ├── pages/            # register_page: home, revenue (Hub), sales (Hub), daten, doku
│   ├── views/            # global_report, pickup, standort, b2b, code_deepdive, promo
│   ├── components/       # ui.py (Filter/Tabs/KPI/Grid-Primitives) + *_charts.py (Plotly)
│   └── backend/          # data.py (Cache), jobs.py (Job-Runner), exports.py, *_tables.py
├── src/revenueblindspots/# Daten-Layer (UI-frei): helpers, overrides, refresh (BigQuery), theming
├── configs/              # locations.yaml (SoT), stayery_brand.yaml
├── data/                 # Parquet-Snapshot + metadata.json (gitignored)
└── pyproject.toml        # uv-managed
```

---

## Caching & Performance

- **`lru_cache` auf den Snapshot-Loadern** (`backend/data.py`), Key =
  Snapshot-Signatur (Pfad+mtime) × Override-Signatur. Filter schneiden das
  gecachte Frame in-memory (`.copy()`), kein wiederholtes Disk-IO.
- Nach einem Refresh-Job: `data.clear_caches()` + `*-version`-Store-Bump →
  alle Seiten lesen frisch.
- **RAM-Hinweis für Deployment:** jeder gunicorn-Worker hält seine eigene
  Cache-Kopie der Frames → `--preload` + wenige Worker (Dockerfile: 2).

---

## Snapshot-Speicherort

Default `data/` im Repo. Override via Env-Var:

```bash
export STAYERY_SNAPSHOT_DIR=/abs/path/to/data          # lokal anderswo
export STAYERY_SNAPSHOT_DIR=gs://stayery-analytics-snapshots   # GCS (zentral)
```

---

## Neuen Standort hinzufügen

`configs/locations.yaml` ist die **Single Source of Truth** für Hotel-Metadaten
(`hotel_code`, `city`, `neighborhood`, `bundesland`, `units_total`,
`opening_date`).

1. **Home** → „Standorte" → „Neuen Standort hinzufügen" → Form ausfüllen →
   erzeugt einen YAML-Snippet.
2. Snippet in `configs/locations.yaml` einfügen.
3. **Daten** → Voll-Refresh → BigQuery zieht den neuen Code mit, Caches werden
   geleert, Standort erscheint überall.

`opening_date` steuert die „noch nicht offen"-Warnungen und den
Späte-Öffner-Ausschluss in Global/Standort/Pickup.

---

## Entwicklung

```bash
uv sync --extra dev            # ruff, pre-commit, nbstripout
uv run pre-commit install
uv run ruff check dash_app src
```

Code-Style: ruff (line-length 100). Konventionen: `def layout(**_kwargs)` je
Seite/View, bare `@callback`, kebab-case-IDs mit Seiten-Präfix, jede Figur durch
`theme.brand_figure`, Tabellen als dash-ag-grid, lange Tasks via
`backend/jobs.py`.

---

## Troubleshooting

**„Kein Snapshot gefunden"** → Seite **Daten** → Voll-Refresh.

**BigQuery-Auth schlägt fehl** → Der Job failt mit klarer Fehlermeldung + Trace.
Lokal: `gcloud auth application-default login`.

**„403 … Permission denied while getting Drive credentials" (Plan-Pull)** →
`ref_tables.plan` ist eine Drive-backed External Table (Google Sheet); das Token
braucht zusätzlich den Drive-Scope:

```bash
gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/bigquery,https://www.googleapis.com/auth/drive.readonly,https://www.googleapis.com/auth/cloud-platform
```

Der Voll-Refresh läuft auch ohne Plan durch (Plan wird übersprungen, ein
bestehender `plan.parquet` bleibt erhalten); „Nur Planzahlen" zeigt den
Drive-Hinweis direkt an.

---

## Lizenz

Proprietär — Stayery internal.
