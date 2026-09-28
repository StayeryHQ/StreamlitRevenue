"""Markdown-Export - sammelt Sektionen + Highlights + Notepad und baut auf
Klick eine Notion-fertige Markdown-Datei.

Zwei Export-Modi:
  - „Aktuelle Ansicht"  - alle Sektionen die der User gerade sieht (= alle
                          registrierten Sektionen), Notepad mit drin.
  - „Anpassen…"         - Multi-Select welche Sektionen rein sollen + Notepad
                          ein/aus.
"""

from __future__ import annotations

import base64
from io import BytesIO

import streamlit as st


def _bucket_key(page: str | None = None) -> str:
    page = page or st.session_state.get("__page", "default")
    return f"export_bucket::{page}"


def reset_export(page: str | None = None) -> None:
    st.session_state[_bucket_key(page)] = []


def register_section(
    section_id: str = "",
    title: str = "",
    *,
    body_markdown: str = "",
    chart_fig=None,
    chart_png: bytes | None = None,
    table_df=None,
    page: str | None = None,
) -> None:
    """Append a section to the export bucket."""
    bucket = st.session_state.setdefault(_bucket_key(page), [])
    item = {"id": section_id, "title": title, "body_markdown": body_markdown}
    if chart_png is not None:
        item["chart_png"] = chart_png
    elif chart_fig is not None:
        item["chart_fig"] = chart_fig
    if table_df is not None:
        # Nur die 50 Zeilen merken; ``to_markdown`` (tabulate) erst beim
        # Export-Klick in ``render_markdown`` - vorher lief es bei jedem Rerun
        # für jede registrierte Sektion.
        item["table_df"] = table_df.head(50).copy()
    bucket.append(item)


def _table_markdown(sec: dict) -> str | None:
    if sec.get("table_markdown"):
        return sec["table_markdown"]
    df = sec.get("table_df")
    if df is None:
        return None
    try:
        return df.to_markdown(index=False)
    except (ImportError, ValueError):
        return df.to_string(index=False)


def _fig_to_b64(fig, dpi: int = 130) -> str:
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def build_markdown(
    page_title: str,
    highlights: list[dict] | None = None,
    page: str | None = None,
    section_ids: list[str] | None = None,
    include_notepad: bool = True,
    include_tables: bool = True,
) -> str:
    """Markdown aus dem Export-Bucket der Session bauen (liest ``session_state``).

    Für Download-Buttons NICHT direkt als ``data=`` verwenden: die Funktion
    braucht den Script-Kontext. Stattdessen ``_snapshot_inputs`` im Seitenlauf
    aufrufen und ``render_markdown`` als Download-Callable übergeben.
    """
    bucket, notes = _snapshot_inputs(page, section_ids, include_notepad)
    return render_markdown(
        page_title, highlights, bucket, notes, include_tables=include_tables
    )


def _snapshot_inputs(
    page: str | None, section_ids: list[str] | None, include_notepad: bool
) -> tuple[list[dict], str]:
    """Bucket + Notepad-Text im Seitenlauf einsammeln (Referenzen, keine Kopien)."""
    bucket = st.session_state.get(_bucket_key(page), [])
    if section_ids is not None:
        wanted = set(section_ids)
        bucket = [s for s in bucket if s["id"] in wanted]
    notes = ""
    if include_notepad:
        try:
            from .notepad import get_notepad
        except ImportError:
            from notepad import get_notepad  # type: ignore
        notes = get_notepad(page)
    return list(bucket), notes


def render_markdown(
    page_title: str,
    highlights: list[dict] | None,
    bucket: list[dict],
    notes: str,
    *,
    include_tables: bool = True,
) -> str:
    """Reiner Renderer (kein ``st.*``): läuft im Download-Thread erst beim Klick.

    Vorher wurde der komplette Markdown inkl. Base64 aller Chart-PNGs bei jedem
    Rerun neu gebaut, sobald „Bericht erzeugen" einmal geklickt war, und die
    „Anpassen"-Variante blieb als String für die ganze Session im
    ``session_state``.
    """
    lines = [f"# {page_title}", ""]

    if highlights:
        lines.append("## Highlights & Alarme")
        lines.append("")
        for h in highlights:
            icon = {"alert": "⚠", "warning": "▲", "info": "ℹ", "success": "✓"}.get(
                h.get("kind", "info"), "•"
            )
            t = h.get("title", "")
            m = h.get("message", "")
            lines.append(f"- {icon} **{t}** - {m}" if t else f"- {icon} {m}")
        lines.append("")

    if notes.strip():
        lines.append("## Notes & Beobachtungen")
        lines.append("")
        lines.append(notes.strip())
        lines.append("")
        lines.append("---")
        lines.append("")

    for sec in bucket:
        lines.append(f"## {sec['title']}")
        lines.append("")
        if sec.get("body_markdown"):
            lines.append(sec["body_markdown"])
            lines.append("")
        if sec.get("chart_png") is not None:
            b64 = base64.b64encode(sec["chart_png"]).decode("ascii")
            lines.append(f"![chart](data:image/png;base64,{b64})")
            lines.append("")
        elif sec.get("chart_fig") is not None:
            b64 = _fig_to_b64(sec["chart_fig"])
            lines.append(f"![chart](data:image/png;base64,{b64})")
            lines.append("")
        if include_tables:
            tbl = _table_markdown(sec)
            if tbl:
                lines.append(tbl)
                lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def download_button(
    page_title: str,
    highlights: list[dict] | None = None,
    filename: str = "report.md",
    *,
    page: str | None = None,
) -> None:
    page_key = page or st.session_state.get("__page", "default")
    bucket = st.session_state.get(_bucket_key(page), [])
    if not bucket:
        st.caption(
            "Noch keine Sektionen geladen. "
            "Sektionen oben öffnen, dann zurückkommen."
        )
        return

    # ---- Master-Toggle ---------------------------------------------------
    include_tables = st.checkbox(
        "Tabellen mitexportieren",
        value=True,
        key=f"_export_inc_tables_{page_key}",
        help="Wenn aus, enthält der Markdown nur Charts + Erklärtexte - "
        "kompakter für reine Recap-Memos. Wenn an, kommen die "
        "Datentabellen unter jedem Chart mit (Top 50 Zeilen).",
    )

    col_a, col_b = st.columns([1, 1])
    # Alt-Flags aus früheren Versionen (Markdown-Payload im Session-State) räumen.
    st.session_state.pop(f"_md_quick::{page_key}", None)
    st.session_state.pop(f"_md_custom_payload::{page_key}", None)

    def _lazy_md(section_ids, include_notepad):
        """Download-Callable: Inputs jetzt einsammeln, rendern erst beim Klick."""
        bucket_now, notes_now = _snapshot_inputs(page, section_ids, include_notepad)

        def _render() -> bytes:
            return render_markdown(
                page_title, highlights, bucket_now, notes_now, include_tables=include_tables
            ).encode("utf-8")

        return _render

    with col_a:
        st.markdown("**Aktuelle Ansicht**")
        st.caption("Alle geladenen Sektionen + Notepad als ein Markdown.")
        st.download_button(
            label="Markdown speichern",
            data=_lazy_md(None, True),
            file_name=filename,
            mime="text/markdown",
            on_click="ignore",
            key=f"_quick_dl_{page_key}",
        )

    with col_b:
        st.markdown("**Anpassen …**")
        with st.expander("Sektionen + Notepad auswählen", expanded=False):
            all_ids = [s["id"] for s in bucket]
            id_to_title = {s["id"]: s["title"] for s in bucket}
            chosen = st.multiselect(
                "Sektionen im Bericht",
                options=all_ids,
                default=all_ids,
                format_func=lambda i: id_to_title.get(i, i),
                key=f"_custom_pick_{page_key}",
            )
            include_notes = st.checkbox(
                "Notepad mitexportieren",
                value=True,
                key=f"_custom_notes_{page_key}",
            )
            st.download_button(
                label="Markdown speichern",
                data=_lazy_md(chosen, include_notes),
                file_name=filename.replace(".md", "_custom.md"),
                mime="text/markdown",
                on_click="ignore",
                key=f"_custom_dl_{page_key}",
            )
