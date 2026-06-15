"""Alarm- / Highlight-Boxen für die Analyse-Pages.

Vier Stile:
  - alert    (rot)   für kritische Abweichungen
  - warning  (gelb)  für auffällige Beobachtungen
  - info     (blau)  für neutrale Hinweise
  - success  (grün)  für positive Findings
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from revenueblindspots.theming import color


def _tint(hex_color: str, white_share: float = 0.88) -> str:
    """Mischt eine Brand-Farbe Richtung Weiß (Tint für Alert-Hintergründe).

    Farben kommen ausschließlich per ``color()`` aus der Brand-YAML
    """
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    mix = lambda c: round(c + (255 - c) * white_share)  # noqa: E731
    return f"#{mix(r):02X}{mix(g):02X}{mix(b):02X}"

_STYLES = {
    "alert": (_tint(color("red")), color("red"), "⚠"),
    "warning": (_tint(color("yellow"), 0.70), color("yellow"), "▲"),
    "info": (_tint(color("blue")), color("blue"), "ℹ"),
    "success": (_tint(color("green")), color("green"), "✓"),
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
        f"color:#000000;padding:10px 14px;border-radius:4px;margin:6px 0;"
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
