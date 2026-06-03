"""Snapshot-Refresh - direkter Draht zu BigQuery.

Die Page macht genau zwei Dinge:
  1. Zeigt den Status des aktuellen lokalen Parquet-Snapshots an (was ist da,
     wie alt, wie viele Reservierungen).
  2. Auf Klick auf den Refresh-Button: ruft `run_refresh()` auf, das BigQuery
     anzapft, Feature-Engineering macht, das neue Parquet schreibt, und die
     Streamlit-Caches leert.

Auth läuft automatisch:
  * Lokal auf dem Mac → gcloud Application Default Credentials
  * Im Docker → Env-var `GCP_SERVICE_ACCOUNT_JSON` (oder
    `GOOGLE_APPLICATION_CREDENTIALS`-File)
Wenn keine Credentials da sind, scheitert der Refresh-Klick mit klarer
Fehlermeldung - kein separater "Connection-Test"-Button nötig.
"""

from __future__ import annotations

import os as _os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT / "streamlit_app"))

import pandas as pd
import streamlit as st

from components import alert_card, inject_brand_css
from components.brand import hero
from revenueblindspots import helpers as H
from revenueblindspots.refresh import run_refresh

# ============================== Page setup =================================
st.set_page_config(
    page_title="Refresh-Snapshot · Stayery",
    page_icon="🔄",
    layout="wide",
)
inject_brand_css()
from components import cached_data as _CD_KEEP

_CD_KEEP.keep_session_state_alive()

hero(
    eyebrow="Snapshot",
    title="Refresh aus BigQuery",
    subtitle="Aktuellen Snapshot anzeigen oder per Klick neu aus BigQuery ziehen.",
)


# ============================== Aktueller Snapshot ========================
st.subheader("Aktueller Snapshot")
meta = H.load_snapshot_metadata()
if meta:
    refreshed_at = str(meta.get("refreshed_at", "?"))[:19].replace("T", " ")
    n_res = meta.get("reservations", {}).get("rows", 0)
    n_nig = meta.get("timeslices", {}).get("rows", 0)
    earliest = meta.get("reservations", {}).get("earliest", "?")[:10]
    latest = meta.get("reservations", {}).get("latest", "?")[:10]
    via = meta.get("refreshed_via", "?")
    c1, c2, c3 = st.columns(3)
    c1.metric("Letzter Refresh", refreshed_at)
    c2.metric("Reservierungen", f"{n_res:,}".replace(",", "."))
    c3.metric("Anreise-Range", f"{earliest} → {latest}")
    st.caption(f"Quelle des letzten Refresh: `{via}` · {n_nig:,} Timeslices"
                .replace(",", "."))
else:
    alert_card(
        "Noch kein Snapshot vorhanden. Refresh unten starten um den ersten zu erstellen.",
        kind="info",
    )

st.divider()


# ============================== Refresh-Konfiguration =====================
st.subheader("Refresh aus BigQuery")

c1, c2, c3 = st.columns(3)
with c1:
    lookback_years = st.number_input(
        "Lookback (Jahre)",
        min_value=1, max_value=10, value=3, step=1,
        help="Wie weit zurück Reservations + Timeslices aus BigQuery ziehen.",
    )
with c2:
    fuzz_threshold = st.slider(
        "Fuzzy-Cluster-Schwelle",
        min_value=70, max_value=95, value=85, step=5,
        help="rapidfuzz token_sort_ratio. Höher = strenger.",
    )
with c3:
    future_buffer_days = st.number_input(
        "Future-Buffer (Tage)",
        min_value=0, max_value=365, value=180, step=30,
        help="Wie weit in die Zukunft Reservations ziehen (Pipeline-Sicht).",
    )

all_props = H.all_properties()
properties = st.multiselect(
    "Standorte", options=all_props, default=all_props,
    help="Welche Standorte mit pullen.",
)

st.caption(
    f"BigQuery-Pull deckt: "
    f"**{(pd.Timestamp.today() - pd.DateOffset(years=lookback_years)).date()}** "
    f"bis **{(pd.Timestamp.today() + pd.Timedelta(days=future_buffer_days)).date()}**"
)

# Snapshot-Pfad - in Expander damit die Default-Sicht schlank bleibt.
with st.expander("Erweitert: Snapshot-Pfad", expanded=False):
    _default_loc = (
        st.session_state.get("snapshot_dir_override")
        or _os.environ.get("STAYERY_SNAPSHOT_DIR")
        or "data"
    )
    snapshot_location = st.text_input(
        "Wohin schreiben",
        value=_default_loc,
        help="Default = `data/` im Repo. Akzeptiert `gs://...`-URIs für GCS.",
        key="snapshot_location_input",
    )
    if snapshot_location.strip():
        st.session_state["snapshot_dir_override"] = snapshot_location.strip()
        _os.environ["STAYERY_SNAPSHOT_DIR"] = snapshot_location.strip()
    else:
        st.session_state.pop("snapshot_dir_override", None)
        _os.environ.pop("STAYERY_SNAPSHOT_DIR", None)

st.divider()


# ============================== Refresh-Button ============================
run = st.button(
    "Aus BigQuery ziehen",
    type="primary",
    help="Pullt aus BigQuery, engineert, schreibt das Parquet. "
          "Dauert 5-15 Minuten.",
)

if run:
    progress_bar = st.progress(0.0, text="Starte Refresh …")
    log = st.empty()
    status_msgs: list[str] = []

    def push(msg: str, pct: "float | None" = None) -> None:
        status_msgs.append(msg)
        log.markdown("\n\n".join(f"- {m}" for m in status_msgs))
        if pct is not None:
            progress_bar.progress(pct, text=msg)

    configured = (
        st.session_state.get("snapshot_dir_override")
        or _os.environ.get("STAYERY_SNAPSHOT_DIR")
        or "data"
    )

    try:
        meta = run_refresh(
            lookback_years=int(lookback_years),
            future_buffer_days=int(future_buffer_days),
            fuzz_threshold=int(fuzz_threshold),
            properties=properties,
            snapshot_dir=configured,
            refreshed_via="streamlit_app",
            progress=push,
        )

        # Caches leeren - Analyse-Pages sehen sonst noch den alten Snapshot.
        st.cache_data.clear()
        for k in list(st.session_state.keys()):
            if str(k).startswith("_stayery_style_applied") or str(k).startswith("_chart_"):
                del st.session_state[k]

        progress_bar.empty()
        st.success(
            f"Refresh fertig. "
            f"{meta['reservations']['rows']:,} Reservations, "
            f"{meta['timeslices']['rows']:,} Timeslices, "
            f"{len(meta['properties'])} Standorte."
            .replace(",", ".")
        )

    except Exception as e:
        progress_bar.empty()
        st.error(f"**{type(e).__name__}**: {e}")
        with st.expander("Stacktrace"):
            import traceback
            st.code(traceback.format_exc())
