"""Excel-Export-Helfer für Download-Buttons (xlsxwriter, lazy).

Konvention für ALLE Downloads der App:

  * ``st.download_button(..., data=<Funktion>, on_click="ignore")``.
    Streamlit (>= 1.52) führt die Funktion erst beim Klick aus - in einem
    eigenen Thread, ohne den Seiten-Rerun zu blockieren. ``on_click="ignore"``
    verhindert, dass der Klick selbst einen kompletten Rerun auslöst.
  * Vorher wurden die Workbooks bei JEDEM Rerun gebaut, ob jemand klickt oder
    nicht - mit openpyxl auf der Pickup-Seite gemessen 39 s CPU und +745 MB RAM
    je Rerun (4 Sheets, ~84k Zeilen). Das war der größte einzelne OOM-Pfad.
  * xlsxwriter schreibt dieselben Sheets mit ~1/3 des Speichers (gemessen
    +264 MB statt +745 MB) und ohne openpyxl-Zellobjekte.

Innerhalb der Funktionen KEINE ``st.*``-Aufrufe (kein ScriptRunContext im
Download-Thread).
"""

from __future__ import annotations

import io
from collections.abc import Iterable, Mapping

import pandas as pd

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def frames_to_xlsx(
    sheets: Mapping[str, pd.DataFrame] | Iterable[tuple[str, pd.DataFrame]],
    *,
    col_width: int = 17,
    autofilter: bool = False,
    datetime_format: str | None = None,
    empty_note: str = "keine Daten",
) -> bytes:
    """Mehrere DataFrames als Multi-Sheet-Workbook (Bytes) schreiben.

    Args:
        sheets: ``{sheet_name: df}`` oder Liste von ``(sheet_name, df)``.
            Leere/None-Frames werden als Hinweis-Sheet geschrieben.
        col_width: Spaltenbreite für alle Spalten.
        autofilter: AutoFilter über die Datenzeilen setzen.
        datetime_format: Excel-Zahlenformat für Datetime-Zellen.
        empty_note: Text für leere Sheets.

    Returns:
        Das Workbook als Bytes (Kopfzeile fett, erste Zeile fixiert).
    """
    items = list(sheets.items()) if isinstance(sheets, Mapping) else list(sheets)
    kwargs: dict = {"engine": "xlsxwriter"}
    if datetime_format:
        kwargs["datetime_format"] = datetime_format
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, **kwargs) as xw:
        for name, df in items:
            out = df if (df is not None and len(df)) else pd.DataFrame({"Hinweis": [empty_note]})
            sheet = str(name)[:31]
            out.to_excel(xw, sheet_name=sheet, index=False)
            ws = xw.sheets[sheet]
            last_col = max(out.shape[1] - 1, 0)
            ws.freeze_panes(1, 0)
            ws.set_column(0, last_col, col_width)
            if autofilter and len(out):
                ws.autofilter(0, 0, len(out), last_col)
    return bio.getvalue()
