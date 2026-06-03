"""Plan-Upload: Wide-Format Excel mit Monats-Planzahlen.

Plan-Stack:
  1. **Upload-Override**: wird über diese Seite hochgeladen und in
     ``data/plan_override.json`` neben dem Snapshot persistiert.
  2. **Repo-Default** - ``data/plan_default.xlsx`` aus dem Git-Repo
  3. **Leer** - wenn weder Default noch Upload vorhanden ist, sind alle
     PLAN-Spalten 0 €

Excel-Format (siehe Expander unten): erste Spalte = Hotel-Label
(``PLAN:<Stadt>``, ``PLAN:<Stadt Neighborhood>`` oder ``PLAN:<HOTEL_CODE>``),
weitere Spalten = Monate (``MM-YY``, ``YYYY-MM`` etc.). Spalten-reihenfolge
ist egal. Der Parser detektiert die Hotel-Label-Spalte automatisch und
parst Monats-Spalten über ihren Header-Text.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT / "streamlit_app"))

import io

import pandas as pd
import streamlit as st

from components import cached_data as CD
from components.brand import hero, inject_brand_css
from revenueblindspots import helpers as H
from revenueblindspots import plan_parser as PP

st.set_page_config(page_title="Plan-Upload · Stayery", page_icon="📥", layout="wide")
inject_brand_css()
CD.keep_session_state_alive()

hero(
    eyebrow="PLAN · Wide-Format Upload",
    title="Monats-Planzahlen pflegen",
    subtitle="Excel-Upload überschreibt den Repo-Default "
    "(`data/plan_default.xlsx`). Override persistiert im Snapshot - "
    "überlebt App-Restart",
)


# ============================== Format spec ===============================
with st.expander("Erwartetes Excel-Format", expanded=False):
    st.markdown(
        """
**Wide-Format** (1 Zeile pro Hotel, 1 Spalte pro Monat):

| Hotel               | `01-25`  | `02-25` | … | `12-26` |
|---------------------|----------|---------|---|---------|
| `PLAN:Berlin`       | 120000   | 135000  | … | 110000  |
| `PLAN:Köln Sülz`    | 80000    | 88000   | … | 75000   |
| `PLAN:FRA_SH`       | 220000   | 245000  | … | 200000  |

**Hotel-Spalte tolerant** : Stadt (`PLAN:Berlin`), Stadt+Neighborhood
(`PLAN:Köln Sülz`), Hotel-Code (`PLAN:CGN_WS`); `PLAN:`-Prefix optional.

**Monats-Header** - `MM-YY`, `YYYY-MM`, `01.2025`, `Jan 2025` werden alle
akzeptiert. Andere Spalten (z.B. „Total") werden ignoriert.

**Reihenfolge spielt keine Rolle.** Die Hotel-Spalte wird automatisch
detektiert (erste Spalte mit nicht-Monats-Header). Neue Jahre kannst du an
beliebiger Stelle einfügen da sich der Parser am Header-Text orientiert.
        """
    )


# ============================== Aktuelle Plan-Quelle ======================
st.subheader("Aktive Plan-Quelle")

# Override aus Session-State (falls noch nicht gesetzt: aus Disk lazy-load)
override_dict = CD.get_plan_override()
default_dict = CD.get_default_plan()
default_path = PP.load_default_plan_path()

if override_dict:
    _src = "**Upload-Override** (persistiert neben Snapshot)"
    _src_kind = "override"
elif default_dict:
    _src = f"**Repo-Default** (`{default_path.relative_to(_REPO_ROOT) if default_path else 'data/plan_default.xlsx'}`)"
    _src_kind = "default"
else:
    _src = "**Kein Plan**"
    _src_kind = "none"

active = CD.get_active_plan()
n_hotels_active = len(active)
n_months_active = len({m for hot in active.values() for m in hot}) if active else 0
total_active = sum(v for hot in active.values() for v in hot.values()) if active else 0.0

c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "Quelle",
    "Override" if _src_kind == "override" else "Default" if _src_kind == "default" else "-",
)
c2.metric("Hotels", n_hotels_active)
c3.metric("Monate", n_months_active)
c4.metric("Total-PLAN (€)", H.fmt_eur(total_active))
st.markdown(f"Aktuell aktiv: {_src}")

# Aktiven Plan als Pivot anzeigen
if active:
    rows_out = [
        {"Hotel-Code": code, "Monat": str(month), "PLAN (€)": v}
        for code, months in active.items()
        for month, v in months.items()
    ]
    df_out = pd.DataFrame(rows_out).sort_values(["Hotel-Code", "Monat"])
    pivot = df_out.pivot_table(
        index="Hotel-Code", columns="Monat", values="PLAN (€)", aggfunc="sum"
    ).fillna(0)
    pivot["Total (€)"] = pivot.sum(axis=1)
    display = pivot.copy()
    for c in display.columns:
        display[c] = display[c].map(H.fmt_eur)
    with st.expander(
        f"Aktiven Plan ansehen ({n_hotels_active} Hotels × {n_months_active} Monate)",
        expanded=False,
    ):
        st.dataframe(display, use_container_width=True)

# Override-Aktionen
if _src_kind == "override":
    st.caption(
        "Upload-Override ist aktiv. Klick auf 'Override löschen', um auf "
        "den Repo-Default zurückzufallen."
    )
    if st.button(
        "Override löschen → Default reaktivieren", type="secondary", key="plan_delete_override"
    ):
        H.delete_plan_override()
        st.session_state.pop("plan_override", None)
        st.rerun()
elif _src_kind == "default":
    st.caption(
        "Der Repo-Default ist aktiv. Lade unten eine Excel hoch, um ihn "
        "zu überschreiben (zentral persistiert, alle User sehen den Override)."
    )
elif _src_kind == "none":
    st.warning(
        "Weder Override noch Default vorhanden. Standort-Analyse und Global "
        "Report zeigen PLAN = 0 €. Lade entweder unten eine Excel hoch oder "
        "committe `data/plan_default.xlsx` ins Repo (Format siehe oben)."
    )


st.divider()


# ============================== Upload-Sektion ============================
st.subheader("1 · Neue Excel hochladen (Override)")
uploaded = st.file_uploader(
    "Plan-Datei auswählen (.xlsx)",
    type=["xlsx", "xls"],
    accept_multiple_files=False,
    key="plan_uploader",
    help="Überschreibt den aktiven Plan. Der Upload wird persistiert",
)

sheet_choice = None
if uploaded is not None:
    try:
        sheets = pd.ExcelFile(io.BytesIO(uploaded.getvalue())).sheet_names
        if len(sheets) > 1:
            sheet_choice = st.selectbox("Sheet", sheets, index=0, key="plan_sheet_choice")
    except Exception as e:
        st.error(f"Datei nicht lesbar: {e}")
        uploaded = None

if uploaded is not None:
    try:
        result = PP.parse_wide_plan(uploaded.getvalue(), sheet_choice)
    except Exception as e:
        st.error(f"Validierungsfehler: {e}")
        st.stop()

    plan_dict = result["plan"]
    rows = result["rows"]

    n_hotels = len(plan_dict)
    n_months = len({m for hot in plan_dict.values() for m in hot})
    total_eur = float(rows["plan_eur"].sum()) if not rows.empty else 0.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Hotels", f"{n_hotels}")
    c2.metric("Monate", f"{n_months}")
    c3.metric("Total-PLAN (€)", H.fmt_eur(total_eur))
    c4.metric("Werte gesamt", f"{len(rows)}")

    st.caption(f"Hotel-Label-Spalte erkannt: **`{result.get('label_col', '?')}`**")

    for warn in result.get("warnings", []):
        st.warning(f"⚠ {warn}")
    if result.get("unknown"):
        st.warning(
            f"⚠ Unbekannte Hotel-Labels ({len(result['unknown'])}): "
            f"{', '.join(result['unknown'][:5])}{'…' if len(result['unknown']) > 5 else ''}"
        )

    if plan_dict:
        st.subheader("2 · Vorschau")
        pivot = rows.pivot_table(
            index="hotel_code", columns="month", values="plan_eur", aggfunc="sum"
        ).fillna(0)
        pivot = pivot.reindex(sorted(pivot.columns), axis=1)
        pivot["Total (€)"] = pivot.sum(axis=1)
        pivot_display = pivot.copy()
        for c in pivot_display.columns:
            pivot_display[c] = pivot_display[c].map(H.fmt_eur)
        st.dataframe(pivot_display, use_container_width=True)

        st.subheader("3 · Override aktivieren")
        col_a, col_b = st.columns([1, 3])
        with col_a:
            if st.button("Plan aktivieren + speichern", type="primary", key="plan_activate"):
                try:
                    saved_to = H.save_plan_override(plan_dict)
                    st.session_state["plan_override"] = plan_dict
                    st.success(
                        f"Override aktiv und gespeichert (`{saved_to}`) - "
                        f"{n_hotels} Hotels, {n_months} Monate, Total "
                        f"{H.fmt_eur(total_eur)}. Überlebt App-Restart."
                    )
                    st.info(
                        "Tipp: Wenn dieser Upload der neue Default für alle "
                        "werden soll, ersetze `data/plan_default.xlsx` im Repo "
                        "(committen + pushen) und lösche dann den Override hier."
                    )
                except Exception as e:
                    st.error(f"Speichern fehlgeschlagen: {e}")
        with col_b:
            st.caption(
                "Der Override wird neben dem Snapshot abgelegt. Bei "
                "GCS-Snapshot ist er also zentral für alle User."
            )


# ============================== Default-Excel Download ====================
st.divider()
st.subheader("Default als Excel herunterladen")
st.caption(
    "Falls du den aktiven Default editieren willst - runterladen, in Excel "
    "anpassen, oben als Override hochladen. Wenn der Override auch der neue "
    "Repo-Default werden soll: Datei zusätzlich nach `data/plan_default.xlsx` "
    "kopieren + committen + pushen."
)

if default_path and default_path.exists():
    with default_path.open("rb") as fh:
        st.download_button(
            f"`{default_path.relative_to(_REPO_ROOT)}` herunterladen",
            data=fh.read(),
            file_name=default_path.name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dl_plan_default",
        )
else:
    st.caption(
        "Es liegt noch keine Default-Datei im Repo. Wenn du eine willst: "
        "Lade oben eine Excel hoch, lass dir den geparsten Plan anzeigen, "
        "kopiere deine Excel nach `data/plan_default.xlsx` und committe sie."
    )


# ============================== Leer-Template Download ===================
st.divider()
st.subheader("Leeres Template (ohne Daten)")
st.caption(
    "Wide-Format-Vorlage mit allen Hotels und 24 Monaten (Jan 2025 – Dez 2026), "
    "Zellen leer. Praktisch um von Null zu starten."
)

import yaml as _yaml

with (_REPO_ROOT / "configs" / "locations.yaml").open(encoding="utf-8") as fh:
    _locs = (_yaml.safe_load(fh) or {}).get("locations", [])

months_template = [f"{m:02d}-{yy:02d}" for yy in (25, 26) for m in range(1, 13)]
labels = []
for loc in _locs:
    city = (loc.get("city") or "").strip()
    neigh = (loc.get("neighborhood") or "").strip()
    label = f"PLAN:{city} {neigh}".strip() if neigh else f"PLAN:{city}"
    labels.append(label)

template = pd.DataFrame({"Hotel": labels})
for m in months_template:
    template[m] = 0
buf = io.BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as w:
    template.to_excel(w, sheet_name="Plan", index=False)
st.download_button(
    "Template herunterladen",
    data=buf.getvalue(),
    file_name="stayery_plan_template.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    key="dl_plan_template",
)
