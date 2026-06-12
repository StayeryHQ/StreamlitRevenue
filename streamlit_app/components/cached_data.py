"""Cache-Layer für die Streamlit-App.

Drei Tasks:

  1. Parquet-Snapshot-Loader (Reservations + Timeslices)
  2. Chart-PNG-Cache: matplotlib-Figures werden gerendert und als PNG bytes
     in `st.session_state` gehalten.
  3. matplotlib-Style + Memory-Cleanup-Utilities.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from revenueblindspots import helpers as H


# ============================== Cache key helper ==========================
def _snapshot_signature() -> str:
    """Stable string for the current snapshot - invalidates cache when it
    changes (env-var override or new snapshot written).
    """
    override = os.environ.get("STAYERY_SNAPSHOT_DIR", "")
    snap_dir = H.find_snapshot_dir()
    if snap_dir is None:
        return f"override={override}|none"
    if isinstance(snap_dir, Path):
        try:
            res_path = snap_dir / H.SNAPSHOT_FILES["reservations"]
            mtime = int(res_path.stat().st_mtime) if res_path.exists() else 0
            return f"local={snap_dir}|mtime={mtime}"
        except OSError:
            return f"local={snap_dir}|nostat"
    return f"remote={snap_dir}"


# ============================== Cached loaders ============================
@st.cache_data(ttl=3600, show_spinner=False, max_entries=4)
def load_snapshot_metadata_cached(_snapshot_sig: str) -> dict:
    return H.load_snapshot_metadata() or {}


@st.cache_data(ttl=3600, show_spinner=False, max_entries=4)
def load_reservations_cached(
    _snapshot_sig: str,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    properties: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    return H.load_reservations(
        start=start,
        end=end,
        properties=list(properties) if properties else None,
    )


@st.cache_data(ttl=3600, show_spinner=False, max_entries=4)
def load_timeslices_cached(
    _snapshot_sig: str,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    properties: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    return H.load_timeslices(
        start=start,
        end=end,
        properties=list(properties) if properties else None,
    )


# ============================== Convenience wrappers =====================
def get_metadata() -> dict:
    return load_snapshot_metadata_cached(_snapshot_signature())


def get_plan_override() -> dict:
    """Persisted user-Override (or empty).
    Fallback auf ``plan_override.json`` neben dem
    Snapshot.
    """
    if "plan_override" in st.session_state:
        return st.session_state["plan_override"] or {}
    plan = H.load_plan_override()
    st.session_state["plan_override"] = plan
    return plan


def get_default_plan() -> dict:
    """Repo-Default-Plan aus ``data/plan_default.xlsx``, einmal pro Session geladen."""
    if "plan_default" not in st.session_state:
        st.session_state["plan_default"] = H.load_default_plan()
    return st.session_state["plan_default"] or {}


def get_active_plan() -> dict:
    """Effektiver Plan für IST/PLAN-Vergleiche.

    Logik: User-Override (Upload), sonst fällt zurück auf den
    Repo-Default . Liefert leeres Dict wenn beides fehlt
    """
    return H.active_plan(get_plan_override(), default=get_default_plan())


def get_reservations(
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    properties: list[str] | None = None,
) -> pd.DataFrame:
    return load_reservations_cached(
        _snapshot_signature(),
        start=start,
        end=end,
        properties=tuple(properties) if properties else None,
    )


def get_timeslices(
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    properties: list[str] | None = None,
) -> pd.DataFrame:
    return load_timeslices_cached(
        _snapshot_signature(),
        start=start,
        end=end,
        properties=tuple(properties) if properties else None,
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
    # Notepad (pro Page) - ohne Re-Touch verwirft Streamlit den State des
    # nicht-gerenderten Notepad-Widgets beim Page-Wechsel, die Notiz ginge
    # verloren. Gleicher Schutz wie für die Filter-Widgets.
    "notepad::",
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
        for k in list(st.session_state.keys()):
            if str(k).startswith("_stayery_style_applied") or str(k).startswith("_chart_"):
                del st.session_state[k]
        st.rerun()
