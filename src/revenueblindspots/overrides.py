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
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import helpers as H

# Schlüssel im JSON-Store: {promo_as_firmencode: {CODE: {firm, note, added}}}.
_STORE_KEY = "promo_as_firmencode"

# Null-ähnliche Platzhalter, die wie "leer" behandelt werden (konsistent zu
# helpers._nonempty / _effective_code).
_NULLISH = {"", "nan", "none", "<na>", "null"}


@lru_cache(maxsize=1)
def _store_path() -> Path:
    """Pfad zum Override-Store (einmal je Prozess aufgelöst).

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
    die ``st.cache_data``-Loader ihre Caches automatisch, wenn eine
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


def _norm(series: pd.Series, *, upper: bool) -> pd.Series:
    """``astype("string").str.strip().str.upper()/lower()`` - kategorie-bewusst.

    Bei ``category``-Spalten wird nur über die (wenigen) Kategorien gerechnet
    und per Codes zurückprojiziert - statt über alle 730k Zeilen.
    """
    if isinstance(series.dtype, pd.CategoricalDtype):
        cats = series.cat.categories.astype("string").str.strip()
        cats = cats.str.upper() if upper else cats.str.lower()
        arr = np.append(cats.to_numpy(dtype=object), None)  # letzter Slot = NaN-Code -1
        out = arr[series.cat.codes.to_numpy()]
        return pd.Series(out, index=series.index, dtype="string")
    s = series.astype("string").str.strip()
    return s.str.upper() if upper else s.str.lower()


def _empty_mask(series: pd.Series) -> pd.Series:
    """True wo der String-Wert leer / null-ähnlich ist."""
    cleaned = _norm(series, upper=False)
    return cleaned.isna() | cleaned.isin(_NULLISH)


def _set_where(col: pd.Series | None, mask: pd.Series, values, *, index=None) -> pd.Series:
    """Neue Spalte: ``values`` wo ``mask`` True, sonst ``col`` - ohne In-Place-Schreiben.

    ``col`` wird als eigene Serie kopiert (eine Spalte, nicht das Frame) und
    dort maskiert beschrieben; das geteilte Original bleibt unberührt. Ist
    ``col`` None, entsteht eine neue String-Spalte über ``index``.

    Args:
        col: Bestehende Spalte oder None.
        mask: Boolean-Serie, wo geschrieben werden soll.
        values: Serie (indexgleich) oder Skalar.
        index: Index für eine neue Spalte (nur wenn ``col`` None).

    Returns:
        Die neue Spalte.
    """
    new = col.copy() if col is not None else pd.Series(pd.NA, index=index, dtype="string")
    if mask.any():
        vals = values[mask] if isinstance(values, pd.Series) else values
        if isinstance(new.dtype, pd.CategoricalDtype):
            # Kategorie-Spalte (helpers.optimize_dtypes): neue Werte müssen erst
            # als Kategorien bekannt sein, sonst TypeError beim Setzen.
            wanted = pd.Series(vals).dropna().unique() if isinstance(vals, pd.Series) else [vals]
            missing = pd.Index(wanted).difference(new.cat.categories)
            if len(missing):
                new = new.cat.add_categories(list(missing))
            if isinstance(vals, pd.Series):
                vals = vals.astype(object)
        new[mask] = vals
    return new


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
    pc_upper = _norm(df["promoCode"], upper=True)
    sel = pc_upper.isin(codes).fillna(False).astype(bool)
    if not sel.any():
        return df

    # Flache Kopie: die Spalten-Arrays werden mit ``df`` geteilt, nur die
    # tatsächlich veränderten Spalten werden als NEUE Arrays gesetzt
    # (``_set_where``) - kein ``.loc``-Schreiben in geteilte Blöcke. Spart die
    # komplette Kopie des 730k-Zeilen-Frames (~650 MB Peak) beim Snapshot-Load.
    out = df.copy(deep=False)
    out["is_reclassified_promo"] = sel
    # Nur die betroffenen Zeilen (``sel``) werden materialisiert - alles
    # andere bleibt NA. Die Masken unten sind immer mit ``sel`` verundet.
    target_code = pd.Series(pd.NA, index=out.index, dtype="string")
    target_code[sel] = out.loc[sel, "promoCode"].astype("string").str.strip()
    firm_map = {c: (mapping.get(c) or {}).get("firm") for c in codes}
    firm_for = pd.Series(pd.NA, index=out.index, dtype="string")
    firm_for[sel] = pc_upper[sel].map(firm_map).astype("string")
    has_firm = firm_for.notna() & (firm_for.str.strip() != "")

    if "corporateCode" in out.columns:
        m = sel & _empty_mask(out["corporateCode"])
        out["corporateCode"] = _set_where(out["corporateCode"], m, target_code)

    if "effective_code" in out.columns:
        m = sel & _empty_mask(out["effective_code"])
        out["effective_code"] = _set_where(out["effective_code"], m, target_code)
    else:
        out["effective_code"] = _set_where(None, sel, target_code, index=out.index)

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
        out["has_code"] = _set_where(out["has_code"], sel, True)

    if "firm_by_code" in out.columns:
        m = sel & _empty_mask(out["firm_by_code"])
        out["firm_by_code"] = _set_where(out["firm_by_code"], m, target_code)
    else:
        out["firm_by_code"] = _set_where(None, sel, target_code, index=out.index)

    firm_mask = sel & has_firm
    if firm_mask.any():
        for col in ("company", "firm_by_effective", "firm_by_effective_fuzzy"):
            if col in out.columns:
                m = firm_mask & _empty_mask(out[col])
                out[col] = _set_where(out[col], m, firm_for)
        if "has_company" in out.columns:
            if out["has_company"].dtype not in (bool, "boolean"):
                out["has_company"] = out["has_company"].astype("boolean")
            out["has_company"] = _set_where(out["has_company"], firm_mask, True)

    return out
