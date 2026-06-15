"""RevenueBlindSpots - Streamlit App Entry Point. Landing-Page: Snapshot-Status, Navigation, Standort-Verwaltung."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

import streamlit as st

sys.path.insert(0, str(_REPO_ROOT / "streamlit_app"))
from components.brand import hero, inject_brand_css, sync_snapshot_override

sync_snapshot_override()

st.set_page_config(
    page_title="Stayery Revenue Analytics",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_brand_css()

hero(
    eyebrow="Stayery · Revenue Analytics",
    title="Self-Service-Analytics für RM & B2B-Outreach",
    subtitle="Wähl links eine Analyse, setze Filter, lade am Ende den Bericht "
    "als Markdown für Notion herunter - oder push einzelne Sektionen "
    "ins Notepad und nimm nur das mit was du brauchst.",
)

# ---------- Snapshot-Status ----------------------------------------------
st.subheader("Datenstand")

from components import cached_data as _CD

meta = _CD.get_metadata()
if not meta:
    st.error(
        "**Kein Snapshot gefunden.** Bitte einmal die `Daten aktualisieren` Page "
        "aufrufen. Bis dahin können die Analyse-Pages keine Daten laden."
    )
else:
    refreshed_at = str(meta.get("refreshed_at", "?"))[:19].replace("T", " ")
    n_res = meta.get("reservations", {}).get("rows", 0)
    n_nig = meta.get("timeslices", {}).get("rows", 0)
    earliest = meta.get("reservations", {}).get("earliest", "?")[:10]
    latest = meta.get("reservations", {}).get("latest", "?")[:10]
    n_props = len(meta.get("properties", []))

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Letzter Refresh", refreshed_at)
    col2.metric("Reservierungen", f"{n_res:,}".replace(",", "."))
    col3.metric("Nächte", f"{n_nig:,}".replace(",", "."))
    col4.metric("Standorte", n_props)

    st.caption(f"Anreise-Range: **{earliest}** bis **{latest}**")

st.divider()

# ---------- Pages overview ------------------------------------------------
st.subheader("Verfügbare Analysen")

cols = st.columns(2)
with cols[0]:
    st.markdown(
        """
        ### Daten aktualisieren
        Daten aus BigQuery ziehen, engineered + fuzzy-clustern, als Parquet
        speichern. **Voraussetzung für alle anderen Pages. Von Admin durchgeführt.**
        """
    )
    st.page_link("pages/0_Daten_Aktualisieren.py", label="→ Daten Aktualisieren")

    st.markdown(
        """
        ### Standort-Analyse
        Tiefer Einzelblick auf einen Standort. KPIs, Pace,
        Heatmaps, LOS, Channel-Mix, Firmenkunden, Top-Vertragscodes.
        """
    )
    st.page_link("pages/1_Standort_Analyse.py", label="→ Standort-Analyse öffnen")

    st.markdown(
        """
        ### Global Report
        Standortübergreifender Quartal-Recap mit IST vs. PLAN vs. Vorjahr.
        Auto-Alerts, Pace-by-Month, Heatmaps, Top-Movers.
        """
    )
    st.page_link("pages/2_Global_Report.py", label="→ Global Report öffnen")

with cols[1]:
    st.markdown(
        """
        ### B2B Deep-Dive
        Zwei lange Tabellen über die Historie: `corporateCode` und Firmen
        (fuzzy-geclustert). Multi-Sheet Excel-Export.
        """
    )
    st.page_link("pages/3_B2B_Deepdive.py", label="→ B2B Deep-Dive öffnen")

    st.markdown(
        """
        ### Code Deep-Dive
        Eine konkrete Firma im 360°-Blick: Revenue-Verlauf, Channel-Evolution,
        Stay-Pattern, Storno-Verhalten, Future-Pipeline.
        """
    )
    st.page_link("pages/4_Code_Deepdive.py", label="→ Code Deep-Dive öffnen")


st.divider()

# ---------- Standort-Verwaltung -------------------------------------------
st.subheader("Standorte")
st.caption(
    "Hotel-Metadaten (Stadt, Units, Bundesland) liegen in "
    "`configs/locations.yaml`. "
    "Neue Standorte - unten YAML-Snippet generieren und in die Datei einfügen (Admin)."
)

import yaml as _yaml

_LOC_PATH = _REPO_ROOT / "configs" / "locations.yaml"
with _LOC_PATH.open(encoding="utf-8") as fh:
    _locs = (_yaml.safe_load(fh) or {}).get("locations", [])

import pandas as _pd

_loc_df = _pd.DataFrame(
    [
        {
            "Code": loc["hotel_code"],
            "Stadt": loc.get("city", ""),
            "Neighborhood": loc.get("neighborhood") or "-",
            "Bundesland": loc.get("bundesland", ""),
            "Units": loc.get("units_total", 0),
            "Eröffnet": str(loc.get("opening_date") or "TBD"),
        }
        for loc in _locs
    ]
)
st.dataframe(_loc_df, hide_index=True, use_container_width=True, height=320)


with st.expander("➕ Neuen Standort hinzufügen", expanded=False):
    st.markdown(
        "Felder ausfüllen & unten erscheint das YAML-Snippet zum Kopieren in "
        "`configs/locations.yaml`. Danach einmal **Daten aktualisieren** ausführen, "
        "damit BigQuery den neuen Code mit zieht."
    )
    c1, c2 = st.columns(2)
    with c1:
        new_code = (
            st.text_input("Hotel-Code (6 Buchstaben)", value="", placeholder="z.B. FTH_HA")
            .strip()
            .upper()
        )
        new_city = st.text_input("Stadt", value="", placeholder="z.B. Fürth").strip()
        new_neigh = st.text_input(
            "Neighborhood (optional)", value="", placeholder="z.B. Innenstadt"
        ).strip()
    with c2:
        _BL = [
            "BE",
            "BW",
            "BY",
            "HB",
            "HE",
            "HH",
            "MV",
            "NI",
            "NW",
            "RP",
            "SH",
            "SL",
            "SN",
            "ST",
            "TH",
            "BB",
        ]
        new_bl = st.selectbox("Bundesland", options=_BL, index=2)
        new_units = st.number_input(
            "Units (Apartments)", min_value=1, max_value=999, value=60, step=1
        )
        new_open = st.date_input("Eröffnungsdatum", value=None, help="Leer lassen = TBD")

    if new_code and new_city:
        existing_codes = {loc["hotel_code"] for loc in _locs}
        if new_code in existing_codes:
            st.warning(f"!Code `{new_code}` existiert bereits in der YAML.")
        else:
            neigh_line = f"    neighborhood: {new_neigh}" if new_neigh else "    neighborhood: null"
            open_line = (
                f"    opening_date: {new_open.isoformat()}"
                if new_open
                else "    opening_date: null   # TBD"
            )
            snippet = (
                f"  - hotel_code: {new_code}\n"
                f"    city: {new_city}\n"
                f"{neigh_line}\n"
                f"    bundesland: {new_bl}\n"
                f"{open_line}\n"
                f"    units_total: {new_units}\n"
                f'    notes: ""\n'
            )
            st.markdown(
                "**YAML-Snippet** (kopieren + ans Ende von `locations:` in der YAML einfügen):"
            )
            st.code(snippet, language="yaml")
            st.caption(
                f"Pfad: `{_LOC_PATH}` - danach **Daten aktualisieren** ausführen, "
                f"damit `{new_code}` aus BigQuery gezogen wird."
            )
