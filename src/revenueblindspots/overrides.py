"""Promo-Code-Reklassifizierung: Override-Store + Anwendung auf Buchungs-Frames.

Marketing-Promocodes und echte Firmencodes landen teils im selben
``promoCode``-Feld. Dieses Modul erlaubt es, einzelne Promocodes als Firmencode
zu *reklassifizieren*: betroffene Buchungen werden so behandelt, als trügen sie
einen ``corporateCode`` (= effektiver Vertragscode). Damit tauchen sie in jeder
Analyse (B2B Deep-Dive, Code Deep-Dive, Global Report) als Firmencode-Buchungen
auf.

Persistenz: ``configs/code_overrides.json`` (stdlib-JSON, keine Extra-Dependency).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

from . import helpers as H

# Schlüssel im JSON-Store: {promo_as_firmencode: {CODE: {firm, note, added}}}.
_STORE_KEY = "promo_as_firmencode"

# Null-ähnliche Platzhalter, die wie "leer" behandelt werden (konsistent zu
# helpers._nonempty / _effective_code).
_NULLISH = {"", "nan", "none", "<na>", "null"}


def _store_path() -> Path:
    """Pfad zum Override-Store.

    Priorisierung:

    1. Umgebungsvariable ``STAYERY_OVERRIDES_FILE`` - wenn gesetzt, gewinnt sie
       immer (nützlich für Tests / bewusste Verlagerung).
    2. Sonst der **Snapshot-/Volume-Ordner** neben den Parquets
       (``find_snapshot_dir`` - im Docker das gemountete Volume ``/app/data``,
       lokal ``<repo>/data``).
    3. Letzte Rückfallebenen: lokaler ``data/``-Ordner, dann ``configs/``.

    Returns:
        Pfad zur JSON-Datei (existiert evtl. noch nicht).
    """
    env = os.environ.get("STAYERY_OVERRIDES_FILE", "").strip()
    if env:
        return Path(env)

    snap = H.find_snapshot_dir()
    if isinstance(snap, Path):
        return snap / "code_overrides.json"

    # snap ist remote (gs://…) oder noch nicht vorhanden -> lokaler data-Ordner
    # (im Docker der Volume-Mount-Point) als Default, configs als letzter Ausweg.
    data_dir = Path(__file__).resolve().parents[2] / "data"
    if data_dir.is_dir():
        return data_dir / "code_overrides.json"
    return H.CONFIGS_DIR / "code_overrides.json"


def store_location() -> str:
    """Aktueller Speicherort des Override-Stores als String (für die UI-Anzeige).

    Returns:
        Absoluter Pfad zur JSON-Datei.
    """
    return str(_store_path())


def load_overrides() -> dict[str, dict[str, dict[str, Any]]]:
    """Lade den Override-Store von Disk.

    Returns:
        Dict der Form ``{"promo_as_firmencode": {CODE: {...}}}``. Leerer Store
        (``{"promo_as_firmencode": {}}``) wenn die Datei fehlt oder kaputt ist.
    """
    path = _store_path()
    if not path.is_file():
        return {_STORE_KEY: {}}
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {_STORE_KEY: {}}
    mapping = data.get(_STORE_KEY) if isinstance(data, dict) else None
    if not isinstance(mapping, dict):
        return {_STORE_KEY: {}}
    # Schlüssel normalisieren (Upper, getrimmt) - defensiv gegen Alt-Einträge.
    clean: dict[str, dict[str, Any]] = {}
    for raw_code, payload in mapping.items():
        code = str(raw_code).strip().upper()
        if not code:
            continue
        clean[code] = payload if isinstance(payload, dict) else {}
    return {_STORE_KEY: clean}


def promo_overrides() -> dict[str, dict[str, Any]]:
    """Convenience: nur die ``{CODE: {...}}``-Map der Promo-Reklassifizierungen.

    Returns:
        Mapping CODE (upper) -> Payload-Dict (z.B. ``{"firm": "BCD Travel"}``).
    """
    return load_overrides()[_STORE_KEY]


def save_overrides(mapping: dict[str, dict[str, Any]]) -> Path:
    """Schreibe den Override-Store atomar auf Disk.

    Args:
        mapping: ``{CODE: {firm?, note?, added?}}``. Schlüssel werden auf
            getrimmtes Upper normalisiert.

    Returns:
        Pfad der geschriebenen Datei.
    """
    clean: dict[str, dict[str, Any]] = {}
    for raw_code, payload in mapping.items():
        code = str(raw_code).strip().upper()
        if not code:
            continue
        clean[code] = payload if isinstance(payload, dict) else {}
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump({_STORE_KEY: clean}, fh, ensure_ascii=False, indent=2, sort_keys=True)
    tmp.replace(path)
    return path


def add_promo_overrides(codes_with_firm: dict[str, str | None]) -> Path:
    """Füge Promocodes als Firmencodes hinzu (merge in den bestehenden Store).

    Args:
        codes_with_firm: ``{CODE: firm_name_or_None}``. Vorhandene Einträge mit
            gleichem Code werden überschrieben.

    Returns:
        Pfad der geschriebenen Datei.
    """
    current = promo_overrides()
    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    for raw_code, firm in codes_with_firm.items():
        code = str(raw_code).strip().upper()
        if not code:
            continue
        firm_clean = (str(firm).strip() or None) if firm is not None else None
        current[code] = {"firm": firm_clean, "added": today}
    return save_overrides(current)


def remove_promo_override(code: str) -> Path:
    """Entferne einen einzelnen Promocode aus dem Store.

    Args:
        code: Der zu entfernende Code (case-insensitive).

    Returns:
        Pfad der geschriebenen Datei.
    """
    current = promo_overrides()
    current.pop(str(code).strip().upper(), None)
    return save_overrides(current)


def override_signature() -> str:
    """Stabile Signatur des Stores für die Cache-Invalidierung.

    Ändert sich, sobald sich die Datei ändert (mtime + Größe). Damit verwerfen
    die Cache-Loader ihre Caches automatisch, wenn eine
    Reklassifizierung gespeichert wird.

    Returns:
        Signatur-String (``none`` wenn kein Store existiert).
    """
    path = _store_path()
    try:
        stat = path.stat()
    except OSError:
        return "none"
    return f"{int(stat.st_mtime)}:{stat.st_size}"


def _empty_mask(series: pd.Series) -> pd.Series:
    """True wo der String-Wert leer / null-ähnlich ist."""
    cleaned = series.astype("string").str.strip().str.lower()
    return cleaned.isna() | cleaned.isin(_NULLISH)


def apply_code_overrides(df: pd.DataFrame) -> pd.DataFrame:
    """Reklassifiziere Promocodes als Firmencodes auf einem Buchungs-Frame.

    Für jede Buchung, deren ``promoCode`` im Override-Store steht, werden die
    Vertragscode-/Firmen-Felder so gesetzt, dass die Buchung downstream als
    Firmencode-Buchung zählt:

    * ``corporateCode`` / ``effective_code`` werden mit dem Promocode gefüllt,
      sofern noch leer (eine bereits gesetzte Firmencode-Buchung bleibt
      unangetastet).
    * ``has_code`` -> True, ``firm_by_code`` wird gesetzt.
    * Wurde im Store ein Firmenname hinterlegt, werden ``company`` /
      ``firm_by_effective`` / ``firm_by_effective_fuzzy`` befüllt (wo leer).

    Idempotent und defensiv: nur vorhandene Spalten werden angefasst. Auf Frames
    ohne ``promoCode`` (z.B. Timeslices vor dem Refresh) passiert nichts.

    Args:
        df: Reservations- oder Timeslices-förmiger Frame.

    Returns:
        Neuer Frame mit angewandten Overrides und Marker-Spalte
        ``is_reclassified_promo``. Bei leerem Store wird ``df`` unverändert
        zurückgegeben (keine Kopie, kein Marker) - der Null-Kosten-Pfad.
    """
    mapping = promo_overrides()
    if not mapping or df is None or getattr(df, "empty", True):
        return df
    if "promoCode" not in df.columns:
        return df

    codes = set(mapping.keys())  # bereits upper/getrimmt
    pc_upper = df["promoCode"].astype("string").str.strip().str.upper()
    sel = pc_upper.isin(codes).fillna(False).astype(bool)
    if not sel.any():
        return df

    out = df.copy()
    out["is_reclassified_promo"] = sel
    target_code = out["promoCode"].astype("string").str.strip()
    firm_for = pc_upper.map(lambda c: (mapping.get(c) or {}).get("firm"))
    firm_for = firm_for.astype("string")
    has_firm = firm_for.notna() & (firm_for.str.strip() != "")

    if "corporateCode" in out.columns:
        m = sel & _empty_mask(out["corporateCode"])
        out.loc[m, "corporateCode"] = target_code[m]

    if "effective_code" in out.columns:
        m = sel & _empty_mask(out["effective_code"])
        out.loc[m, "effective_code"] = target_code[m]
    else:
        out.loc[sel, "effective_code"] = target_code[sel]

    if "has_code" in out.columns:
        if out["has_code"].dtype not in (bool, "boolean"):
            # Defensiv: falls die Spalte NULLs enthält (z.B. Timeslices, wo
            # `has_code` nicht für jede Zeile gesetzt ist), kommt sie als
            # object oder - nach `_optimize_string_memory` - als
            # string[pyarrow] an. Auf die nullable "boolean"-Dtype casten
            # (erhält NA statt sie in bool zu erzwingen); ein direktes
            # `= True` auf einer Arrow-String-Spalte würde sonst TypeError
            # werfen.
            out["has_code"] = out["has_code"].astype("boolean")
        out.loc[sel, "has_code"] = True

    if "firm_by_code" in out.columns:
        m = sel & _empty_mask(out["firm_by_code"])
        out.loc[m, "firm_by_code"] = target_code[m]
    else:
        out.loc[sel, "firm_by_code"] = target_code[sel]

    firm_mask = sel & has_firm
    if firm_mask.any():
        for col in ("company", "firm_by_effective", "firm_by_effective_fuzzy"):
            if col in out.columns:
                m = firm_mask & _empty_mask(out[col])
                out.loc[m, col] = firm_for[m]
        if "has_company" in out.columns:
            if out["has_company"].dtype not in (bool, "boolean"):
                out["has_company"] = out["has_company"].astype("boolean")
            out.loc[firm_mask, "has_company"] = True

    return out
