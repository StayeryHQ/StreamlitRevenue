# streamlit_app/components/plotly_theme.py
# Zentrales Brand-Styling für PLOTLY-Figuren - 1:1 portiert aus
# OverbookingAnalyse/dash_app/theme.py (der verbindliche Grafik-Standard für
# die schrittweise Plotly-/Dash-Migration: Schriftart, Farben, Margins,
# Legende, Grid). Quelle der Farbwerte ist dieselbe configs/stayery_brand.yaml
# wie für matplotlib (theming.py) und die Dash-App.

from __future__ import annotations

from revenueblindspots.theming import load_brand_config

_brand = load_brand_config()
_core = _brand["colors"]["core"]
_sup = _brand["colors"]["supporting"]

# ---- Farben (identisch zur Dash-App) ---------------------------------------
YELLOW = _core["yellow"]
BLACK = _core["black"]
WHITE = _core["white"]
GREEN = _sup["green"]
ORANGE = _sup["orange"]
RED = _sup["red"]
BLUE = _sup["blue"]
PINK = _sup["pink"]
PURPLE = _sup["purple"]

# Kategoriale Serien-Farben in Brand-Reihenfolge (wie dash_app/theme.py).
CATEGORICAL = [YELLOW, BLUE, GREEN, ORANGE, PINK, PURPLE, RED]

# ---- Typografie -------------------------------------------------------------
_typ = _brand.get("typography", {})
FONT_FAMILY = ", ".join(
    [_typ.get("primary", "Neue Haas Grotesk Display Pro"),
     *_typ.get("primary_fallback", ["Helvetica Neue", "Helvetica", "Arial", "sans-serif"])]
)
HEADING_FONT_FAMILY = ", ".join(
    [_typ.get("display", "Topol"),
     *_typ.get("display_fallback", ["Neue Haas Grotesk Display Pro", "Arial", "sans-serif"])]
)

# Neutral-Grau für Vorjahres-/Vergleichsserien (Brand-Neutral Grey).
GREY = "#666666"
GRIDCOLOR = "#EEEEEE"


def brand_figure(fig):
    """Brand-Font + cleanes weißes Layout auf eine Plotly-Figur anwenden (in place).

    Wörtlich übernommen aus ``OverbookingAnalyse/dash_app/theme.py`` - damit
    Revenue- und Overbooking-Grafiken identisch aussehen (Vorgabe für die
    Dash-Migration).
    """
    fig.update_layout(
        font=dict(family=FONT_FAMILY, color=BLACK, size=13),
        paper_bgcolor=WHITE,
        plot_bgcolor=WHITE,
        margin=dict(l=50, r=20, t=40, b=40),
        colorway=CATEGORICAL,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    fig.update_xaxes(showgrid=True, gridcolor=GRIDCOLOR, zeroline=False)
    fig.update_yaxes(showgrid=True, gridcolor=GRIDCOLOR, zeroline=False)
    return fig


# Einheitliche st.plotly_chart-Config (kein Plotly-Logo, aufgeräumte Modebar).
PLOTLY_CONFIG = {
    "displaylogo": False,
    "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"],
}
