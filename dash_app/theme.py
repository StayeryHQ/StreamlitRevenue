# dash_app/theme.py
# Central brand styling for the Dash app - colours, fonts, Plotly defaults.
# Colour source is configs/stayery_brand.yaml, same as the overbooking tool.

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).resolve().parents[1] / "configs" / "stayery_brand.yaml"


@lru_cache(maxsize=1)
def _brand() -> dict:
    return yaml.safe_load(_CONFIG_PATH.read_text())


_core = _brand()["colors"]["core"]
_sup = _brand()["colors"]["supporting"]

# ---- Colours ---------------------------------------------------------------
YELLOW = _core["yellow"]
BLACK = _core["black"]
WHITE = _core["white"]
GREEN = _sup["green"]
ORANGE = _sup["orange"]
RED = _sup["red"]
BLUE = _sup["blue"]
PINK = _sup["pink"]
PURPLE = _sup["purple"]

# Neutral grey for previous-year / comparison series.
GREY = "#666666"
GRIDCOLOR = "#EEEEEE"

# Categorical series colours (brand order).
CATEGORICAL = [YELLOW, BLUE, GREEN, ORANGE, PINK, PURPLE, RED]

# Sequential scale for "more is more" heatmaps (revenue, counts).
HEAT_SCALE = [[0.0, WHITE], [0.5, YELLOW], [1.0, ORANGE]]
# Diverging scale for YoY deltas (negative = red, positive = green).
DIVERGING_SCALE = [[0.0, RED], [0.5, WHITE], [1.0, GREEN]]

# ---- Typography ------------------------------------------------------------
_typ = _brand()["typography"]
FONT_FAMILY = ", ".join([_typ["primary"], *_typ["primary_fallback"]])
HEADING_FONT_FAMILY = ", ".join([_typ["display"], *_typ["display_fallback"]])

# ---- dash-mantine-components theme -----------------------------------------
# primaryColor "dark" => controls render near-black; yellow stays an explicit
# accent so text-on-accent contrast is readable.
DMC_THEME = {
    "primaryColor": "dark",
    "defaultRadius": "md",
    "fontFamily": FONT_FAMILY,
    "fontFamilyMonospace": "SFMono-Regular, Menlo, monospace",
    "headings": {"fontFamily": HEADING_FONT_FAMILY, "fontWeight": "700"},
}

# ---- Stylesheets -----------------------------------------------------------
EXTERNAL_STYLESHEETS = [
    "https://cdn.jsdelivr.net/npm/bootswatch@5.3.3/dist/flatly/bootstrap.min.css",
    "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css",
]


# ---- Plotly defaults -------------------------------------------------------
def brand_figure(fig):
    """Apply the brand font + a clean white layout to a Plotly figure in place."""
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
