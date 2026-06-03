"""Alarm- / Highlight-Boxen für die Analyse-Pages.

Vier Stile:
  - alert    (rot)   für kritische Abweichungen ("Berlin -12% vs PLAN")
  - warning  (gelb)  für auffällige Beobachtungen ("OTA-Anteil +8pp YoY")
  - info     (blau)  für neutrale Hinweise
  - success  (grün)  für positive Findings
"""

from __future__ import annotations

import streamlit as st

_STYLES = {
    "alert": ("#fde7e3", "#9a2316", "⚠"),
    "warning": ("#fff5d6", "#9a6f00", "▲"),
    "info": ("#e3eaf5", "#1f3d7a", "ℹ"),
    "success": ("#e3f5ea", "#137a3a", "✓"),
}


def alert_card(message: str, kind: str = "info", *, title: str | None = None) -> None:
    """Render a coloured highlight box.

    Args:
        message: text body of the alert (plain string or markdown).
        kind: one of 'alert', 'warning', 'info', 'success'.
        title: optional bold title above the body.
    """
    bg, fg, icon = _STYLES.get(kind, _STYLES["info"])
    title_html = (
        f'<div style="font-weight:700;margin-bottom:4px;">{icon} {title}</div>'
        if title
        else f'<span style="font-weight:700;margin-right:6px;">{icon}</span>'
    )
    body = message.replace("\n", "<br>")
    st.markdown(
        f'<div style="background:{bg};border-left:4px solid {fg};'
        f"color:#1a1a1a;padding:10px 14px;border-radius:4px;margin:6px 0;"
        f'font-size:0.92em;line-height:1.45;">'
        f"{title_html}{body}</div>",
        unsafe_allow_html=True,
    )


def alert_cards(highlights: list[dict]) -> None:
    """Render a vertical stack of alerts from a list of dicts.

    Each dict: {"kind": "alert", "title": "Berlin -12%", "message": "..."}.
    Used at the top of an analysis page to surface the 3-5 most important findings.
    """
    if not highlights:
        alert_card(
            "Keine Auffälligkeiten gefunden",
            kind="success",
        )
        return
    for h in highlights:
        alert_card(
            h.get("message", ""),
            kind=h.get("kind", "info"),
            title=h.get("title"),
        )
