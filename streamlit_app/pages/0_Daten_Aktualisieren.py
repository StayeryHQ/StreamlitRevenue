"""Daten aktualisieren.

Die Page macht drei Dinge:
  1. Zeigt den Status des aktuellen lokalen Parquet-Snapshots an (was ist da,
     wie alt, wie viele Reservierungen, Stand der Planzahlen).
  2. Voll-Refresh: startet `scripts/refresh_snapshot.py` als EIGENEN PROZESS -
     BigQuery-Pull (Reservations + Timeslices + Planzahlen),
     Feature-Engineering, Parquets schreiben. Der Fortschritt wird aus dem
     Subprozess gestreamt.
  3. Plan-Refresh: dasselbe Script mit `--plan-only` - pullt nur
     `ref_tables.plan` und schreibt `plan.parquet`.

Warum Subprozess (RAM-Postmortem F2): der Refresh baut den kompletten Datensatz
mehrfach parallel im Speicher auf. Lief das im Webserver-Prozess, riss der Peak
den ganzen Container mit - und der freigegebene Speicher kam anschließend nicht
ans Betriebssystem zurück. Ein Subprozess endet und gibt garantiert alles frei.
Die Streamlit-Caches werden VOR und NACH dem Refresh geleert (F3).

Unten ist der aktive Plan einsehbar (Pivot Hotel × Monat + Rohdaten).

Auth läuft automatisch:
  * Lokal auf dem Mac → gcloud Application Default Credentials
  * Im Docker → Env-var `GCP_SERVICE_ACCOUNT_JSON` (oder
    `GOOGLE_APPLICATION_CREDENTIALS`-File)
Wenn keine Credentials da sind, scheitert der Refresh-Klick mit klarer
Fehlermeldung.
"""

from __future__ import annotations

import json
import os as _os
import subprocess
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

# Der Refresh läuft NICHT mehr in diesem Prozess (F2) - siehe
# ``_run_refresh_subprocess`` weiter unten. ``run_refresh``/``refresh_plan``
# werden hier deshalb bewusst nicht mehr importiert.
_REFRESH_SCRIPT = _REPO_ROOT / "scripts" / "refresh_snapshot.py"
_PROGRESS_MARKER = "@@P@@"
_RESULT_MARKER = "@@RESULT@@"

# ============================== Page setup =================================
st.set_page_config(
    page_title="Daten aktualisieren",
    page_icon="🔄",
    layout="wide",
)
inject_brand_css()
CD.keep_session_state_alive()
CD.freshness_badge()  # Freshness-Ampel in der Sidebar

hero(
    eyebrow="Daten",
    title="Daten aktualisieren",
    subtitle="Snapshot + Planzahlen anzeigen oder per Klick neu aus BigQuery ziehen.",
)

st.caption(
    "**Logik:** Reservations nach `arrival ≥ Start` (offen in die Zukunft), "
    "Timeslices nach `StayDate ≥ Start`. Planzahlen aus dem "
    "Drive-Sheet `ref_tables.plan`. DHW Input Datei in BigQuery eingelesen. "
)


def _run_refresh_subprocess(extra_args: list[str], push) -> dict:
    """``scripts/refresh_snapshot.py`` als eigenen Prozess starten (F2).

    Vorher rief diese Seite ``run_refresh()`` direkt auf - also im selben
    Prozess, der auch die Seiten für alle anderen Nutzer ausliefert. Sämtliche
    Zwischenframes lagen damit im Speicher des Webservers, überlagert mit den
    Caches aller offenen Sessions. Und weil ein langlebiger Python-Prozess den
    freigegebenen Speicher nicht ans Betriebssystem zurückgibt, blieb der Server
    auch nach einem erfolgreichen Refresh dauerhaft aufgebläht.

    Als Subprozess entsteht der Peak in einem Prozess, der danach endet - das
    Betriebssystem holt sich alles zurück, ohne Allokator-Tricks.

    Der Fortschritt wird über ``@@P@@``-JSON-Zeilen auf stdout gestreamt und
    unverändert an ``push`` weitergereicht, sodass Progress-Bar und Log genauso
    aussehen wie vorher.

    Args:
        extra_args: CLI-Argumente hinter ``--json-progress``.
        push: ``(msg, pct) -> None`` - die Progress-Closure der Seite.

    Returns:
        Das Ergebnis-Dict des Scripts (``metadata``-Dict bzw. Plan-Block).

    Raises:
        FileNotFoundError: Wenn das Refresh-Script fehlt (Image ohne ``scripts/``).
        RuntimeError: Bei Exit-Code != 0 oder fehlendem Ergebnis; die Message
            enthält die letzten Ausgabezeilen des Subprozesses.
    """
    if not _REFRESH_SCRIPT.is_file():
        raise FileNotFoundError(
            f"Refresh-Script nicht gefunden: {_REFRESH_SCRIPT}\n\n"
            "Im Docker-Image muss `COPY scripts ./scripts` im Dockerfile stehen."
        )

    cmd = [sys.executable, "-u", str(_REFRESH_SCRIPT), "--json-progress", *extra_args]
    env = dict(_os.environ, PYTHONUNBUFFERED="1")

    proc = subprocess.Popen(
        cmd,
        cwd=str(_REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,   # Tracebacks landen im selben Strom
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )

    result: dict | None = None
    tail: list[str] = []
    try:
        for raw_line in proc.stdout:
            line = raw_line.rstrip("\n")
            if line.startswith(_PROGRESS_MARKER):
                try:
                    event = json.loads(line[len(_PROGRESS_MARKER):])
                except json.JSONDecodeError:
                    continue
                push(str(event.get("msg", "")), event.get("pct"))
            elif line.startswith(_RESULT_MARKER):
                try:
                    result = json.loads(line[len(_RESULT_MARKER):])
                except json.JSONDecodeError:
                    result = None
            elif line.strip():
                tail.append(line)
                del tail[:-80]   # nur die letzten 80 Zeilen aufheben
    finally:
        if proc.stdout is not None:
            proc.stdout.close()
        returncode = proc.wait()

    if returncode != 0 or result is None:
        detail = "\n".join(tail[-40:]) or "(keine Ausgabe)"
        raise RuntimeError(
            f"Refresh-Prozess beendet mit Exit-Code {returncode}.\n\n{detail}"
        )
    return result


# ============================== Aktueller Stand ===========================
st.subheader("Aktueller Stand")
meta = H.load_snapshot_metadata(st.session_state.get("snapshot_dir_override") or None)
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
        st.caption("Planzahlen: **noch nicht gezogen**, unten 'Nur Planzahlen aktualisieren'.")
else:
    alert_card(
        "Noch kein Snapshot vorhanden. Refresh unten starten um zu erstellen.",
        kind="info",
    )

st.divider()


# ============================== Refresh-Konfiguration =====================
st.subheader("Voll-Refresh aus BigQuery")
st.caption(
    "Reservations + Timeslices + Planzahlen gemeinsam. Läuft in einem eigenen "
    "Prozess, damit der Speicher-Peak den Webserver nicht mitreißt. "
    "Bitte während des Ladens nicht die Seite wechseln."
)

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
    f"bis **offen** (alle zukünftigen Anreisen/Nächte ohne future-cap)"
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
    # Override lebt NUR im Session-State (Review A12.8) - keine os.environ-
    # Mutation mehr, die alle gleichzeitigen User des Servers treffen würde.
    if snapshot_location.strip():
        st.session_state["snapshot_dir_override"] = snapshot_location.strip()
    else:
        st.session_state.pop("snapshot_dir_override", None)


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
        help="Pullt nur `ref_tables.plan` und schreibt plan.parquet.",
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

    # F3: Caches VOR dem Refresh leeren, nicht danach. Vorher lag der komplette
    # alte Snapshot (gemessen ~1,2 GB über alle cache_resource-Einträge) während
    # des gesamten Refreshs daneben im Speicher und hat den Peak mit nach oben
    # geschoben. Der Subprozess braucht die Caches des Webservers ohnehin nicht.
    push("Leere Caches vor dem Refresh …", 0.01)
    CD.purge_snapshot_caches()

    try:
        if run:
            args = [
                "--lookback-years", str(int(lookback_years)),
                "--fuzz-threshold", str(int(fuzz_threshold)),
                "--snapshot-dir", _configured_dir(),
                "--refreshed-via", "streamlit_app",
            ]
            if properties:
                args += ["--properties", *properties]
            meta = _run_refresh_subprocess(args, push)
            CD.purge_snapshot_caches()
            progress_bar.empty()
            st.success(
                f"Refresh fertig. "
                f"{meta['reservations']['rows']:,} Reservations, "
                f"{meta['timeslices']['rows']:,} Timeslices, "
                f"{len(meta['properties'])} Standorte. Planzahlen inklusive."
                .replace(",", ".")
            )
        else:
            plan_meta = _run_refresh_subprocess(
                [
                    "--plan-only",
                    "--snapshot-dir", _configured_dir(),
                    "--refreshed-via", "streamlit_app",
                ],
                push,
            )
            CD.purge_snapshot_caches()
            progress_bar.empty()
            st.success(
                f"Planzahlen aktualisiert: {plan_meta['hotels']} Hotels, "
                f"{plan_meta['rows']} Zeilen, "
                f"{str(plan_meta.get('earliest', '?'))[:7]} → "
                f"{str(plan_meta.get('latest', '?'))[:7]}."
            )

    except Exception as e:
        progress_bar.empty()
        # Der Subprozess ist beendet, sein Speicher ist zurück - aber der Server
        # hat evtl. schon wieder Caches aufgebaut. Aufräumen und weiter.
        CD.purge_snapshot_caches()
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
