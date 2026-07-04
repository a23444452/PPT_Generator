"""Styles：視覺風格與色盤目錄，移植自 ppt-master（MIT License）。"""

from app.styles.catalog import (
    StyleCatalogError,
    clear_cache,
    list_palettes,
    list_styles,
    load_palette,
    load_style,
)

__all__ = [
    "StyleCatalogError",
    "clear_cache",
    "list_palettes",
    "list_styles",
    "load_palette",
    "load_style",
]
