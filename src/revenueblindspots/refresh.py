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

Auth-Quellen (in dieser Reihenfolge probiert). ``ref_tables.plan`` ist eine
Drive-backed External Table (Google Sheet) - die SA-Key-Files fordern dafür den
Drive-Scope an; der gcloud-ADC nutzt die beim Login erteilten Scopes:
  1. ``GCP_SERVICE_ACCOUNT_JSON_FILE`` env-var zeigt auf ein Service-Account-File.
  2. ``GOOGLE_APPLICATION_CREDENTIALS`` env-var zeigt auf ein Service-Account-File.
  3. gcloud Application Default Credentials (lokaler Dev). Für den Plan-Pull
     einmalig MIT Drive-Scope einloggen::

         gcloud auth application-default login \\
             --scopes=https://www.googleapis.com/auth/bigquery,\\
             https://www.googleapis.com/auth/drive.readonly,\\
             https://www.googleapis.com/auth/cloud-platform
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
# `ref_tables.plan` ist eine Drive-backed External Table (Google Sheet). Damit
# BigQuery das Sheet lesen darf, braucht das Token NEBEN dem BigQuery- auch den
# Drive-Scope - sonst: "403 Permission denied while getting Drive credentials".
# Gilt für Service-Account-Files (SA muss zusätzlich Leserechte am Sheet haben)
# UND für lokales gcloud-ADC (siehe DRIVE_AUTH_HINT / README).
_BQ_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/bigquery",
    "https://www.googleapis.com/auth/drive.readonly",
)

DRIVE_AUTH_HINT = (
    "Die Plan-Tabelle `ref_tables.plan` ist eine Drive-backed External Table "
    "(Google Sheet). Dein Token hat keinen Drive-Lesezugriff.\n\n"
    "Lokal (gcloud) einmalig MIT Drive-Scope neu einloggen:\n\n"
    "    gcloud auth application-default login \\\n"
    "        --scopes=https://www.googleapis.com/auth/bigquery,"
    "https://www.googleapis.com/auth/drive.readonly,"
    "https://www.googleapis.com/auth/cloud-platform\n\n"
    "Voraussetzung: dein Google-Account (bzw. die Service-Account-Mail) hat "
    "Leserecht auf das Sheet. Danach Refresh erneut starten."
)


def _is_drive_permission_error(exc: Exception) -> bool:
    """True wenn der Fehler der typische Drive-Scope-403 der Plan-Tabelle ist."""
    msg = str(exc).lower()
    return "drive" in msg and (
        "denied" in msg or "permission" in msg or "accessdenied" in msg
    )


def get_bigquery_client():
    """Build a BigQuery client from the first available credential source.

    Service-Account-Key-Files fordern den Drive-Scope an (``_BQ_SCOPES``) - SAs
    unterliegen der User-Consent-Blockade nicht und können das Drive-Sheet hinter
    ``ref_tables.plan`` lesen. Der lokale gcloud-ADC erzwingt KEINE Scopes (das
    würde bei nicht erteiltem Drive-Scope je nach google-auth-Version den
    Token-Refresh und damit auch die echten BQ-Tabellen blocken) - er nutzt die
    beim Login erteilten Scopes. Reservations/Timeslices brauchen nur BigQuery
    (geht immer); der Drive-backed Plan-Pull scheitert ohne Drive-Scope mit dem
    ``DRIVE_AUTH_HINT`` und wird im Voll-Refresh non-fatal behandelt.
    """
    from google.cloud import bigquery
    from google.oauth2 import service_account

    sa_json_file = os.environ.get("GCP_SERVICE_ACCOUNT_JSON_FILE")
    if sa_json_file and Path(sa_json_file).exists():
        creds = service_account.Credentials.from_service_account_file(
            sa_json_file, scopes=list(_BQ_SCOPES)
        )
        return bigquery.Client(credentials=creds, project=creds.project_id)

    sa_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if sa_file and Path(sa_file).exists():
        creds = service_account.Credentials.from_service_account_file(
            sa_file, scopes=list(_BQ_SCOPES)
        )
        return bigquery.Client(credentials=creds, project=creds.project_id)

    # ADC (lokaler gcloud-Login): keine Scopes erzwingen - das Token bringt die
    # beim Login erteilten Scopes selbst mit.
    return bigquery.Client()


# ============================== Refresh ===================================
def _noop_progress(_msg: str, _pct: "float | None" = None) -> None:
    """Default no-op progress callback wenn der Caller keinen angibt."""
    pass


def _resolve_snapshot_dir(snapshot_dir: "str | Path | None") -> "str | Path":
    """Ziel-Verzeichnis auflösen - env-var, Repo-data/, oder gs://-URI."""
    _REPO_ROOT = Path(__file__).resolve().parents[2]
    if snapshot_dir is None:
        snapshot_dir = os.environ.get("STAYERY_SNAPSHOT_DIR") or str(_REPO_ROOT / "data")
    if isinstance(snapshot_dir, str) and snapshot_dir.startswith("gs://"):
        return snapshot_dir
    target = Path(snapshot_dir).expanduser()
    if not target.is_absolute():
        target = _REPO_ROOT / target
    return target


def _pull_plan(client, progress: ProgressCallback, pct: float = 0.5) -> pd.DataFrame:
    """Planzahlen aus `ref_tables.plan` ziehen (komplette Tabelle, klein)."""
    cols = ",\n        ".join(H.PLAN_COLUMNS)
    sql = f"""
    SELECT
        {cols}
    FROM `{H.PLAN_TABLE}`
    """
    t0 = time.time()
    try:
        df = client.query(sql).to_dataframe()
    except Exception as e:
        if _is_drive_permission_error(e):
            raise PermissionError(f"{e}\n\n{DRIVE_AUTH_HINT}") from e
        raise
    progress(f"✓ {len(df):,} Plan-Zeilen geladen ({time.time() - t0:.1f}s)", pct)
    return df


def refresh_plan(
    snapshot_dir: "str | Path | None" = None,
    refreshed_via: str = "refresh.refresh_plan",
    progress: ProgressCallback | None = None,
    client=None,
) -> dict:
    """Nur die Planzahlen aktualisieren - schnell (Sekunden, eine kleine Tabelle).

    Pullt `ref_tables.plan` komplett, schreibt ``plan.parquet`` neben den
    Snapshot und ergänzt den Plan-Block im ``metadata.json``. Reservations/
    Timeslices bleiben unangetastet.

    Returns:
        Den Plan-Metadata-Block (rows, hotels, Monatsrange, refreshed_at).
    """
    progress = progress or _noop_progress
    if client is None:
        progress("Authentifiziere mit BigQuery …", 0.1)
        client = get_bigquery_client()
        progress(f"Authentifiziert (Projekt {client.project})", 0.2)
    df = _pull_plan(client, progress, pct=0.6)
    target = _resolve_snapshot_dir(snapshot_dir)
    progress(f"Schreibe plan.parquet nach {target} …", 0.8)
    plan_meta = H.save_plan(df, snapshot_dir=target, refreshed_via=refreshed_via)
    progress(
        f"✓ Plan hinterlegt + verifiziert: {plan_meta['rows']} Zeilen, "
        f"{plan_meta['hotels']} Hotels",
        1.0,
    )
    return plan_meta


def run_refresh(
    lookback_years: int = 3,
    fuzz_threshold: int = 85,
    properties: list[str] | None = None,
    snapshot_dir: "str | Path | None" = None,
    refreshed_via: str = "refresh.run_refresh",
    progress: ProgressCallback | None = None,
) -> dict:
    """Pull aus BigQuery, engineer, fuzzy-cluster, snapshot schreiben.

    Args:
        lookback_years: Wie viele Jahre rückwärts pullen (default 3). Der Pull
            zieht ab ``heute - lookback_years`` ALLE zukünftigen Anreisen/
            Nächte (keine Obergrenze) - volle Lead-Time-Pipeline.
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
    pull_start = (
        pd.Timestamp.today().normalize() - pd.DateOffset(years=lookback_years)
    ).normalize()

    # ----- 3. Reservations pull ----------
    progress(
        f"Ziehe Reservations (ab {pull_start.date()}, offen in die Zukunft) …", 0.15
    )
    _RES_COLS = ",\n    ".join(H.RES_COLUMNS)
    res_sql = f"""
    SELECT
        {_RES_COLS}
    FROM `{H.RES_TABLE}`
    WHERE property_code IN UNNEST(@properties)
      AND DATE(arrival) >= @start
    """
    params = [
        bigquery.ArrayQueryParameter("properties", "STRING", properties),
        bigquery.ScalarQueryParameter("start", "DATE", pull_start.date()),
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
      AND serviceDate >= @start
    """
    cfg = bigquery.QueryJobConfig(query_parameters=params)
    t0 = time.time()
    raw_nig = client.query(nig_sql, job_config=cfg).to_dataframe()
    progress(
        f"✓ {len(raw_nig):,} Timeslices geladen ({time.time() - t0:.1f}s)", 0.55
    )

    # ----- 4b. Planzahlen pull (klein, gleiche Auth) ----------
    # NON-FATAL: scheitert der Plan-Pull (z.B. fehlender Drive-Scope lokal),
    # soll der Voll-Refresh der echten BQ-Tabellen trotzdem durchlaufen. Ein
    # bestehender `plan.parquet` wird dann NICHT überschrieben (siehe Save).
    progress("Ziehe Planzahlen …", 0.56)
    try:
        raw_plan = _pull_plan(client, progress, pct=0.58)
    except Exception as e:
        raw_plan = None
        progress(f"⚠ Planzahlen übersprungen (bestehender Plan bleibt): {e}", 0.58)

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
    progress(f"✓ firm_by_* Spalten angelegt ({time.time() - t0:.1f}s)", 0.89)

    # ----- 6b. Reservation-Felder auf Timeslices broadcasten ----------
    # Damit nightly die reservation-level / "nach Erstellungsdatum"-Analysen auf
    # der Nacht-Netto-Basis tragen kann (Vorlaufzeit, Firmen-Cluster, Codes, …).
    progress("Broadcaste Reservation-Felder auf Timeslices …", 0.90)
    nig = H.enrich_timeslices_with_reservation_fields(nig, res)
    progress("✓ nightly um Reservation-Felder angereichert", 0.91)

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
            "pull_end": "open",
            "refreshed_via": refreshed_via,
        },
    )
    if raw_plan is not None and not raw_plan.empty:
        plan_meta = H.save_plan(raw_plan, snapshot_dir=target, refreshed_via=refreshed_via)
        progress(f"✓ Snapshot + Plan geschrieben ({plan_meta['rows']} Plan-Zeilen)", 0.98)
    else:
        progress(
            "✓ Snapshot geschrieben - Plan übersprungen, bestehender plan.parquet bleibt.",
            0.98,
        )

    # ----- 9. Round-trip verify ----------
    progress("Verifikation: Snapshot zurücklesen …", 0.99)
    res_back = H.load_reservations(snapshot_dir=target)
    nig_back = H.load_timeslices(snapshot_dir=target)
    assert len(res_back) == len(res), "Round-trip Reservations weicht ab"
    assert len(nig_back) == len(nig), "Round-trip Timeslices weicht ab"
    progress("✓ Round-trip OK", 1.0)

    return meta
