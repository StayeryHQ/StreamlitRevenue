"""Billige, exakte Cache-Keys für DataFrame-Argumente von ``st.cache_data``.

Streamlits Default-Hash für DataFrames ≥ 50 000 Zeilen ist eine 10 000-Zeilen-
Stichprobe (``runtime/caching/hashing.py``): gemessen 0,27 s je Aufruf und
nur so eindeutig wie die Stichprobe. Die Frames, die die Tabellen-/Chart-
Builder bekommen, sind aber immer Teilmengen des geteilten Snapshot-Slices
(``cached_data._session_slice`` schreibt die Slice-Signatur in ``df.attrs``;
pandas reicht ``attrs`` durch ``[mask]``, ``.copy()``, ``groupby`` weiter).
Der Key ist deshalb:

    Slice-Signatur | Spalten+Dtypes | Hash der Index-Positionen

Das identifiziert die Zeilenmenge exakt (Index = Positionen im Slice) und
kostet Millisekunden. Frames ohne Signatur (kleine Ergebnis-Tabellen) werden
vollständig gehasht - exakt statt Stichprobe.

Verwendung::

    @st.cache_data(ttl=3600, max_entries=8, hash_funcs=DF_HASH_FUNCS)
"""

from __future__ import annotations

import hashlib

import pandas as pd
from pandas.util import hash_pandas_object

SLICE_SIG_ATTR = "slice_sig"


def df_cache_key(df: pd.DataFrame) -> str:
    """Exakter, billiger Key für ein DataFrame-Argument (siehe Modul-Docstring)."""
    cols = hashlib.md5(
        "|".join(f"{c}:{df[c].dtype}" for c in df.columns).encode("utf-8")
    ).hexdigest()[:12]
    sig = df.attrs.get(SLICE_SIG_ATTR) if isinstance(df.attrs, dict) else None
    if sig and len(df):
        idx_hash = hashlib.md5(hash_pandas_object(df.index).to_numpy().tobytes()).hexdigest()[:16]
        return f"slice:{sig}|cols={cols}|n={len(df)}|idx={idx_hash}"
    # Kein Slice-Bezug: vollständiger Inhalts-Hash (kleine Frames).
    try:
        vals = hash_pandas_object(df, index=True).to_numpy().tobytes()
    except TypeError:
        vals = df.to_json(date_format="iso", default_handler=str).encode("utf-8")
    return f"full:cols={cols}|n={len(df)}|v={hashlib.md5(vals).hexdigest()[:16]}"


DF_HASH_FUNCS = {pd.DataFrame: df_cache_key}
