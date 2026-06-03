"""Snapshot-Refresh-Pipeline - single source of truth.

Wird aufgerufen von:
  * ``scripts/refresh_snapshot.py``                    (CLI / GitHub Action)
  * ``streamlit_app/pages/0_Refresh_Snapshot.py``      (manueller UI-Override)
  * potenzielle weitere Caller (Docker-Cron, REST-Endpoint, …)

Caller-spezifische Unterschiede werden über zwei Parameter kontrolliert:

  * ``progress`` - eine Callback-Funktion ``progress(msg: str, pct: float | None)``.
    CLI passt ``print``-Wrapper, Streamlit passt eine Closure die st.progress
    + st.empty.markdown updated. Wenn None → silent.

  * ``refreshed_via`` - Freitext-Marker der im ``metadata.json`` landet, damit
    man später nachvollziehen kann wer den Snapshot geschrieben hat.

Auth-Quellen (in dieser Reihenfolge probiert):
  1. ``GCP_SERVICE_ACCOUNT_JSON`` env-var enthält JSON inline (GitHub Action,
     Docker-Secret).
  2. ``GOOGLE_APPLICATION_CREDENTIALS`` env-var zeigt auf ein Service-Account-File.
  3. gcloud Application Default Credentials (lokaler Dev nach
     ``gcloud auth application-default login``).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable

import pandas as pd

from . import helpers as H

# Optional[Callable[[str, float | None], None]]
ProgressCallback = Callable[[str, "float | None"], None]


# ============================== Auth ======================================
def get_bigquery_client():
    """Build a BigQuery client from the first available credential source."""
    from google.cloud import bigquery
    from google.oauth2 import service_account

    sa_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
    if sa_json:
        creds_info = json.loads(sa_json)
        creds = service_account.Credentials.from_service_account_info(creds_info)
        return bigquery.Client(credentials=creds, project=creds.project_id)

    sa_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if sa_file and Path(sa_file).exists():
        creds = service_account.Credentials.from_service_account_file(sa_file)
        return bigquery.Client(credentials=creds, project=creds.project_id)

    return bigquery.Client()


# ============================== Refresh ===================================
def _noop_progress(_msg: str, _pct: "float | None" = None) -> None:
    """Default no-op progress callback wenn der Caller keinen angibt."""
    pass


def run_refresh(
    lookback_years: int = 3,
    future_buffer_days: int = 180,
    fuzz_threshold: int = 85,
    properties: list[str] | None = None,
    snapshot_dir: "str | Path | None" = None,
    refreshed_via: str = "refresh.run_refresh",
    progress: ProgressCallback | None = None,
) -> dict:
    """Pull aus BigQuery, engineer, fuzzy-cluster, snapshot schreiben.

    Args:
        lookback_years: Wie viele Jahre rückwärts pullen (default 3).
        future_buffer_days: Wie viele Tage in die Zukunft pullen (default 180,
            für die Pipeline-Sicht in Code Deep-Dive).
        fuzz_threshold: rapidfuzz token_sort_ratio - höher = strenger (default 85).
        properties: Liste von hotel_codes. None oder leer → alle aus locations.yaml.
        snapshot_dir: Ziel-Pfad. None → ``$STAYERY_SNAPSHOT_DIR`` env-var, sonst
            ``data/`` im Repo. ``gs://``-URIs werden remote behandelt.
        refreshed_via: Marker im metadata.json (z.B. ``streamlit_app``,
            ``scripts/refresh_snapshot.py``, ``github_action``).
        progress: Optional ``(msg, pct_or_none) -> None``. Wird nach jedem
            Pipeline-Schritt aufgerufen. None → silent.

    Returns:
        Das ``metadata.json``-Dict (siehe ``H.save_snapshot``).

    Raises:
        Was auch immer ``bigquery.Client.query`` oder die engineering-Funktionen
        an Exceptions werfen. Caller ist verantwortlich für try/except.
    """
    from google.cloud import bigquery

    progress = progress or _noop_progress
    _REPO_ROOT = Path(__file__).resolve().parents[2]

    # ----- 1. Auth ----------
    progress("Authentifiziere mit BigQuery …", 0.05)
    client = get_bigquery_client()
    progress(f"Authentifiziert (Projekt {client.project})", 0.10)

    # ----- 2. Properties + Pull-Window ----------
    if not properties:
        properties = H.all_properties()
    pull_end = pd.Timestamp.today().normalize() + pd.Timedelta(days=future_buffer_days)
    pull_start = (pull_end - pd.DateOffset(years=lookback_years)).normalize()

    # ----- 3. Reservations pull ----------
    progress(
        f"Ziehe Reservations ({pull_start.date()} – {pull_end.date()}) …", 0.15
    )
    _RES_COLS = ",\n    ".join(H.RES_COLUMNS)
    res_sql = f"""
    SELECT
        {_RES_COLS}
    FROM `{H.RES_TABLE}`
    WHERE property_code IN UNNEST(@properties)
      AND DATE(arrival) BETWEEN @start AND @end
    """
    params = [
        bigquery.ArrayQueryParameter("properties", "STRING", properties),
        bigquery.ScalarQueryParameter("start", "DATE", pull_start.date()),
        bigquery.ScalarQueryParameter("end", "DATE", pull_end.date()),
    ]
    cfg = bigquery.QueryJobConfig(query_parameters=params)
    t0 = time.time()
    raw_res = client.query(res_sql, job_config=cfg).to_dataframe()
    progress(
        f"✓ {len(raw_res):,} Reservations geladen ({time.time() - t0:.1f}s)", 0.35
    )

    # ----- 4. Timeslices pull ----------
    progress("Ziehe Timeslices …", 0.40)
    _SLICE_COLS = ",\n    ".join(H.SLICE_COLUMNS)
    nig_sql = f"""
    SELECT
        {_SLICE_COLS}
    FROM `{H.SLICE_TABLE}`
    WHERE property_code IN UNNEST(@properties)
      AND serviceDate BETWEEN @start AND @end
    """
    cfg = bigquery.QueryJobConfig(query_parameters=params)
    t0 = time.time()
    raw_nig = client.query(nig_sql, job_config=cfg).to_dataframe()
    progress(
        f"✓ {len(raw_nig):,} Timeslices geladen ({time.time() - t0:.1f}s)", 0.55
    )

    # ----- 5. Engineering ----------
    progress("Feature-Engineering Reservations …", 0.60)
    t0 = time.time()
    res = pd.concat(
        [H.engineer_reservations(g, pc) for pc, g in raw_res.groupby("property_code")],
        ignore_index=True,
    )
    dropped_res = H.zero_night_drops()["reservations"]
    progress(
        f"✓ {len(res):,} Reservations engineered (drops {dropped_res}) "
        f"({time.time() - t0:.1f}s)",
        0.70,
    )

    progress("Feature-Engineering Timeslices …", 0.72)
    t0 = time.time()
    nig = pd.concat(
        [H.engineer_timeslices(g, pc) for pc, g in raw_nig.groupby("property_code")],
        ignore_index=True,
    )
    progress(f"✓ {len(nig):,} Timeslices engineered ({time.time() - t0:.1f}s)", 0.80)

    # ----- 6. Fuzzy-Cluster ----------
    progress("Fuzzy-Cluster der Firmennamen …", 0.82)
    t0 = time.time()
    H.add_firm_definitions(res, apply_fuzzy=True, fuzzy_threshold=int(fuzz_threshold))
    progress(f"✓ firm_by_* Spalten angelegt ({time.time() - t0:.1f}s)", 0.90)

    # ----- 7. Resolve snapshot target ----------
    if snapshot_dir is None:
        snapshot_dir = os.environ.get("STAYERY_SNAPSHOT_DIR") or str(_REPO_ROOT / "data")
    if isinstance(snapshot_dir, str) and snapshot_dir.startswith("gs://"):
        target: "str | Path" = snapshot_dir
    else:
        target = Path(snapshot_dir).expanduser()
        if not target.is_absolute():
            target = _REPO_ROOT / target
    progress(f"Schreibe Snapshot nach {target} …", 0.92)

    # ----- 8. Save ----------
    meta = H.save_snapshot(
        res,
        nig,
        snapshot_dir=target,
        lookback_years=int(lookback_years),
        extra_metadata={
            "fuzz_threshold": int(fuzz_threshold),
            "pull_start": pull_start.date().isoformat(),
            "pull_end": pull_end.date().isoformat(),
            "refreshed_via": refreshed_via,
        },
    )
    progress("✓ Snapshot geschrieben", 0.98)

    # ----- 9. Round-trip verify ----------
    progress("Verifikation: Snapshot zurücklesen …", 0.99)
    res_back = H.load_reservations(snapshot_dir=target)
    nig_back = H.load_timeslices(snapshot_dir=target)
    assert len(res_back) == len(res), "Round-trip Reservations weicht ab"
    assert len(nig_back) == len(nig), "Round-trip Timeslices weicht ab"
    progress("✓ Round-trip OK", 1.0)

    return meta
