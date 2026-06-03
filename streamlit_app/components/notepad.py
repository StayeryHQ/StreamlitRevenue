"""Notepad - sticky Sidebar-Companion mit Snippet-Push.

Pro Analyse-Page hat der User ein freies Notiz-Feld in der Sidebar.
"""

from __future__ import annotations

import streamlit as st


def _notepad_key(page: str | None = None) -> str:
    page = page or st.session_state.get("__page", "default")
    return f"notepad::{page}"


def _pending_key(page: str | None = None) -> str:
    page = page or st.session_state.get("__page", "default")
    return f"_pending_snippet::{page}"


def _clear_pending_key(page: str | None = None) -> str:
    page = page or st.session_state.get("__page", "default")
    return f"_pending_clear_notepad::{page}"


def render_notepad(page: str | None = None) -> None:
    """Render the sidebar notepad. **Call once at the END of the sidebar.**"""
    page = page or st.session_state.get("__page", "default")
    key = _notepad_key(page)
    pending = _pending_key(page)
    clear_flag = _clear_pending_key(page)

    # Pending actions VOR dem Widget anwenden:
    if st.session_state.pop(clear_flag, False):
        st.session_state[key] = ""
    if pending in st.session_state:
        existing = st.session_state.get(key, "") or ""
        block = st.session_state.pop(pending)
        if block and block not in existing:
            st.session_state[key] = (existing + block).lstrip()

    st.sidebar.markdown(
        '<div class="stayery-notepad-header">'
        '<span class="dot"></span> Notepad'
        "</div>"
        '<div class="stayery-notepad-hint">'
        "Eigene Beobachtungen tippen oder per <strong>📋 In Notepad</strong>-Button "
        "unter Sektionen befüllen. Wird mit dem Bericht exportiert."
        "</div>",
        unsafe_allow_html=True,
    )
    st.sidebar.text_area(
        "Notepad",
        key=key,
        height=320,
        placeholder="z.B. Mai-Peak verdankt Q3-Convention im Westend …",
        label_visibility="collapsed",
    )
    cols = st.sidebar.columns(2)
    if cols[0].button("Leeren", key=f"_btn_notepad_clear_{page}", use_container_width=True):
        st.session_state[clear_flag] = True
        st.rerun()
    cols[1].caption(f"{len(st.session_state.get(key, ''))} Zeichen")


def push_snippet(section_id: str, snippet: str, page: str | None = None) -> None:
    """Render a button that queues `snippet` for the next render's notepad."""
    page = page or st.session_state.get("__page", "default")
    btn_key = f"_btn_snippet_{page}_{section_id}"
    if st.button(
        "📋 In Notepad übernehmen", key=btn_key, help="Fügt die Sektions-Kennzahlen ans Notepad an"
    ):
        pending = _pending_key(page)
        existing_pending = st.session_state.get(pending, "")
        block = f"\n\n- {section_id} -\n{snippet.strip()}"
        st.session_state[pending] = existing_pending + block
        st.rerun()


def get_notepad(page: str | None = None) -> str:
    """Return the notepad text for export inclusion."""
    return st.session_state.get(_notepad_key(page), "") or ""


def clear_notepad(page: str | None = None) -> None:
    st.session_state[_notepad_key(page)] = ""
