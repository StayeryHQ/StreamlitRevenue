"""Cache-Layer für die Streamlit-App.

Drei Tasks:

  1. Parquet-Snapshot-Loader (Reservations + Timeslices)
  2. Chart-PNG-Cache: matplotlib-Figures werden gerendert und als PNG bytes
     in `st.session_state` gehalten.
  3. matplotlib-Style + Memory-Cleanup-Utilities.
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import streamlit as st

from revenueblindspots import helpers as H
from revenueblindspots import overrides as OV

from .cache_keys import SLICE_SIG_ATTR


# ============================== Cache key helper ==========================
def _resolved_snapshot_dir():
    """Snapshot-Verzeichnis auflösen: env ``STAYERY_SNAPSHOT_DIR`` → Repo-Default.

    Der Pfad ist eine Deployment-Eigenschaft und für ALLE Sessions identisch.
    Der frühere Per-Session-Override (``snapshot_dir_override``) ist entfernt:
    er erzeugte je Session einen anderen Cache-Key für dieselben Parquets
    (``local=data`` vs. ``local=/app/data``), und mit ``max_entries=1`` haben
    sich die Sessions den geteilten Snapshot gegenseitig aus dem Cache
    verdrängt (Reload 7-8 s + >1 GB Peak bei jedem Wechsel).

    Lokale Pfade werden absolut aufgelöst, damit die Signatur eindeutig ist.
    """
    snap = H.find_snapshot_dir()
    if isinstance(snap, Path):
        return snap.expanduser().resolve()
    return snap


def _snapshot_signature() -> str:
    """Stable string for the current snapshot - invalidates cache when it changes."""
    snap_dir = _resolved_snapshot_dir()
    if snap_dir is None:
        return "none"
    if isinstance(snap_dir, Path):
        try:
            res_path = snap_dir / H.SNAPSHOT_FILES["reservations"]
            mtime = int(res_path.stat().st_mtime) if res_path.exists() else 0
            return f"local={snap_dir}|mtime={mtime}"
        except OSError:
            return f"local={snap_dir}|nostat"
    return f"remote={snap_dir}"


def _override_signature() -> str:
    """Signatur des Promo-Reklassifizierungs-Stores (Cache-Invalidierung).

    Ändert sich, sobald eine Reklassifizierung gespeichert/entfernt wird - die
    Daten-Loader laden dann mit frisch angewandten Overrides neu.
    """
    return OV.override_signature()


# ============================== Cached loaders ============================
# WICHTIG: Die Signatur-Parameter dürfen NICHT mit "_" beginnen - Streamlit
# schließt Unterstrich-Parameter vom Cache-Key aus. Vorher war die
# mtime-/Override-Invalidierung dadurch komplett wirkungslos (Review A2-Familie);
# nur das explizite st.cache_*.clear() nach dem Refresh hat es kaschiert.
# ``_snap_dir`` bleibt bewusst ungehasht (durch die Signatur bestimmt).
@st.cache_data(ttl=3600, show_spinner=False, max_entries=4)
def load_snapshot_metadata_cached(snapshot_sig: str, _snap_dir=None) -> dict:
    return H.load_snapshot_metadata(_snap_dir) or {}


@st.cache_data(ttl=3600, show_spinner=False, max_entries=4)
def load_plan_cached(snapshot_sig: str, _snap_dir=None) -> pd.DataFrame:
    """Planzahlen aus ``plan.parquet`` (BigQuery-Snapshot), cache-invalidiert
    über den Snapshot-Signatur-Key."""
    return H.load_plan(_snap_dir)


# Großer, unveränderlicher Snapshot: EIN cache_resource-Eintrag je Tabelle
# (geteilt über alle Sessions, keine Kopie pro Cache-Hit). Gefiltert wird danach
# in-memory - kein wiederholter Disk-Read.
#
# Review RAM-Postmortem:
#   F4 - vorher gab es je Tabelle ZWEI Einträge: ``_raw_*`` und, darauf
#        aufbauend, ``_overridden_*``. ``apply_code_overrides`` legt eine Kopie
#        an, sobald der Override-Store greift - der rohe Frame blieb daneben
#        gecacht. Gemessen ≈ 817 MB, auf die nie jemand direkt zugegriffen hat.
#        Jetzt: Overrides direkt im gecachten Loader, ein Eintrag pro Tabelle.
#   F3 - ``max_entries`` fehlte. Streamlit setzt ``None`` intern auf
#        ``math.inf`` (``runtime/caching/cache_resource_api.py``), der Cache war
#        also unbegrenzt: nach einem Refresh lag der alte Snapshot bis zu einer
#        Stunde (TTL) neben dem neuen im Speicher. ``max_entries=1`` verdrängt
#        den alten Eintrag, sobald die Snapshot-Signatur wechselt.
@st.cache_resource(ttl=3600, show_spinner=False, max_entries=1)
def _reservations_cached(snapshot_sig: str, override_sig: str, _snap_dir=None) -> pd.DataFrame:
    """Reservations aus dem Snapshot, Promo-Overrides bereits angewandt."""
    return OV.apply_code_overrides(H.load_reservations(snapshot_dir=_snap_dir))


@st.cache_resource(ttl=3600, show_spinner=False, max_entries=1)
def _timeslices_cached(snapshot_sig: str, override_sig: str, _snap_dir=None) -> pd.DataFrame:
    """Timeslices aus dem Snapshot, Promo-Overrides bereits angewandt."""
    return OV.apply_code_overrides(H.load_timeslices(snapshot_dir=_snap_dir))


def _filter_frame(
    df: pd.DataFrame,
    date_col: str,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
    properties: tuple[str, ...] | None,
) -> pd.DataFrame:
    """In-Memory-Filter (Datum + Standorte) auf dem geteilten Snapshot.

    Identische Semantik wie der Disk-Filter ``helpers._read_parquet_with_filter``
    (Kalendertag-normalisiert, ``property_code`` per ``isin``), aber ohne den
    Snapshot erneut von der Platte zu lesen und ohne das geteilte (gecachte)
    Frame zu verändern.

    ``df[mask]`` materialisiert bereits ein NEUES Frame - das frühere
    zusätzliche ``.copy()`` hat denselben Slice ein zweites Mal angelegt
    (gemessen: +421 MB Peak je Rerun bei allen Standorten). Ohne jedes
    Filterkriterium wird das geteilte Frame selbst zurückgegeben; Seiten
    schreiben NIE in ``nightly``/``res`` (Konvention - abgeleitete Frames
    kommen aus ``groupby``/``[mask]`` und sind ohnehin eigene Objekte).
    """
    mask = None
    if (start is not None or end is not None) and date_col in df.columns:
        col = df[date_col]
        if not pd.api.types.is_datetime64_any_dtype(col):
            col = pd.to_datetime(col, errors="coerce")
        day = col.dt.normalize()
        if start is not None:
            m = day >= pd.Timestamp(start).normalize()
            mask = m if mask is None else (mask & m)
        if end is not None:
            m = day <= pd.Timestamp(end).normalize()
            mask = m if mask is None else (mask & m)
    if properties and "property_code" in df.columns:
        m = df["property_code"].isin(list(properties))
        mask = m if mask is None else (mask & m)
    if mask is None:
        return df
    return df[mask]


# ============================== Per-Session-Slice-Cache ===================
# Jeder Rerun einer Seite (jeder Widget-Klick) hat den Slice der Seite neu aus
# dem geteilten Snapshot geschnitten (~1 s + 170-420 MB je Rerun, bei
# ``fastReruns`` auch mehrfach parallel). Der Slice hängt nur von Snapshot,
# Overrides und den Filterwerten ab - er wird deshalb je Session EINMAL pro
# Filterkombination berechnet und wiederverwendet. Genau ein Eintrag je
# Tabelle (timeslices/reservations): ein Filterwechsel ersetzt ihn, sodass pro
# Session nie mehr als ein Slice je Tabelle lebt (wie vorher, nur ohne die
# Kopie bei jedem Rerun). ``st.cache_data`` wäre hier falsch: es würde den
# Slice bei jedem Lesen entpickeln (gemessen 0,5 s + zweite Kopie).
_SLICE_CACHE_KEY = "_snapshot_slice_cache"


def _slice_signature(kind: str, start, end, properties) -> str:
    s = pd.Timestamp(start).normalize().date() if start is not None else "-"
    e = pd.Timestamp(end).normalize().date() if end is not None else "-"
    p = "+".join(sorted(properties)) if properties else "*"
    return f"{kind}|{_snapshot_signature()}|{_override_signature()}|{s}|{e}|{p}"


def _session_slice(kind: str, df: pd.DataFrame, date_col: str, start, end, properties):
    sig = _slice_signature(kind, start, end, properties)
    bucket = st.session_state.setdefault(_SLICE_CACHE_KEY, {})
    hit = bucket.get(sig)
    if hit is not None:
        return hit
    out = _filter_frame(df, date_col, start, end, properties)
    if out is df:
        out = df.copy(deep=False)  # eigenes attrs-Dict, Spalten bleiben geteilt
    out.attrs[SLICE_SIG_ATTR] = sig  # -> cache_keys.df_cache_key
    for k in [k for k in bucket if k.startswith(kind + "|")]:
        bucket.pop(k, None)
    bucket[sig] = out
    return out


@st.cache_resource(ttl=3600, show_spinner=False, max_entries=3)
def _bookings_cached(slice_sig: str, _nig: pd.DataFrame) -> pd.DataFrame:
    """Buchungs-Frame (eine Zeile je ``id``) aus einem Timeslices-Slice.

    ``reservations_from_timeslices`` lief vorher auf 4 Seiten bei JEDEM Rerun
    ungecacht (gemessen 1-4,5 s). Der Key ist die Slice-Signatur (Snapshot,
    Overrides, Fenster, Standorte), also prozessweit geteilt; ``max_entries=3``
    begrenzt den Speicher auf drei Buchungs-Frames (≤ ~150 MB je Frame).
    """
    return H.reservations_from_timeslices(_nig)


def get_bookings_from(nightly: pd.DataFrame) -> pd.DataFrame:
    """Gecachter Ersatz für ``H.reservations_from_timeslices(nightly)``.

    Gibt eine flache Kopie zurück: Seiten dürfen Spalten ersetzen
    (``res["company"] = ...``), ohne das geteilte Cache-Objekt zu verändern.
    """
    sig = nightly.attrs.get(SLICE_SIG_ATTR) or _slice_signature(
        "timeslices", None, None, tuple(nightly["property_code"].dropna().unique())
    )
    return _bookings_cached(sig, nightly).copy(deep=False)


# ============================== Convenience wrappers =====================
def get_metadata() -> dict:
    return load_snapshot_metadata_cached(_snapshot_signature(), _resolved_snapshot_dir())


def get_plan_df() -> pd.DataFrame:
    """Planzahlen aus ``plan.parquet`` (BigQuery-Snapshot). Leer wenn fehlt."""
    return load_plan_cached(_snapshot_signature(), _resolved_snapshot_dir())


def get_active_plan() -> dict:
    """Plan als ``{property_code: {"YYYY-MM": eur}}`` für IST/PLAN-Vergleiche.

    Einzige Quelle: ``plan.parquet`` aus dem BigQuery-Snapshot (kein Upload/
    Override mehr). Leeres Dict wenn noch kein Plan-Snapshot existiert.
    """
    return H.plan_to_dict(get_plan_df())


def get_reservations(
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    properties: list[str] | None = None,
) -> pd.DataFrame:
    df = _reservations_cached(
        _snapshot_signature(), _override_signature(), _resolved_snapshot_dir()
    )
    return _session_slice(
        "reservations", df, "arrival", start, end, tuple(properties) if properties else None
    )


def get_timeslices(
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    properties: list[str] | None = None,
) -> pd.DataFrame:
    df = _timeslices_cached(
        _snapshot_signature(), _override_signature(), _resolved_snapshot_dir()
    )
    return _session_slice(
        "timeslices", df, "serviceDate", start, end, tuple(properties) if properties else None
    )


# ============================== Chart-PNG-Cache ===========================
_CHART_CACHE_MAX = 24  # je Session; PNG ~100-300 KB, Extras (kleine Frames) mit
_DEFAULT_DPI = 130  # hochstellen wennimmernoch unscharf

def snapshot_tag() -> str:
    """Short tag to mix into chart cache keys so a snapshot refresh invalidates
    every cached PNG automatically.
    """
    return _snapshot_signature()


def chart_png(cache_key: str, fig_fn, *args, dpi: int = _DEFAULT_DPI, **kwargs):
    """Render a chart function to PNG bytes"""
    bucket = st.session_state.setdefault("_chart_png_cache", {})
    extras_bucket = st.session_state.setdefault("_chart_extras_cache", {})

    if cache_key in bucket:
        cached = bucket[cache_key]
        if cache_key in extras_bucket:
            return cached, extras_bucket[cache_key]
        return cached

    result = fig_fn(*args, **kwargs)
    if isinstance(result, tuple):
        fig, *extras = result
        extras = tuple(extras) if extras else None
    else:
        fig, extras = result, None

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    # OO-Figure (theming.subplots): nicht bei pyplot registriert, kein close nötig.
    png = buf.getvalue()

    bucket[cache_key] = png
    if extras is not None:
        extras_bucket[cache_key] = extras

    # Simple LRU-ish cap (insertion order)
    if len(bucket) > _CHART_CACHE_MAX:
        for k in list(bucket.keys())[: len(bucket) - _CHART_CACHE_MAX]:
            bucket.pop(k, None)
            extras_bucket.pop(k, None)

    return (png, extras) if extras is not None else png


# ============================== Style + cleanup ===========================
_STYLE_APPLIED = False


def apply_stayery_style_once() -> None:
    """matplotlib-Brand-Style EINMAL je Prozess setzen (rcParams sind prozessweit).

    Vorher pro Session (Session-State-Flag) - das schrieb dieselben globalen
    rcParams aus jeder Session neu. Ein ``collect()`` mit ``plt.close("all")``
    am Seitenende gibt es nicht mehr: Figuren kommen aus ``theming.subplots``
    (OO-API, nicht bei pyplot registriert) und ``runner.postScriptGC`` (Default
    True) lässt den GC ohnehin nach jedem Lauf laufen.
    """
    global _STYLE_APPLIED
    if _STYLE_APPLIED:
        return
    from revenueblindspots.theming import apply_stayery_style

    apply_stayery_style()
    import matplotlib as mpl

    mpl.rcParams["savefig.dpi"] = _DEFAULT_DPI
    mpl.rcParams["figure.dpi"] = _DEFAULT_DPI
    _STYLE_APPLIED = True


# ============================== Data-table expander =======================
def data_table_expander(
    df,
    *,
    title: str = "Datentabelle",
    filename: str | None = None,
    expanded: bool = False,
    max_rows_display: int = 200,
    height: int | None = None,
) -> None:
    """Standard-UI für „Tabelle zu diesem Chart" - Expander + CSV-Download."""
    if df is None:
        return
    try:
        import pandas as _pd

        if not isinstance(df, _pd.DataFrame):
            df = _pd.DataFrame(df)
        if df.empty:
            return
    except Exception:
        return

    with st.expander(title, expanded=expanded):
        display_df = df.head(max_rows_display) if len(df) > max_rows_display else df
        kwargs = {"hide_index": True, "use_container_width": True}
        if height is not None:
            kwargs["height"] = height
        st.dataframe(display_df, **kwargs)
        if len(df) > max_rows_display:
            st.caption(
                f"Anzeige limitiert auf {max_rows_display} Zeilen "
                f"({len(df):,} insgesamt) - der CSV-Download enthält alle Daten.".replace(",", ".")
            )
        # CSV erst beim Klick erzeugen (data=<Funktion>, on_click="ignore") -
        # vorher lief ``to_csv`` der kompletten Tabelle bei jedem Rerun, auch
        # bei zugeklapptem Expander (17 Aufrufstellen).
        st.download_button(
            "Als CSV herunterladen",
            data=lambda: df.to_csv(index=False).encode("utf-8"),
            file_name=(filename or "datentabelle") + ".csv",
            mime="text/csv",
            on_click="ignore",
            key=f"dl_csv_{title}_{filename or 'x'}",
        )


# ============================== Filter persistence =======================
_PERSIST_KEY_PREFIXES: tuple[str, ...] = (
    # Global Report Sidebar
    "global_",
    # Global Report Quartal/Free-Period
    "q_old",
    "q_new",
    "go_start",
    "go_end",
    "gn_start",
    "gn_end",
    # Standort-Analyse Sidebar
    "standort_",
    "po_start",
    "po_end",
    "pn_start",
    "pn_end",
    # B2B Deep-Dive Sidebar
    "b2b_",
    # Code Deep-Dive Sidebar
    "cd_",
    # Pickup / Vorlauf-Analyse Sidebar
    "pu_",
    # Promo-Codes Sidebar
    "promo_",
    # Notepad-Store
    "notepad_store::",
)

_WRITE_PROTECTED_PATTERNS: tuple[str, ...] = (
    "FormSubmitter:",
    "_btn",
    "_reset",
    "dl_",
    "uploader",
)


def _is_persist_key(k) -> bool:
    if not isinstance(k, str):
        return False
    return any(k.startswith(p) for p in _PERSIST_KEY_PREFIXES)


def _is_write_protected_key(k) -> bool:
    if not isinstance(k, str):
        return False
    return any(p in k for p in _WRITE_PROTECTED_PATTERNS)


def keep_session_state_alive() -> None:
    """Filter-State über Page-Wechsel persistieren"""
    # 1. Cleanup vergifteter Widget-Keys
    if not st.session_state.get("_kssa_cleanup_done"):
        for k in list(st.session_state.keys()):
            if _is_write_protected_key(k):
                try:
                    del st.session_state[k]
                except Exception:
                    pass
        st.session_state["_kssa_cleanup_done"] = True

    # 2. Re-touch Filter-Keys
    for k in list(st.session_state.keys()):
        if not _is_persist_key(k):
            continue
        try:
            st.session_state[k] = st.session_state[k]
        except Exception:
            # Defensive: falls ein Filter-Key doch zu einem write-protected
            # Widget gehört, überspringen statt crashen.
            continue


# ============================== Sidebar tools ============================
def purge_snapshot_caches() -> None:
    """Alle Daten-Caches leeren und den Speicher zurückgeben (nur Refresh-Seite).

    Den manuellen Sidebar-Button „Cache leeren" gibt es nicht mehr: alle Caches
    sind über Snapshot-mtime + Override-Signatur selbst-invalidierend, und der
    Button hat die GLOBALEN Caches aller Nutzer geleert (jede andere Session
    musste den Snapshot neu laden). ``cache_data.clear()`` allein reicht nicht -
    die Snapshot-Lader laufen über ``@st.cache_resource``.

    ``H.release_memory()`` am Ende gibt die freigewordenen Seiten so weit wie
    möglich ans Betriebssystem zurück; ohne den Aufruf bleibt der Prozess auch
    nach dem Leeren aufgebläht (gemessen ~530 MB über Grundlast).
    """
    st.cache_data.clear()
    st.cache_resource.clear()  # Snapshot-Lader (cache_resource) mitleeren!
    for k in list(st.session_state.keys()):
        if str(k).startswith(("_chart_", _SLICE_CACHE_KEY)):
            del st.session_state[k]
    H.release_memory()


# ============================== Freshness-Badge ===========================
# Ampel-Schwellen (Stunden seit letztem Snapshot-Refresh).
_FRESH_GREEN_H = 5.0
_FRESH_YELLOW_H = 15.0


def freshness_badge(container=None) -> None:
    """Farbiger Sidebar-Indikator: wann die Daten zuletzt aktualisiert wurden.

    Grün < 5 h · Gelb 5-15 h · Rot > 15 h (Alter = jetzt − ``refreshed_at``,
    beides Europe/Berlin). Zeigt Datum + Uhrzeit des Refreshs und das Alter.
    Auf jeder Seite in der Sidebar aufrufen.
    """
    from revenueblindspots.theming import color as _brand_color

    target = container if container is not None else st.sidebar

    meta = get_metadata()
    raw = str(meta.get("refreshed_at") or "").strip()
    ts = pd.to_datetime(raw, errors="coerce") if raw else pd.NaT

    if pd.isna(ts):
        dot, label = "#666666", "<strong>Daten-Stand:</strong> unbekannt - bitte Refresh ausführen"
    else:
        if ts.tzinfo is None:
            ts = ts.tz_localize("Europe/Berlin")
        ts = ts.tz_convert("Europe/Berlin")
        now = pd.Timestamp.now(tz="Europe/Berlin")
        age_h = max((now - ts).total_seconds() / 3600.0, 0.0)
        if age_h < _FRESH_GREEN_H:
            dot = _brand_color("green")
        elif age_h <= _FRESH_YELLOW_H:
            dot = _brand_color("yellow")
        else:
            dot = _brand_color("red")
        age_txt = f"vor {age_h:.1f} h" if age_h < 48 else f"vor {age_h / 24:.1f} Tagen"
        label = (
            f"<strong>Daten-Stand:</strong> {ts:%d.%m.%Y}, {ts:%H:%M} Uhr"
            f"<br><span style='color:#666666'>{age_txt} aktualisiert</span>"
        )

    target.markdown(
        '<div style="display:flex;align-items:flex-start;gap:8px;font-size:0.8rem;'
        "color:#000;background:#FAFAF5;border:1px solid #ECEAE0;border-radius:10px;"
        'padding:7px 10px;margin:6px 0;line-height:1.35;">'
        f'<span style="width:10px;height:10px;border-radius:50%;background:{dot};'
        'border:1px solid rgba(0,0,0,0.25);flex:0 0 auto;margin-top:2px;"></span>'
        f"<span>{label}</span></div>",
        unsafe_allow_html=True,
    )
