"""Aggregation für die Promo-Codes-Page.

Eine Zeile je ``promoCode`` mit denselben B2B-Metriken wie ``b2b_tables`` plus
zwei Promo-spezifische Signale:

  * **Auch als corporateCode?** - der gleiche Code-String wird woanders bereits
    als ``corporateCode`` geführt -> starkes Indiz für einen Firmencode.
  * **Firmencode-Verdacht** - Heuristik aus dem corporateCode-Treffer + einem
    dominanten Firmennamen unter den Buchungen.

Außerdem eine **Status**-Spalte, die reklassifizierte Codes markiert.
"""

from __future__ import annotations

import pandas as pd

# Null-ähnliche Platzhalter (konsistent zu helpers / overrides).
_NULLISH = {"", "nan", "none", "<na>", "null"}


def _dominant_firm(sub_df: pd.DataFrame, col: str, min_share: float = 0.5) -> tuple[str, float]:
    """Häufigster Firmenname in ``col`` + dessen Anteil (0..1).

    Args:
        sub_df: Buchungen einer Promocode-Gruppe.
        col: Spalte mit Firmennamen (z.B. ``firm_by_effective_fuzzy``).
        min_share: Schwelle, ab der der Top-Name als "dominant" zurückgegeben
            wird.

    Returns:
        ``(name, share)`` - leerer Name wenn nichts dominiert.
    """
    if col not in sub_df.columns:
        return "", 0.0
    s = sub_df[col].dropna().astype(str).str.strip()
    s = s[~s.str.lower().isin(_NULLISH)]
    if s.empty:
        return "", 0.0
    vc = s.value_counts(normalize=True)
    top_share = float(vc.iloc[0])
    if top_share >= min_share:
        return str(vc.index[0]), top_share
    return "", top_share


def _firm_names(sub_df: pd.DataFrame, col: str, top_n: int = 3) -> str:
    """Top-N Firmennamen einer Gruppe als ``A / B / C …``."""
    if col not in sub_df.columns:
        return ""
    s = sub_df[col].dropna().astype(str).str.strip()
    s = s[~s.str.lower().isin(_NULLISH)]
    if s.empty:
        return ""
    vc = s.value_counts()
    return " / ".join(vc.index[:top_n].astype(str)) + (" …" if len(vc) > top_n else "")


def aggregate_promo_codes(
    res: pd.DataFrame,
    active_ts: pd.Timestamp,
    corporate_code_set: set[str] | None = None,
    reclassified_codes: set[str] | None = None,
) -> pd.DataFrame:
    """Aggregiere alle ``promoCode``-Werte zu einer Zeile pro Code.

    Args:
        res: Engineerter Buchungs-Frame mit ``promoCode``.
        active_ts: „Aktiv"-Schwelle - Codes mit Buchung ≥ diesem Anreise-Datum
            gelten als aktiv.
        corporate_code_set: Menge aller corporateCode-Strings (upper) im
            Datensatz - für das „Auch als corporateCode?"-Signal. Wird bei
            ``None`` aus ``res`` berechnet.
        reclassified_codes: Menge der bereits als Firmencode reklassifizierten
            Codes (upper) - für die Status-Spalte.

    Returns:
        DataFrame, absteigend nach „Revenue gesamt (€)". Leer (mit Spalten) wenn
        keine Promocodes vorliegen.
    """
    base_cols = [
        "Promocode",
        "Status",
        "Firmencode-Verdacht",
        "Auch als corporateCode?",
        "Firmenname(n)",
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
    if "promoCode" not in res.columns:
        return pd.DataFrame(columns=base_cols)

    d = res[res["promoCode"].notna()].copy()
    d["promoCode"] = d["promoCode"].astype(str).str.strip()
    d = d[~d["promoCode"].str.lower().isin(_NULLISH)]
    if d.empty:
        return pd.DataFrame(columns=base_cols)

    if corporate_code_set is None:
        if "corporateCode" in res.columns:
            cc = res["corporateCode"].dropna().astype(str).str.strip().str.upper()
            corporate_code_set = set(cc[~cc.str.lower().isin(_NULLISH)].unique())
        else:
            corporate_code_set = set()
    reclassified_codes = reclassified_codes or set()

    rows = []
    for key, sub in d.groupby("promoCode"):
        key_up = str(key).upper()
        also_corp = key_up in corporate_code_set
        firm_name, firm_share = _dominant_firm(sub, "firm_by_effective_fuzzy")
        is_reclassified = key_up in reclassified_codes
        # Verdacht: bereits reklassifiziert ODER auch als corporateCode geführt
        # ODER ein klar dominanter Firmenname (≥ 60 %).
        suspect = is_reclassified or also_corp or (firm_share >= 0.6 and bool(firm_name))
        rows.append(
            {
                "Promocode": key,
                "Status": "✓ Firmencode (reklassifiziert)" if is_reclassified else "Promo",
                "Firmencode-Verdacht": "⚑ ja" if suspect else "-",
                "Auch als corporateCode?": "✓" if also_corp else "-",
                "Firmenname(n)": _firm_names(sub, "firm_by_effective_fuzzy"),
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
                "Aktiv seit Schwelle?": "✓ ja"
                if bool((sub["arrival"] >= active_ts).any())
                else "-",
                "Erste Buchung": sub["arrival"].min(),
                "Letzte Buchung": sub["arrival"].max(),
            }
        )

    out = pd.DataFrame(rows)
    return out.sort_values("Revenue gesamt (€)", ascending=False).reset_index(drop=True)


def format_display(table: pd.DataFrame) -> pd.DataFrame:
    """Datums-Spalten in lesbare Strings - für das Anzeige-Grid / den Export.

    Args:
        table: Ergebnis von :func:`aggregate_promo_codes`.

    Returns:
        Kopie mit formatierten Datumsfeldern (Reihenfolge unverändert).
    """
    if table.empty:
        return table
    out = table.copy()
    for col in ("Erste Buchung", "Letzte Buchung"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col]).dt.strftime("%d.%m.%Y")
    return out
