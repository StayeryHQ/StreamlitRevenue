# EVALUATION · Dash-Migration vs. Plotly-in-Streamlit

*Stand 14.07.2026 · Basis: vollständige Analyse beider Codebases (StreamlitRevenue ~13,5k LOC; OverbookingAnalyse/dash_app ~4,5k LOC Dash + Backend) + Performance-Benchmark mit dem echten Snapshot. Nur Bewertung — keine Implementierung.*

---

## 0 · Kurzfassung

**Die Performance-Sorge ist der falsche Entscheidungsgrund — in beide Richtungen.** Gemessen an euren Datengrößen ist Plotly-in-Streamlit performant (Figuren bauen in 1–3 ms, Payloads 4–15 KB), und Streamlit ist nicht der Flaschenhals. Eine Dash-Migration lohnt sich **nicht wegen Performance**, sondern — wenn überhaupt — wegen **Konsolidierung**: Ihr habt zwei Stayery-Analytics-Apps mit derselben Brand-YAML, derselben Datenquelle und laut eurem Plan.md wandern bereits Sektionen (Vorlaufzeit/Storno, Daily Occupancy) von der einen in die andere. EIN Tool, EIN Deployment, EIN Login wäre der echte Gewinn.

**Zweite Kernerkenntnis:** Die teuerste gemeinsame Arbeit beider Optionen ist identisch — **alle ~40 matplotlib-Charts müssen sowieso zu Plotly umgeschrieben werden** (Dash rendert nur Plotly). Diese Arbeit ist zu ~95 % zwischen beiden Welten portabel (`go.Figure` ist `go.Figure`). Plotly-first in Streamlit ist also **kein Umweg**, selbst wenn später Dash kommt.

---

## 1 · Performance-Faktencheck (gemessen, echter Snapshot)

| Messung | Ergebnis |
|---|---|
| matplotlib Pace-Chart → PNG (Status quo, pro Chart pro Cache-Miss) | **103 ms**, 37 KB |
| Plotly Pace-Chart → Figure + JSON | **2,1 ms**, 4 KB |
| Plotly Daily-Occupancy (92 Tage × 3 LOS gestapelt — größter Chart der App) | **2,4 ms**, 12 KB |
| Plotly Heatmap Standort × Monat (11 × 36) | **1,0 ms**, 15 KB |
| Typischer Rerun-Datenteil (Periodenfilter + Channel-Aggregation, 306k Zeilen) | **9,7 ms** |
| Snapshot im RAM (deep, object-Strings) | **2.047 MB** ⚠️ |

**Interpretation:**

1. **Was die App heute langsam anfühlt, ist matplotlib + das Rerun-Modell, nicht die Daten.** 100+ ms pro Chart × 5 Sektionen sichtbar = die halbe Sekunde, die man spürt. Genau dafür wurde der 200-Zeilen-PNG-Cache gebaut (mit all seinen Key-Fallen aus dem Review).
2. **Plotly macht das Problem 50× kleiner statt größer.** Eure Charts sind aggregiert winzig (12 Balken, 9-Zellen-Heatmaps, 92-Punkte-Serien). Die Sorge „Plotly wird Streamlit langsam machen" trifft auf Apps mit 100k-Punkte-Scatterplots zu — nicht auf euch. Figuren müssen nicht einmal gecacht werden; der PNG-Cache kann ersatzlos weg. Bei jedem Rerun gehen ein paar KB JSON über den (bereits konfigurierten) Websocket — vernachlässigbar.
3. **Das Rerun-Problem löst `st.fragment`** (seit 1.37 stabil, steht als Kommentar schon in eurem pyproject): Sektionen rerendern isoliert, ein Toggle-Klick rechnet nicht mehr die ganze Seite.
4. **Der echte Performance-Befund ist der RAM:** 32 MB Parquet werden im Speicher zu **2 GB**, weil fast alle String-Spalten `object`-dtype sind. Für Streamlit (ein Prozess, `cache_resource` teilt) tragbar; für Dash mit gunicorn-Multi-Worker wären es **2 GB × Worker**. Fix ist framework-unabhängig und billig: String-Spalten beim Snapshot-Schreiben auf `category` casten → geschätzt 5–10× kleiner, schnellere groupbys obendrein. **Das sollte vor jeder Migration passieren und nützt beiden Optionen.**

---

## 2 · Caching: die ehrliche Gegenüberstellung

**Streamlit (Status quo nach den Fixes vom 13.07.):** funktioniert. `cache_resource` für den Snapshot, `cache_data` für Tabellen, Signatur-Invalidierung repariert. Mit Plotly entfällt die dritte Schicht (PNG-Session-Cache) komplett — *weniger* Caching-Komplexität als heute, nicht mehr. Restrisiko: die bekannten `_`-Parameter-Fallen bei neuen cache_data-Funktionen (Team kennt sie jetzt).

**Dash (wie in OverbookingAnalyse gebaut):** Caching ist Handarbeit, aber euer Muster dort ist solide: `lru_cache(maxsize=1)` auf den unveränderlichen Parquet-Load + Versions-`dcc.Store` zum Invalidieren + Background-Callbacks für den Refresh. Der Unterschied zur Revenue-App: Overbooking hat EIN festes 14-Tage-Fenster — die Revenue-App hat **frei parametrisierte Filter** (Perioden × Standorte × Toggles). Dafür braucht Dash keyed Memoization (`flask-caching` oder `lru_cache` mit hashbaren Args) — machbar, aber genau die Fehlerklasse, die wir in Streamlit gerade zweimal gefixt haben, baut man sich hier neu von Hand. Dash rechnet dafür **nur den betroffenen Callback** statt der ganzen Seite — feiner granular als Streamlit, auch mit Fragments.

**Fazit Caching:** kein Sieger. Streamlit = fertige Semantik mit bekannten Fallen; Dash = volle Kontrolle mit Eigenbau-Pflicht. Die Sorge „Caching-Probleme bei Plotly-in-Streamlit" ist unbegründet — es wird simpler als heute.

---

## 3 · Was aus der Overbooking-Dash-App wirklich wiederverwendbar ist

Ich habe `dash_app/` komplett gelesen. Qualität ist hoch (Pages-Router, dash-mantine-components 2.x, AG Grid, Background-Callback-Manager mit Diskcache/Celery-Umschaltung, sauberes Store-Ownership). Konkret übernehmbar:

| Baustein | Wiederverwendung |
|---|---|
| `app.py` App-Factory (Pages, MantineProvider, Navbar, gunicorn-`server`) | ✅ 1:1 als Shell |
| `theme.py` + `assets/brand.css` (liest dieselbe `stayery_brand.yaml`!) | ✅ 1:1 |
| `brand_figure()` Plotly-Defaults | ✅ 1:1 — nützt sogar der Streamlit-Option |
| KPI-Tiles, `_tile`/`_graph_tile`-Cards, Filter-Patterns (`panels.py`, SegmentedControls) | ✅ als Muster/Komponenten |
| AG-Grid-Column-Defs + Row-Selection-Drilldown | ✅ als Muster — ersetzt `st.dataframe`+Split-View, wird dabei besser |
| Background-Callback-Muster (`jobs.py`, `data_update.py`) | ✅ löst die „Daten aktualisieren"-Seite mit Fortschritt — der sonst schwierigste Teil einer Dash-Migration ist bei euch schon gelöst |
| Seitenlogik (Occupancy, Model-Performance …) | ❌ domänenspezifisch |

Aus **StreamlitRevenue** überlebt eine Migration: der komplette `src/revenueblindspots`-Layer (bewusst streamlit-frei), die Tabellen-Builder in `global_tables`/`chart_data` (Decorator-Tausch nötig), Konfigs, Doku-Inhalte. **Neu schreiben:** alle 8 Seiten-Layouts + Callbacks (~6–7k LOC), Notepad, Markdown-Export, Lazy-Sections-Äquivalent, Filter-Persistenz (→ `dcc.Store`).

---

## 4 · Aufwand & Risiko (Schätzungen — bitte als Bandbreiten lesen)

| | **Option B: Plotly + Fragments in Streamlit** | **Option A: Voll-Migration Dash** |
|---|---|---|
| Kern-Aufwand | Top-5-Charts 2–3 Tage; alle Charts + Fragments + PNG-Cache-Rückbau **~1,5–2,5 Wochen** | Parität aller 8 Seiten **~5–8 Wochen** (ein Dev mit eurer Dash-Erfahrung; inkl. Test/Abnahme) |
| Export-Berichte (Markdown mit Chart-Bildern) | Plotly braucht `kaleido` für PNG-Einbettung (+1 Dependency) | komplett neu zu bauen |
| Regression-Risiko | klein — Datenlogik unangetastet, Chart für Chart abnehmbar | hoch — genau die Fehlerklasse „Neuimplementierung weicht ab" (A1–A7) entsteht bei Rewrites; Abnahme gegen Alt-App nötig |
| Team-Fit | Streamlit-Muster etabliert | Dash-Kompetenz nachweislich vorhanden (Overbooking-App), aber Callback-Modell ist die steilere Lernkurve für Neue |
| Deployment | unverändert | gunicorn hinter demselben Traefik/ForwardAuth — unproblematisch; RAM-Thema (Kap. 1.4) vorher lösen |
| Was danach besser ist | Interaktivität, weniger Cache-Code | + feingranulare Reaktivität, AG Grid, natives URL-Routing/Deep-Links, EIN Tool mit Overbooking |

**Strangler-Option statt Big Bang:** Traefik routet heute schon pfadbasiert. Beide Apps können parallel laufen (`/_streamlit` + `/overbooking`), und die Revenue-Seiten können **einzeln** in die Dash-App umziehen (B2B/Promo zuerst — tabellenlastig, AG Grid glänzt; Standort-Analyse zuletzt und dabei gleich nach eurem Plan.md restrukturiert). Kein Stichtag, jederzeit stoppbar.

---

## 5 · Empfehlung

1. **Sofort, framework-unabhängig:** Snapshot-Spalten auf `category` casten (2-GB-RAM-Fix) — Voraussetzung für alles Weitere.
2. **Option B jetzt starten** (Plotly + `st.fragment`, beginnend mit Pace/Scorecard/Daily-Occ als Spike): beseitigt nachweislich ~90 % der gefühlten Trägheit in Tagen statt Wochen, und die Chart-Arbeit ist zu ~95 % nach Dash portabel — kein verlorener Aufwand.
3. **Die Dash-Frage als Produktentscheidung treffen, nicht als Performance-Entscheidung:** Wollt ihr Revenue-Analytics und Overbooking langfristig als EIN Tool? Wenn ja → nach dem Plotly-Spike seitenweise Migration per Strangler-Pattern (Reihenfolge: B2B/Promo → Pickup → Global → Standort inkl. Plan.md-Restrukturierung → Daten-Update auf euer Background-Callback-Muster). Wenn nein → Option B genügt; Deep-Links und globaler Filter-Kontext (euer Plan.md Hebel 2+3) sind auch in Streamlit machbar.

*Nicht bewertet (fehlende Grundlage): tatsächliche Nutzerzahlen/Gleichzeitigkeit — bei >10 parallelen Vielklickern würde Dashs Callback-Modell stärker wiegen; bei 2–5 Analysten ist es egal.*
