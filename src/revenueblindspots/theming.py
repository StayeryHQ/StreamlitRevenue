"""Stayery brand theming for matplotlib.

Loads the brand spec from ``configs/stayery_brand.yaml`` and applies matplotlib
styles. Font selection uses a fallback chain so charts render acceptably on
machines without the proprietary Stayery fonts installed.

Usage::

    from revenueblindspots.theming import apply_stayery_style, categorical_palette
    apply_stayery_style()
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import matplotlib as mpl
import yaml

from .helpers import CONFIGS_DIR

# Path to the brand spec - co-located with all other configs.
_BRAND_CONFIG: Path = CONFIGS_DIR / "stayery_brand.yaml"


@lru_cache(maxsize=1)
def load_brand_config() -> dict[str, Any]:
    """Load the Stayery brand spec from YAML (cached per process)."""
    with _BRAND_CONFIG.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _color_lookup() -> dict[str, str]:
    """Flatten the {core, supporting} palettes into one name->hex dict."""
    cfg = load_brand_config()
    return {**cfg["colors"]["core"], **cfg["colors"]["supporting"]}


def color(name: str) -> str:
    """Return a single Stayery color hex by its name.

    Args:
        name: One of black, white, yellow, pink, green, orange, red, blue, purple.
    """
    lookup = _color_lookup()
    if name not in lookup:
        raise KeyError(f"Unknown Stayery color '{name}'. Known: {sorted(lookup)}")
    return lookup[name]


def categorical_palette(n: int | None = None) -> list[str]:
    """Return the Stayery categorical palette as a list of hex strings.

    Args:
        n: Optional number of colors to return.

    Returns:
        Hex strings in canonical order from ``configs/stayery_brand.yaml``.
    """
    cfg = load_brand_config()
    lookup = _color_lookup()
    palette = [lookup[name] for name in cfg["categorical_order"]]
    if n is None:
        return palette
    if n <= len(palette):
        return palette[:n]
    return [palette[i % len(palette)] for i in range(n)]


def diverging_triplet() -> tuple[str, str, str]:
    """Return (negative, neutral, positive) hex triplet for diverging encodings."""
    cfg = load_brand_config()
    lookup = _color_lookup()
    div = cfg["diverging"]
    return lookup[div["negative"]], lookup[div["neutral"]], lookup[div["positive"]]


def apply_stayery_style() -> None:
    """Apply the Stayery matplotlib style globally for the current session."""
    cfg = load_brand_config()
    lookup = _color_lookup()

    primary_chain = [cfg["typography"]["primary"]] + cfg["typography"][
        "primary_fallback"
    ]  # concatenates two lists to result in a list of strings
    palette = categorical_palette()

    mpl.rcParams.update(
        {
            # ---- Typography ------------------------------------------------
            "font.family": "sans-serif",
            "font.sans-serif": primary_chain,
            "font.size": 11,
            "axes.titlesize": 14,
            "axes.titleweight": "bold",
            "axes.labelsize": 11,
            "axes.labelweight": "regular",
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "legend.fontsize": 10,
            "figure.titlesize": 16,
            "figure.titleweight": "bold",
            # ---- Color cycle -----------------------------------------------
            "axes.prop_cycle": mpl.cycler(color=palette),
            # ---- Backgrounds (premium, clean) ------------------------------
            "figure.facecolor": lookup["white"],
            "axes.facecolor": lookup["white"],
            "savefig.facecolor": lookup["white"],
            # ---- Spines (minimal: only bottom & left) ----------------------
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.edgecolor": lookup["black"],
            "axes.linewidth": 1.0,
            # ---- Grid (subtle horizontal only) -----------------------------
            "axes.grid": True,
            "axes.grid.axis": "y",
            "grid.color": "#E5E5E5",
            "grid.linewidth": 0.6,
            "grid.linestyle": "-",
            # ---- Ticks (quiet) ---------------------------------------------
            "xtick.color": lookup["black"],
            "ytick.color": lookup["black"],
            "xtick.direction": "out",
            "ytick.direction": "out",
            # ---- Lines & markers -------------------------------------------
            "lines.linewidth": 2.0,
            "lines.markersize": 6,
            # ---- Figure size & resolution ----------------------------------
            "figure.figsize": (10, 5.5),
            "figure.dpi": 110,
            "savefig.dpi": 200,
            "savefig.bbox": "tight",
        }
    )
