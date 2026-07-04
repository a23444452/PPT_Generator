"""風格與色盤目錄（app.styles.catalog）測試。"""

import pytest

from app.styles.catalog import (
    clear_cache,
    list_palettes,
    list_styles,
    load_palette,
    load_style,
)


@pytest.fixture(autouse=True)
def _clear_cache_around_test():
    """避免測試間快取互相污染（尤其是自訂 base_dir 的測試）。"""
    clear_cache()
    yield
    clear_cache()


# ---------- 視覺風格 ----------


def test_list_styles_returns_four_entries_with_id_and_name_zh():
    styles = list_styles()
    assert len(styles) == 4
    ids = {s["id"] for s in styles}
    assert ids == {"swiss-minimal", "soft-rounded", "dark-tech", "editorial"}
    for s in styles:
        assert s["id"]
        assert s["name_zh"]
        assert s["tagline_zh"]


def test_load_style_returns_full_text_body():
    text = load_style("swiss-minimal")
    assert "# Visual style: swiss-minimal" in text
    assert "Strict Swiss-grid discipline" in text
    # frontmatter 區塊本身不應混入回傳的正文
    assert not text.startswith("---")


def test_load_style_unknown_id_raises_key_error():
    with pytest.raises(KeyError):
        load_style("does-not-exist")


# ---------- 色盤 ----------


def test_list_palettes_returns_three_entries_with_id_and_name_zh():
    palettes = list_palettes()
    assert len(palettes) == 3
    ids = {p["id"] for p in palettes}
    assert ids == {"cool-corporate", "editorial-classic", "mono-ink"}
    for p in palettes:
        assert p["id"]
        assert p["name_zh"]
        assert p["tagline_zh"]


def test_load_palette_returns_full_text_body():
    text = load_palette("cool-corporate")
    assert "# Palette: cool-corporate" in text
    assert not text.startswith("---")


def test_load_palette_unknown_id_raises_key_error():
    with pytest.raises(KeyError):
        load_palette("does-not-exist")


# ---------- 自訂 base_dir 與快取 ----------


def test_custom_base_dir_is_isolated_from_default(tmp_path):
    styles_dir = tmp_path / "styles" / "visual"
    styles_dir.mkdir(parents=True)
    (styles_dir / "custom-style.md").write_text(
        "---\n"
        "id: custom-style\n"
        "name_zh: 測試風格\n"
        "tagline_zh: 一個假的測試用風格\n"
        "---\n"
        "# Visual style: custom-style\n"
        "測試內容\n",
        encoding="utf-8",
    )
    palettes_dir = tmp_path / "styles" / "palettes"
    palettes_dir.mkdir(parents=True)

    styles = list_styles(base_dir=tmp_path)
    assert len(styles) == 1
    assert styles[0]["id"] == "custom-style"
    assert styles[0]["name_zh"] == "測試風格"

    text = load_style("custom-style", base_dir=tmp_path)
    assert "測試內容" in text

    # 預設目錄不受自訂 base_dir 影響
    default_styles = list_styles()
    assert len(default_styles) == 4
