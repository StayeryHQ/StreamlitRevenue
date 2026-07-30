"""Table for B2B Deep-Dive two tabs
(inkl. Storno + No-Show):

  - aggregate_corporate_codes(res, active_ts)   corporateCode
  - aggregate_firms(res, active_ts)             fuzzy-clustered
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _join_props(s: pd.Series) -> str:
    return ", ".join(sorted(s.dropna().astype(str).unique()))


def _top3_firms(s: pd.Series) -> str:
    s = s.dropna().astype(str).str.strip()
    s = s[s != ""]
    if s.empty:
        return ""
    return " / ".join(list(s.value_counts().index[:3]))


def _codes_from_series(s: pd.Series, top_n: int = 3) -> str:
    s = s.dropna().astype(str).str.strip()
    s = s[s != ""]
    if s.empty:
        return ""
    vc = s.value_counts()
    return " / ".join(vc.index[:top_n].astype(str)) + (" …" if len(vc) > top_n else "")


# ============================== Helpers ====================================
def _paired_dominant(sub_df: pd.DataFrame, other_col: str, min_share: float = 0.5) -> str:
    """Wenn diese Code-Gruppe vorwiegend mit einem Wert in ``other_col`` gepaart
    ist, gib diesen Wert + Anteil zurück. Sonst leer.
    """
    if other_col not in sub_df.columns:
        return ""
    other = sub_df[other_col].dropna().astype(str).str.strip()
    other = other[other != ""]
    if other.empty:
        return ""
    vc = other.value_counts(normalize=True)
    top = vc.iloc[0]
    if top >= min_share:
        return f"{vc.index[0]} ({top * 100:.0f}%)"
    return ""


def _codes_used_by_firm(sub_df: pd.DataFrame, code_col: str, top_n: int = 3) -> str:
    """List of codes this firm has used sorted by frequency."""
    if code_col not in sub_df.columns:
        return ""
    s = sub_df[code_col].dropna().astype(str).str.strip()
    s = s[s != ""]
    if s.empty:
        return ""
    vc = s.value_counts()
    return " / ".join(vc.index[:top_n].astype(str)) + (" …" if len(vc) > top_n else "")


# ============================== Core aggregator ============================
def _aggregate_by(
    res: pd.DataFrame,
    group_col: str,
    active_ts: pd.Timestamp,
    paired_other_col: str | None = None,
) -> pd.DataFrame:
    """One row per group_col value with all the B2B-relevant metrics."""
    base_cols = [
        group_col,
        "Buchungen gesamt",
        "davon realisiert",
        "davon storniert",
        "davon no-show",
        "Revenue gesamt (€)",
        "Revenue realisiert (€)",
        "Revenue verloren (€)",
        "Nächte realisiert",
        "# Standorte",
        "Standorte",
        "Aktiv seit Schwelle?",
        "Erste Buchung",
        "Letzte Buchung",
    ]
    if group_col != "firm_by_effective_fuzzy":
        base_cols.append("Firmenname(n)")
    if paired_other_col:
        base_cols.append("Auch mit (häufigster Wert)")

    if group_col not in res.columns:
        return pd.DataFrame(columns=base_cols)
    d = res[res[group_col].notna() & (res[group_col].astype(str).str.strip() != "")].copy()
    d[group_col] = d[group_col].astype(str).str.strip()
    if d.empty:
        return pd.DataFrame(columns=base_cols)

    # Vectorised groupby.agg (one C-level pass) instead of a Python loop over
    # thousands of groups doing per-group pandas ops - the roster's main cost.
    real = d["is_realized"].to_numpy()
    d["_rev_real"] = np.where(real, d["revenue"].to_numpy(), 0.0)
    nights = d["nights"].fillna(0).to_numpy() if "nights" in d.columns else np.zeros(len(d))
    d["_nights_real"] = np.where(real, nights, 0.0)
    d["_active"] = d["arrival"] >= active_ts
    d["_lost"] = d["lost_revenue"].to_numpy() if "lost_revenue" in d.columns else 0.0

    g = d.groupby(group_col, sort=False)
    out = g.agg(**{
        "Buchungen gesamt": ("revenue", "size"),
        "davon realisiert": ("is_realized", "sum"),
        "davon storniert": ("is_cancelled", "sum"),
        "davon no-show": ("is_no_show", "sum"),
        "Revenue gesamt (€)": ("revenue", "sum"),
        "Revenue realisiert (€)": ("_rev_real", "sum"),
        "Revenue verloren (€)": ("_lost", "sum"),
        "Nächte realisiert": ("_nights_real", "sum"),
        "# Standorte": ("property_code", "nunique"),
        "Aktiv seit Schwelle?": ("_active", "max"),
        "Erste Buchung": ("arrival", "min"),
        "Letzte Buchung": ("arrival", "max"),
    })
    out["Standorte"] = g["property_code"].agg(_join_props)
    out["Aktiv seit Schwelle?"] = np.where(out["Aktiv seit Schwelle?"], "✓ ja", "-")
    for c in ("Buchungen gesamt", "davon realisiert", "davon storniert", "davon no-show",
              "Nächte realisiert", "# Standorte"):
        out[c] = out[c].astype(int)
    if group_col != "firm_by_effective_fuzzy":
        out["Firmenname(n)"] = (g["firm_by_effective_fuzzy"].agg(_top3_firms)
                                if "firm_by_effective_fuzzy" in d.columns else "")
    if paired_other_col:
        out["Auch mit (häufigster Wert)"] = g.apply(
            lambda s: _paired_dominant(s, paired_other_col))

    out = out.reset_index()
    return out.sort_values("Revenue gesamt (€)", ascending=False).reset_index(drop=True)


# ============================== Public API ================================
def aggregate_corporate_codes(res: pd.DataFrame, active_ts: pd.Timestamp) -> pd.DataFrame:
    """Alle ``corporateCode``Werte seit Start."""
    out = _aggregate_by(res, "corporateCode", active_ts, paired_other_col=None)
    return out.rename(columns={"corporateCode": "Corporate-Code"})


def aggregate_firms(res: pd.DataFrame, active_ts: pd.Timestamp) -> pd.DataFrame:
    """Fuzzy-geclusterte Firmen mit corporateCode-Aufschlüsselung."""
    out = _aggregate_by(res, "firm_by_effective_fuzzy", active_ts)
    if out.empty:
        return out
    out = out.rename(columns={"firm_by_effective_fuzzy": "Firma"})

    codes_corporate: dict[str, str] = {}
    sub_with_firm = res[res["firm_by_effective_fuzzy"].notna()]
    for firm, sub in sub_with_firm.groupby("firm_by_effective_fuzzy"):
        codes_corporate[firm] = _codes_used_by_firm(sub, "corporateCode")
    out["Genutzte corporateCodes"] = out["Firma"].map(codes_corporate).fillna("")
    return out


# ============================== Display formatting =========================
def export_frame(table: pd.DataFrame, kind: str) -> pd.DataFrame:
    """Spalten-Reihenfolge wie ``format_display``, aber ROHE Werte.

    Für Excel-/CSV-Exporte: Zahlen bleiben Zahlen, Datumsfelder bleiben
    Datetime (Excel kann damit rechnen/sortieren) - keine String-Formatierung.
    """
    if table.empty:
        return table
    return table.reindex(columns=[c for c in _column_order(kind) if c in table.columns])


def format_display(table: pd.DataFrame, kind: str) -> pd.DataFrame:
    """Reorder + format columns for the display grid.

    kind: ``corporate`` / ``firm``
    """
    if table.empty:
        return table
    out = table.copy()
    # Format dates as readable strings
    for col in ("Erste Buchung", "Letzte Buchung"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col]).dt.strftime("%d.%m.%Y")

    return out.reindex(columns=[c for c in _column_order(kind) if c in out.columns])


def _column_order(kind: str) -> list[str]:
    """Kanonische Spalten-Reihenfolge je Tabellen-Art (Anzeige UND Export)."""
    _metrics = [
        "Aktiv seit Schwelle?",
        "Erste Buchung",
        "Letzte Buchung",
        "# Standorte",
        "Standorte",
        "Buchungen gesamt",
        "davon realisiert",
        "davon storniert",
        "davon no-show",
        "Revenue gesamt (€)",
        "Revenue realisiert (€)",
        "Revenue verloren (€)",
        "Nächte realisiert",
    ]
    if kind == "firm":
        return ["Firma", "Genutzte corporateCodes", *_metrics]
    if kind == "corporate":
        return ["Corporate-Code", "Firmenname(n)", *_metrics]
    raise ValueError(f"Unsupported kind={kind!r}; supported: 'corporate', 'firm'.")
