"""B2B Deep-Dive - alle Codes & Firmen über die Historie.

Zwei Ansichten: apaleo `corporateCode` und fuzzy-geclusterte Firmen.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT / "streamlit_app"))

import pandas as pd
import streamlit as st

from components import b2b_tables as B
from components import cached_data as CD
from components import drilldown as DD
from components import (
    download_button,
    inject_brand_css,
    render_notepad,
    sync_snapshot_override,
)
from components.alerts import alert_card
from components.brand import hero
from components.export import register_section, reset_export
from revenueblindspots import helpers as H

st.set_page_config(
    page_title="B2B Deep-Dive · Stayery",
    page_icon="🏢",
    layout="wide",
)
inject_brand_css()
CD.apply_stayery_style_once()
sync_snapshot_override()
CD.keep_session_state_alive()  # MUST run before any widget renders this page

PAGE = "b2b"
st.session_state["__page"] = PAGE

hero(
    eyebrow="B2B · Outreach-Universe",
    title="Alle Codes & Firmen über die Historie",
    subtitle="Zwei lange Tabellen für Sales: apaleo `corporateCode` und "
    "fuzzy-geclusterte Firmen - inkl. Storno + No-Show. "
    "Multi-Sheet Excel-Export am Seitenende.",
)


# ============================== Sidebar filter =============================
with st.sidebar:
    st.header("Filter")

    meta = CD.get_metadata()
    if not meta:
        st.error("Kein Snapshot - bitte erst `Daten aktualisieren` ausführen.")
        st.stop()

    all_props = meta.get("properties") or H.all_properties()
    # Standorte die zu Beginn des Lookbacks noch nicht offen waren werden
    # weiter unten via alert_card markiert

    with st.form("b2b_filter", clear_on_submit=False, border=False):
        props_pick = st.multiselect(
            "Standorte",
            options=all_props,
            default=all_props,
            key="b2b_props_pick",
        )
        default_start = (pd.Timestamp.today().normalize() - pd.DateOffset(years=3)).date()
        lookback_start = st.date_input(
            "Historie ab",
            value=default_start,
            help="Ab welchem Anreise-Datum gelistet wird.",
            key="b2b_start",
        )
        active_since = st.date_input(
            '„Aktiv"-Schwelle',
            value=pd.Timestamp.today().normalize().replace(day=1).date(),
            help="Codes/Firmen mit Buchung ≥ diesem Datum gelten als 'aktiv'.",
            key="b2b_active",
        )
        st.form_submit_button("Tabellen aktualisieren", use_container_width=True)

    if not props_pick:
        st.warning("Bitte mindestens einen Standort wählen.")
        st.stop()

    st.divider()
    CD.cache_clear_button()
    st.caption(f"Snapshot vom **{str(meta.get('refreshed_at', '?'))[:10]}**")

render_notepad(PAGE)


start_ts = pd.Timestamp(lookback_start)
active_ts = pd.Timestamp(active_since)
end_ts = pd.Timestamp.today().normalize() + pd.Timedelta(days=180)


st.markdown(f"""
**Analyse-Setup:**
- Historie: **{start_ts:%d.%m.%Y} – {end_ts:%d.%m.%Y}**
- „Aktiv"-Schwelle: Buchung mit Anreise **≥ {active_ts:%d.%m.%Y}**
- Standorte: **{len(props_pick)}** ({", ".join(props_pick)})
""")

st.caption(
    "**Datenbasis & Filter:** Nacht-Netto je Firma/Code (1 Zeile = 1 Buchung, "
    "Counts = Buchungen). Lade-Fenster + Revenue über **Aufenthalt** (serviceDate); "
    "Erste/Letzte Buchung und die Aktiv-seit-Schwelle nach **Anreise** (arrival). "
    "Roster über die ganze Historie inkl. Storno + No-Show; Revenue verloren = "
    "einbehaltene Netto-Fee, gedeckelt aufs Nacht-Netto."
)


# ============================== Data load ==================================
# Revenue-Konsistenz: Firmen-/Code-Revenue läuft auf der Nacht-Netto-Basis -
# nightly auf Buchungs-Ebene zurückfalten (revenue = Summe der Nacht-Netto je
# Buchung, inkl. kept/lost). Solange der Snapshot die gebroadcasteten Felder
# noch nicht trägt (vor dem Foundation-Voll-Refresh) Fallback auf die
# services-inklusive Reservations + Hinweis-Banner.
with st.spinner("Lade Daten aus dem Parquet-Snapshot …"):
    nightly = CD.get_timeslices(start=start_ts, end=end_ts, properties=props_pick)
    _enriched = H.timeslices_are_enriched(nightly)
    if _enriched:
        res = H.reservations_from_timeslices(nightly)
    else:
        res = CD.get_reservations(start=start_ts, end=end_ts, properties=props_pick)
if res.empty:
    st.warning("Keine Reservierungen im gewählten Zeitraum.")
    st.stop()

if not _enriched:
    alert_card(
        "Firmen-/Code-Revenue läuft noch auf der services-inklusiven "
        "Reservations-Basis. Für die konsistente Nacht-Netto-Sicht einmal "
        "Voll-Refresh ziehen (Daten aktualisieren).",
        kind="info",
    )

reset_export(PAGE)


# Warnung: Standorte ohne historische Daten in der Lookback-Periode.
_late_b2b = H.properties_without_old_data(props_pick, start_ts)
if _late_b2b:
    _lines = ", ".join(f"{pc} (eröffnet {H.opening_date(pc):%d.%m.%Y})" for pc in _late_b2b)
    alert_card(
        f"Folgende Standorte waren zu Beginn der Lookback-Periode noch nicht "
        f"offen: {_lines}. Die Tabellen unten enthalten dort nur Daten "
        f"ab Eröffnungsdatum.",
        kind="info",
    )


# Cache je (snapshot + properties + period + active_ts).
@st.cache_data(ttl=3600, show_spinner=False, max_entries=4)
def _build_tables(
    _sig: str, _active_ts: pd.Timestamp, _props: tuple, _start: pd.Timestamp, _end: pd.Timestamp
):
    def _safe(fn, *args):
        try:
            return fn(*args)
        except Exception as e:
            st.warning(
                f"Aggregator `{fn.__name__}` schlug fehl: {e} - leere Tabelle wird angezeigt."
            )
            return pd.DataFrame()

    return (
        _safe(B.aggregate_corporate_codes, res, _active_ts),
        _safe(B.aggregate_firms, res, _active_ts),
    )


with st.spinner("Aggregiere Codes & Firmen …"):
    cp_table, fm_table = _build_tables(
        f"{meta.get('refreshed_at', '?')}|{len(res)}",
        active_ts,
        tuple(props_pick),
        start_ts,
        end_ts,
    )


def _summary_caption(t: pd.DataFrame, label: str) -> None:
    if t.empty:
        return
    n_active = int((t["Aktiv seit Schwelle?"] == "✓ ja").sum())
    rev_tot = float(t["Revenue gesamt (€)"].sum())
    rev_real = float(t["Revenue realisiert (€)"].sum())
    st.markdown(
        f"**{len(t):,} {label}** im Lookback · davon **{n_active:,} aktiv** "
        f"seit {active_ts:%d.%m.%Y} · Total-Revenue: **{H.fmt_eur(rev_tot)}** "
        f"(realisiert: {H.fmt_eur(rev_real)})."
    )


# ============================== Drilldown-Helper ===========================
def _resolve_corp(code: str):
    """Buchungen für einen corporateCode + open_code für den Deep-Dive-Button."""
    sub = res[res["corporateCode"].astype(str).str.strip().str.upper() == code.upper()]
    return sub, f"`{code}`", code


def _resolve_firm(firm: str):
    """Buchungen für eine Fuzzy-Firma + dominanter corporateCode (open_code)."""
    sub = res[res["firm_by_effective_fuzzy"].astype(str).str.strip() == firm.strip()]
    open_code = None
    if "corporateCode" in sub.columns:
        cc = sub["corporateCode"].dropna().astype(str).str.strip()
        cc = cc[cc != ""]
        if not cc.empty:
            open_code = str(cc.value_counts().index[0])
    return sub, firm, open_code


def _table_with_drilldown(
    display_df, *, code_col, table_key, flag_key, section_id, section_title, resolver
):
    """Tabelle full-size, bis eine Zeile gewählt ist; dann Split mit Deep-Dive rechts."""
    st.caption(
        "Zeile **anklicken** → die Tabelle rückt nach links und rechts erscheint der "
        "kompakte Deep-Dive (kein Seitenwechsel). Ohne Auswahl bleibt sie full-size."
    )
    has_sel = bool(st.session_state.get(flag_key, False))
    if has_sel:
        tcol, dcol = st.columns([3, 2], gap="large")
    else:
        tcol, dcol = st.container(), None
    with tcol:
        ev = st.dataframe(
            display_df,
            hide_index=True,
            use_container_width=True,
            height=520,
            key=table_key,
            on_select="rerun",
            selection_mode="single-row",
        )
    register_section(section_id, section_title, table_df=display_df.head(30), page=PAGE)

    rows = DD.get_selection_rows(ev)
    sel = (
        str(display_df.iloc[rows[0]][code_col])
        if rows and 0 <= rows[0] < len(display_df)
        else None
    )
    new_has = sel is not None
    if new_has != has_sel:
        st.session_state[flag_key] = new_has
        st.rerun()
    if sel and dcol is not None:
        sub, label, open_code = resolver(sel)
        DD.compact_deepdive(
            dcol,
            sub,
            label,
            period_start=active_ts,
            period_end=end_ts,
            cache_salt=f"b2b::{CD.snapshot_tag()}",
            open_code=open_code,
            page=PAGE,
            section_id=f"{section_id}_dd",
        )


# ============================== Tabs =======================================
# key= verankert die Tab-Auswahl über Reruns (Streamlit ≥ 1.55 stateful tabs),
# damit der Klick-Drilldown nicht zurück auf Tab 1 springt.
tab1, tab2 = st.tabs(
    [
        f"1 · Corporate-Codes ({len(cp_table):,})",
        f"2 · Firmen fuzzy ({len(fm_table):,})",
    ],
    key="_b2b_dd_tabs",
)


with tab1:
    st.markdown(f"## 1 · Alle `corporateCode` seit {start_ts:%Y}")
    st.caption(
        "Bei Stayery wird i.d.R. `corporateCode` gepflegt (Corporate-Rate / OTA-Code), "
        "nicht der harte apaleo-`company_code`. Diese Tabelle ist daher die "
        "primäre Code-Sicht."
    )
    if cp_table.empty:
        alert_card("Keine `corporateCode`-Werte im Lookback gefunden.", kind="info")
    else:
        _summary_caption(cp_table, "Corporate-Codes")
        cp_display = B.format_display(cp_table, "corporate")
        _table_with_drilldown(
            cp_display,
            code_col="Corporate-Code",
            table_key="_b2b_cp_select",
            flag_key="_b2b_cp_has_sel",
            section_id="cp",
            section_title="1 · Corporate-Codes",
            resolver=_resolve_corp,
        )


with tab2:
    st.markdown(f"## 2 · Alle Firmen (Fuzzy-Cluster) seit {start_ts:%Y}")
    st.caption(
        "Fuzzy-Cluster - `company_name` + `booker_name` + `guest_name`-Varianten "
        "werden zu einer kanonischen Firma zusammengezogen."
    )
    if fm_table.empty:
        alert_card("Keine Firmennamen im Lookback gefunden.", kind="info")
    else:
        _summary_caption(fm_table, "Firmen")
        fm_display = B.format_display(fm_table, "firm")
        _table_with_drilldown(
            fm_display,
            code_col="Firma",
            table_key="_b2b_fm_select",
            flag_key="_b2b_fm_has_sel",
            section_id="fm",
            section_title="2 · Firmen fuzzy",
            resolver=_resolve_firm,
        )


# ===== Sammel-Export =======================================================
st.divider()
st.subheader("Bericht exportieren")

# Multi-Sheet Excel nur wenn mindestens eine der beiden Tabellen Inhalt hat.
_sheets: dict[str, pd.DataFrame] = {}
if not cp_table.empty:
    _sheets["corporate_codes"] = B.format_display(cp_table, "corporate")
if not fm_table.empty:
    _sheets["firmen_fuzzy"] = B.format_display(fm_table, "firm")

if _sheets:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for _name, _df in _sheets.items():
            _df.to_excel(w, sheet_name=_name, index=False)
    st.download_button(
        f"Alle Tabellen als Excel ({len(_sheets)} Sheet{'s' if len(_sheets) > 1 else ''})",
        data=buf.getvalue(),
        file_name=f"b2b_deepdive_{start_ts:%Y%m%d}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="dl_b2b_all",
    )
else:
    st.caption("Excel-Export ist deaktiviert - beide Tabellen sind leer.")

download_button(
    page_title=f"B2B Deep-Dive · ab {start_ts:%d.%m.%Y}",
    filename=f"b2b_recap_{start_ts:%Y%m%d}.md",
    page=PAGE,
)

CD.collect()
