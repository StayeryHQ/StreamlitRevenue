"""Notepad - sticky Sidebar-Companion mit Snippet-Push.

Pro Analyse-Page hat der User ein freies Notiz-Feld in der Sidebar.

Persistenz über Page-Wechsel: Der Inhalt lebt in einem eigenen, NICHT an ein
Widget gebundenen Session-State-Key (``notepad_store::{page}``). Solche Keys
verwirft Streamlit nie - im Gegensatz zu Widget-Keys, deren State beim Wechsel
auf eine andere Page verloren gehen kann. Das Textfeld selbst
(``notepad_input::{page}``) wird daher bei jedem Render frisch aus dem Store
geseedet und per ``on_change`` wieder in den Store zurückgespiegelt.
"""

from __future__ import annotations

import streamlit as st


def _page(page: str | None) -> str:
    return page or st.session_state.get("__page", "default")


def _store_key(page: str | None = None) -> str:
    """Persistenter Store-Key - Quelle der Wahrheit, kein Widget-Key."""
    return f"notepad_store::{_page(page)}"


def _input_key(page: str | None = None) -> str:
    """Widget-Key der text_area - darf von Streamlit verworfen werden."""
    return f"notepad_input::{_page(page)}"


def render_notepad(page: str | None = None) -> None:
    """Render the sidebar notepad. **Call once at the END of the sidebar.**"""
    page = _page(page)
    store = _store_key(page)
    inp = _input_key(page)
    st.session_state.setdefault(store, "")

    # Textfeld jeden Render frisch aus dem persistenten Store seeden: der
    # Widget-Key kann beim Page-Wechsel verloren gehen, der Store nie.
    st.session_state[inp] = st.session_state[store]

    def _sync() -> None:
        st.session_state[store] = st.session_state.get(inp, "")

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
        key=inp,
        height=320,
        placeholder="z.B. Mai-Peak verdankt Q3-Convention im Westend …",
        label_visibility="collapsed",
        on_change=_sync,
    )
    cols = st.sidebar.columns(2)
    if cols[0].button("Leeren", key=f"_btn_notepad_clear_{page}", use_container_width=True):
        st.session_state[store] = ""
        st.rerun()
    cols[1].caption(f"{len(st.session_state[store])} Zeichen")


def push_snippet(section_id: str, snippet: str, page: str | None = None) -> None:
    """Render a button that appends `snippet` to the page notepad."""
    page = _page(page)
    btn_key = f"_btn_snippet_{page}_{section_id}"
    if st.button(
        "📋 In Notepad übernehmen", key=btn_key, help="Fügt die Sektions-Kennzahlen ans Notepad an"
    ):
        store = _store_key(page)
        existing = st.session_state.get(store, "") or ""
        block = f"\n\n- {section_id} -\n{snippet.strip()}"
        if block.strip() not in existing:
            st.session_state[store] = (existing + block).lstrip()
        st.rerun()


def get_notepad(page: str | None = None) -> str:
    """Return the notepad text for export inclusion."""
    return st.session_state.get(_store_key(page), "") or ""
