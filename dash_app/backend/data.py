# dash_app/backend/data.py
# Cache layer over the parquet snapshot. Mirrors the overbooking tool's
# data_access pattern: lru_cache'd loaders keyed by an explicit signature,
# in-memory filtering with .copy(), cache_clear() after a refresh job plus a
# *-version dcc.Store bump on the pages. No BigQuery is ever touched here -
# only the refresh job (backend/jobs.py + pages/daten.py) talks to BigQuery.
#
# RAM note: each worker process holds ONE reservations + ONE timeslices frame
# (plus the override view when overrides exist). Fine for a single local
# process; for gunicorn use --preload and max 2 workers.

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

from revenueblindspots import helpers as H
from revenueblindspots import overrides as OV


def snapshot_signature() -> str:
    """Stable string for the current snapshot - changes when ANY snapshot file does.

    Fingerprints the mtimes of all four snapshot files (reservations, timeslices,
    plan, metadata), not just reservations.parquet. A plan-only refresh
    (``refresh_plan``) rewrites plan.parquet + metadata.json but leaves
    reservations.parquet untouched; keying on reservations alone would leave the
    _plan / _metadata caches stale. In-process that is masked by the explicit
    clear_caches() the refresh page runs, but a separate gunicorn worker only sees
    the change through this signature - so it must cover plan + metadata too.
    """
    snap_dir = H.find_snapshot_dir()
    if snap_dir is None:
        return "none"
    if isinstance(snap_dir, Path):
        try:
            parts = []
            for key in ("reservations", "timeslices", "plan", "metadata"):
                p = snap_dir / H.SNAPSHOT_FILES[key]
                parts.append(str(int(p.stat().st_mtime)) if p.exists() else "0")
            return f"local={snap_dir}|mtimes={'-'.join(parts)}"
        except OSError:
            return f"local={snap_dir}|nostat"
    return f"remote={snap_dir}"


@lru_cache(maxsize=2)
def _metadata(snapshot_sig: str) -> dict:
    return H.load_snapshot_metadata() or {}


@lru_cache(maxsize=2)
def _plan(snapshot_sig: str) -> pd.DataFrame:
    return H.load_plan()


@lru_cache(maxsize=1)
def _raw_reservations(snapshot_sig: str) -> pd.DataFrame:
    return H.load_reservations()


@lru_cache(maxsize=1)
def _raw_timeslices(snapshot_sig: str) -> pd.DataFrame:
    return H.load_timeslices()


@lru_cache(maxsize=1)
def _overridden_reservations(snapshot_sig: str, override_sig: str) -> pd.DataFrame:
    return OV.apply_code_overrides(_raw_reservations(snapshot_sig))


@lru_cache(maxsize=1)
def _overridden_timeslices(snapshot_sig: str, override_sig: str) -> pd.DataFrame:
    return OV.apply_code_overrides(_raw_timeslices(snapshot_sig))


def _filter_frame(
    df: pd.DataFrame,
    date_col: str,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
    properties: tuple[str, ...] | None,
) -> pd.DataFrame:
    """In-memory filter (calendar-day normalised dates + property isin), same
    semantics as helpers._read_parquet_with_filter but without a disk read."""
    mask = pd.Series(True, index=df.index)
    if (start is not None or end is not None) and date_col in df.columns:
        col = df[date_col]
        if not pd.api.types.is_datetime64_any_dtype(col):
            col = pd.to_datetime(col, errors="coerce")
        day = col.dt.normalize()
        if start is not None:
            mask &= day >= pd.Timestamp(start).normalize()
        if end is not None:
            mask &= day <= pd.Timestamp(end).normalize()
    if properties and "property_code" in df.columns:
        mask &= df["property_code"].isin(list(properties))
    return df[mask].copy()


# ---- public API ------------------------------------------------------------
def get_metadata() -> dict:
    return _metadata(snapshot_signature())


def get_plan_df() -> pd.DataFrame:
    return _plan(snapshot_signature())


def get_active_plan() -> dict:
    """Plan as {property_code: {"YYYY-MM": eur}}; empty dict when no plan snapshot."""
    return H.plan_to_dict(get_plan_df())


def get_reservations(
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    properties: list[str] | None = None,
) -> pd.DataFrame:
    df = _overridden_reservations(snapshot_signature(), OV.override_signature())
    return _filter_frame(df, "arrival", start, end, tuple(properties) if properties else None)


def get_timeslices(
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    properties: list[str] | None = None,
) -> pd.DataFrame:
    df = _overridden_timeslices(snapshot_signature(), OV.override_signature())
    return _filter_frame(df, "serviceDate", start, end, tuple(properties) if properties else None)


def clear_caches() -> None:
    """Drop every cached frame - call after a refresh job or an override write."""
    for fn in (_metadata, _plan, _raw_reservations, _raw_timeslices,
               _overridden_reservations, _overridden_timeslices):
        fn.cache_clear()
