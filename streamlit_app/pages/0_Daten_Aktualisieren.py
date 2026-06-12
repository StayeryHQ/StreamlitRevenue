"""Daten aktualisieren - direkter Draht zu BigQuery.

Die Page macht drei Dinge:
  1. Zeigt den Status des aktuellen lokalen Parquet-Snapshots an (was ist da,
     wie alt, wie viele Reservierungen, Stand der Planzahlen).
  2. Voll-Refresh: ruft `run_refresh()` auf - BigQuery-Pull (Reservations +
     Timeslices + Planzahlen), Feature-Engineering, Parquets schreiben,
     Streamlit-Caches leeren.
  3. Plan-Refresh: ruft `refresh_plan()` auf - pullt nur
     `ref_tables.plan` (Sekunden) und schreibt `plan.parquet`.

Unten ist der aktive Plan einsehbar (Pivot Hotel × Monat + Rohdaten).

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
from components import cached_data as CD
from components.brand import hero
from revenueblindspots import helpers as H
from revenueblindspots.refresh import refresh_plan, run_refresh

# ============================== Page setup =================================
st.set_page_config(
    page_title="Daten aktualisieren · Stayery",
    page_icon="🔄",
    layout="wide",
)
inject_brand_css()
CD.keep_session_state_alive()

hero(
    eyebrow="Daten",
    title="Daten aktualisieren",
    subtitle="Snapshot + Planzahlen anzeigen oder per Klick neu aus BigQuery ziehen.",
)


def _clear_caches() -> None:
    """Analyse-Pages sehen sonst noch die alten Daten."""
    st.cache_data.clear()
    for k in list(st.session_state.keys()):
        if str(k).startswith("_stayery_style_applied") or str(k).startswith("_chart_"):
            del st.session_state[k]


# ============================== Aktueller Stand ===========================
st.subheader("Aktueller Stand")
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
    plan_meta = meta.get("plan") or {}
    if plan_meta:
        st.caption(
            f"Planzahlen: Stand **{str(plan_meta.get('refreshed_at', '?'))[:10]}** · "
            f"{plan_meta.get('hotels', '?')} Hotels · "
            f"{str(plan_meta.get('earliest', '?'))[:7]} → {str(plan_meta.get('latest', '?'))[:7]}"
        )
    else:
        st.caption("Planzahlen: **noch nicht gezogen** - unten 'Nur Planzahlen aktualisieren'.")
else:
    alert_card(
        "Noch kein Snapshot vorhanden. Refresh unten starten um den ersten zu erstellen.",
        kind="info",
    )

st.divider()


# ============================== Refresh-Konfiguration =====================
st.subheader("Voll-Refresh aus BigQuery")
st.caption("Reservations + Timeslices + Planzahlen in einem Rutsch. Dauert 5-15 Minuten.")

c1, c2 = st.columns(2)
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

all_props = H.all_properties()
properties = st.multiselect(
    "Standorte", options=all_props, default=all_props,
    help="Welche Standorte mit pullen.",
)

st.caption(
    f"BigQuery-Pull deckt: "
    f"**{(pd.Timestamp.today() - pd.DateOffset(years=lookback_years)).date()}** "
    f"bis **offen** (alle zukünftigen Anreisen/Nächte, kein Future-Cap)"
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


def _configured_dir() -> str:
    return (
        st.session_state.get("snapshot_dir_override")
        or _os.environ.get("STAYERY_SNAPSHOT_DIR")
        or "data"
    )


# ============================== Refresh-Buttons ===========================
col_full, col_plan = st.columns([1, 1])
with col_full:
    run = st.button(
        "Voll-Refresh starten",
        type="primary",
        help="Pullt Reservations + Timeslices + Plan, engineert, schreibt die Parquets.",
    )
with col_plan:
    run_plan_only = st.button(
        "Nur Planzahlen aktualisieren",
        help="Pullt nur `ref_tables.plan` und schreibt plan.parquet - dauert Sekunden.",
    )

if run or run_plan_only:
    progress_bar = st.progress(0.0, text="Starte …")
    log = st.empty()
    status_msgs: list[str] = []

    def push(msg: str, pct: "float | None" = None) -> None:
        status_msgs.append(msg)
        log.markdown("\n\n".join(f"- {m}" for m in status_msgs))
        if pct is not None:
            progress_bar.progress(pct, text=msg)

    try:
        if run:
            meta = run_refresh(
                lookback_years=int(lookback_years),
                fuzz_threshold=int(fuzz_threshold),
                properties=properties,
                snapshot_dir=_configured_dir(),
                refreshed_via="streamlit_app",
                progress=push,
            )
            _clear_caches()
            progress_bar.empty()
            st.success(
                f"Refresh fertig. "
                f"{meta['reservations']['rows']:,} Reservations, "
                f"{meta['timeslices']['rows']:,} Timeslices, "
                f"{len(meta['properties'])} Standorte. Planzahlen inklusive."
                .replace(",", ".")
            )
        else:
            plan_meta = refresh_plan(
                snapshot_dir=_configured_dir(),
                refreshed_via="streamlit_app",
                progress=push,
            )
            _clear_caches()
            progress_bar.empty()
            st.success(
                f"Planzahlen aktualisiert: {plan_meta['hotels']} Hotels, "
                f"{plan_meta['rows']} Zeilen, "
                f"{str(plan_meta.get('earliest', '?'))[:7]} → "
                f"{str(plan_meta.get('latest', '?'))[:7]}."
            )

    except Exception as e:
        progress_bar.empty()
        st.error(f"**{type(e).__name__}**: {e}")
        with st.expander("Stacktrace"):
            import traceback
            st.code(traceback.format_exc())


# ============================== Planzahlen einsehen =======================
st.divider()
st.subheader("Planzahlen")

plan_df = CD.get_plan_df()
if plan_df.empty:
    alert_card(
        "Noch keine Planzahlen im Snapshot. Oben 'Nur Planzahlen aktualisieren' "
        "klicken (oder Voll-Refresh).",
        kind="info",
    )
else:
    _months = pd.to_datetime(plan_df["month"]).dt.to_period("M")
    n_hotels = int(plan_df["property_code"].nunique())
    n_months = int(_months.nunique())
    c1, c2, c3 = st.columns(3)
    c1.metric("Hotels", n_hotels)
    c2.metric("Monate", n_months)
    c3.metric("Total-PLAN (€)", H.fmt_eur(float(plan_df["revenue"].fillna(0).sum())))

    pivot = (
        plan_df.assign(Monat=_months.astype(str))
        .pivot_table(index="property_code", columns="Monat", values="revenue", aggfunc="sum")
        .fillna(0)
    )
    pivot["Total (€)"] = pivot.sum(axis=1)
    display = pivot.copy()
    for c in display.columns:
        display[c] = display[c].map(H.fmt_eur)
    with st.expander(f"Plan ansehen ({n_hotels} Hotels × {n_months} Monate)", expanded=False):
        st.dataframe(display, use_container_width=True)

    CD.data_table_expander(
        plan_df,
        title="Rohdaten (inkl. RevPAR, Sold-/House-/OOO-Counts)",
        filename="planzahlen",
    )
