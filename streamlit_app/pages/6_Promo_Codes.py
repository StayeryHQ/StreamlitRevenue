"""Promo-Codes - Promo-Universe + Reklassifizierung zu Firmencodes.

Drei Bausteine:
  1. Promo-Tabelle (alle promoCodes über die Historie, inkl. Firmencode-Verdacht).
  2. Split-View-Drilldown: Code links anklicken -> kompakter Deep-Dive rechts.
  3. Reklassifizierung: Promocodes, die eigentlich Firmencodes sind, als solche
     markieren -> wirkt global (B2B/Code Deep-Dive) über die Override-Schicht.
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
from components import (
    download_button,
    inject_brand_css,
    render_notepad,
    sync_snapshot_override,
)
from components import drilldown as DD
from components import promo_tables as P
from components.alerts import alert_card
from components.brand import hero
from components.export import register_section, reset_export
from revenueblindspots import helpers as H
from revenueblindspots import overrides as OV

st.set_page_config(
    page_title="Promo-Codes · Stayery",
    page_icon="🎟️",
    layout="wide",
)
inject_brand_css()
CD.apply_stayery_style_once()
sync_snapshot_override()
CD.keep_session_state_alive()  # MUST run before any widget renders this page

PAGE = "promo"
st.session_state["__page"] = PAGE

hero(
    eyebrow="Promo · Marketing-Codes & Reklassifizierung",
    title="Promo-Codes über die Historie",
    subtitle="Alle promoCodes als lange Tabelle, Split-View-Drilldown je Code und "
    "ein Werkzeug, um als Firmencode getarnte Promocodes sauber umzuziehen - "
    "die Reklassifizierung wirkt global in B2B- & Code-Deep-Dive.",
)


# ============================== Sidebar filter =============================
with st.sidebar:
    st.header("Filter")

    meta = CD.get_metadata()
    if not meta:
        st.error("Kein Snapshot - bitte erst `Daten aktualisieren` ausführen.")
        st.stop()

    all_props = meta.get("properties") or H.all_properties()

    with st.form("promo_filter", clear_on_submit=False, border=False):
        props_pick = st.multiselect(
            "Standorte",
            options=all_props,
            default=all_props,
            key="promo_props_pick",
        )
        default_start = (pd.Timestamp.today().normalize() - pd.DateOffset(years=3)).date()
        lookback_start = st.date_input(
            "Historie ab",
            value=default_start,
            help="Ab welchem Anreise-Datum gelistet wird.",
            key="promo_start",
        )
        active_since = st.date_input(
            '„Aktiv"-Schwelle',
            value=pd.Timestamp.today().normalize().replace(day=1).date(),
            help="Promocodes mit Buchung ≥ diesem Datum gelten als 'aktiv'.",
            key="promo_active",
        )
        st.form_submit_button("Tabelle aktualisieren", use_container_width=True)

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


# ============================== Data load ==================================
# promoCode lebt primär in den Reservations. Sobald der Refresh promoCode auch in
# die Timeslices broadcastet, läuft die Promo-Sicht auf der Stay-Netto-Basis;
# davor wird die services-inklusive Reservations-Basis verwendet.
with st.spinner("Lade Daten aus dem Parquet-Snapshot …"):
    nightly = CD.get_timeslices(start=start_ts, end=end_ts, properties=props_pick)
    if H.timeslices_are_enriched(nightly) and "promoCode" in nightly.columns:
        res = H.reservations_from_timeslices(nightly)
        revenue_basis = "Stay-Netto (Timeslices)"
    else:
        res = CD.get_reservations(start=start_ts, end=end_ts, properties=props_pick)
        revenue_basis = "services-inklusive Reservations"

if res.empty:
    st.warning("Keine Reservierungen im gewählten Zeitraum.")
    st.stop()

st.caption(
    f"**Datenbasis:** Revenue läuft auf **{revenue_basis}**. 1 Zeile = 1 Buchung; "
    "Counts = Buchungen. Storno + No-Show inklusive; Revenue verloren = "
    "einbehaltene Netto-Fee, gedeckelt aufs Buchungs-Netto."
)
if "promoCode" not in res.columns:
    st.error(
        "Im aktuellen Snapshot fehlt die Spalte `promoCode` - bitte einmal "
        "`Daten aktualisieren` ausführen."
    )
    st.stop()

reset_export(PAGE)


# Aktueller Override-Stand (für Status-Spalte + Verdacht).
_override_map = OV.promo_overrides()
_reclassified = set(_override_map.keys())

if "corporateCode" in res.columns:
    _cc = res["corporateCode"].dropna().astype(str).str.strip().str.upper()
    _corp_set = set(_cc[_cc != ""].unique())
else:
    _corp_set = set()


@st.cache_data(ttl=3600, show_spinner=False, max_entries=4)
def _build_promo_table(_sig: str, _active_ts: pd.Timestamp, _ovsig: str):
    try:
        return P.aggregate_promo_codes(
            res, _active_ts, corporate_code_set=_corp_set, reclassified_codes=_reclassified
        )
    except Exception as e:  # pragma: no cover - defensiv
        st.warning(f"Promo-Aggregation schlug fehl: {e} - leere Tabelle.")
        return pd.DataFrame()


with st.spinner("Aggregiere Promo-Codes …"):
    promo_table = _build_promo_table(
        f"{meta.get('refreshed_at', '?')}|{len(res)}", active_ts, OV.override_signature()
    )

if promo_table.empty:
    alert_card("Keine `promoCode`-Werte im Lookback gefunden.", kind="info")
    st.stop()


# ============================== Summary ====================================
n_codes = len(promo_table)
n_suspect = int((promo_table["Firmencode-Verdacht"] == "⚑ ja").sum())
n_reclass = int((promo_table["Status"].str.startswith("✓")).sum())
rev_tot = float(promo_table["Revenue gesamt (€)"].sum())
st.markdown(
    f"**{n_codes:,} Promocodes** im Lookback · **{n_suspect:,}** mit Firmencode-Verdacht · "
    f"**{n_reclass:,}** bereits reklassifiziert · Total-Revenue **{H.fmt_eur(rev_tot)}**.".replace(
        ",", "."
    )
)


# ============================== Split-View =================================
st.divider()
st.subheader("Promo-Tabelle + Drilldown")
st.caption(
    "Zeile **anklicken** → die Tabelle rückt nach links und rechts erscheint der "
    "kompakte Deep-Dive für diesen Code (kein Seitenwechsel). Ohne Auswahl bleibt "
    "die Tabelle in voller Breite. Spalte **Firmencode-Verdacht** markiert Codes, "
    "die wahrscheinlich Firmencodes sind."
)

display_df = P.format_display(promo_table)
register_section("promo_all", "Promo-Codes (alle)", table_df=display_df.head(50), page=PAGE)

# Layout-Entscheidung über einen eigenen Flag (KEIN Widget-State): Tabelle bleibt
# full-size, bis tatsächlich eine Zeile gewählt ist - erst dann der Split.
_has_sel = bool(st.session_state.get("_promo_has_sel", False))
if _has_sel:
    _table_col, _detail_col = st.columns([3, 2], gap="large")
else:
    _table_col, _detail_col = st.container(), None

with _table_col:
    event = st.dataframe(
        display_df,
        hide_index=True,
        use_container_width=True,
        height=560,
        key="_promo_table_select",
        on_select="rerun",
        selection_mode="single-row",
    )

_rows = DD.get_selection_rows(event)
selected_code: str | None = (
    str(display_df.iloc[_rows[0]]["Promocode"])
    if _rows and 0 <= _rows[0] < len(display_df)
    else None
)

# Flag mit der echten Auswahl synchronisieren -> ein Rerun schaltet das Layout um.
_new_has_sel = selected_code is not None
if _new_has_sel != _has_sel:
    st.session_state["_promo_has_sel"] = _new_has_sel
    st.rerun()

if selected_code and _detail_col is not None:
    _is_reclass = selected_code.upper() in _reclassified
    _status = "✓ als Firmencode reklassifiziert" if _is_reclass else "Promo (nicht reklassifiziert)"
    _sub = res[res["promoCode"].astype(str).str.strip().str.upper() == selected_code.upper()]
    DD.compact_deepdive(
        _detail_col,
        _sub,
        f"`{selected_code}`",
        period_start=active_ts,
        period_end=end_ts,
        cache_salt=f"promo::{CD.snapshot_tag()}",
        caption=f"Status: **{_status}**",
        open_code=selected_code,
        page=PAGE,
        section_id=f"promo_code_{selected_code}",
    )


# ============================== Reklassifizierung ==========================
st.divider()
st.subheader("Promocodes als Firmencodes reklassifizieren")
st.caption(
    "Trägt man hier Codes ein, werden ihre Buchungen **global** als Firmencode-"
    "Buchungen behandelt (corporateCode = Promocode). Wirkt sofort auf Reservations-"
    "Basis; die Stay-Netto-Sichten von B2B/Code Deep-Dive ziehen nach dem nächsten "
    "`Daten aktualisieren` nach."
)

# --- Bestehende Reklassifizierungen ---------------------------------------
if _override_map:
    ov_rows = [
        {
            "Promocode": c,
            "Firmenname": (p.get("firm") or "-"),
            "seit": p.get("added", "-"),
        }
        for c, p in sorted(_override_map.items())
    ]
    st.markdown(f"**Aktuell reklassifiziert ({len(ov_rows)}):**")
    st.dataframe(pd.DataFrame(ov_rows), hide_index=True, use_container_width=True)
    to_remove = st.multiselect(
        "Reklassifizierung entfernen",
        options=sorted(_override_map.keys()),
        key="_promo_remove_pick",
    )
    if st.button("Ausgewählte entfernen", key="_promo_remove_btn") and to_remove:
        for c in to_remove:
            OV.remove_promo_override(c)
        st.success(f"{len(to_remove)} Reklassifizierung(en) entfernt.")
        st.rerun()
else:
    st.caption("Noch keine Reklassifizierungen gespeichert.")

# --- Neue hinzufügen -------------------------------------------------------
st.markdown("**Neue Codes als Firmencode markieren**")
suspect_codes = (
    promo_table.loc[promo_table["Firmencode-Verdacht"] == "⚑ ja", "Promocode"].astype(str).tolist()
)
quick_pick = st.multiselect(
    "Schnellauswahl (Codes mit Firmencode-Verdacht)",
    options=[c for c in suspect_codes if c.upper() not in _reclassified],
    key="_promo_quick_pick",
    help="Vorgefiltert auf Codes, die wahrscheinlich Firmencodes sind.",
)
paste = st.text_area(
    "Oder Liste einfügen - eine Zeile pro Code, optional `CODE = Firmenname`",
    placeholder="BCDB = BCD Travel\nBAU10\nIANUS10 = Ianus GmbH",
    key="_promo_paste",
    height=120,
)


def _parse_paste(text: str) -> dict[str, str | None]:
    """Parst die eingefügte Liste zu ``{CODE: firm_or_None}``."""
    result: dict[str, str | None] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        firm: str | None = None
        for sep in ("=", ":", "\t", ","):
            if sep in line:
                code_part, firm_part = line.split(sep, 1)
                line = code_part.strip()
                firm = firm_part.strip() or None
                break
        if line:
            result[line.upper()] = firm
    return result


if st.button("Als Firmencodes speichern", key="_promo_save_btn", type="primary"):
    to_add: dict[str, str | None] = {c.upper(): None for c in quick_pick}
    to_add.update(_parse_paste(paste))
    if not to_add:
        st.warning("Keine Codes angegeben.")
    else:
        OV.add_promo_overrides(to_add)
        st.success(
            f"{len(to_add)} Code(s) als Firmencode reklassifiziert: "
            f"{', '.join(sorted(to_add))}. Wirkt jetzt global."
        )
        st.rerun()


# ============================== Export =====================================
st.divider()
st.subheader("Bericht exportieren")

# Aktualisiertes Firmencode-Sheet = Corporate-Code-Tabelle NACH Override (enthält
# die reklassifizierten Promocodes). Läuft auf demselben res wie oben.
try:
    cp_after = B.aggregate_corporate_codes(res, active_ts)
    firmencode_sheet = B.format_display(cp_after, "corporate")
except Exception:  # pragma: no cover - defensiv
    firmencode_sheet = pd.DataFrame()

_sheets: dict[str, pd.DataFrame] = {"promo_codes": display_df}
if not firmencode_sheet.empty:
    _sheets["firmencodes_aktualisiert"] = firmencode_sheet
if _override_map:
    _sheets["reklassifizierung"] = pd.DataFrame(
        [
            {"Promocode": c, "Firmenname": (p.get("firm") or ""), "seit": p.get("added", "")}
            for c, p in sorted(_override_map.items())
        ]
    )

buf = io.BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as w:
    for _name, _df in _sheets.items():
        _df.to_excel(w, sheet_name=_name[:31], index=False)
st.download_button(
    f"Alle Tabellen als Excel ({len(_sheets)} Sheets)",
    data=buf.getvalue(),
    file_name=f"promo_codes_{start_ts:%Y%m%d}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    key="dl_promo_all",
)
st.caption(
    "Das Sheet **firmencodes_aktualisiert** ist die Corporate-Code-Tabelle inklusive "
    "der hier reklassifizierten Promocodes."
)

download_button(
    page_title=f"Promo-Codes · ab {start_ts:%d.%m.%Y}",
    filename=f"promo_recap_{start_ts:%Y%m%d}.md",
    page=PAGE,
)

CD.collect()
