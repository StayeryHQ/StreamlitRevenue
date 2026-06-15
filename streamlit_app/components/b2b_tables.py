"""Table for B2B Deep-Dive two tabs
(inkl. Storno + No-Show):

  - aggregate_corporate_codes(res, active_ts)   corporateCode
  - aggregate_firms(res, active_ts)             fuzzy-clustered
"""

from __future__ import annotations

import pandas as pd


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

    rows = []
    for key, sub in d.groupby(group_col):
        active_in_period = bool((sub["arrival"] >= active_ts).any())
        row = {
            group_col: key,
            "Buchungen gesamt": int(len(sub)),
            "davon realisiert": int(sub["is_realized"].sum()),
            "davon storniert": int(sub["is_cancelled"].sum()),
            "davon no-show": int(sub["is_no_show"].sum()),
            "Revenue gesamt (€)": float(sub["revenue"].sum()),
            "Revenue realisiert (€)": float(sub.loc[sub["is_realized"], "revenue"].sum()),
            "Revenue verloren (€)": float(sub["lost_revenue"].sum())
            if "lost_revenue" in sub.columns
            else 0.0,
            "Nächte realisiert": int(sub.loc[sub["is_realized"], "nights"].fillna(0).sum()),
            "# Standorte": int(sub["property_code"].nunique()),
            "Standorte": ", ".join(sorted(sub["property_code"].dropna().unique())),
            "Aktiv seit Schwelle?": "✓ ja" if active_in_period else "-",
            "Erste Buchung": sub["arrival"].min(),
            "Letzte Buchung": sub["arrival"].max(),
        }
        if group_col != "firm_by_effective_fuzzy":
            if "firm_by_effective_fuzzy" in sub.columns:
                firms = sub["firm_by_effective_fuzzy"].dropna().astype(str).str.strip()
                firms = firms[firms != ""]
                if not firms.empty:
                    top_firms = firms.value_counts()
                    names = list(top_firms.index[:3])
                    row["Firmenname(n)"] = " / ".join(names)
                else:
                    row["Firmenname(n)"] = ""
            else:
                row["Firmenname(n)"] = ""
        if paired_other_col:
            row["Auch mit (häufigster Wert)"] = _paired_dominant(sub, paired_other_col)
        rows.append(row)

    out = pd.DataFrame(rows)
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
def format_display(table: pd.DataFrame, kind: str) -> pd.DataFrame:
    """Reorder + format columns for st.dataframe rendering.

    kind: ``corporate`` / ``firm``
    """
    if table.empty:
        return table
    out = table.copy()
    # Format dates as readable strings
    for col in ("Erste Buchung", "Letzte Buchung"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col]).dt.strftime("%d.%m.%Y")

    if kind == "firm":
        cols = [
            "Firma",
            "Genutzte corporateCodes",
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
    elif kind == "corporate":
        cols = [
            "Corporate-Code",
            "Firmenname(n)",
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
    else:
        raise ValueError(f"Unsupported kind={kind!r}; supported: 'corporate', 'firm'.")
    return out.reindex(columns=[c for c in cols if c in out.columns])
