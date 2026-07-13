"""Stayery brand für Streamlit-UI (CSS + Snapshot-Override-Bridge).

**Verantwortlichkeiten im Brand-System**:

  • ``configs/stayery_brand.yaml``        = Brand-Spec / SoT (Farben, Fonts).
  • ``src/revenueblindspots/theming.py``  = liest YAML, setzt **matplotlib**.
  • ``streamlit_app/components/brand.py`` = liest YAML, generiert **CSS** für
                                             die Streamlit-UI.

Wenn du einen Brand-Farbwert ändern willst mach nur in der YAML.

Fonts: **Neue Haas Grotesk Display Pro** + **Topol** laufen über
``@font-face`` aus ``streamlit_app/static/fonts/``.
Ohne die Files fällt der Stack auf System-Fonts.
"""

from __future__ import annotations

import sys
from pathlib import Path
from string import Template

import streamlit as st

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from revenueblindspots.theming import load_brand_config

# =============================================================================
# UI-Neutrals
# =============================================================================
_UI = {
    "ink": "#000000",  # primary text (Brand-Neutral Black)
    "ink_soft": "#666666",  # secondary text (Brand-Neutral Grey)
    "caption": "#666666",
    "muted": "#666666",
    "bg": "#FAFAF5",  # soft off-white (sidebar, hover bg)
    "bg_warm": "#FFFCF0",  # notepad / textarea (very subtle warm)
    "border": "#ECEAE0",  # subtle dividers / card borders
    "border_soft": "#F2F0E6",
}


def _brand_tokens() -> dict[str, str]:
    """Mischt Brand-Farben aus der YAML mit den UI-Neutrals."""
    cfg = load_brand_config()
    core = cfg["colors"]["core"]
    return {
        "yellow": core["yellow"],
        "black": core["black"],
        "white": core["white"],
        **_UI,
    }


# =============================================================================
# CSS-Template - Token-Substitution via string.Template
# =============================================================================
_BRAND_CSS = Template(r"""
<style>
/* -------------------------------------------------------------------------
   0 - Brand-Fonts aus streamlit_app/static/fonts/.
       Wenn die OTF-Files dort fehlen, fällt der font-family-Stack auf
       System-Fonts zurück.
   ------------------------------------------------------------------------- */
/* Neue Haas Grotesk Display Pro - Regular 400 (DS-55Rg = echtes Display) */
@font-face {
    font-family: "Neue Haas Grotesk Display Pro";
    src: url("./app/static/fonts/NeueHaasGroteskDisplay-Regular.otf") format("opentype");
    font-weight: 400; font-style: normal; font-display: swap;
}
@font-face {
    font-family: "Neue Haas Grotesk Display Pro";
    src: url("./app/static/fonts/NeueHaasGroteskDisplay-Italic.otf") format("opentype");
    font-weight: 400; font-style: italic; font-display: swap;
}
/* Medium 500 + Bold 700 kommen aus TX (Text-Pro) - Linotype liefert die
   schwereren Weights für Display nicht; TX und DS sind visuell ~95% identisch. */
@font-face {
    font-family: "Neue Haas Grotesk Display Pro";
    src: url("./app/static/fonts/NeueHaasGroteskDisplay-Medium.otf") format("opentype");
    font-weight: 500; font-style: normal; font-display: swap;
}
@font-face {
    font-family: "Neue Haas Grotesk Display Pro";
    src: url("./app/static/fonts/NeueHaasGroteskDisplay-MediumItalic.otf") format("opentype");
    font-weight: 500; font-style: italic; font-display: swap;
}
@font-face {
    font-family: "Neue Haas Grotesk Display Pro";
    src: url("./app/static/fonts/NeueHaasGroteskDisplay-Bold.otf") format("opentype");
    font-weight: 700; font-style: normal; font-display: swap;
}
@font-face {
    font-family: "Neue Haas Grotesk Display Pro";
    src: url("./app/static/fonts/NeueHaasGroteskDisplay-BoldItalic.otf") format("opentype");
    font-weight: 700; font-style: italic; font-display: swap;
}
/* Topol - Headlines/Statements/Zahlen, immer ALL CAPS, nie Body Text */
@font-face {
    font-family: "Topol";
    src: url("./app/static/fonts/Topol-Bold.otf") format("opentype");
    font-weight: 700; font-style: normal; font-display: swap;
}

/* -------------------------------------------------------------------------
   1 - Grundlayout
   ------------------------------------------------------------------------- */
#MainMenu, footer, header[data-testid="stHeader"] { visibility: hidden; }
[data-testid="stToolbar"] { visibility: hidden; }
[data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"],
[data-testid="stExpandSidebarButton"] {
    visibility: visible !important;
}

.block-container {
    padding-top: 1.4rem !important;
    padding-bottom: 3rem !important;
    max-width: 1280px !important;
}

html, body, [class*="css"], .stMarkdown, .stText, .stMetric, button, input, select, textarea {
    font-family: "Neue Haas Grotesk Display Pro",
                 "Helvetica Neue", Helvetica, Arial, sans-serif !important;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}

/* -------------------------------------------------------------------------
   2 - Headings - bold, mit dezenter Yellow-Akzent-Linie unten
   ------------------------------------------------------------------------- */
/* H1 / Headlines / Statements - Topol Bold, ALL CAPS (Brand-Standard).
   Kein manuelles letter-spacing (Tracking-Regel). */
h1 {
    color: ${ink};
    font-family: "Topol", "Neue Haas Grotesk Display Pro",
                 "Helvetica Neue", Helvetica, Arial, sans-serif !important;
    font-weight: 700;
    text-transform: uppercase;
    font-size: 2.4rem !important;
    margin-bottom: 0.6rem !important;
}
/* Sub-Headlines (kurz, scannbar) - Neue Haas, ALL CAPS */
h2 {
    color: ${ink};
    font-weight: 600;
    text-transform: uppercase;
    font-size: 1.55rem !important;
    margin-top: 1.4rem !important;
    margin-bottom: 0.5rem !important;
    padding-bottom: 0.35rem;
    border-bottom: 1px solid ${border};
    position: relative;
}
h2::after {
    content: "";
    position: absolute;
    left: 0;
    bottom: -1px;
    width: 48px;
    height: 3px;
    background: ${yellow};
    border-radius: 1px;
}
h3 { color: ${ink}; font-weight: 600; margin-top: 1.0rem; margin-bottom: 0.4rem; }
h4 { color: ${ink}; font-weight: 600; margin-top: 0.6rem; margin-bottom: 0.3rem; }

/* -------------------------------------------------------------------------
   3 - Buttons 
   ------------------------------------------------------------------------- */
.stButton > button,
.stDownloadButton > button,
.stFormSubmitButton > button,
[data-testid^="baseButton-"] {
    background: ${white} !important;
    color: ${ink} !important;
    border: 1px solid ${ink} !important;
    border-radius: 12px !important;
    font-weight: 500 !important;
    font-size: 0.875rem !important;
    text-transform: uppercase !important;  /* CTAs - Neue Haas, ALL CAPS */
    padding: 0.55rem 1.2rem !important;
    box-shadow: 0 1px 0 rgba(0,0,0,0.04);
    transition: transform .22s cubic-bezier(.22,1,.36,1),
                background .22s cubic-bezier(.22,1,.36,1),
                color .18s ease,
                border-color .18s ease,
                box-shadow .25s cubic-bezier(.22,1,.36,1);
}
.stButton > button:hover,
.stDownloadButton > button:hover,
.stFormSubmitButton > button:hover,
[data-testid^="baseButton-"]:hover {
    background: #FFFBE3 !important;          /* sanfter gelber Hue, kein harter Yellow-Fill */
    color: ${ink} !important;                /* Text BLEIBT schwarz - kein white-on-yellow */
    border-color: ${ink} !important;
    transform: translateY(-2px);
    box-shadow: 0 6px 14px rgba(255,230,80,0.40), 0 2px 4px rgba(0,0,0,0.08) !important;
}
.stButton > button:active,
.stDownloadButton > button:active,
.stFormSubmitButton > button:active {
    transform: translateY(0);
    box-shadow: 0 1px 2px rgba(0,0,0,0.10) !important;
    transition-duration: .06s;
}
.stButton > button:focus-visible,
.stDownloadButton > button:focus-visible,
.stFormSubmitButton > button:focus-visible {
    outline: none !important;
    box-shadow: 0 0 0 3px rgba(255,230,80,0.55), 0 4px 12px rgba(0,0,0,0.08) !important;
}
/* Primary buttons (type="primary") = Yellow CTA */
.stButton > button[kind="primary"],
.stFormSubmitButton > button[kind="primaryFormSubmit"],
[data-testid="baseButton-primary"],
[data-testid="baseButton-primaryFormSubmit"] {
    background: ${yellow} !important;
    color: ${ink} !important;
    font-weight: 600 !important;
}
.stButton > button[kind="primary"]:hover,
.stFormSubmitButton > button[kind="primaryFormSubmit"]:hover,
[data-testid="baseButton-primary"]:hover,
[data-testid="baseButton-primaryFormSubmit"]:hover {
    background: #FFF1A8 !important;          /* dunklerer Yellow-Hue beim Hover */
    color: ${ink} !important;                /* Text BLEIBT schwarz */
    border-color: ${ink} !important;
    box-shadow: 0 8px 18px rgba(255,230,80,0.55), 0 2px 5px rgba(0,0,0,0.10) !important;
}
[data-testid="stSidebar"] .stFormSubmitButton > button {
    padding: 0.45rem 0.9rem !important;
    font-size: 0.82rem;
}

/* -------------------------------------------------------------------------
   4 - Sidebar
   ------------------------------------------------------------------------- */
[data-testid="stSidebar"] {
    background: ${white};
    border-right: 1px solid ${border};
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h2 {
    border-bottom: none;
    padding-bottom: 0;
    font-size: 0.72rem !important;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: ${caption} !important;
    font-weight: 600;
    margin-top: 1.2rem !important;
    margin-bottom: 0.4rem !important;
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h2::after { display: none; }
[data-testid="stSidebar"] a[aria-current="page"] {
    background: ${yellow} !important;
    color: ${ink} !important;
    font-weight: 600 !important;
    border-radius: 10px !important;
}
[data-testid="stSidebar"] hr { margin: 1.5rem 0 !important; }

/* -------------------------------------------------------------------------
   5 - Metric Cards
   ------------------------------------------------------------------------- */
[data-testid="stMetric"] {
    background: ${white};
    border: 1px solid ${border};
    padding: 1rem 1.2rem;
    border-radius: 14px;
    transition: border-color .22s ease,
                transform .22s cubic-bezier(.22,1,.36,1),
                box-shadow .25s cubic-bezier(.22,1,.36,1);
    box-shadow: 0 1px 0 rgba(0,0,0,0.02);
}
[data-testid="stMetric"]:hover {
    border-color: ${ink};
    transform: translateY(-3px);
    box-shadow: 0 8px 20px rgba(0,0,0,0.06), 0 2px 4px rgba(0,0,0,0.04);
}
[data-testid="stMetricLabel"] {
    color: ${caption};
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-size: 0.72rem !important;
}
/* Zahlen - Topol Bold (Brand-Standard "Numbers / Signage") */
[data-testid="stMetricValue"] {
    color: ${ink} !important;
    font-family: "Topol", "Neue Haas Grotesk Display Pro",
                 "Helvetica Neue", Helvetica, Arial, sans-serif !important;
    font-weight: 700 !important;
    font-size: 1.85rem !important;
    line-height: 1.15;
}
[data-testid="stMetricDelta"] {
    font-weight: 500;
    font-size: 0.82rem !important;
}

/* -------------------------------------------------------------------------
   6 - Tables
   ------------------------------------------------------------------------- */
[data-testid="stDataFrame"] {
    border: 1px solid ${border};
    border-radius: 12px;
    overflow: hidden;
}
[data-testid="stDataFrame"] thead tr th {
    background: ${bg};
    color: ${ink};
    font-weight: 600;
    letter-spacing: 0.02em;
}

/* -------------------------------------------------------------------------
   7 - Text-Areas (Notepad)
   ------------------------------------------------------------------------- */
.stTextArea textarea {
    border: 1px solid ${border} !important;
    background: ${bg_warm};
    border-radius: 12px;
    font-family: "Neue Haas Grotesk Display Pro", "Helvetica Neue", Helvetica, Arial, sans-serif !important;
    color: ${ink};
    transition: border-color .15s ease, box-shadow .2s ease;
}
.stTextArea textarea:focus {
    border-color: ${ink} !important;
    box-shadow: 0 0 0 1px ${ink} !important;
}

/* Input + Selectboxes auch abgerundet */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stDateInput"] input,
[data-baseweb="select"] > div {
    border-radius: 10px !important;
}

/* -------------------------------------------------------------------------
   8 - Section dividers
   ------------------------------------------------------------------------- */
hr {
    border: none;
    border-top: 1px solid ${border};
    margin: 1.2rem 0 !important;
}

/* Streamlit Vertical-Spacing zwischen Block-Containern reduzieren */
[data-testid="stVerticalBlock"] > div { gap: 0.5rem !important; }
[data-testid="stImage"] { margin: 0.3rem 0 !important; }
[data-testid="stMarkdownContainer"] p { margin-bottom: 0.4rem; }
.element-container { margin-bottom: 0.4rem !important; }

/* -------------------------------------------------------------------------
   9 - Status-Container
   ------------------------------------------------------------------------- */
[data-testid="stStatusWidget"] {
    background: ${bg};
    border-left: 3px solid ${yellow};
    border-radius: 10px;
}

/* -------------------------------------------------------------------------
   10 - TOC
   ------------------------------------------------------------------------- */
.stayery-toc {
    margin: 0 0 2rem 0;
    padding: 1rem 0 1.1rem 0;
    border-top: 1px solid ${border};
    border-bottom: 1px solid ${border};
    display: flex;
    flex-wrap: wrap;
    gap: 1.3rem 0;
    align-items: baseline;
}
.stayery-toc-label {
    font-size: 0.68rem;
    text-transform: uppercase;
    letter-spacing: 0.18em;
    color: ${caption};
    font-weight: 600;
    margin-right: 1.5rem;
    padding-top: 0.05rem;
}
.stayery-toc-links {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem 1.6rem;
    flex: 1;
}
.stayery-toc a {
    text-decoration: none;
    color: ${ink};
    font-size: 0.88rem;
    font-weight: 500;
    border-bottom: 1px solid transparent;
    padding-bottom: 1px;
    transition: color .12s ease, border-color .12s ease;
    cursor: pointer;
}
.stayery-toc a:hover { border-bottom-color: ${yellow}; }
.stayery-toc .num {
    color: ${muted};
    font-variant-numeric: tabular-nums;
    margin-right: 0.35rem;
    font-weight: 400;
}

/* -------------------------------------------------------------------------
   11 - Back-to-top link
   ------------------------------------------------------------------------- */
.stayery-totop {
    text-align: right;
    margin-top: 0.6rem;
    font-size: 0.75rem;
}
.stayery-totop a {
    color: ${caption};
    text-decoration: none;
    transition: color .12s ease;
    cursor: pointer;
}
.stayery-totop a:hover { color: ${ink}; }

/* -------------------------------------------------------------------------
   12 - Expander
   ------------------------------------------------------------------------- */
.streamlit-expanderHeader, [data-testid="stExpander"] summary {
    font-weight: 500;
    color: ${ink_soft};
    background: ${bg};
    border: 1px solid ${border};
    border-radius: 10px;
}
.streamlit-expanderHeader:hover, [data-testid="stExpander"] summary:hover {
    color: ${ink};
    background: ${border_soft};
}

/* -------------------------------------------------------------------------
   13 - Notepad
   ------------------------------------------------------------------------- */
.stayery-notepad-header {
    font-size: 1.0rem;
    font-weight: 700;
    color: ${ink};
    margin: 1.4rem 0 0.4rem 0;
    padding-top: 0.8rem;
    border-top: 2px solid ${yellow};
    display: flex;
    align-items: center;
    gap: 0.5rem;
}
.stayery-notepad-header .dot {
    width: 8px; height: 8px;
    background: ${yellow};
    border: 1px solid ${ink};
    border-radius: 50%;
    display: inline-block;
}
.stayery-notepad-hint {
    color: ${caption};
    font-size: 0.78rem;
    margin-bottom: 0.5rem;
}

/* -------------------------------------------------------------------------
   14 - Accent Hero in headline
   ------------------------------------------------------------------------- */
.stayery-hero {
    padding: 1.6rem 0 0.6rem;
    border-bottom: 1px solid ${border};
    margin-bottom: 1.6rem;
}
.stayery-hero-eyebrow {
    font-size: 0.68rem;
    text-transform: uppercase;
    letter-spacing: 0.22em;
    color: ${caption};
    font-weight: 600;
    margin-bottom: 0.3rem;
    display: inline-block;
    position: relative;
    padding-left: 18px;
}
.stayery-hero-eyebrow::before {
    content: "";
    position: absolute;
    left: 0; top: 50%;
    width: 12px; height: 2px;
    background: ${yellow};
    transform: translateY(-50%);
}
.stayery-hero-subtitle {
    color: ${ink_soft};
    font-size: 1.05rem;
    margin-top: 0.2rem;
    max-width: 720px;
}
</style>
""")


def inject_brand_css() -> None:
    """Render the CSS block. Call once near the top of every page."""
    css = _BRAND_CSS.safe_substitute(_brand_tokens())
    st.markdown(css, unsafe_allow_html=True)


def hero(eyebrow: str, title: str, subtitle: str | None = None) -> None:
    """Editorial block"""
    sub = f'<div class="stayery-hero-subtitle">{subtitle}</div>' if subtitle else ""
    st.markdown(
        f'<div class="stayery-hero">'
        f'<div class="stayery-hero-eyebrow">{eyebrow}</div>'
        f'<h1 style="margin-top:0">{title}</h1>'
        f"{sub}</div>",
        unsafe_allow_html=True,
    )


def sync_snapshot_override() -> str | None:
    """Session-Snapshot-Override zurückgeben (KEINE env-Mutation mehr).

    Der Override lebt rein im ``st.session_state`` und wird von
    ``cached_data._resolved_snapshot_dir()`` gelesen (Review A12.8). Vorher
    wurde hier ``os.environ`` beschrieben - prozessweit, also für ALLE
    gleichzeitigen User des Servers. Funktion bleibt als Shim erhalten,
    weil alle Seiten sie aufrufen.
    """
    return st.session_state.get("snapshot_dir_override")
