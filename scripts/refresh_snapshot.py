"""Snapshot-Refresh & CLI-Wrapper für automatisierte und manuelle Runs.

Die eigentliche Pipeline liegt in ``src/revenueblindspots/refresh.py``; diese
Datei ist ein CLI-Wrapper.

Seit dem RAM-Postmortem (F2) ist das ZUGLEICH der Pfad, den die Streamlit-Seite
„Daten aktualisieren" benutzt: sie startet dieses Script als eigenen Prozess,
statt ``run_refresh()`` im Webserver-Prozess aufzurufen. Der Refresh-Peak
entsteht damit in einem Prozess, der danach endet - und beim Beenden gibt das
Betriebssystem garantiert den kompletten Speicher zurück, was innerhalb eines
langlebigen Python-Prozesses nachweislich nicht passiert.

Usage::

    python scripts/refresh_snapshot.py
    python scripts/refresh_snapshot.py --lookback-years 5
    python scripts/refresh_snapshot.py --properties FRA_SH BER_FR
    python scripts/refresh_snapshot.py --snapshot-dir gs://stayery-snapshots
    python scripts/refresh_snapshot.py --plan-only

Auth-Pfade:
  1. ``GCP_SERVICE_ACCOUNT_JSON_FILE`` env-var
  2. ``GOOGLE_APPLICATION_CREDENTIALS`` env-var
  3. gcloud Application Default Credentials (lokaler Dev fallback)

Maschinenlesbarer Modus (``--json-progress``): jeder Fortschrittsschritt wird
als eine Zeile ``@@P@@{"msg": ..., "pct": ...}`` ausgegeben, das Endergebnis als
``@@RESULT@@{...}``. Alles andere auf stdout/stderr ist freier Text und darf vom
Aufrufer als Log behandelt werden.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from revenueblindspots.refresh import refresh_plan, run_refresh  # noqa: E402

# Marker für den maschinenlesbaren Modus - müssen mit
# ``streamlit_app/pages/0_Daten_Aktualisieren.py`` übereinstimmen.
PROGRESS_MARKER = "@@P@@"
RESULT_MARKER = "@@RESULT@@"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--lookback-years", type=int, default=3,
                   help="Wie weit zurück die Daten ziehen (default 3). "
                        "Alle künftigen Anreisen/Nächte werden gezogen.")
    p.add_argument("--fuzz-threshold", type=int, default=85,
                   help="rapidfuzz token_sort_ratio - höher = strenger (default 85).")
    p.add_argument("--properties", nargs="*", default=None,
                   help="Welche Hotel-Codes pullen. Default: alle aus locations.yaml.")
    p.add_argument("--snapshot-dir", default=None,
                   help="Wohin schreiben. Default: data/ im Repo. Akzeptiert gs:// URI.")
    p.add_argument("--plan-only", action="store_true",
                   help="Nur `ref_tables.plan` ziehen und plan.parquet schreiben.")
    p.add_argument("--refreshed-via", default=None,
                   help="Marker fürs metadata.json (default: scripts/refresh_snapshot.py).")
    p.add_argument("--json-progress", action="store_true",
                   help="Fortschritt als @@P@@-JSON-Zeilen ausgeben (für die Streamlit-Seite).")
    return p.parse_args()


def _make_progress(json_mode: bool):
    """Progress-Callback passend zum Ausgabemodus."""
    if json_mode:
        def _json_progress(msg: str, pct: float | None = None) -> None:
            print(PROGRESS_MARKER + json.dumps({"msg": msg, "pct": pct},
                                               ensure_ascii=False), flush=True)
        return _json_progress

    def _cli_progress(msg: str, _pct: float | None = None) -> None:
        print(f"[refresh] {msg}", flush=True)
    return _cli_progress


def main() -> None:
    args = _parse_args()
    progress = _make_progress(args.json_progress)
    default_via = "scripts/refresh_snapshot.py"

    try:
        if args.plan_only:
            result = refresh_plan(
                snapshot_dir=args.snapshot_dir,
                refreshed_via=args.refreshed_via or default_via,
                progress=progress,
            )
        else:
            result = run_refresh(
                lookback_years=args.lookback_years,
                fuzz_threshold=args.fuzz_threshold,
                properties=args.properties,
                snapshot_dir=args.snapshot_dir,
                refreshed_via=args.refreshed_via or default_via,
                progress=progress,
            )
    except Exception as e:
        if args.json_progress:
            # Im JSON-Modus liest der Aufrufer stdout - Typ und Text dorthin,
            # der volle Stacktrace nach stderr (wird ebenfalls eingesammelt).
            print(f"FEHLER {type(e).__name__}: {e}", flush=True)
        else:
            print(f"[refresh] FEHLGESCHLAGEN: {type(e).__name__}: {e}",
                  file=sys.stderr, flush=True)
        traceback.print_exc()
        sys.exit(1)

    if args.json_progress:
        print(RESULT_MARKER + json.dumps(result, ensure_ascii=False, default=str), flush=True)
        return

    print()
    print("=" * 60)
    if args.plan_only:
        print("Plan-Refresh fertig")
        print(f"  Zeilen : {result['rows']}")
        print(f"  Hotels : {result['hotels']}")
        print(f"  Range  : {str(result.get('earliest'))[:7]} bis {str(result.get('latest'))[:7]}")
    else:
        print("Refresh fertig")
        print(f"  Reservations : {result['reservations']['rows']:,}")
        print(f"  Timeslices   : {result['timeslices']['rows']:,}")
        print(f"  Standorte    : {len(result['properties'])}")
        print(f"  Anreise-Range: {result['reservations']['earliest'][:10]} bis "
              f"{result['reservations']['latest'][:10]}")
    print("=" * 60)


if __name__ == "__main__":
    main()
