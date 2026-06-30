"""Shared helpers.

Config (locations, plan), BigQuery columns, snapshot IO (parquet),
feature engineering, KPI helpers, period math, formatting.

Planzahlen: kommen aus BigQuery (``ref_tables.plan``) und werden beim
Refresh als ``plan.parquet`` geschrieben. Pages holen sich das Dict über
``plan_to_dict(load_plan())`` und reichen es an ``plan_revenue(plan=...)``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

CONFIGS_DIR: Path = Path(__file__).resolve().parents[2] / "configs"

# German hotel-stay VAT - net = gross / (1 + VAT_RATE).
VAT_RATE: float = 0.07


def to_net(gross: Any) -> Any:
    """Convert a gross amount to net."""
    return gross / (1.0 + VAT_RATE)


# =============================================================================
# Config - locations.yaml & Planzahlen (BigQuery ref_tables.plan)
# =============================================================================
@lru_cache(maxsize=1)
def _locations() -> list[dict[str, Any]]:
    with (CONFIGS_DIR / "locations.yaml").open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)["locations"]


def location(property_code: str) -> dict[str, Any]:
    """Return the locations.yaml entry for one hotel."""
    for loc in _locations():
        if loc["hotel_code"] == property_code:
            return loc
    raise KeyError(f"Unknown property '{property_code}' - see configs/locations.yaml")


def units_total(property_code: str) -> int:
    """Total bookable units for a hotel."""
    return int(location(property_code)["units_total"])


def city(property_code: str) -> str:
    """City name for a hotel (chart labels)."""
    return str(location(property_code)["city"])


def city_label(property_code: str) -> str:
    """Disambiguating label for tables.

    Falls dieselbe Stadt mehrere Stayeries hat, wird das
    `neighborhood`-Feld angehängt.
    """
    loc = location(property_code)
    city_name = str(loc.get("city") or "").strip()
    neigh = str(loc.get("neighborhood") or "").strip()
    same_city = [
        l for l in _locations()
        if str(l.get("city") or "").strip().lower() == city_name.lower()
    ]
    if len(same_city) > 1:
        return f"{city_name} {neigh}" if neigh else f"{city_name} ({property_code})"
    return city_name


def all_properties() -> list[str]:
    """All hotel codes from locations.yaml."""
    return [loc["hotel_code"] for loc in _locations()]


def opening_date(property_code: str) -> pd.Timestamp | None:
    """Eröffnungsdatum aus locations.yaml, None wenn TBD.

    Akzeptiert ISO (``2026-04-01`` bevorzugt), ``DD-MM-YYYY`` (deutsch),
    ``DD.MM.YYYY``, oder bereits ein date-Objekt.
    """
    raw = location(property_code).get("opening_date")
    if not raw:
        return None
    if isinstance(raw, (pd.Timestamp,)):
        return raw
    # ISO via YAML-Parser kommt als date oder datetime
    try:
        import datetime as _dt
        if isinstance(raw, (_dt.date, _dt.datetime)):
            return pd.Timestamp(raw)
    except ImportError:
        pass
    s = str(raw).strip()
    # ISO-Form (YYYY-MM-DD)
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        try:
            return pd.Timestamp(s)
        except (ValueError, TypeError):
            pass
    # DD-MM-YYYY / DD.MM.YYYY
    try:
        return pd.Timestamp(pd.to_datetime(s, dayfirst=True))
    except (ValueError, TypeError):
        return None


def properties_without_old_data(
    properties: list[str],
    old_end: pd.Timestamp,
) -> list[str]:
    """Hotel-Codes deren ``opening_date`` nach ``old_end`` liegt haben in Old keine Daten"""
    flagged: list[str] = []
    for pc in properties:
        try:
            opened = opening_date(pc)
        except KeyError:
            continue
        if opened is not None and opened > old_end:
            flagged.append(pc)
    return flagged


def is_open_in_period(
    property_code: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    min_overlap_days: int = 1,
) -> bool:
    """True wenn der Standort innerhalb des Zeitraums mindestens ``min_overlap_days`` Tage offen war.

    Standorte ohne hinterlegtes Eröffnungsdatum gelten defensiv als
    *nicht* offen.
    """
    try:
        opened = opening_date(property_code)
    except KeyError:
        return False
    if opened is None:
        return False
    overlap_start = max(opened, start)
    if overlap_start > end:
        return False
    return (end - overlap_start).days + 1 >= min_overlap_days


def filter_open_properties(
    properties: list[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    min_overlap_days: int = 1,
) -> list[str]:
    """Reduktion einer Property-Liste auf jene, die im Zeitraum offen waren.

    Reihenfolge der Eingabe wird beibehalten. Wird in Sidebars / Daten-Pulls
    genutzt, damit nicht-offene Standorte gar nicht erst geladen werden.
    """
    return [p for p in properties
            if is_open_in_period(p, start, end, min_overlap_days=min_overlap_days)]


# =============================================================================
# Planzahlen - BigQuery `ref_tables.plan` plan.parquet neben dem Snapshot
# =============================================================================
# refresh.refresh_plan pullt die Tabelle und schreibt das Parquet.

PLAN_TABLE = "stayery-analytics.ref_tables.plan"

# property_id wird beim Speichern zu property_code normalisiert
PLAN_COLUMNS = [
    "property_id",
    "month",
    "revenue",
    "rev_par",
    "sold_count",
    "house_count",
    "ooo_count",
]
_PLAN_COLUMNS_NORMALIZED = ["property_code"] + PLAN_COLUMNS[1:]


def load_plan(snapshot_dir: "Path | str | None" = None) -> pd.DataFrame:
    """Planzahlen aus ``<snapshot_dir>/plan.parquet`` (BigQuery-Snapshot).

    Einzige Plan-Quelle. Liefert ein leeres DataFrame (mit den normalisierten
    Spalten) wenn das File fehlt. Lokaler Pfad oder ``gs://``-URI - pandas/
    pyarrow lesen beides transparent.
    """
    snap = snapshot_dir or find_snapshot_dir()
    if snap is None:
        return pd.DataFrame(columns=_PLAN_COLUMNS_NORMALIZED)
    path = _join_snapshot(snap, SNAPSHOT_FILES["plan"])
    if not _snapshot_exists(path):
        return pd.DataFrame(columns=_PLAN_COLUMNS_NORMALIZED)
    return pd.read_parquet(str(path))


def _write_metadata_json(meta: dict[str, Any], snapshot_dir: "Path | str") -> None:
    """``metadata.json`` an die Snapshot-Location schreiben (lokal oder ``gs://``)."""
    import json as _json
    meta_path = _join_snapshot(snapshot_dir, SNAPSHOT_FILES["metadata"])
    body = _json.dumps(meta, indent=2, ensure_ascii=False)
    if _is_remote(meta_path):
        import fsspec
        with fsspec.open(meta_path, "w") as f:
            f.write(body)
    else:
        Path(meta_path).write_text(body, encoding="utf-8")


def save_plan(plan_df: pd.DataFrame, snapshot_dir: "Path | str",
              *, refreshed_via: str = "?") -> dict[str, Any]:
    """``plan.parquet`` schreiben + ``metadata.json`` um den Plan-Block ergänzen.

    Returns den Plan-Block.
    """
    df = plan_df.copy()
    if "property_id" in df.columns and "property_code" not in df.columns:
        df = df.rename(columns={"property_id": "property_code"})
    df["month"] = pd.to_datetime(df["month"], errors="coerce")
    df = df.dropna(subset=["property_code", "month"])
    df = df.sort_values(["property_code", "month"]).reset_index(drop=True)

    if not _is_remote(snapshot_dir):
        snapshot_dir = Path(snapshot_dir)
        snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = _join_snapshot(snapshot_dir, SNAPSHOT_FILES["plan"])
    df.to_parquet(str(path), compression="snappy", index=False)

    _back = load_plan(snapshot_dir)
    if len(_back) != len(df):
        raise RuntimeError(
            f"Plan-Roundtrip fehlgeschlagen: {len(_back)} Zeilen zurückgelesen, "
            f"{len(df)} geschrieben ({path})."
        )

    plan_meta: dict[str, Any] = {
        "rows": int(len(df)),
        "hotels": int(df["property_code"].nunique()) if len(df) else 0,
        "earliest": df["month"].min().isoformat() if len(df) else None,
        "latest": df["month"].max().isoformat() if len(df) else None,
        "refreshed_at": pd.Timestamp.now(tz="Europe/Berlin").isoformat(),
        "refreshed_via": refreshed_via,
    }
    meta = load_snapshot_metadata(snapshot_dir) or {}
    meta["plan"] = plan_meta
    _write_metadata_json(meta, snapshot_dir)
    return plan_meta


def plan_to_dict(plan_df: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Parquet-Plan -> ``{property_code: {"YYYY-MM": revenue_eur}}``.

    Das Format, das ``plan_revenue()`` konsumiert (Monats-Keys als
    ``YYYY-MM``-Strings). Doppelte ``(code, monat)``-Zeilen werden summiert.
    Leeres Dict wenn der Plan leer/None ist.
    """
    if plan_df is None or plan_df.empty:
        return {}
    df = plan_df.copy()
    df["month"] = pd.to_datetime(df["month"], errors="coerce")
    df = df.dropna(subset=["property_code", "month"])
    if df.empty:
        return {}
    ym = df["month"].dt.strftime("%Y-%m")
    grouped = df.assign(_ym=ym).groupby(["property_code", "_ym"])["revenue"].sum()
    out: dict[str, dict[str, float]] = {}
    for (pc, month_key), value in grouped.items():
        out.setdefault(str(pc), {})[str(month_key)] = float(value)
    return out


def plan_revenue(
    property_code: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    plan: dict[str, dict[str, float]] | None = None,
) -> float:
    """Geplantes Revenue für ein Hotel über [start, end] (pro-rata je Monat).

    ``plan`` ist das Dict aus ``plan_to_dict(load_plan())``:
    ``{property_code: {"YYYY-MM": revenue_eur}}``. Fehlt der Plan -> 0.0.
    """
    months = (plan or {}).get(property_code, {})
    total = 0.0
    for ym, value in months.items():
        period = pd.Period(str(ym), freq="M")
        m_start, m_end = period.start_time, period.end_time.normalize()
        overlap_start = max(m_start, start)
        overlap_end = min(m_end, end)
        days_overlap = (overlap_end - overlap_start).days + 1
        if days_overlap <= 0:
            continue
        total += float(value) * days_overlap / period.days_in_month
    return total


# =============================================================================
# Parquet snapshot - single source of truth for the analysis pages.
# =============================================================================
# The "Daten aktualisieren" page is the only place that talks to BigQuery; it
# writes a pre-engineered parquet to `data/` (or `gs://…` via env-var).
# All analysis pages read that snapshot and filter in-memory - zero
# BigQuery cost per filter change.

SNAPSHOT_FILES = {
    "reservations": "reservations.parquet",
    "timeslices":   "timeslices.parquet",
    "plan":         "plan.parquet",
    "metadata":     "metadata.json",
}


def _is_remote(path) -> bool:
    """True iff path is a cloud-storage URI (gs://, s3://, …)."""
    return isinstance(path, str) and path.startswith(("gs://", "s3://"))


def _join_snapshot(snapshot_dir, filename: str):
    """Join a filename onto a snapshot directory - works for local Paths
    and remote ``gs://`` / ``s3://`` URIs alike. Returns a ``Path`` or ``str``.
    """
    if _is_remote(snapshot_dir):
        return f"{str(snapshot_dir).rstrip('/')}/{filename}"
    return Path(snapshot_dir) / filename


def _snapshot_exists(path) -> bool:
    """Check if a file exists at a Path or remote URI."""
    if _is_remote(path):
        try:
            import fsspec
            fs, p = fsspec.url_to_fs(path)
            return fs.exists(p)
        except ImportError:
            return False
    return Path(path).is_file()


def find_snapshot_dir() -> "Path | str | None":
    """Locate the snapshot directory.

    Search order:
      1. Env-var ``STAYERY_SNAPSHOT_DIR`` - local path or ``gs://``-URI.
      2. ``<repo>/data/`` next to ``src/``.
    Returns ``None`` if nothing is found.
    """
    import os as _os

    custom = _os.environ.get("STAYERY_SNAPSHOT_DIR")
    if custom:
        custom = custom.strip()
        if _is_remote(custom):
            return custom
        p = Path(custom).expanduser()
        # Return the path even if it doesn't exist yet - save_snapshot will create it.
        return p

    local = Path(__file__).resolve().parents[2] / "data"
    if (local / SNAPSHOT_FILES["reservations"]).is_file():
        return local
    return None


def load_snapshot_metadata(snapshot_dir: "Path | str | None" = None) -> dict[str, Any]:
    """Load ``metadata.json`` from the snapshot dir (refresh time, row counts, …).

    Works for both local paths and remote ``gs://`` URIs.
    """
    import json as _json

    snap = snapshot_dir or find_snapshot_dir()
    if snap is None:
        return {}
    meta_path = _join_snapshot(snap, SNAPSHOT_FILES["metadata"])
    if not _snapshot_exists(meta_path):
        return {}
    try:
        if _is_remote(meta_path):
            import fsspec
            with fsspec.open(meta_path, "r") as f:
                return _json.loads(f.read())
        return _json.loads(Path(meta_path).read_text())
    except (ValueError, OSError, ImportError):
        return {}


def _read_parquet_with_filter(
    path,
    date_col: str,
    start: "pd.Timestamp | str | None",
    end: "pd.Timestamp | str | None",
    properties: list[str] | None,
) -> pd.DataFrame:
    """Read a parquet file and apply common filters (date range, property list).

    Accepts a local ``Path`` or a ``gs://`` URI - pandas/pyarrow handles
    both transparently when ``gcsfs`` is installed.

    The date filter is normalised to the calendar day on both ends - same
    semantics as ``filter_period()``.
    """
    df = pd.read_parquet(str(path))
    if start is not None or end is not None:
        # Ensure date_col is datetime; engineered snapshots already are.
        if not pd.api.types.is_datetime64_any_dtype(df[date_col]):
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        day = df[date_col].dt.normalize()
        if start is not None:
            df = df[day >= pd.Timestamp(start).normalize()]
            day = day.loc[df.index]
        if end is not None:
            df = df[day <= pd.Timestamp(end).normalize()]
    if properties:
        df = df[df["property_code"].isin(properties)]
    return df.copy()


def load_reservations(
    start: "pd.Timestamp | str | None" = None,
    end: "pd.Timestamp | str | None" = None,
    properties: list[str] | None = None,
    snapshot_dir: "Path | str | None" = None,
) -> pd.DataFrame:
    """Load reservations from the parquet snapshot (no BigQuery required).

    Snapshot kann lokal (``Path``) oder remote (``gs://bucket/…``) sein.
    Im Remote-Fall wird ``gcsfs`` als Treiber gebraucht - automatisch über
    ``fsspec`` von pandas/pyarrow geladen.

    Args:
        start, end: filter on ``arrival`` (calendar-day inclusive). None = no bound.
        properties: list of hotel_codes to include. None / empty = all.
        snapshot_dir: override the auto-detected snapshot location.
    """
    snap = snapshot_dir or find_snapshot_dir()
    if snap is None:
        raise FileNotFoundError(
            "Snapshot nicht gefunden. Bitte erst einmal `Daten aktualisieren` "
            "ausführen (Streamlit-App)."
        )
    path = _join_snapshot(snap, SNAPSHOT_FILES["reservations"])
    if not _snapshot_exists(path):
        raise FileNotFoundError(
            f"Reservations-Snapshot fehlt: {path}\n"
            f"Bitte `Daten aktualisieren` ausführen."
        )
    return _read_parquet_with_filter(path, "arrival", start, end, properties)


def load_timeslices(
    start: "pd.Timestamp | str | None" = None,
    end: "pd.Timestamp | str | None" = None,
    properties: list[str] | None = None,
    snapshot_dir: "Path | str | None" = None,
) -> pd.DataFrame:
    """Load timeslices (one row per stay-night) from the parquet snapshot.

    Lokaler Pfad oder ``gs://``-URI, beides funktioniert. Filter auf ``serviceDate``.
    """
    snap = snapshot_dir or find_snapshot_dir()
    if snap is None:
        raise FileNotFoundError(
            "Snapshot nicht gefunden. Bitte erst `Daten aktualisieren` ausführen."
        )
    path = _join_snapshot(snap, SNAPSHOT_FILES["timeslices"])
    if not _snapshot_exists(path):
        raise FileNotFoundError(
            f"Timeslices-Snapshot fehlt: {path}\n"
            f"Bitte `Daten aktualisieren` ausführen."
        )
    return _read_parquet_with_filter(path, "serviceDate", start, end, properties)


def save_snapshot(
    res: pd.DataFrame,
    nig: pd.DataFrame,
    snapshot_dir: "Path | str",
    *,
    lookback_years: int | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist reservations + timeslices to the snapshot directory.

    Schreibt drei Files an die angegebene Location - entweder lokal (Pfad)
    oder remote (``gs://bucket/optional-prefix``). 

    Files:
      * ``reservations.parquet`` - engineered
      * ``timeslices.parquet``   - engineered
      * ``metadata.json``        - refresh timestamp, row counts, date ranges
    """
    import json as _json

    is_remote = _is_remote(snapshot_dir)
    if not is_remote:
        snapshot_dir = Path(snapshot_dir)
        snapshot_dir.mkdir(parents=True, exist_ok=True)

    res_path = _join_snapshot(snapshot_dir, SNAPSHOT_FILES["reservations"])
    nig_path = _join_snapshot(snapshot_dir, SNAPSHOT_FILES["timeslices"])
    meta_path = _join_snapshot(snapshot_dir, SNAPSHOT_FILES["metadata"])

    # pandas writes to gs:// when fsspec/gcsfs is available - same call for both.
    res.to_parquet(str(res_path), compression="snappy", index=False)
    nig.to_parquet(str(nig_path), compression="snappy", index=False)

    # Build metadata
    def _date_range(df: pd.DataFrame, col: str) -> dict[str, Any]:
        if col not in df.columns or df[col].dropna().empty:
            return {"earliest": None, "latest": None}
        s = pd.to_datetime(df[col], errors="coerce").dropna()
        return {"earliest": s.min().isoformat(), "latest": s.max().isoformat()}

    meta = {
        "refreshed_at": pd.Timestamp.now(tz="Europe/Berlin").isoformat(),
        "lookback_years": lookback_years,
        "snapshot_dir": str(snapshot_dir),
        "reservations": {
            "rows": int(len(res)),
            **_date_range(res, "arrival"),
        },
        "timeslices": {
            "rows": int(len(nig)),
            **_date_range(nig, "serviceDate"),
        },
        "properties": sorted(res["property_code"].dropna().unique().tolist())
                       if "property_code" in res.columns else [],
    }
    if extra_metadata:
        meta.update(extra_metadata)

    meta_json = _json.dumps(meta, indent=2, ensure_ascii=False)
    if is_remote:
        import fsspec
        with fsspec.open(meta_path, "w") as f:
            f.write(meta_json)
    else:
        Path(meta_path).write_text(meta_json)
    return meta

# =============================================================================
# BigQuery - table names + PII-curated column lists
# =============================================================================
RES_TABLE = "stayery-analytics.reporting.reservations"
SLICE_TABLE = "stayery-analytics.reporting.reservations_timeslices"

# Columns pulled from `reservations`. PII (guest names, e-mail, phone, birth
# date, street address, payment data, free-text comments, internal guest id)
# is deliberately NOT selected. Country code + preferred language are kept -
# they are not personally identifying and drive the DE-vs-International view.
RES_COLUMNS: tuple[str, ...] = (
    "id",
    "bookingId",
    "status",
    "travelPurpose",
    "source",
    "channelCode",
    "property_code",
    "property_name",
    "ratePlan_code",
    "ratePlan_name",
    "unitGroup_name",
    "totalGrossAmount_amount",
    "adults",
    "cancellationFee_fee_amount",
    "noShowFee_fee_amount",
    "company_name",
    "company_code",
    "corporateCode",
    "primaryGuest_company_name",
    "booker_company_name",
    "promoCode",
    "commission_amount",
    "primaryGuest_address_countryCode",
    "primaryGuest_preferredLanguage",
    "arrival",
    "departure",
    "created",
    "modified",
    "is_first_res",
    "is_last_res",
    "cancellationTime"
)

# Columns pulled from `reservations_timeslices` (one row per stay-night).
SLICE_COLUMNS: tuple[str, ...] = (
    "id",
    "bookingId",
    "status",
    "travelPurpose",
    "source",
    "channelCode",
    "property_code",
    "property_name",
    "ratePlan_code",
    "ratePlan_name",
    "unitGroup_name",
    "serviceDate",
    "baseAmount_grossAmount",
    "baseAmount_netAmount",
    "adults",
    "corporateCode",
    "primaryGuest_address_countryCode",
    "primaryGuest_preferredLanguage",
    "arrival",
    "departure",
    "created",
    "is_first_res",
    "is_last_res",
)


CHANNEL_COMBO_MAP = {
    "Ibe": "Direct_Website",
    "Direct": "Direct_Offline",
}

LOS_BINS = [-0.1, 6, 28, np.inf]
LOS_LABELS = ["short_<=6", "mid_7-28", "long_29+"]

# =============================================================================
# Lead-time & Storno-Timing axes - IDENTICAL bucket grid so every chart that
# plots either axis is directly comparable. Storno additionally carries the
# "nach Anreise" segment (cancellations recorded after the check-in date).
# Spec: same_day, 1-3, 4-7, then 3-day steps through 26-28, then 29+.
# =============================================================================
LEAD_BINS = [-1e9, 0, 3, 7, 10, 13, 16, 19, 22, 25, 28, 1e9]
LEAD_LABELS = [
    "same_day",
    "1-3 T",
    "4-7 T",
    "8-10 T",
    "11-13 T",
    "14-16 T",
    "17-19 T",
    "20-22 T",
    "23-25 T",
    "26-28 T",
    "29+ T",
]

# Storno timing - days before arrival. Negative = after check-in.
# Same grid as LEAD_LABELS with the "nach Anreise" segment prepended; the
# "Anreisetag" bucket is the same_day equivalent.
CANCEL_TIMING_BINS = [-1e9, -1, 0, 3, 7, 10, 13, 16, 19, 22, 25, 28, 1e9]
CANCEL_TIMING_LABELS = [
    "nach Anreise",
    "Anreisetag",
    "1-3 T",
    "4-7 T",
    "8-10 T",
    "11-13 T",
    "14-16 T",
    "17-19 T",
    "20-22 T",
    "23-25 T",
    "26-28 T",
    "29+ T",
]

GROUP_BINS = [0, 1, 2, 4, 1e9]
GROUP_LABELS = ["single", "2_rooms", "3-4_rooms", "5+_rooms"]



def classify_channel(channel_code: Any, source: Any) -> str:
    """Combine apaleo channelCode + source into one analytical label."""
    cc = "" if pd.isna(channel_code) else str(channel_code).strip()
    if cc in CHANNEL_COMBO_MAP:
        return CHANNEL_COMBO_MAP[cc]
    src = "" if pd.isna(source) else str(source).strip()
    return f"OTA_{src}" if src else f"OTA_{cc or 'Other'}"


def normalize_room_category(series: pd.Series, property_code: str) -> pd.Series:
    """Hotel-specific room-category clean-up. Returns a new Series."""
    s = series.astype("string")
    if property_code == "BIE_HB":
        s = s.str.replace(" AIRCON", "", regex=False).str.strip()
    return s


# =============================================================================
# Feature engineering
# =============================================================================
_UNKNOWN_ORIGIN = {"", "NAN", "NONE", "<NA>", "NAT", "NULL"}

# apaleo status enum - used by _add_status_flags below.
REALIZED_STATUS = {"Confirmed", "InHouse", "CheckedOut"}
CANCELLED_STATUS = {"Canceled"}
NO_SHOW_STATUS = {"NoShow"}


def _add_status_flags(df: pd.DataFrame) -> None:
    s = df["status"].astype(str)
    df["is_realized"] = s.isin(REALIZED_STATUS)
    df["is_cancelled"] = s.isin(CANCELLED_STATUS)
    df["is_no_show"] = s.isin(NO_SHOW_STATUS)


def _add_channel(df: pd.DataFrame) -> None:
    df["channel_combo"] = [
        classify_channel(c, s) for c, s in zip(df["channelCode"], df["source"], strict=True)
    ]
    df["channel_group"] = np.where(
        df["channel_combo"].str.startswith("Direct"),
        "Direct",
        np.where(df["channel_combo"].str.startswith("OTA"), "OTA", "Other"),
    )


def _add_origin(df: pd.DataFrame) -> None:
    """Origin country with a country-code → preferred-language fallback."""
    cc = df["primaryGuest_address_countryCode"]
    lang = df.get("primaryGuest_preferredLanguage", pd.Series([None] * len(df)))
    origin = cc.where(cc.notna(), lang.astype(str).str.upper())
    clean = origin.astype(str).str.upper().str.strip()
    unknown = clean.isin(_UNKNOWN_ORIGIN)
    df["origin"] = origin
    df["is_international"] = (~unknown) & clean.ne("DE")


def _to_dt(series: pd.Series, tz: str = "Europe/Berlin") -> pd.Series:
    """Parse to datetime, localise to ``tz`` and drop the tz (naive result).

    BigQuery TIMESTAMP columns arrive timezone-aware (UTC). Standardmäßig wird
    nach ``Europe/Berlin`` konvertiert (lokale Kalender-Sicht). ALLE
    Zeitstempel-Spalten - inkl. ``created`` - laufen über diesen Default, damit
    die Tag-/Monatszuordnung über sämtliche Datumsspalten konsistent ist.

    Historie: ``created`` wurde früher bewusst in UTC gehalten (``tz="UTC"``), um
    dem BigQuery-Dashboard mit ``DATE(created)`` (= UTC) zu entsprechen. Das
    erzeugte aber einen Sonderfall - nahe Mitternacht erstellte Buchungen fielen
    in einen anderen Kalendertag als alle anderen Spalten (Anreise/Aufenthalt/
    Storno). Seit der Vereinheitlichung nutzt ``created`` denselben
    ``Europe/Berlin``-Default; der ``tz``-Parameter bleibt erhalten, wird aktuell
    aber nicht mehr für eine UTC-Sonderbehandlung gebraucht.
    """
    s = pd.to_datetime(series, errors="coerce")
    if getattr(s.dt, "tz", None) is not None:
        s = s.dt.tz_convert(tz).dt.tz_localize(None)
    return s


def _nights(arrival: pd.Series, departure: pd.Series) -> pd.Series:
    """Whole-night count between arrival and departure.

    Both timestamps are normalised to midnight before subtracting, so a
    same-day-afternoon arrival followed by a next-morning departure correctly
    yields one night (not a fractional value). Pure calendar-day arithmetic.
    """
    return (departure.dt.normalize() - arrival.dt.normalize()).dt.days


# Drop-counter so the refresh page can surface how many zero-night rows
# (same-day arrival/departure data errors) were filtered out during engineering.
_LAST_ZERO_NIGHT_DROPS: dict[str, int] = {"timeslices": 0, "reservations": 0}


def zero_night_drops() -> dict[str, int]:
    """Counts of rows dropped by engineer_* because nights == 0 (data errors)."""
    return dict(_LAST_ZERO_NIGHT_DROPS)


def _drop_zero_nights(df: pd.DataFrame, kind: str) -> pd.DataFrame:
    """Drop rows where the parent reservation has arrival == departure.

    These are data errors (a stay must span at least one night) - keeping them
    poisons ADR (NaN denominators), occupancy (no room-night) and LOS-bucket
    stats. We record the drop count so the refresh page can surface it.
    """
    if "nights" not in df.columns:
        return df
    bad = df["nights"].fillna(0).le(0)
    _LAST_ZERO_NIGHT_DROPS[kind] = int(bad.sum())
    return df.loc[~bad].copy()


def engineer_timeslices(df: pd.DataFrame, property_code: str) -> pd.DataFrame:
    """Enrich the nightly (timeslices) frame - returns a copy.

    Adds: stay_date, revenue (net €/night), revenue_gross, status flags,
    channel_combo / channel_group, origin / is_international, nights,
    los_bucket, room_category, stay_year_month, stay_weekday, check_in_weekday.
    """
    df = df.copy()
    for c in ("arrival", "departure"):
        df[c] = _to_dt(df[c])
    # created nach Europe/Berlin - wie ALLE anderen Zeitstempel (arrival,
    # departure, serviceDate, Storno). Einheitliche Kalendertag-Zuordnung über
    # alle Spalten; kein UTC-Sonderfall mehr, der Grenz-Buchungen am Tagesrand in
    # einen anderen Erstellungs-Tag/-Monat schob.
    df["created"] = _to_dt(df["created"])
    # BigQuery DATE columns arrive as datetime.date objects (object dtype) -
    # convert in place so downstream code (Parquet, .dt accessor, .min().date(),
    # date arithmetic) all behaves like the other timestamp columns.
    df["serviceDate"] = _to_dt(df["serviceDate"])
    df["stay_date"] = df["serviceDate"]   # alias kept for backward-compat
    df["revenue"] = pd.to_numeric(df["baseAmount_netAmount"], errors="coerce").fillna(0.0)
    df["revenue_gross"] = pd.to_numeric(df["baseAmount_grossAmount"], errors="coerce").fillna(0.0)
    df["adults"] = pd.to_numeric(df["adults"], errors="coerce")

    _add_status_flags(df)
    _add_channel(df)
    _add_origin(df)

    df["nights"] = _nights(df["arrival"], df["departure"])
    df["los_bucket"] = pd.cut(df["nights"], bins=LOS_BINS, labels=LOS_LABELS)
    df["room_category"] = normalize_room_category(df["unitGroup_name"], property_code)

    # Group size = distinct reservations sharing a bookingId.
    size = df.groupby("bookingId")["id"].transform("nunique")
    df["booking_size"] = size
    df["group_size_bucket"] = pd.cut(size, bins=GROUP_BINS, labels=GROUP_LABELS)

    df["stay_year_month"] = df["stay_date"].dt.to_period("M").astype(str)
    df["stay_weekday"] = df["stay_date"].dt.day_name()
    df["check_in_weekday"] = df["arrival"].dt.day_name()
    return _drop_zero_nights(df, "timeslices")


def engineer_reservations(df: pd.DataFrame, property_code: str) -> pd.DataFrame:
    """Enrich the reservation-level frame - returns a copy.

    Adds: revenue (net €), gross_amount, nights, status flags, channel,
    origin, los_bucket, lead_time_days / lead_time_bucket,
    cancel_lead_time_days (via `cancellationTime`, Fallback `modified`),
    booking_size / group_size_bucket, room_category, rate-plan flags, has_promo /
    has_company, calendar fields, adr_per_night, kept_revenue / lost_revenue.
    """
    df = df.copy()
    for c in ("arrival", "departure", "modified", "cancellationTime"):
        if c in df.columns:
            df[c] = _to_dt(df[c])
    # created nach Europe/Berlin - konsistent zu allen anderen Zeitstempeln und
    # zur Timeslice-Engineering (kein UTC-Sonderfall mehr).
    if "created" in df.columns:
        df["created"] = _to_dt(df["created"])
    df["gross_amount"] = pd.to_numeric(df["totalGrossAmount_amount"], errors="coerce").fillna(0.0)
    df["revenue"] = to_net(df["gross_amount"])
    df["adults"] = pd.to_numeric(df["adults"], errors="coerce")

    _add_status_flags(df)
    _add_channel(df)
    _add_origin(df)

    df["nights"] = _nights(df["arrival"], df["departure"])
    df["los_bucket"] = pd.cut(df["nights"], bins=LOS_BINS, labels=LOS_LABELS)
    df["lead_time_days"] = (df["arrival"].dt.normalize() - df["created"].dt.normalize()).dt.days
    df["lead_time_bucket"] = pd.cut(df["lead_time_days"], bins=LEAD_BINS, labels=LEAD_LABELS)

    # Storno-Zeitpunkt: `cancellationTime` ist der echte apaleo-Cancel-Zeitstempel
    # (in den Reservations zu ~100 % gefüllt). `modified` ist nur der Fallback-
    # Proxy, falls `cancellationTime` mal leer ist (Alt-Buchungen / fehlende Daten).
    if "cancellationTime" in df.columns:
        df["cancel_time"] = df["cancellationTime"].where(
            df["cancellationTime"].notna(), df["modified"]
        )
    else:
        df["cancel_time"] = df["modified"]
    df["cancel_lead_time_days"] = np.where(
        df["is_cancelled"],
        (df["arrival"].dt.normalize() - df["cancel_time"].dt.normalize()).dt.days,
        np.nan,
    )

    size = df.groupby("bookingId")["id"].transform("count")
    df["booking_size"] = size
    df["group_size_bucket"] = pd.cut(size, bins=GROUP_BINS, labels=GROUP_LABELS)

    df["room_category"] = normalize_room_category(df["unitGroup_name"], property_code)

    rp = df["ratePlan_name"].astype(str).str.lower()
    df["is_flex"] = rp.str.contains("flex", na=False)
    df["is_corporate_rate"] = rp.str.contains("firmen|corporate|business|hrs", regex=True, na=False)

    df["has_promo"] = _nonempty(df["promoCode"])
    # Unified contract code (company_code ?? corporateCode) - captures both
    # apaleo Companies AND corporate / OTA codes via a single group-by key.
    df["effective_code"] = _effective_code(df)
    df["has_code"] = df["effective_code"].notna()

    df["company"] = _effective_company(df)
    df["has_company"] = df["company"].notna()

    df["arrival_weekday"] = df["arrival"].dt.day_name()
    df["arrival_year_month"] = df["arrival"].dt.to_period("M").astype(str)
    df["created_year_month"] = df["created"].dt.to_period("M").astype(str)
    df["adr_per_night"] = df["revenue"] / df["nights"].replace(0, np.nan)

    # Storno economics straight from the apaleo fee columns (net basis).
    # Realized → full revenue kept; cancelled / no-show → the retained fee,
    # capped at the reservation revenue.
    fee_cancel = to_net(
        pd.to_numeric(df["cancellationFee_fee_amount"], errors="coerce").fillna(0.0)
    )
    fee_noshow = to_net(pd.to_numeric(df["noShowFee_fee_amount"], errors="coerce").fillna(0.0))
    df["kept_revenue"] = np.select(
        [df["is_realized"], df["is_cancelled"], df["is_no_show"]],
        [
            df["revenue"],
            np.minimum(fee_cancel, df["revenue"]),
            np.minimum(fee_noshow, df["revenue"]),
        ],
        default=0.0,
    )
    df["lost_revenue"] = (df["revenue"] - df["kept_revenue"]).round(2)
    df["kept_revenue"] = df["kept_revenue"].round(2)
    return _drop_zero_nights(df, "reservations")


def _nonempty(series: pd.Series) -> pd.Series:
    """True where the string value is present and not a null-ish placeholder."""
    cleaned = series.astype(str).str.strip().str.lower()
    return ~cleaned.isin({"", "nan", "none", "<na>", "null"})


# Apaleo carries two parallel contract-code fields:
#   * ``company_code``  - set when an apaleo Company account is linked to the
#                         reservation (the strict / hard link).
#   * ``corporateCode`` - set when a corporate / OTA booking code is attached,
#                         even if no apaleo Company is linked. Frequently
#                         filled when the hard link isn't, so analyses that
#                         only look at company_code drastically undercount
#                         business volume.
# We expose a unified ``effective_code`` that prefers company_code and falls
# back to corporateCode, so every downstream "contract" calculation sees both.
_CODE_PRIORITY = ("company_code", "corporateCode")


def _effective_code(df: pd.DataFrame) -> pd.Series:
    """First non-empty contract code: company_code → corporateCode.

    Returns a string Series with NaN where neither field is populated. Both
    fields are stripped and null-placeholder values ("", "nan", "none",
    "<na>", "null") are treated as empty. The result is what downstream
    analytics should treat as "this booking is on a contract".
    """
    code = pd.Series(pd.NA, index=df.index, dtype="object")
    for col in _CODE_PRIORITY:
        if col not in df.columns:
            continue
        vals = df[col].astype(str).str.strip()
        valid = ~vals.str.lower().isin({"", "nan", "none", "<na>", "null"})
        code = code.fillna(vals.where(valid))
    return code


# Priority for the combined "effective company" field: the linked apaleo
# company first, then the booker's company, then the guest's employer, and
# finally the unified contract code (company_code or corporateCode) as a
# last-resort firm identifier.
_COMPANY_PRIORITY = (
    "company_name",
    "booker_company_name",
    "primaryGuest_company_name",
    "_effective_code_for_walk",   # injected at call time, see _effective_company
)


def _effective_company(df: pd.DataFrame) -> pd.Series:
    """First non-empty company identifier across the priority columns.

    Many business travellers book without a formal apaleo company account, so
    relying on ``company_name`` alone undercounts corporate demand. This walks
    company_name → booker_company_name → primaryGuest_company_name →
    effective_code (= company_code ?? corporateCode) and takes the first value
    that is present.
    """
    company = pd.Series(pd.NA, index=df.index, dtype="object")
    # Pre-compute the unified code so it's available as a fallback identifier.
    fallback_code = _effective_code(df)
    for col in _COMPANY_PRIORITY:
        if col == "_effective_code_for_walk":
            vals = fallback_code.astype(str).str.strip()
            valid = ~vals.str.lower().isin({"", "nan", "none", "<na>", "null"})
            company = company.fillna(vals.where(valid))
            continue
        if col not in df.columns:
            continue
        vals = df[col].astype(str).str.strip()
        valid = ~vals.str.lower().isin({"", "nan", "none", "<na>", "null"})
        company = company.fillna(vals.where(valid))
    return company


# =============================================================================
# KPI engine
# =============================================================================
def landscape_kpis(
    nightly: pd.DataFrame,
    units: int,
    period_days_: int,
    realized_only: bool = True,
    reservations: pd.DataFrame | None = None,
) -> dict[str, float]:
    """Headline KPIs (revenue, ADR, occupancy, ALOS) für eine nightly-Slice.

    **Datenquelle: ausschließlich ``timeslices``** (Parquet ``timeslices.parquet``).
    Eine Zeile = eine genutzte Hotel-Nacht. ``nightly["revenue"]`` ist das ECHTE
    Netto pro Nacht (``baseAmount_netAmount``) - es variiert von Nacht zu Nacht
    (unterschiedliche Tagesraten), KEINE Gleichverteilung booking ÷ LOS. Genau
    deshalb laufen die Stay-/serviceDate-Sichten über die Timeslices und nicht
    über die Reservations (die das pro-Nacht-Detail gar nicht abbilden könnten).

    **Filter-Pipeline** (passiert in den Pages, BEVOR diese Funktion gerufen wird):

        nightly = H.load_timeslices(...)             # alle Nächte im Snapshot
        nig     = H.filter_period(nightly, start, end, date_col="stay_date")
        kpi     = H.landscape_kpis(nig, units, period_days)

    → Wir sehen also nur Nächte deren ``stay_date`` zwischen ``start`` und
    ``end`` liegt. Was VOR oder NACH dem Window an derselben Reservation
    hängt, fließt NICHT ein.

    ----------------------------------------------------------------------
    Zwei mögliche ADR/ALOS-Berechnungen (Diskussion siehe README §KPI-Logik):

    (A) "Timeslice-only" / Window-sauber  ← **wir nutzen das hier**
        - ``adr_eur``        = sum(revenue der Nights im Window) / Nights im Window
        - ``alos_nights_ts`` = Nights im Window / unique Reservations im Window
        → Antwort auf: *"Was kam in diesem Fenster real rein, pro Nacht?"*
        → Bei einer 14-Nacht-Buchung mit nur 3 Nächten im Window zählen
           genau 3 Nights und 3 × Nightly-Revenue.

    (B) "Reservation-based" / Bookings-zentriert
        - ``adr_eur_res``        = sum(booking_revenue) / sum(booking_nights)
                                    für alle Buchungen, die mindestens 1 Nacht
                                    im Window haben
        - ``alos_nights_res``    = mean(booking_nights) für dieselben Buchungen
        → Antwort auf: *"Was ist der durchschnittliche Gast den wir in diesem
           Fenster gesehen haben, über seine GANZE Buchung gerechnet?"*
        → Bei einer 14-Nacht-Buchung mit 3 Nächten im Window zählen alle
           14 Nights und das gesamte Booking-Revenue.

    **Für korrekte Variante-B-ADR**: das optionale ``reservations`` Argument
    übergeben (DataFrame mit ``id``, ``nights``, ``revenue``). Ohne das wird
    ``adr_eur_reservation`` NaN, weil aus ``nightly`` allein nicht die GANZE
    Buchungs-Länge ableitbar ist - ``nightly`` enthält nur Nights IM Window.

    Returns:
        revenue_eur           - sum of nightly revenue in window
        adr_eur               - primary ADR (Timeslice, "Variante A")
        adr_eur_reservation   - alternative ADR (Reservation-based, "Variante B")
        occupancy_pct         - room_nights / (units * period_days) * 100
        alos_nights           - primary ALOS = alos_nights_reservation (B,
                                  konvention der Hotelbranche)
        alos_nights_timeslice - alternative ALOS (A, window-sauber)
        n_bookings, room_nights, period_days, units_total
    """
    nig = nightly[nightly["is_realized"]] if realized_only else nightly
    revenue = float(nig["revenue"].sum())
    room_nights = int(len(nig))
    n_book = int(nig["id"].nunique())

    # Variante A - Timeslice-only ("was war IM Window")
    adr_timeslice  = revenue / room_nights if room_nights else float("nan")
    alos_timeslice = room_nights / n_book if n_book else float("nan")

    # Variante B - Reservation-based ("die ganze Buchung, wenn ≥1 Nacht drin").
    # Braucht das booking-level ``reservations``-Frame, weil ``nightly`` nur die
    # window-Slice ist - es liefert die gesamte Buchungs-LOS + das Booking-Total.
    # Revenue-Basis: auf der Standort-Seite wird hier (enriched) das aus den
    # Timeslices zurückgefaltete Nacht-Netto-Frame übergeben, ``revenue`` ist also
    # die Summe der Nacht-Netto je Buchung (OHNE Services) - konsistent mit der
    # restlichen App. Nur im Fallback (vor dem Voll-Refresh) ist es das
    # services-inklusive Reservations-Revenue.
    if n_book and reservations is not None and not reservations.empty:
        ids_in_window = set(nig["id"].dropna().unique())
        res_sub = reservations[reservations["id"].isin(ids_in_window)]
        if realized_only and "is_realized" in res_sub.columns:
            res_sub = res_sub[res_sub["is_realized"]]
        booking_revenue_total = float(res_sub["revenue"].sum())
        booking_nights_total  = int(res_sub["nights"].fillna(0).sum())
        adr_reservation = (booking_revenue_total / booking_nights_total
                            if booking_nights_total else float("nan"))
        alos_reservation = (float(res_sub["nights"].mean())
                             if len(res_sub) else float("nan"))
    elif n_book:
        # Fallback ohne reservations-DataFrame: ALOS-B via dedup im window
        # (korrekt weil ``nights`` in timeslices = volle Booking-LOS),
        # ADR-B nicht sauber rechenbar → NaN.
        deduped = nig.drop_duplicates("id")
        alos_reservation = float(deduped["nights"].mean()) if len(deduped) else float("nan")
        adr_reservation = float("nan")
    else:
        adr_reservation = float("nan")
        alos_reservation = float("nan")

    capacity = units * period_days_
    occupancy = room_nights / capacity * 100 if capacity else float("nan")

    return {
        "revenue_eur":            revenue,
        # Primary KPIs (was wir in den Headline-Cards anzeigen):
        "adr_eur":                adr_timeslice,
        "alos_nights":            alos_reservation,   # Hotelbranche-Konvention
        # Alternativen für transparency / Vergleich mit anderen Dashboards:
        "adr_eur_reservation":    adr_reservation,
        "alos_nights_timeslice":  alos_timeslice,
        # Common:
        "occupancy_pct":          occupancy,
        "n_bookings":             n_book,
        "room_nights":            room_nights,
        "period_days":            period_days_,
        "units_total":            units,
    }


def monthly_landscape(
    nightly: pd.DataFrame, units: int, realized_only: bool = True
) -> pd.DataFrame:
    """Per-month KPI DataFrame for trend lines."""
    nig = nightly[nightly["is_realized"]] if realized_only else nightly
    rows = []
    for ym, g in nig.groupby("stay_year_month"):
        days = pd.Period(ym, freq="M").days_in_month
        revenue = float(g["revenue"].sum())
        rn = int(len(g))
        deduped = g.drop_duplicates("id")
        rows.append(
            {
                "stay_year_month": ym,
                "days_in_month": days,
                "revenue_eur": revenue,
                "adr_eur": revenue / rn if rn else float("nan"),
                "occupancy_pct": rn / (units * days) * 100 if units * days else float("nan"),
                "alos_nights": float(deduped["nights"].mean()) if len(deduped) else float("nan"),
                "n_bookings": int(len(deduped)),
                "room_nights": rn,
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        # Leerer Slice (z.B. später Öffner ohne Daten in der Periode): leeres
        # Frame mit den erwarteten Spalten zurückgeben, statt bei .sort_values
        # auf eine nicht existierende Spalte zu crashen (KeyError).
        return pd.DataFrame(
            columns=[
                "stay_year_month", "days_in_month", "revenue_eur", "adr_eur",
                "occupancy_pct", "alos_nights", "n_bookings", "room_nights",
            ]
        )
    return out.sort_values("stay_year_month").reset_index(drop=True)


def pace_to_plan(
    start: pd.Timestamp,
    end: pd.Timestamp,
    today: pd.Timestamp | None = None,
) -> dict[str, float | str]:
    """Zeit-Fortschritt der Periode

    Returns:
        ``days_elapsed``, ``days_total``, ``elapsed_pct``,
        ``status`` ('completed', 'in_progress', 'future').

    Reine Ist-Sicht: wie weit ist die Periode zeitlich durch (Stichtag ``today``,
    in den Reports der Snapshot-Stand). Damit ordnet man IST/PLAN ein - bei 30 %
    verstrichener Zeit sind ~30 % vom PLAN = on-pace. Es wird NICHT auf das
    Periodenende hochgerechnet/extrapoliert.
    """
    today = pd.Timestamp(today) if today is not None else pd.Timestamp.today().normalize()
    days_total = period_days(start, end)
    if today < start:
        return {
            "days_elapsed": 0,
            "days_total": days_total,
            "elapsed_pct": 0.0,
            "status": "future"
        }
    if today >= end:
        return {
            "days_elapsed": days_total,
            "days_total": days_total,
            "elapsed_pct": 100.0,
            "status": "completed"
        }
    days_elapsed = (today - start).days + 1
    elapsed_pct = days_elapsed / days_total * 100
    return {
        "days_elapsed": days_elapsed,
        "days_total": days_total,
        "elapsed_pct": elapsed_pct,
        "status": "in_progress"
    }


def union_period(
    *periods: tuple[pd.Timestamp, pd.Timestamp],
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Smallest window covering all given periods - handy for one BigQuery pull
    that feeds multiple analysis windows in the same session.
    """
    starts = [p[0] for p in periods]
    ends = [p[1] for p in periods]
    return min(starts), max(ends)


def pace_by_month(
    nightly: pd.DataFrame,
    year_old: int,
    year_new: int,
    snapshot_date: pd.Timestamp,
    *,
    realized_only: bool = True,
    properties: list[str] | None = None,
) -> pd.DataFrame:
    """Pace by month - 3 Revenue-Werte je **Übernachtungs-Monat** (1-12).

    Läuft auf den **Timeslices** (``nightly``): eine Zeile = eine Nacht,
    ``revenue`` = Nacht-Netto (``baseAmount_netAmount``). Jede Nacht wird ihrem
    eigenen ``stay_date`` (= ``serviceDate``) zugeordnet - das Revenue landet im
    Monat der tatsächlichen Übernachtung, NICHT der Buchung/Anreise.

      - ``ist_eom_old``  : finale realisierte Realität für ``year_old`` (alle
                            12 Stay-Monate, realized-only).
      - ``ist_asof_old`` : On-the-books-Stand am ``snapshot_date`` minus 366
                            Tage (Vorjahres-Pendant des Snapshot-Stichtags).
      - ``ist_asof_new`` : On-the-books-Stand am ``snapshot_date``.

    "On the books" am Stichtag T = die Nacht gehört zu einer Buchung mit
    ``created <= T`` UND (nicht storniert ODER Storno erst nach T, d.h.
    ``cancel_time > T``). So zählen Nächte, die am Stichtag noch standen aber
    später storniert wurden, korrekt mit - sonst unterschätzen die asof-Serien
    den damaligen Stand.

    Storno-Zeitpunkt = ``cancel_time`` (trägt aus dem Engineering bereits
    ``cancellationTime`` mit ``modified`` als Fallback); fehlt ``cancel_time``,
    wird die rohe ``modified``-Spalte genutzt. Hat eine stornierte Nacht gar
    keinen Storno-Zeitstempel, wird sie ausgeschlossen (statt zeitlich
    rekonstruiert). NoShows sind überall ausgeschlossen. Alle Stichtage hängen
    am ``snapshot_date`` (Parquet-Stand), nie an "heute".
    """
    df = nightly
    if properties:
        df = df[df["property_code"].isin(properties)]
    # NoShows immer raus (Pace-Konvention).
    if "is_no_show" in df.columns:
        df = df[~df["is_no_show"].astype(bool)]
    if df.empty:
        return pd.DataFrame(columns=["month", "ist_eom_old", "ist_asof_old", "ist_asof_new"])

    stay_col = "stay_date" if "stay_date" in df.columns else "serviceDate"
    stay = pd.to_datetime(df[stay_col]).dt.normalize()
    created = pd.to_datetime(df["created"]).dt.normalize()
    rev = df["revenue"].astype(float)
    month = stay.dt.month

    cancelled = (
        df["is_cancelled"].astype(bool)
        if "is_cancelled" in df.columns
        else pd.Series(False, index=df.index)
    )
    realized = (
        df["is_realized"].astype(bool)
        if "is_realized" in df.columns
        else ~cancelled
    )
    # Storno-Zeitstempel: cancel_time (= cancellationTime ?? modified aus dem
    # Engineering), sonst rohe modified-Spalte; fehlt beides -> Stornos raus.
    _cancel_col = (
        "cancel_time" if "cancel_time" in df.columns
        else ("modified" if "modified" in df.columns else None)
    )
    cancel_ts = (
        pd.to_datetime(df[_cancel_col], errors="coerce").dt.normalize()
        if _cancel_col is not None
        else None
    )

    snap = pd.Timestamp(snapshot_date).normalize()
    snap_old = snap - pd.Timedelta(days=366)

    is_old_year = stay.dt.year == year_old
    is_new_year = stay.dt.year == year_new

    def _otb(asof: pd.Timestamp, year_mask: pd.Series) -> pd.Series:
        """Nacht-Netto on-the-books am Stichtag, gruppiert nach Stay-Monat."""
        if cancel_ts is not None:
            # nicht storniert ODER Storno erst nach dem Stichtag; storniert
            # ohne Zeitstempel -> raus.
            still_on = (~cancelled) | (cancelled & cancel_ts.notna() & (cancel_ts > asof))
        else:
            still_on = ~cancelled
        m = year_mask & (created <= asof) & still_on
        return rev[m].groupby(month[m]).sum()

    # finale Realität fürs alte Jahr: realized-only (bzw. nicht-storniert wenn
    # is_realized fehlt). realized_only=False -> alle nicht-stornierten Nächte.
    eom_base = realized if realized_only else ~cancelled
    eom_mask = is_old_year & eom_base
    eom_old = rev[eom_mask].groupby(month[eom_mask]).sum()

    asof_old = _otb(snap_old, is_old_year)
    asof_new = _otb(snap, is_new_year)

    out = pd.DataFrame({
        "month":        list(range(1, 13)),
        "ist_eom_old":  [float(eom_old.get(m, 0.0))  for m in range(1, 13)],
        "ist_asof_old": [float(asof_old.get(m, 0.0)) for m in range(1, 13)],
        "ist_asof_new": [float(asof_new.get(m, 0.0)) for m in range(1, 13)],
    })
    return out


# =============================================================================
# Firm-resolution definitions - multiple ways to identify the booking firm.
# =============================================================================
# Each definition produces a string identifier per reservation. NaN = no firm
# under that definition. The B2B deep-dive runs the same analysis once per
# active definition and surfaces them side-by-side so the user can compare.
FIRM_DEFINITIONS: tuple[str, ...] = (
    "firm_by_code",            # apaleo company_code only - strict contract view
    "firm_by_effective",       # priority walk: company_name → booker → guest → code
    "firm_by_effective_fuzzy", # effective + fuzzy-clustered name variants merged
    "firm_by_business_purpose",# travelPurpose == "Business" → effective company
)

FIRM_DEFINITION_LABELS: dict[str, str] = {
    "firm_by_code": "Company-Code (Vertrag)",
    "firm_by_effective": "Effective Company (Priority-Walk)",
    "firm_by_effective_fuzzy": "Effective + Fuzzy-Cluster",
    "firm_by_business_purpose": "Reisezweck = Business",
}


def add_firm_definitions(
    df: pd.DataFrame,
    *,
    apply_fuzzy: bool = True,
    fuzzy_threshold: int = 85,
) -> pd.DataFrame:
    """Add the four ``firm_by_*`` columns to a reservations frame in place.

    Returns the same frame (modified). All four columns hold either a string
    identifier or ``pd.NA``. The fuzzy column only differs from the effective
    column when fuzzy clustering is enabled and finds variants to merge.

    Idempotent: existing ``firm_by_*`` columns are not recomputed - useful
    when re-running without paying the fuzzy pipeline cost again.
    """
    # 1. firm_by_code - unified contract code: apaleo company_code falls back
    #    to corporateCode (corporate / OTA booking codes). If the engineered
    #    column ``effective_code`` is already present (set by
    #    engineer_reservations), use it directly; otherwise compute on the fly.
    if "firm_by_code" not in df.columns:
        if "effective_code" in df.columns:
            code = df["effective_code"]
        else:
            code = _effective_code(df)
        cleaned = code.astype("string").str.strip()
        df["firm_by_code"] = cleaned.where(
            cleaned.notna() & ~cleaned.str.lower().isin({"", "nan", "none", "<na>", "null"})
        )

    # 2. firm_by_effective - uses the existing priority-walk if present.
    if "firm_by_effective" not in df.columns:
        if "company" in df.columns:
            df["firm_by_effective"] = df["company"].astype("string").where(df["company"].notna())
        else:
            df["firm_by_effective"] = _effective_company(df).astype("string")

    # 3. firm_by_effective_fuzzy - fuzzy-cluster the effective name.
    if "firm_by_effective_fuzzy" not in df.columns:
        if apply_fuzzy:
            df["firm_by_effective_fuzzy"] = cluster_companies(
                df["firm_by_effective"], threshold=fuzzy_threshold,
            )
        else:
            df["firm_by_effective_fuzzy"] = df["firm_by_effective"]

    # 4. firm_by_business_purpose - effective company filtered to business trips.
    if "firm_by_business_purpose" not in df.columns:
        is_business = df["travelPurpose"].astype(str).str.lower().eq("business")
        df["firm_by_business_purpose"] = df["firm_by_effective"].where(is_business)

    return df


# Konstante Booking-Level-Felder, die per ``id`` auf die Timeslices gebroadcastet
# werden, damit die Nightly-Tabelle die reservation-level / "nach
# Erstellungsdatum"-Analysen auf der Nacht-Netto-Basis tragen kann. BEWUSST OHNE
# Booking-€-Summen (``kept_revenue`` / ``lost_revenue``) - die würden sich über
# die Nächte vervielfachen.
_RESERVATION_FIELDS_FOR_TIMESLICES: tuple[str, ...] = (
    "firm_by_code",
    "firm_by_effective",
    "firm_by_effective_fuzzy",
    "firm_by_business_purpose",
    "company",
    "has_company",
    "company_code",
    "effective_code",
    "has_code",
    "has_promo",
    # Roher Promocode-String - nötig, damit die Promo-Reklassifizierung
    # (overrides.apply_code_overrides) auch auf der Nacht-Netto-Basis greift.
    "promoCode",
    "lead_time_days",
    "lead_time_bucket",
    "cancel_lead_time_days",
    "cancel_time",
    "is_flex",
    "is_corporate_rate",
    "created_year_month",
    "arrival_weekday",
    # Roh-Fee-Beträge (buchungsweit konstant) - daraus rechnet
    # ``reservations_from_timeslices`` kept/lost auf der Nacht-Netto-Basis.
    "cancellationFee_fee_amount",
    "noShowFee_fee_amount",
)


def enrich_timeslices_with_reservation_fields(
    nig: pd.DataFrame, res: pd.DataFrame
) -> pd.DataFrame:
    """Broadcast konstante Booking-Level-Felder von ``res`` auf ``nig`` (per ``id``).

    Jede Stay-Nacht erbt die buchungsweit konstanten Attribute ihrer Reservierung
    (Vorlaufzeit, Firmen-Clustering, Vertragscodes, Rate-Flags), damit die
    Nightly-Tabelle die reservation-level / "nach Erstellungsdatum"-Analysen auf
    der Nacht-Netto-Revenue-Basis rechnen kann. Booking-€-Summen
    (``kept_revenue`` / ``lost_revenue``) werden bewusst NICHT mitgebroadcastet -
    sie würden sich über die Nächte vervielfachen.

    Defensiv: nur Felder, die in ``res`` vorhanden und in ``nig`` noch nicht da
    sind, werden ergänzt. Nächte, deren ``id`` keine Reservierung matcht, bleiben
    NaN. Verändert die Zeilenzahl nicht (Left-Join auf eindeutige ``id``).

    Args:
        nig: Engineerte Timeslices (eine Zeile je Stay-Nacht, ``id`` = Reservierungs-id).
        res: Engineerte Reservations inkl. ``firm_by_*`` (eine Zeile je ``id``).

    Returns:
        ``nig`` mit den zusätzlichen Spalten (Kopie).
    """
    if "id" not in nig.columns or "id" not in res.columns:
        return nig
    cols = [
        c
        for c in _RESERVATION_FIELDS_FOR_TIMESLICES
        if c in res.columns and c not in nig.columns
    ]
    if not cols:
        return nig
    lookup = res.drop_duplicates("id").set_index("id")[cols]
    return nig.join(lookup, on="id")


def timeslices_are_enriched(nightly: pd.DataFrame) -> bool:
    """True wenn ``nightly`` die gebroadcasteten Booking-Felder trägt.

    Sentinel für "Snapshot nach dem Foundation-Refresh" - die reservation-level
    Analysen brauchen u.a. ``lead_time_bucket`` und ``firm_by_effective_fuzzy``.
    """
    if nightly is None or nightly.empty:
        return False
    return "lead_time_bucket" in nightly.columns and "firm_by_effective_fuzzy" in nightly.columns


def reservations_from_timeslices(nightly: pd.DataFrame) -> pd.DataFrame:
    """Timeslices auf Buchungs-Ebene zurückfalten (eine Zeile je ``id``).

    ``revenue`` = Summe der (geladenen) Nacht-Netto je Buchung
    (``baseAmount_netAmount``); alle anderen Spalten sind buchungsweit konstant
    und werden via ``first()`` übernommen. Ergebnis ist ein reservations-förmiges
    Frame, das die services-inklusive ``reservations`` in den reservation-level /
    "nach Erstellungsdatum"-Analysen ersetzt - gleiche Nacht-Netto-Revenue-Basis
    wie die Aufenthalts-Tabellen. Counts auf dem Ergebnis zählen Buchungen (eine
    Zeile je ``id``), nicht Nächte.

    ``kept_revenue`` / ``lost_revenue`` werden hier neu auf der Nacht-Netto-Basis
    berechnet (identische Storno-Ökonomie wie ``engineer_reservations``, nur mit
    Nacht-Netto statt services-inklusivem Booking-Revenue): realized → voll
    behalten; Storno/No-Show → die einbehaltene Fee, gedeckelt auf das
    Nacht-Netto der Buchung.

    Voraussetzung: ``nightly`` ist angereichert
    (siehe ``enrich_timeslices_with_reservation_fields`` /
    ``timeslices_are_enriched``).
    """
    if nightly is None or nightly.empty or "id" not in nightly.columns:
        return nightly.iloc[0:0].copy() if nightly is not None else pd.DataFrame()
    g = nightly.groupby("id", sort=False)
    out = g.first()
    out["revenue"] = g["revenue"].sum()

    # Storno-Ökonomie auf Nacht-Netto-Basis (analog engineer_reservations).
    if {"is_realized", "is_cancelled", "is_no_show"}.issubset(out.columns):
        rev = out["revenue"].astype(float)

        def _fee(col: str) -> pd.Series:
            if col in out.columns:
                return to_net(pd.to_numeric(out[col], errors="coerce").fillna(0.0))
            return pd.Series(0.0, index=out.index)

        fee_cancel = _fee("cancellationFee_fee_amount")
        fee_noshow = _fee("noShowFee_fee_amount")
        kept = np.select(
            [out["is_realized"], out["is_cancelled"], out["is_no_show"]],
            [rev, np.minimum(fee_cancel, rev), np.minimum(fee_noshow, rev)],
            default=0.0,
        )
        out["kept_revenue"] = np.round(kept, 2)
        out["lost_revenue"] = np.round(rev - kept, 2)

    return out.reset_index()


# =============================================================================
# Fuzzy company-name clustering - merges legal-form / spelling variants.
# =============================================================================
def cluster_companies(
    names: pd.Series,
    *,
    threshold: int = 85,
    block_prefix_len: int = 3,
    max_block_size: int = 2000,
) -> pd.Series:
    """Cluster a Series of free-text company names into canonical labels.

    Returns a Series of the same shape, mapping each input name to its cluster
    representative (the highest-frequency variant within the cluster). NaN
    inputs stay NaN. Idempotent: passing an already-clustered Series doesn't
    change it.

    Implementation: token-prefix blocking → within-block fuzzy similarity
    (rapidfuzz.process.cdist with token_sort_ratio) → union-find clustering
    → anti-chaining post-pass so transitively-bridged members get ejected.

    If ``rapidfuzz`` is not installed the function falls back to no-op
    behaviour (returns the input unchanged) with a warning - clusters can
    always be added later by installing rapidfuzz and re-running.
    """
    import re as _re
    import unicodedata as _ud
    from collections import defaultdict as _dd

    try:
        from rapidfuzz import fuzz as _fuzz, process as _process  # type: ignore
    except ImportError:
        import warnings as _warnings
        _warnings.warn(
            "rapidfuzz not installed - cluster_companies falling back to "
            "identity mapping. Run `pip install rapidfuzz` for full fuzzy "
            "clustering."
        )
        return names

    legal_forms = (
        "ag & co. kg", "ag & co kg", "gmbh & co. kg", "gmbh & co kg",
        "se & co. kg", "se & co kg", "aktiengesellschaft",
        "gmbh", "ag", "se", "kg", "ohg", "ug", "e.v.", "ev",
        "limited", "ltd", "ltd.", "inc", "inc.", "corp", "corp.",
        "company", "co.", "co", "plc", "llc", "n.v.", "nv",
        "sa", "s.a.", "spa", "s.p.a.", "bv", "b.v.",
    )
    segment_patterns = (
        r",?\s*segment\s+\S+.*$",
        r",?\s*pg\s+\d+.*$",
        r",?\s*region\s+\S+.*$",
        r",?\s*division\s+\S+.*$",
        r",?\s*business\s*unit\s+\S+.*$",
        r"\s+-\s+.*$",
    )

    def normalise(name: object) -> str:
        if pd.isna(name):
            return ""
        s = str(name).strip().lower()
        s = _ud.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
        for pat in segment_patterns:
            s = _re.sub(pat, "", s, flags=_re.IGNORECASE)
        s = _re.sub(r"[^a-z0-9\s]", " ", s)
        for lf in legal_forms:
            s = _re.sub(rf"\b{_re.escape(lf)}\b", " ", s)
        return _re.sub(r"\s+", " ", s).strip()

    # 1. Unique names ranked by frequency - top variant becomes representative.
    freq = names.dropna().value_counts()
    if freq.empty:
        return names
    unique = freq.index.to_numpy()
    n = len(unique)
    normalised = np.array([normalise(s) for s in unique])

    # 2. Blocking on first ``block_prefix_len`` chars of each token.
    blocks: dict[str, list[int]] = _dd(list)
    for i, nm in enumerate(normalised):
        if not nm:
            continue
        for key in {tok[:block_prefix_len] for tok in nm.split() if tok}:
            blocks[key].append(i)

    # 3. Union-find clustering inside each block.
    parent = list(range(n))
    rank = [0] * n

    def find(x: int) -> int:
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if rank[ra] < rank[rb]:
            ra, rb = rb, ra
        parent[rb] = ra
        if rank[ra] == rank[rb]:
            rank[ra] += 1

    scorer = _fuzz.token_sort_ratio
    for idxs in blocks.values():
        if len(idxs) < 2 or len(idxs) > max_block_size:
            continue
        norms = normalised[idxs].tolist()
        sims = _process.cdist(
            norms, norms, scorer=scorer, score_cutoff=threshold,
            dtype=np.uint8, workers=-1,
        )
        rows, cols = np.where(sims >= threshold)
        mask = rows < cols
        for r, c in zip(rows[mask], cols[mask]):
            union(idxs[r], idxs[c])

    # 4. Map each unique input to the highest-frequency variant in its cluster.
    roots = [find(i) for i in range(n)]
    cluster_rep: dict[int, int] = {}
    for i in range(n):
        r = int(roots[i])
        if r not in cluster_rep:
            cluster_rep[r] = i
    canonical = {unique[i]: unique[cluster_rep[int(roots[i])]] for i in range(n)}

    # 5. Anti-chaining: members not similar enough to the rep get ejected.
    norm_map = dict(zip(unique.tolist(), normalised.tolist()))
    cluster_members: dict[object, list[object]] = _dd(list)
    for orig, can in canonical.items():
        cluster_members[can].append(orig)
    for can, members in list(cluster_members.items()):
        if len(members) < 2:
            continue
        can_norm = norm_map.get(can, "")
        for m in members:
            if m == can:
                continue
            if scorer(norm_map.get(m, ""), can_norm) < threshold:
                canonical[m] = m

    return names.map(canonical).where(names.notna())


def revenue_by(nightly: pd.DataFrame, *dims: str, realized_only: bool = True) -> pd.DataFrame:
    """Aggregate net revenue + room nights + bookings by one or more dims."""
    df = nightly[nightly["is_realized"]] if realized_only else nightly
    g = (
        df.groupby(list(dims), observed=True)
        .agg(
            revenue_eur=("revenue", "sum"),
            room_nights=("revenue", "size"),
            n_bookings=("id", "nunique"),
        )
        .reset_index()
    )
    g["adr_eur"] = (g["revenue_eur"] / g["room_nights"]).round(2)
    g["revenue_eur"] = g["revenue_eur"].round(0)
    return g


def yoy_by(
    nig_old: pd.DataFrame,
    nig_new: pd.DataFrame,
    *dims: str,
    realized_only: bool = True,
    value: str = "revenue_eur",
) -> pd.DataFrame:
    """Side-by-side YoY along dims with abs Δ, % Δ and share-shift (pp)."""
    a = revenue_by(nig_old, *dims, realized_only=realized_only).set_index(list(dims))
    b = revenue_by(nig_new, *dims, realized_only=realized_only).set_index(list(dims))
    cols = [value, "room_nights", "n_bookings"]
    out = a[cols].join(b[cols], lsuffix="_old", rsuffix="_new", how="outer").fillna(0)
    out[f"{value}_delta_abs"] = out[f"{value}_new"] - out[f"{value}_old"]
    out[f"{value}_delta_pct"] = np.where(
        out[f"{value}_old"] > 0,
        (out[f"{value}_new"] / out[f"{value}_old"] - 1) * 100,
        np.nan,
    )
    s_old, s_new = out[f"{value}_old"].sum(), out[f"{value}_new"].sum()
    out["share_old_pct"] = (out[f"{value}_old"] / s_old * 100).round(1) if s_old else np.nan
    out["share_new_pct"] = (out[f"{value}_new"] / s_new * 100).round(1) if s_new else np.nan
    out["share_delta_pp"] = (out["share_new_pct"] - out["share_old_pct"]).round(1)
    return out.sort_values(f"{value}_new", ascending=False)


def yoy_two_panel(nig_old, nig_new, dim, super_title, year_old, year_new):
    """Two-panel YoY chart: revenue bars (left) + share-shift in pp (right).

    Grouped by ``dim``. Returns a matplotlib Figure. Shared by several
    Standort-Analyse sections so the YoY layout stays consistent.
    """
    import matplotlib.pyplot as plt

    from .theming import categorical_palette, color

    pal = categorical_palette()
    yoy = yoy_by(nig_old, nig_new, dim).reset_index()
    yoy[dim] = yoy[dim].astype(str)
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.4))

    ax = axes[0]
    y = np.arange(len(yoy))
    w = 0.4
    ax.barh(
        y - w / 2,
        yoy["revenue_eur_old"],
        w,
        color=pal[1],
        edgecolor=color("black"),
        linewidth=0.4,
        label=str(year_old),
    )
    ax.barh(
        y + w / 2,
        yoy["revenue_eur_new"],
        w,
        color=pal[0],
        edgecolor=color("black"),
        linewidth=0.4,
        label=str(year_new),
    )
    for i, (vo, vn) in enumerate(zip(yoy["revenue_eur_old"], yoy["revenue_eur_new"], strict=True)):
        ax.text(max(vo, vn), i, "  Δ " + fmt_eur(vn - vo), va="center", fontsize=9)
    ax.set_yticks(y)
    ax.set_yticklabels(yoy[dim])
    ax.set_xlabel("Revenue (EUR, netto)")
    ax.set_title("Revenue YoY")
    ax.legend(frameon=False, fontsize=9)

    ax = axes[1]
    ax.barh(
        y,
        yoy["share_delta_pp"],
        color=[color("green") if v >= 0 else color("red") for v in yoy["share_delta_pp"]],
        edgecolor=color("black"),
        linewidth=0.4,
    )
    for i, v in enumerate(yoy["share_delta_pp"]):
        ax.text(v, i, f"  {v:+.1f} pp", va="center", fontsize=9)
    ax.axvline(0, color="black", linewidth=0.5)
    ax.set_yticks(y)
    ax.set_yticklabels(yoy[dim])
    ax.set_xlabel("Anteils-Verschiebung (pp)")
    ax.set_title("Anteils-Verschiebung")
    fig.suptitle(super_title, fontsize=13, weight="bold", y=1.0)
    fig.tight_layout()
    return fig


# =============================================================================
# Period helpers - fully dynamic analysis window
# =============================================================================
_MONTHS_DE_SHORT = {
    1: "Jan",
    2: "Feb",
    3: "Mär",
    4: "Apr",
    5: "Mai",
    6: "Jun",
    7: "Jul",
    8: "Aug",
    9: "Sep",
    10: "Okt",
    11: "Nov",
    12: "Dez",
}
_MONTHS_DE_LONG = {
    1: "Januar",
    2: "Februar",
    3: "März",
    4: "April",
    5: "Mai",
    6: "Juni",
    7: "Juli",
    8: "August",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "Dezember",
}


def filter_period(
    df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, date_col: str
) -> pd.DataFrame:
    """Filter a DataFrame to the day-window [start, end], both bounds inclusive.

    The date column is normalised to midnight first, so a timestamp column
    (e.g. ``arrival``) is matched on its calendar day - the end bound stays
    inclusive even for same-day afternoon timestamps.
    """
    day = df[date_col].dt.normalize()
    return df[(day >= start.normalize()) & (day <= end.normalize())].copy()


def period_days(start_ts: pd.Timestamp, end_ts: pd.Timestamp) -> int:
    """Inclusive day count between two timestamps."""
    return int((end_ts - start_ts).days) + 1


def mirror_years(ts: pd.Timestamp, years: int) -> pd.Timestamp:
    """Shift a timestamp back by ``years`` whole calendar years.

    Keeps month and day so a comparison window lands on the same calendar
    position in the earlier year (e.g. ``2026-06-25`` minus 1 year is
    ``2025-06-25``). A ``29 February`` source clamps to ``28 February`` in a
    non-leap target year. ``years`` may be zero (no shift) or negative (shift
    forward).

    Args:
        ts: Source timestamp.
        years: Number of years to subtract (negative adds years).

    Returns:
        The year-shifted, midnight-normalised timestamp.
    """
    ts = pd.Timestamp(ts).normalize()
    target_year = ts.year - int(years)
    try:
        return ts.replace(year=target_year)
    except ValueError:
        # 29 Feb -> 28 Feb in a non-leap target year.
        return ts.replace(year=target_year, day=28)


# Deutsche Monats-Kurzlabels (Index 0 = Januar) - genutzt von den
# Monat+Tag-Filtern im Global Report (jahr-unabhängige Erstellungs-Fenster).
MONTH_ABBR_DE: tuple[str, ...] = (
    "Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
    "Jul", "Aug", "Sep", "Okt", "Nov", "Dez",
)


def clamp_day(year: int, month: int, day: int) -> pd.Timestamp:
    """Build a midnight ``Timestamp`` for (year, month, day), clamping the day.

    A day beyond the month's length is clamped to the last valid day (e.g. day
    31 in a 30-day month becomes 30, 29/30/31 Feb become 28/29). Lets the
    month+day creation-date filters accept any day 1-31 without raising for
    short months.

    Args:
        year: Calendar year the month/day is anchored to.
        month: Month 1-12.
        day: Desired day 1-31 (clamped to the month length).

    Returns:
        Midnight-normalised ``pd.Timestamp``.
    """
    first = pd.Timestamp(year=int(year), month=int(month), day=1)
    last_day = (first + pd.offsets.MonthEnd(0)).day
    return pd.Timestamp(
        year=int(year), month=int(month), day=min(int(day), int(last_day))
    ).normalize()


def asof_on_the_books_mask(
    df: pd.DataFrame,
    asof: pd.Timestamp,
    *,
    include_cancellations: bool,
) -> pd.Series:
    """Boolean mask of rows that were on the books at ``asof`` (point-in-time).

    A row counts as on the books at the cutoff when it was already created
    (``created <= asof``) and - unless cancellations are included - had at that
    date neither been cancelled nor resolved as a no-show. Both the cancellation
    and the no-show test are applied **point-in-time**, each with its own
    resolution date:

    * Storno: the row is still on the books if it was never cancelled, or
      cancelled strictly after ``asof`` (``cancel_time > asof``). A cancelled row
      whose ``cancel_time`` is missing is treated as cancelled and dropped.
    * No-show: a no-show only becomes *known* on the arrival day - until then the
      guest could still check in. The resolution date is therefore ``arrival``:
      the row stays on the books while ``arrival > asof`` and only drops once the
      cutoff has reached the arrival day (``asof >= arrival``). A no-show row
      whose ``arrival`` is missing is treated as resolved and dropped.

    Konsequenz: liegt das Erstellungs-Fenster komplett vor dem
    Aufenthalts-Fenster (z.B. gebucht im Juni, Aufenthalt im Juli), ist
    ``asof < arrival`` für alle Zeilen - No-Shows zählen dann per Default mit,
    weil am Stichtag noch nicht bekannt war, dass der Gast nicht kommt.
    Überschneiden sich Erstellungs- und Aufenthalts-Fenster (z.B. beides im
    Juli), werden früh gebuchte, No-Shows als
    aufgelöst erkannt und fallen aus der realized-Sicht.

    Same convention as the Global-Report Storno/No-Show toggle, applied here
    point-in-time for both event types.

    Args:
        df: Nightly/timeslices frame with ``created``, ``is_cancelled``,
            ``is_no_show``, ``cancel_time`` and ``arrival`` columns.
        asof: Point-in-time cutoff, inclusive on ``created``.
        include_cancellations: When ``True`` every row created on or before
            ``asof`` counts (cancellations + no-shows included); when ``False``
            the point-in-time cancellation AND no-show filters apply.

    Returns:
        Boolean ``pd.Series`` aligned to ``df.index``. Empty input yields an
        empty boolean Series.
    """
    if df is None or len(df) == 0:
        return pd.Series([], dtype=bool)
    asof = pd.Timestamp(asof).normalize()
    created = pd.to_datetime(df["created"]).dt.normalize()
    created_ok = created <= asof
    if include_cancellations:
        return created_ok

    # --- Storno point-in-time: aufgelöst am cancel_time ---
    cancelled = (
        df["is_cancelled"].astype(bool)
        if "is_cancelled" in df.columns
        else pd.Series(False, index=df.index)
    )
    if "cancel_time" in df.columns:
        cancel_ts = pd.to_datetime(df["cancel_time"], errors="coerce").dt.normalize()
        cancel_still_on = (~cancelled) | (cancelled & cancel_ts.notna() & (cancel_ts > asof))
    else:
        cancel_still_on = ~cancelled

    # --- No-Show point-in-time
    no_show = (
        df["is_no_show"].astype(bool)
        if "is_no_show" in df.columns
        else pd.Series(False, index=df.index)
    )
    if "arrival" in df.columns:
        arrival_ts = pd.to_datetime(df["arrival"], errors="coerce").dt.normalize()
        no_show_still_on = (~no_show) | (no_show & arrival_ts.notna() & (arrival_ts > asof))
    else:
        no_show_still_on = ~no_show

    return created_ok & cancel_still_on & no_show_still_on


def fmt_eur(value: float, decimals: int = 0) -> str:
    """Format a number as a German-style euro string, e.g. '1.234 €'."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "–"
    return f"{value:,.{decimals}f} €".replace(",", "X").replace(".", ",").replace("X", ".")

