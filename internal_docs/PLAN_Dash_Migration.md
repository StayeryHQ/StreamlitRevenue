# PLAN · Migration Revenue-Analytics → Dash (Arbeitsdokument)

*Stand 20.07.2026 · Ersetzt den Plan vom 14.07. Alte Annahme „Monorepo-Merge in OverbookingAnalyse" ist verworfen: Die Dash-App entsteht **in diesem Repo** (`dash_app/`), die Overbooking-App wird nur als Referenz gelesen, nie angefasst. Streamlit wird vollständig abgelöst und entfernt (kein Strangler mehr — rein lokal, nichts committed).*

---

## 0 · Entscheidungen (Ruby, 20.07.)

1. **Keine 1:1-Seitenstruktur.** Navbar gruppiert: **Revenue** = Global Report, Pickup, Standort · **Sales** = B2B, Code-Deepdive, Promo-Codes. B2B/Promo werden NICHT zusammengelegt.
2. **Standort §11–13 (Firmenkunden, Direct-Offline-Segmente, Vertragscodes) ziehen auf die B2B-Seite um** — klare Trennung Revenue vs. Sales.
3. **Notepad + Notion-Markdown-Export: gestrichen.** Exporte = Excel (openpyxl via `dcc.send_bytes`) + CSV (AG-Grid `exportDataAsCsv`).
4. **`streamlit_app/` wird am Ende gelöscht**, ebenso alle Streamlit-Deps und -Referenzen (Git-History hält die Kopie).
5. **Server/Deployment bleibt außen vor**, wird aber mitgedacht (siehe §4 Risiken: gunicorn/RAM).

## 1 · Architektur (Spiegel der Overbooking-App)

Regel: Wer die Overbooking-App versteht, versteht diese. Identische Schichten, Konventionen, Optik.

```
dash_app/
  app.py            App-Factory, Navbar (gruppiert), MantineProvider, React-18.2-Pin
  theme.py          Farben/Fonts aus configs/stayery_brand.yaml, brand_figure(), DMC_THEME
  assets/           brand.css (Navbar/Wordmark/Fonts, wie Overbooking), fonts/*.otf
  pages/            home, global_report, pickup, standort, b2b, code_deepdive, promo, daten, doku
  components/       ui.py (kpi_card, chart_card, info_icon, job_loader, …) + <seite>_charts.py (Plotly-Builder)
  backend/          data.py (Cache-Layer), jobs.py (file-backed Job-Runner), exports.py,
                    global_tables.py / chart_data.py / b2b_tables.py / promo_tables.py (pure pandas, aus Streamlit portiert, @st.cache_data entfernt)
src/revenueblindspots/   UNVERÄNDERT (streamlit-frei): helpers, overrides, refresh (BigQuery)
```

Konventionen (aus Overbooking übernommen): `def layout(**_kwargs)` je Seite; bare `@callback`; kebab-case-IDs mit Seiten-Präfix (`gr-`, `pu-`, `st-`, `b2b-`, `cd-`, `pr-`, `du-`); jede Figur endet mit `theme.brand_figure(fig)` und rendert mit `config={"displayModeBar": False}`; Tabellen = dash-ag-grid; ein Owner pro `dcc.Store`; lange Tasks NIE inline, sondern `backend/jobs.py` (kick/seen/poll-Triade); Fehler in Renders degradieren leise, Jobs failen laut; jede Kennzahl bekommt ein `info_icon` (Texte aus `components/tooltips.py`).

## 2 · Daten & Caching

- `backend/data.py` ersetzt `cached_data.py`: `lru_cache` auf Snapshot-Loader, Key = `snapshot_signature()` (Pfad+mtime) × `override_signature()`. Filter (`get_timeslices/get_reservations`) schneiden in-memory mit `.copy()`. `clear_caches()` nach Refresh-Job + `*-version`-Store-Bump.
- Snapshot-Pfad: env `STAYERY_SNAPSHOT_DIR` → Repo-`data/`. Der Session-Pfad-Override der Streamlit-Seite entfällt (war Session-Feature; env reicht lokal).
- Aggregations-Builder (global_tables etc.) laufen ungecacht pro Callback — bei 78k/310k Zeilen ok; falls spürbar träge → flask-caching gezielt nachrüsten (offen, siehe §5).
- BigQuery wird ausschließlich vom Refresh-Job berührt (Seite „Daten"), nie von Filtern/Interaktionen.

## 3 · Seiten-Mapping

| Dash-Seite (URL, Order) | Quelle | Änderungen |
|---|---|---|
| Home `/` 0 | Home.py | KPI-Zeile, Freshness, Seitenkarten, Standort-YAML-Snippet-Generator |
| Global Report `/global` 1 (Revenue) | 1_Global_Report | Scorecard/Heatmaps/Donuts → Plotly (Donuts → Balken wie Overbooking-Stil), Recap-Tabellen → AG Grid, auto_alerts → dmc.Alert |
| Pickup `/pickup` 2 (Revenue) | 2_Pickup_Analyse | Pace-Fig war schon Plotly; st.line_chart/bar_chart → Plotly; 3 Excel/CSV-Exporte |
| Standort `/standort` 3 (Revenue) | 3_Standort_Analyse §1–10 | §11–13 → B2B; Lazy-Sections → normale Sections (Callbacks laden eh on-demand) |
| B2B `/b2b` 4 (Sales) | 4_B2B_Deepdive + Standort §11–13 | Roster als AG Grid, Drilldown = Drawer, Link zu `/code?code=…` |
| Code-Deepdive `/code` 5 (Sales) | 5_Code_Deepdive | Deep-Link via Query-Param `?code=` |
| Promo-Codes `/promo` 6 (Sales) | 6_Promo_Codes | Reklassifizierungs-Tool schreibt `code_overrides.json` → Override-Signatur invalidiert Caches |
| Daten `/daten` 7 | 0_Daten_Aktualisieren | Voll-/Plan-Refresh als file-backed Job (Ring-Loader, Cancel), Planzahlen-Ansicht |
| Doku `/doku` 8 | 7_Dokumentation | dcc.Markdown / dmc.Accordion, rein statisch |

Entfällt ersatzlos: notepad.py, export.py (Markdown/Notion), section.py (Lazy-Load), brand.py (CSS-Injection), Chart-PNG-Cache, matplotlib-Chartmodule (durch Plotly-Neubau ersetzt), `keep_session_state_alive` (Dash-Stores machen das nativ).

## 4 · Risiken

| Risiko | Status/Gegenmaßnahme |
|---|---|
| **RAM × Worker**: lru_cache hält Reservations+Timeslices (+Override-Kopie) einmal **pro Prozess**. Bei gunicorn n Worker = n×. | Lokal (ein Prozess) unkritisch. Für Server: `--preload` + max 2 Worker + Memory-Limit; steht hier als Merkzettel, Deployment ist explizit out of scope. |
| **Parquet-Snapshot fehlt/partiell** (aktuell fehlt `plan.parquet`!) | Alle Loader liefern leere Frames statt Crash; Seiten zeigen „keine Daten"-Hinweis. PLAN-Vergleiche zeigen aktuell 0/— bis ein Plan-Refresh lief. |
| **BigQuery-Auth** (SA-Key/ADC) nur im Refresh-Job | Job failt laut mit Traceback im Job-File; UI zeigt Fehler-Alert. Kein BQ-Zugriff aus Filtern. |
| **Rewrite-Abweichungen** (A1-Fehlerklasse): matplotlib→Plotly-Neubau kann Zahlen verfälschen | Zahlenlogik bleibt in `src/` + portierten pure-pandas-Buildern (unverändert bis auf Decorator-Strip); Charts konsumieren nur deren Output. Sichtprüfung je Seite. |
| **Streamlit-spezifische Semantik** (Form-Submit, Session-Persistenz) | Dash: Filter wirken direkt (kein „Anwenden"-Formular mehr); Persistenz über `persistence=True`/Stores wo sinnvoll. |
| **Ein Thread-Job + Dev-Server**: Refresh-Job (1–3 min BigQuery) als Daemon-Thread | Muster aus Overbooking inkl. Orphan-Detection nach App-Restart. |

## 5 · Log (Edits / Findings während der Migration)

- 20.07. Plan neu geschrieben (dieses Dokument). Alte Version beschrieb Monorepo-/Strangler-Ansatz — obsolet.
- 20.07. Befund Explorationsphase: `src/revenueblindspots` ist komplett streamlit-frei → wird 1:1 wiederverwendet. `helpers.yoy_two_panel` (matplotlib) wird von keiner Seite aufgerufen → entfällt. `tabulate`-Dep hing nur am Markdown-Export → entfällt. `plan.parquet` fehlt im aktuellen Snapshot (metadata.json ohne plan-Block).
- 20.07. `plotly_theme.py` (Streamlit-Brücke) geht in `dash_app/theme.py` auf; Farbquelle bleibt `configs/stayery_brand.yaml`.

### 28.07. — Umsetzung abgeschlossen (Stand dieser Session)

**Architektur-Update ggü. §2/§3 (UX-Rethink, Ruby):** Statt 9 flacher Nav-Seiten jetzt **Tabbed Hubs**. Navbar = Home · Revenue · Sales · Daten · Doku.
- `pages/revenue.py` + `pages/sales.py` sind schlanke Hub-Router (`dcc.Tabs` → rendern die aktive View in ein Content-Div; Deep-Link via `?tab=`).
- Die eigentlichen Seiten leben als **Views** in `dash_app/views/` (kein `register_page`; exponieren `layout()`, Callbacks bei Import). Ein Hub importiert sie.
- **Sticky Filterleiste**: `ui.filter_shell(primary, advanced=ui.advanced_popover(...), chips_id=...)` — Primärfilter sticky, Sekundärfilter im „Erweitert"-Popover (eine MATCH-Toggle-Callback in `ui.py` für alle). Aktive Filter als Chips (`ui.filter_chips`, on/hi/off).
- **Sektions-Tabs** je View: `ui.section_tabs(...)` (dmc.Tabs, `keepMounted=True` → ein Daten-Callback füllt alle Tabs).

**Gebaut:** Scaffold (app/theme/brand.css/Fonts), `backend/` (data lru_cache, jobs file-backed, exports, *_tables portiert), `components/ui.py` + `tooltips.py` + Plotly-Chart-Module (`global_report_charts`, `pickup_charts`, `standort_charts`, `code_charts`, `b2b_charts`). Views: global_report, pickup, standort (Revenue) · b2b, code_deepdive, promo (Sales). Pages: home, daten (Refresh-Job mit Ring-Progress/Cancel), doku. Standort §11–13 (Firmenkunden/Direct-Offline/Vertragscodes) sind wie geplant in **B2B** umgezogen.

**Verifiziert:** App bootet, 5 Nav-Seiten, 39 Callbacks, keine Duplicate-Outputs, alle Routen HTTP 200. Haupt-Daten-Callbacks gegen echten Snapshot ausgeführt: standort 38 Outputs/16 Figuren, pickup 14/6 — fehlerfrei. Chart-Builder je View gegen echte Daten smoke-getestet.

**Cleanup:** `streamlit_app/` + `.streamlit/` gelöscht. Streamlit/matplotlib/tabulate aus pyproject+requirements raus, `dash`/`dash-mantine-components`/`dash-ag-grid`/`gunicorn` rein. Dockerfile auf gunicorn+Dash (Port 8050, `--preload`, 2 Worker). `helpers.yoy_two_panel` (tote mpl-Funktion) entfernt. `theming.py` Font-Pfad → `dash_app/assets/fonts`. Alle Streamlit-Referenzen in Code/Docstrings/README gescrubt (Repo-Name „StreamlitRevenue" bleibt).

**Offen / bewusst deferred:**
- **Server-Side (per Ruby deferred):** `compose.yaml` + `.github/workflows/deploy.yaml` referenzieren noch `/_streamlit`-Route, `streamlit-auth`-Middleware, Port 8501 und den Image-Namen `streamlit_revenue`. Brauchen einen Dash-Pass (Port 8050, Routing/Auth-Naming, Image-Name) wenn Deployment ansteht.
- **Stale interne Docs:** `HANDBUCH_Codebase.md` beschreibt die (gelöschte) Streamlit-App; `EVAL_Dash_vs_Plotly.md` + `Plan.md` sind Vor-Migrations-Entscheidungsdokumente. Kandidaten zum Neu-Schreiben (HANDBUCH → Dash) bzw. Löschen (EVAL/Plan.md) — bewusst noch nicht angefasst, damit du entscheidest.
- **Perf-Feintuning:** Aggregationen laufen ungecacht pro Callback (bei 78k/310k Zeilen ok). `section_tabs` mit `keepMounted=True` rendert alle Tab-Figuren; falls spürbar träge → lazy-load pro Tab oder `flask-caching` gezielt nachrüsten.
- **Parität:** Sichtprüfung Zahl-für-Zahl gegen die (auf `main` noch laufende) Streamlit-App steht aus — die Fachlogik ist identisch (geteiltes `src/` + portierte pure-pandas-Builder), aber ein Augen-Diff je Seite ist empfehlenswert.

### 30.07. — UI/UX- & Performance-Phase (Feedback Ruby)

**Logik-Audit (3 Agenten, gegen `main:streamlit_app/`):** Port ist inhaltlich treu. 1 echter Bug gefixt: `snapshot_signature()` fingerprintete nur `reservations.parquet` → Plan-only-Refresh invalidierte Plan/Metadata-Caches nicht über Worker-Grenzen; jetzt alle 4 Snapshot-Files. Kleine Parität-Korrektur: §4 Channel×Reisezweck Anteils-Panel wieder per-Row (6 Balken, wie Original) via `share_rows`. Dead code entfernt (Nav-Group-Logik, ungenutzte Hub-Stores). daten `_poll` gibt Erfolgs-Alert jetzt nur einmalig aus (nicht jeden Tick).

**Aufgabenstruktur (Tasks 14-18):**
1. *Filter-Stabilität (14, erledigt):* Page-level `dcc.Loading` in den Hubs entfernt — es legte den Dot-Spinner bei JEDEM Filterwechsel über den ganzen Content inkl. Filterleiste ("Seite lädt komplett neu"). Jetzt bleiben Navbar + Filterleiste stehen; nur die Sektionen darunter zeigen per-Graph-Skeletons.
2. *Filter-Redesign (15, weitgehend erledigt):* `ui.location_select` = kompakte Standort-Box (feste Breite, gekappte Höhe → scrollt statt zu wachsen; Anzahl steht in den Chips), überall statt der Riesen-MultiSelect. Advanced-Popover war unzuverlässig → jetzt "Erweitert"-Button + inline `dmc.Collapse` (`ui.filter_shell`/`advanced_popover` umgebaut, Call-Sites unverändert). Offen: optionaler Master-Collapse der ganzen Leiste; Sales-Reihenfolge-Feinschliff.
3. *Downloads (16, TODO — Rubys Top-Prio):* Streamlit-Style zurückholen — pro Grafik (PNG/CSV) + pro Seite Multi-Export (Sektionen wählbar) als Notion-Markdown + Excel.
4. *Quick UI (17, erledigt):* Home-Freshness als Brand-Pill (statt roher Kreis); "Read-only" aus dem Self-Service-Badge raus; Daten-Fuzz-Slider-Marks überlappten die Caption → `marginBottom`; Global-Report Top-Movers aus dem Heatmaps-Tab in Überblick verschoben.
5. *Performance (18, TODO):* großer Single-Callback rechnet alle Tabs; `get_timeslices` kopiert 281 MB pro Call. Plan: keyed Cache für gefilterte Frames, lazy Compute nur des aktiven Section-Tabs, Hub-Navigation profilen, "lädt ewig"-Fälle (u.a. Daten Aktueller Stand beim First-Load) beheben. Wichtig fürs Server-Deployment (lokal schon spürbar → remote schlimmer).
