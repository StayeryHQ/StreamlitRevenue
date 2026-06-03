"""Markdown-Export - sammelt Sektionen + Highlights + Notepad und baut auf
Klick eine Notion-fertige Markdown-Datei.

Zwei Export-Modi:
  • „Aktuelle Ansicht"  - alle Sektionen die der User gerade sieht (= alle
                          registrierten Sektionen), Notepad mit drin.
  • „Anpassen…"         - Multi-Select welche Sektionen rein sollen + Notepad
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
        try:
            item["table_markdown"] = table_df.head(50).to_markdown(index=False)
        except (ImportError, ValueError):
            item["table_markdown"] = table_df.head(50).to_string(index=False)
    bucket.append(item)


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
    bucket = st.session_state.get(_bucket_key(page), [])
    if section_ids is not None:
        wanted = set(section_ids)
        bucket = [s for s in bucket if s["id"] in wanted]

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

    if include_notepad:
        try:
            from .notepad import get_notepad
        except ImportError:
            from notepad import get_notepad  # type: ignore
        notes = get_notepad(page)
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
        if include_tables and sec.get("table_markdown"):
            lines.append(sec["table_markdown"])
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
            "Noch keine Sektionen geladen - der Export bleibt leer. "
            "Sektionen oben öffnen, dann hier zurückkommen."
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
    flag_quick = f"_md_quick::{page_key}"
    flag_custom = f"_md_custom_payload::{page_key}"

    with col_a:
        st.markdown("**Aktuelle Ansicht**")
        st.caption("Alle geladenen Sektionen + Notepad als ein Markdown.")
        if st.button("Bericht erzeugen", key=f"_quick_btn_{page_key}"):
            st.session_state[flag_quick] = True
        if st.session_state.get(flag_quick):
            with st.spinner("Erzeuge Markdown + Chart-PNGs …"):
                md = build_markdown(
                    page_title,
                    highlights=highlights,
                    page=page,
                    section_ids=None,
                    include_notepad=True,
                    include_tables=include_tables,
                )
            st.download_button(
                label="Markdown speichern",
                data=md.encode("utf-8"),
                file_name=filename,
                mime="text/markdown",
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
            if st.button("Bericht erzeugen", key=f"_custom_btn_{page_key}"):
                with st.spinner("Erzeuge Markdown + Chart-PNGs …"):
                    md = build_markdown(
                        page_title,
                        highlights=highlights,
                        page=page,
                        section_ids=chosen,
                        include_notepad=include_notes,
                        include_tables=include_tables,
                    )
                st.session_state[flag_custom] = md
            if st.session_state.get(flag_custom):
                st.download_button(
                    label="Markdown speichern",
                    data=st.session_state[flag_custom].encode("utf-8"),
                    file_name=filename.replace(".md", "_custom.md"),
                    mime="text/markdown",
                    key=f"_custom_dl_{page_key}",
                )
