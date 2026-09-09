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


# ============================== Cache key helper ==========================
def _resolved_snapshot_dir():
    """Snapshot-Verzeichnis auflösen: Session-Override → env/Repo-Default.

    Der Pfad-Override aus der „Daten aktualisieren"-Seite lebt NUR noch im
    ``st.session_state`` der jeweiligen Session (Review A12.8) - vorher wurde
    ``os.environ`` mutiert, was prozessweit ALLE gleichzeitigen User traf.
    """
    override = st.session_state.get("snapshot_dir_override")
    if override:
        s = str(override).strip()
        if s:
            if s.startswith(("gs://", "s3://")):
                return s
            return Path(s).expanduser()
    return H.find_snapshot_dir()


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


# Großer, unveränderlicher Snapshot: einmal je Snapshot-Signatur via
# cache_resource in den Speicher (geteilt über alle Sessions, keine Kopie pro
# Cache-Hit). Gefiltert wird danach in-memory - kein wiederholter Disk-Read.
@st.cache_resource(ttl=3600, show_spinner=False)
def _raw_reservations(snapshot_sig: str, _snap_dir=None) -> pd.DataFrame:
    return H.load_reservations(snapshot_dir=_snap_dir)


@st.cache_resource(ttl=3600, show_spinner=False)
def _raw_timeslices(snapshot_sig: str, _snap_dir=None) -> pd.DataFrame:
    return H.load_timeslices(snapshot_dir=_snap_dir)


# Promo→Firmencode-Reklassifizierung, einmal je (Snapshot, Override-Stand).
@st.cache_resource(ttl=3600, show_spinner=False)
def _overridden_reservations(snapshot_sig: str, override_sig: str, _snap_dir=None) -> pd.DataFrame:
    return OV.apply_code_overrides(_raw_reservations(snapshot_sig, _snap_dir))


@st.cache_resource(ttl=3600, show_spinner=False)
def _overridden_timeslices(snapshot_sig: str, override_sig: str, _snap_dir=None) -> pd.DataFrame:
    return OV.apply_code_overrides(_raw_timeslices(snapshot_sig, _snap_dir))


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
    Frame zu verändern
    """
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
    df = _overridden_reservations(
        _snapshot_signature(), _override_signature(), _resolved_snapshot_dir()
    )
    return _filter_frame(
        df, "arrival", start, end, tuple(properties) if properties else None
    )


def get_timeslices(
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    properties: list[str] | None = None,
) -> pd.DataFrame:
    df = _overridden_timeslices(
        _snapshot_signature(), _override_signature(), _resolved_snapshot_dir()
    )
    return _filter_frame(
        df, "serviceDate", start, end, tuple(properties) if properties else None
    )


# ============================== Chart-PNG-Cache ===========================
_CHART_CACHE_MAX = 64
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

    import matplotlib.pyplot as plt

    result = fig_fn(*args, **kwargs)
    if isinstance(result, tuple):
        fig, *extras = result
        extras = tuple(extras) if extras else None
    else:
        fig, extras = result, None

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
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


def render_chart(
    cache_key: str,
    fig_fn,
    *args,
    register=None,
    register_kwargs=None,
    dpi: int = _DEFAULT_DPI,
    **kwargs,
):
    """Convenience: chart_png + st.image + optional register_section."""
    result = chart_png(cache_key, fig_fn, *args, dpi=dpi, **kwargs)
    if isinstance(result, tuple):
        png, extras = result
    else:
        png, extras = result, None
    st.image(png, use_container_width=False)
    if register is not None and register_kwargs is not None:
        register(chart_png=png, **register_kwargs)
    return extras


# ============================== Style + cleanup ===========================
def apply_stayery_style_once() -> None:
    """Apply matplotlib brand style once per session."""
    if not st.session_state.get("_stayery_style_applied"):
        from revenueblindspots.theming import apply_stayery_style

        apply_stayery_style()
        import matplotlib as mpl

        mpl.rcParams["savefig.dpi"] = _DEFAULT_DPI
        mpl.rcParams["figure.dpi"] = _DEFAULT_DPI
        mpl.rcParams["figure.max_open_warning"] = 50
        st.session_state["_stayery_style_applied"] = True


def collect() -> None:
    """plt.close('all') + gc - call at end of each page."""
    import gc

    import matplotlib.pyplot as plt

    plt.close("all")
    gc.collect()


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
        csv_bytes = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Als CSV herunterladen",
            data=csv_bytes,
            file_name=(filename or "datentabelle") + ".csv",
            mime="text/csv",
            key=f"dl_csv_{title}_{filename or 'x'}_{len(df)}",
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
def cache_clear_button() -> None:
    if st.sidebar.button(
        "Cache leeren",
        use_container_width=True,
        help="Snapshot + Chart-Cache wieder von Disk laden.",
    ):
        st.cache_data.clear()
        st.cache_resource.clear()  # Snapshot-Lader (cache_resource) mitleeren!
        for k in list(st.session_state.keys()):
            if str(k).startswith("_stayery_style_applied") or str(k).startswith("_chart_"):
                del st.session_state[k]
        st.rerun()


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
