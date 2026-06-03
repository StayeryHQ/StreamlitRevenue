# RevenueBlindSpots — Streamlit App

Self-Service-Web-App für Stayery-Manager. Wer keinen BigQuery-Zugang hat
öffnet die App, setzt Filter, lässt die Analyse durchlaufen, schreibt
eigene Notizen rein und lädt einen Notion-fertigen Markdown-Report.

## Struktur

```
streamlit_app/
  Home.py                          ← Entry: Begrüßung + Snapshot-Status
  pages/
    1_Standort_Analyse.py          ← POC, voll funktionsfähig
    2_Global_Report.py             ← Day 2
    3_B2B_Deepdive.py              ← Day 2
    4_Code_Deepdive.py             ← Day 2
    5_Plan_Upload.py               ← Phase 5
  components/
    alerts.py                      ← Highlight-Boxen
    section.py                     ← Markdown-Header-Wrapper
    notes.py                       ← User-Notiz-Felder (session-state)
    export.py                      ← Markdown-Export für Notion
.streamlit/config.toml             ← schwarz-weiß-Theme
requirements-app.txt               ← Dependencies (Streamlit Cloud liest das)
```

## Lokal starten

```bash
# Im Repo-Root
uv pip install -r requirements-app.txt        # oder: pip install …
streamlit run streamlit_app/Home.py
```

Standardmäßig läuft die App auf <http://localhost:8501>.

**Voraussetzung:** ein Snapshot muss vorliegen unter `data/reservations.parquet`
+ `data/timeslices.parquet` + `data/metadata.json`. Wenn nicht, einmal
`notebooks/00_refresh_snapshot.ipynb` durchlaufen lassen.

## Deployment auf Streamlit Cloud (Day 2)

1. Repo auf GitHub pushen (private OK)
2. <https://share.streamlit.io> → New App → Repo + Branch wählen
3. Main file path: `streamlit_app/Home.py`
4. Python version: 3.11 oder 3.12
5. Requirements file: `requirements-app.txt`
6. Secrets (kommt in den Streamlit-Cloud-Dialog):
   - GCP-Service-Account-JSON für Drive- / GCS-Snapshot-Zugriff
   - Notion-API-Token (Phase 2)
7. Restrict-Access: `@stayery.com` Google-Emails (Settings → Sharing)

## Was die App heute kann (Day 1)

- ✓ Schwarz-weiß-Theme, kein Streamlit-Branding
- ✓ Multi-Page-Sidebar
- ✓ Snapshot-Status oben auf der Home
- ✓ Standort-Analyse vollständig (Filter, KPIs, Channel-Mix, LOS, Storno, Top-Firmen, Top-Codes)
- ✓ Loading-Status mit Section-Progress
- ✓ Auto-erkannte Highlights / Alarme oben auf der Page
- ✓ Notiz-Felder pro Sektion mit Session-State
- ✓ Markdown-Download für Notion (mit Auto-Insights, Bildern als base64, Tabellen, User-Notizen)
- ✓ Copy-to-Clipboard-Block für schnelles Einfügen

## Was Day 2 kommt

- Global Report Page (Recap, Scorecard, Pace-to-Plan)
- B2B Deep-Dive Page
- Code Deep-Dive Page
- Excel-Plan-Upload
- Notion-API-Block-Export
- Deployment auf Streamlit Cloud + Google SSO
