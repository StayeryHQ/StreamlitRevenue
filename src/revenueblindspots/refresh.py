"""Snapshot-Refresh-Pipeline.

Wird aufgerufen von:
  * ``scripts/refresh_snapshot.py``  
  * ``streamlit_app/pages/0_Daten_Aktualisieren.py``
  
Caller-spezifische Unterschiede werden über zwei Parameter kontrolliert:

  * ``progress`` - eine Callback-Funktion ``progress(msg: str, pct: float | None)``.
    CLI passt ``print``-Wrapper, Streamlit passt eine Closure die st.progress
    + st.empty.markdown updated

  * ``refreshed_via`` - Freitext-Marker der im ``metadata.json`` landet

Auth-Quellen ``ref_tables.plan`` ist eine
Drive-backed External Table (Google Sheet) - die SA-Key-Files fordern dafür den
Drive-Scope an, der gcloud-ADC nutzt die beim Login erteilten Scopes:
  1. ``GCP_SERVICE_ACCOUNT_JSON_FILE`` env-var zeigt auf ein Service-Account-File.
  2. ``GOOGLE_APPLICATION_CREDENTIALS`` env-var zeigt auf ein Service-Account-File.
  3. gcloud Application Default Credentials (lokaler Dev). Für den Plan-Pull
     einmalig einloggen:

         gcloud auth application-default login \\
             --scopes=https://www.googleapis.com/auth/bigquery,\\
             https://www.googleapis.com/auth/drive.readonly,\\
             https://www.googleapis.com/auth/cloud-platform

        Might not work especially für planzahle
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from . import helpers as H

# Optional[Callable[[str, float | None], None]]
ProgressCallback = Callable[[str, "float | None"], None]


# ============================== Auth ======================================
_BQ_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/bigquery",
    "https://www.googleapis.com/auth/drive.readonly",
)

DRIVE_AUTH_HINT = (
    "Die Plan-Tabelle `ref_tables.plan` ist eine Drive-backed External Table "
    "(Google Sheet). Dein Token hat keinen Drive-Lesezugriff.\n\n"
    "Lokal (gcloud) einmalig neu einloggen:\n\n"
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
    return "drive" in msg and ("denied" in msg or "permission" in msg or "accessdenied" in msg)


def get_bigquery_client():
    """Build a BigQuery client from the first available credential source.

    Service-Account-Key-Files fordern den Drive-Scope an (``_BQ_SCOPES``) - SAs
    unterliegen der User-Consent-Blockade nicht und können das Drive-Sheet hinter
    ``ref_tables.plan`` lesen. Der lokale gcloud-ADC erzwingt keine Scopes sondern nutzt die
    beim Login erteilten Scopes. Reservations/Timeslices brauchen nur BigQuery
    der Drive-backed Plan-Pull scheitert ohne Drive-Scope mit dem
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

    # ADC (lokaler gcloud-Login): keine Scopes erzwingen
    return bigquery.Client()


# ============================== Refresh ===================================
def _noop_progress(_msg: str, _pct: float | None = None) -> None:
    """Default no-op progress callback wenn der Caller keinen angibt."""
    pass


def _resolve_snapshot_dir(snapshot_dir: str | Path | None) -> str | Path:
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
    snapshot_dir: str | Path | None = None,
    refreshed_via: str = "refresh.refresh_plan",
    progress: ProgressCallback | None = None,
    client=None,
) -> dict:
    """Nur die Planzahlen aktualisieren.

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


def _engineer_grouped(raw: pd.DataFrame, engineer_fn) -> pd.DataFrame:
    """``engineer_fn`` je ``property_code`` anwenden und wieder zusammenfügen.

    Speicherschonende Variante des früheren
    ``pd.concat([engineer_fn(g, pc) for pc, g in raw.groupby("property_code")])``:
    die Teilstücke werden in einer Schleife aufgebaut und die Liste unmittelbar
    nach dem ``concat`` geleert, sodass nicht Liste + Ergebnis + Rohframe
    gleichzeitig im Speicher stehen.

    Die Gruppenreihenfolge bleibt die von ``groupby`` (sortiert nach
    ``property_code``) - die Zeilenreihenfolge im Snapshot ändert sich also
    nicht gegenüber der alten Implementierung.

    Args:
        raw: Rohframe mit Spalte ``property_code``.
        engineer_fn: ``(df, property_code) -> DataFrame``.

    Returns:
        Das zusammengefügte, engineerte Frame (leer wenn ``raw`` leer ist).
    """
    parts: list[pd.DataFrame] = []
    for pc, group in raw.groupby("property_code"):
        parts.append(engineer_fn(group, pc))
        del group
    if not parts:
        return raw.iloc[0:0].copy()
    if len(parts) == 1:
        return parts.pop().reset_index(drop=True)
    out = pd.concat(parts, ignore_index=True)
    parts.clear()
    return out


def run_refresh(
    lookback_years: int = 3,
    fuzz_threshold: int = 85,
    properties: list[str] | None = None,
    snapshot_dir: str | Path | None = None,
    refreshed_via: str = "refresh.run_refresh",
    progress: ProgressCallback | None = None,
) -> dict:
    """Pull aus BigQuery, engineer, fuzzy-cluster, snapshot schreiben.

    Args:
        lookback_years: Wie viele Jahre rückwärts pullen (default 3 ohne obergrenze)
        fuzz_threshold: rapidfuzz token_sort_ratio - höher = strenger (default 85).
        properties: Liste von hotel_codes. None oder leer : alle aus locations.yaml.
        snapshot_dir: Ziel-Pfad. None : ``$STAYERY_SNAPSHOT_DIR`` env-var, sonst
            ``data/`` im Repo. ``gs://``-URIs werden remote behandelt.
        refreshed_via: Marker im metadata.json (z.B. ``streamlit_app``,
            ``scripts/refresh_snapshot.py``, ``github_action``).
        progress: Optional ``(msg, pct_or_none) -> None``.

    Returns:
        Das ``metadata.json``-Dict (siehe ``H.save_snapshot``).

    Raises:
        Was ``bigquery.Client.query`` oder die engineering-Funktionen
        an Exceptions werfen. Caller ist verantwortlich für try/except.
    """
    from google.cloud import bigquery

    progress = progress or _noop_progress

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
    progress(f"Ziehe Reservations (ab {pull_start.date()}, offen in die Zukunft) …", 0.15)
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
    # F5: object-Strings sofort auf Arrow umstellen. BigQuery liefert
    # object-dtype; alles was danach kommt (engineer_*, concat, join) erbt den
    # dtype. Gemessen macht das bei den Timeslices 1514 MB vs. 687 MB aus.
    raw_res = H.optimize_string_memory(raw_res)
    progress(f"✓ {len(raw_res):,} Reservations geladen ({time.time() - t0:.1f}s)", 0.35)

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
    raw_nig = H.optimize_string_memory(raw_nig)  # F5, s.o.
    progress(f"✓ {len(raw_nig):,} Timeslices geladen ({time.time() - t0:.1f}s)", 0.55)

    # ----- 4b. Planzahlen pull (klein, gleiche Auth) ----------
    # NON-FATAL und bestehender plan wird bei error nicht überschrieben
    progress("Ziehe Planzahlen …", 0.56)
    try:
        raw_plan = _pull_plan(client, progress, pct=0.58)
    except Exception as e:
        raw_plan = None
        progress(f"⚠ Planzahlen übersprungen (bestehender Plan bleibt): {e}", 0.58)

    # ----- 5. Engineering ----------
    # F6: Vorher stand hier ``pd.concat([f(g) for pc, g in raw.groupby(...)])``.
    # Bei dem Muster leben die komplette Teilstück-Liste, das concat-Ergebnis UND
    # das Rohframe gleichzeitig im Speicher (gemessen +618 MB allein für die
    # Timeslices). Jetzt: Schleife, Rohframe vor dem concat freigeben, Teilstücke
    # direkt nach dem concat.
    progress("Feature-Engineering Reservations …", 0.60)
    t0 = time.time()
    res = _engineer_grouped(raw_res, H.engineer_reservations)
    del raw_res
    H.release_memory()
    dropped_res = H.zero_night_drops()["reservations"]
    progress(
        f"✓ {len(res):,} Reservations engineered (drops {dropped_res}) ({time.time() - t0:.1f}s)",
        0.70,
    )

    progress("Feature-Engineering Timeslices …", 0.72)
    t0 = time.time()
    nig = _engineer_grouped(raw_nig, H.engineer_timeslices)
    del raw_nig
    H.release_memory()
    progress(f"✓ {len(nig):,} Timeslices engineered ({time.time() - t0:.1f}s)", 0.80)

    # ----- 6. Fuzzy-Cluster ----------
    progress("Fuzzy-Cluster der Firmennamen …", 0.82)
    t0 = time.time()
    H.add_firm_definitions(res, apply_fuzzy=True, fuzzy_threshold=int(fuzz_threshold))
    progress(f"✓ firm_by_* Spalten angelegt ({time.time() - t0:.1f}s)", 0.89)

    # ----- 6b. Reservation-Felder auf Timeslices broadcasten ----------
    # um korrekte rev ohne services darzustellen
    progress("Broadcaste Reservation-Felder auf Timeslices …", 0.90)
    # Der Left-Join legt zwangsläufig eine Kopie an; durch das Rebinding wird das
    # alte Frame sofort danach freigegeben statt erst am Funktionsende.
    nig = H.enrich_timeslices_with_reservation_fields(nig, res)
    H.release_memory()
    progress("✓ nightly um Reservation-Felder angereichert", 0.91)

    # ----- 7. Resolve snapshot target ----------
    target = _resolve_snapshot_dir(snapshot_dir)  # eine Auflösung, kein Inline-Duplikat (D4)
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

    # ----- 9. Verifikation ----------
    # F7: Vorher wurde hier der komplette Snapshot ein zweites Mal in den
    # Speicher gelesen, nur um die Zeilenzahl zu vergleichen (gemessen +423 MB,
    # und zwar exakt am Peak - res/nig/raw_* lebten alle noch). Die Zeilenzahl
    # steht im Parquet-Footer; die Metadaten zu lesen kostet praktisch nichts.
    progress("Verifikation: Zeilenzahlen aus den Parquet-Metadaten …", 0.99)
    res_rows = H.parquet_num_rows(H._join_snapshot(target, H.SNAPSHOT_FILES["reservations"]))
    nig_rows = H.parquet_num_rows(H._join_snapshot(target, H.SNAPSHOT_FILES["timeslices"]))
    if res_rows != len(res):
        raise RuntimeError(
            f"Round-trip Reservations weicht ab: {res_rows} geschrieben, {len(res)} erwartet."
        )
    if nig_rows != len(nig):
        raise RuntimeError(
            f"Round-trip Timeslices weicht ab: {nig_rows} geschrieben, {len(nig)} erwartet."
        )

    del res, nig
    H.release_memory()
    _peak = H.peak_rss_mb()
    progress(f"✓ Verifikation OK · Peak-RSS dieses Prozesses: {_peak:.0f} MB", 1.0)

    return meta
