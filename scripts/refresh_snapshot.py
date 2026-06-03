"""Headless Snapshot-Refresh - CLI-Wrapper für die GitHub Action und manuelle Runs.

Die eigentliche Pipeline liegt in ``src/revenueblindspots/refresh.run_refresh()``
- diese Datei ist nur ein dünner CLI-Wrapper drumherum (Args parsen,
print-Progress-Callback, Exit-Code setzen).

Usage::

    python scripts/refresh_snapshot.py
    python scripts/refresh_snapshot.py --lookback-years 5 --future-buffer-days 365
    python scripts/refresh_snapshot.py --properties FRA_SH BER_FR
    python scripts/refresh_snapshot.py --snapshot-dir gs://stayery-snapshots

Auth-Pfade (in Reihenfolge):
  1. ``GCP_SERVICE_ACCOUNT_JSON`` env-var (JSON inline - GitHub Action)
  2. ``GOOGLE_APPLICATION_CREDENTIALS`` env-var (Pfad zu File - klassisches GCP)
  3. gcloud Application Default Credentials (lokaler Dev)
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from revenueblindspots.refresh import run_refresh


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--lookback-years", type=int, default=3,
                   help="Wie weit zurück Reservations + Timeslices ziehen (default 3).")
    p.add_argument("--future-buffer-days", type=int, default=180,
                   help="Wie weit in die Zukunft Reservations ziehen für Pipeline (default 180).")
    p.add_argument("--fuzz-threshold", type=int, default=85,
                   help="rapidfuzz token_sort_ratio - höher = strenger (default 85).")
    p.add_argument("--properties", nargs="*", default=None,
                   help="Welche Hotel-Codes pullen. Default: alle aus locations.yaml.")
    p.add_argument("--snapshot-dir", default=None,
                   help="Wohin schreiben. Default: data/ im Repo. Akzeptiert gs:// URI.")
    return p.parse_args()


def _cli_progress(msg: str, _pct: "float | None" = None) -> None:
    """Print-basierte Progress-Anzeige für die CLI / GitHub-Action-Logs."""
    print(f"[refresh] {msg}", flush=True)


def main() -> None:
    args = _parse_args()
    try:
        meta = run_refresh(
            lookback_years=args.lookback_years,
            future_buffer_days=args.future_buffer_days,
            fuzz_threshold=args.fuzz_threshold,
            properties=args.properties,
            snapshot_dir=args.snapshot_dir,
            refreshed_via="scripts/refresh_snapshot.py",
            progress=_cli_progress,
        )
    except Exception as e:
        print(f"[refresh] FEHLGESCHLAGEN: {type(e).__name__}: {e}",
              file=sys.stderr, flush=True)
        traceback.print_exc()
        sys.exit(1)

    print()
    print("=" * 60)
    print("Refresh fertig")
    print(f"  Reservations : {meta['reservations']['rows']:,}")
    print(f"  Timeslices   : {meta['timeslices']['rows']:,}")
    print(f"  Standorte    : {len(meta['properties'])}")
    print(f"  Anreise-Range: {meta['reservations']['earliest'][:10]} bis "
          f"{meta['reservations']['latest'][:10]}")
    print("=" * 60)


if __name__ == "__main__":
    main()
