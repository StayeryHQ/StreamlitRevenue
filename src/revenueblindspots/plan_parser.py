"""Parser für das Wide-Format Plan-Excel.

Drei öffentliche Funktionen:

  - ``parse_wide_plan(source, sheet_name=None)`` - kernparser. ``source`` kann
    ``bytes``, ein Datei-Pfad (``str`` / ``Path``) oder ein file-like Objekt sein.
    Rückgabe: ``{"plan": {hotel_code: {YYYY-MM: eur}}, "rows": preview_df,
                "unknown": [...], "warnings": [...], "sheet": str, "sheets": [str]}``.
  - ``load_default_plan_path()`` - Pfad zur ``data/plan_default.xlsx``, oder None.
  - ``load_default_plan()`` - bequem: lädt die Default-Datei und gibt nur den
    ``plan``-Dict zurück (`{hotel_code: {YYYY-MM: eur}}`).

Robustheit:
  - **Monats-Spalten** werden über Header-Text geparst (`_parse_month_header`),
    NICHT über Position. Reihenfolge egal
  - **Hotel-Label-Spalte** wird automatisch detektiert - die erste Spalte,
    deren Header NICHT als Monat parsbar ist, ist die Label-Spalte. Damit
    überlebt der Parser auch, wenn jemand die Reihenfolge der Spalten ändert.
"""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

import pandas as pd

# Späte Imports innerhalb der Funktionen, damit das Modul ohne `yaml`
# laufen kann (für reine Parser-Tests).


# ============================== Month header parser =======================
_MONTH_NAMES_DE = {
    "jan": 1, "feb": 2, "mär": 3, "mar": 3, "apr": 4, "mai": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "okt": 10, "oct": 10, "nov": 11, "dez": 12, "dec": 12,
}


def parse_month_header(raw) -> str | None:
    """Convert various month-header formats to canonical 'YYYY-MM'.

    Accepted: ``01-25``, ``01-2025``, ``2025-01``, ``Jan 2025``, ``25-Jan``,
    ``01.2025``, ``01/25``, plus pandas Timestamp/Period objects.
    Returns None if the input cannot be interpreted as a month.
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    if isinstance(raw, pd.Period):
        return str(raw)
    if isinstance(raw, pd.Timestamp):
        return raw.strftime("%Y-%m")
    s = str(raw).strip()
    if not s:
        return None
    # MM-YY (e.g. '01-25')
    m = re.fullmatch(r"(\d{1,2})[-./](\d{2})", s)
    if m:
        mm, yy = int(m.group(1)), int(m.group(2))
        if 1 <= mm <= 12:
            return f"20{yy:02d}-{mm:02d}"
    # MM-YYYY (e.g. '01-2025' or '1.2025')
    m = re.fullmatch(r"(\d{1,2})[-./](\d{4})", s)
    if m:
        mm, yyyy = int(m.group(1)), int(m.group(2))
        if 1 <= mm <= 12:
            return f"{yyyy:04d}-{mm:02d}"
    # YYYY-MM (e.g. '2025-01')
    m = re.fullmatch(r"(\d{4})[-./](\d{1,2})", s)
    if m:
        yyyy, mm = int(m.group(1)), int(m.group(2))
        if 1 <= mm <= 12:
            return f"{yyyy:04d}-{mm:02d}"
    # 'Jan 2025' / '25-Jan'
    parts = re.split(r"[\s\-]+", s.lower())
    if len(parts) == 2:
        for a, b in [(parts[0], parts[1]), (parts[1], parts[0])]:
            if a[:3] in _MONTH_NAMES_DE and re.fullmatch(r"\d{2,4}", b):
                mm = _MONTH_NAMES_DE[a[:3]]
                yyyy = int(b) if len(b) == 4 else 2000 + int(b)
                return f"{yyyy:04d}-{mm:02d}"
    # Fallback to pandas
    try:
        return pd.Timestamp(s).strftime("%Y-%m")
    except (ValueError, TypeError):
        return None


# ============================== Property resolver =========================
def _location_index(locations_path: Path | None = None) -> dict[str, str]:
    """Build a flexible lookup: city / 'city neighborhood' / hotel_code → hotel_code.

    Cities with multiple hotels (e.g. Köln) get value ``__AMBIGUOUS__`` for
    the bare-city key - caller must use 'city neighborhood' to disambiguate.
    """
    import yaml
    if locations_path is None:
        locations_path = (Path(__file__).resolve().parents[2]
                           / "configs" / "locations.yaml")
    with Path(locations_path).open(encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    idx: dict[str, str] = {}
    for loc in cfg.get("locations", []):
        code = loc["hotel_code"]
        city = (loc.get("city") or "").strip()
        neigh = (loc.get("neighborhood") or "").strip()
        idx[code.upper()] = code
        if city:
            idx.setdefault(city.lower(), code)  # first hit wins
            if neigh:
                idx[f"{city} {neigh}".lower()] = code
    cities_count: dict[str, int] = {}
    for loc in cfg.get("locations", []):
        c = (loc.get("city") or "").strip().lower()
        if c:
            cities_count[c] = cities_count.get(c, 0) + 1
    for c, n in cities_count.items():
        if n > 1:
            idx[c] = "__AMBIGUOUS__"
    return idx


def resolve_property(raw: str, idx: dict[str, str]) -> tuple[str | None, str | None]:
    """Resolve a user-typed label to a hotel_code.

    Returns ``(hotel_code, error_message)``. ``hotel_code`` is None if not resolved.
    Accepts: ``PLAN:Berlin``, ``Berlin``, ``Köln Sülz``, ``CGN_WS``, …
    """
    s = str(raw).strip()
    if ":" in s:
        s = s.split(":", 1)[1].strip()
    if not s:
        return None, "leer"
    hit = idx.get(s.upper())
    if hit and hit != "__AMBIGUOUS__":
        return hit, None
    hit = idx.get(s.lower())
    if hit == "__AMBIGUOUS__":
        return None, (f"'{s}' ist mehrdeutig (mehrere Hotels in dieser Stadt) - "
                      f"bitte Stadt + Neighborhood angeben, z.B. 'Köln Sülz'.")
    if hit:
        return hit, None
    return None, f"'{s}' kein bekannter Standort"


# ============================== Hotel-label column detection ==============
def _detect_label_column(columns: list) -> tuple[Any, list, list]:
    """Find the column that holds hotel labels.

    Algorithm: erste Spalte deren Header NICHT als Monat parsbar ist gewinnt.
    Damit ist die Reihenfolge der Excel-Spalten egal - solange genau eine
    nicht-Monat-Spalte existiert.

    Returns:
        (label_col, month_cols_resolved, bad_label_cols_extras)
        - label_col: the chosen hotel-label column
        - month_cols_resolved: list of (raw_col, 'YYYY-MM' or None)
        - bad_label_cols_extras: weitere non-month-Spalten (Warning anzeigen)
    """
    non_month: list = []
    month_pairs: list = []
    for c in columns:
        ym = parse_month_header(c)
        if ym is None:
            non_month.append(c)
        else:
            month_pairs.append((c, ym))
    if not non_month:
        raise ValueError(
            "Keine Hotel-Label-Spalte gefunden - alle Spalten-Header sehen wie "
            "Monate aus. Erste Spalte muss Hotel-Namen / -Codes enthalten."
        )
    label_col = non_month[0]
    extras = non_month[1:]
    # Auch leere/„unparseable" Header (z.B. „Total") rutschen als non_month
    # rein - die zählen wir aber nicht als Hotel-Spalten, sondern als Extras.
    return label_col, month_pairs, extras


# ============================== Core parser ===============================
def parse_wide_plan(
    source: bytes | str | Path,
    sheet_name: str | None = None,
    locations_path: Path | None = None,
) -> dict[str, Any]:
    """Parse a wide-format Plan-Excel into the override dict shape.

    ``source`` may be raw ``bytes`` (from an upload), a filesystem path, or
    a ``pathlib.Path``. Sheet defaults to the first one.

    Returns ``{"plan": {hotel_code: {YYYY-MM: eur}}, "rows": preview_df,
                "unknown": [labels], "warnings": [strings],
                "sheet": str, "sheets": [str]}``.
    """
    if isinstance(source, (bytes, bytearray)):
        bio: Any = io.BytesIO(bytes(source))
    elif isinstance(source, (str, Path)):
        bio = io.BytesIO(Path(source).read_bytes())
    else:
        bio = source

    xl = pd.ExcelFile(bio)
    sheet = sheet_name or xl.sheet_names[0]
    df = pd.read_excel(bio, sheet_name=sheet, header=0)
    if df.empty or df.shape[1] < 2:
        raise ValueError("Datei hat keine Daten oder weniger als 2 Spalten.")

    idx = _location_index(locations_path)
    label_col, month_pairs, extra_label_cols = _detect_label_column(list(df.columns))
    valid_month_cols = [(c, ym) for c, ym in month_pairs if ym]

    plan: dict[str, dict[str, float]] = {}
    unknown: list[str] = []
    preview_rows: list[dict] = []
    for _, r in df.iterrows():
        label = r[label_col]
        if pd.isna(label) or not str(label).strip():
            continue
        code, err = resolve_property(label, idx)
        if not code:
            unknown.append(f"{label} ({err})")
            continue
        for raw_col, ym in valid_month_cols:
            val = r[raw_col]
            try:
                v = float(val)
            except (TypeError, ValueError):
                continue
            if pd.isna(v):
                continue
            plan.setdefault(code, {})[ym] = v
            preview_rows.append({"hotel_code": code, "month": ym, "plan_eur": v})

    warnings: list[str] = []
    if extra_label_cols:
        warnings.append(
            f"{len(extra_label_cols)} weitere Nicht-Monats-Spalten wurden "
            f"ignoriert: {', '.join(str(c) for c in extra_label_cols[:5])}"
            f"{'…' if len(extra_label_cols) > 5 else ''}. Falls eine davon "
            f"die Hotel-Spalte ist, lösche die andere(n) und lade neu hoch."
        )
    return {
        "plan": plan,
        "rows": pd.DataFrame(preview_rows),
        "unknown": unknown,
        "warnings": warnings,
        "sheet": sheet,
        "sheets": xl.sheet_names,
        "label_col": label_col,
    }


# ============================== Default-Plan loaders ======================
def load_default_plan_path() -> Path | None:
    """Return the path to the repo-committed default plan, or None if missing."""
    p = Path(__file__).resolve().parents[2] / "data" / "plan_default.xlsx"
    return p if p.exists() else None


def load_default_plan() -> dict[str, dict[str, float]]:
    """Parse ``data/plan_default.xlsx`` if present and return the ``plan`` dict.

    Returns an empty dict if the file does not exist or parses to nothing -
    callers can treat empty as „kein Default vorhanden".
    """
    path = load_default_plan_path()
    if path is None:
        return {}
    try:
        result = parse_wide_plan(path)
    except Exception:
        # Defensive: lieber leerer Default als gecrashte App
        return {}
    return result.get("plan") or {}
