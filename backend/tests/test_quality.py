"""SVG 品質檢查（app.generation.quality）測試。"""

from app.generation.quality import EXPECTED_VIEWBOX, check_svg

VALID_SVG = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="{EXPECTED_VIEWBOX}">
  <rect x="0" y="0" width="1280" height="720" fill="#ffffff"/>
  <text x="40" y="100" font-size="24">Hello</text>
</svg>"""


def test_valid_svg_passes():
    assert check_svg(VALID_SVG) == []


def test_bad_xml_reports_xml_error():
    problems = check_svg("<svg><rect></svg>")  # 標籤未正確配對
    assert len(problems) == 1
    assert "XML" in problems[0]


def test_non_svg_root_is_reported():
    problems = check_svg('<div xmlns="http://www.w3.org/2000/svg"></div>')
    assert any("svg" in p for p in problems)


def test_missing_viewbox_is_reported():
    svg = '<svg xmlns="http://www.w3.org/2000/svg"></svg>'
    problems = check_svg(svg)
    assert any("viewBox" in p for p in problems)


def test_wrong_viewbox_is_reported():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 600"></svg>'
    problems = check_svg(svg)
    assert any("viewBox" in p for p in problems)


def test_text_overflow_reports_estimated_pixels():
    # font-size 40，英文字元約 0.6 倍寬 => 24 字 * 40 * 0.6 = 576px 起算於 x=800
    # x(800) + 576 = 1376 > 1280（viewBox 寬）
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="{EXPECTED_VIEWBOX}">
  <text x="800" y="100" font-size="40">This text is way too long!!!</text>
</svg>"""
    problems = check_svg(svg)
    assert len(problems) == 1
    assert "超出右緣" in problems[0]
    assert "This text i" not in problems[0]  # 只取前 10 字
    assert "This text " in problems[0]
    assert "px" in problems[0]


def test_external_image_href_is_reported():
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="{EXPECTED_VIEWBOX}">
  <image href="https://example.com/pic.png" x="0" y="0" width="100" height="100"/>
</svg>"""
    problems = check_svg(svg)
    assert any("image" in p or "href" in p for p in problems)


def test_local_asset_image_href_passes():
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="{EXPECTED_VIEWBOX}">
  <image href="assets/pic.png" x="0" y="0" width="100" height="100"/>
</svg>"""
    assert check_svg(svg) == []


def test_data_uri_image_href_passes():
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="{EXPECTED_VIEWBOX}">
  <image href="data:image/png;base64,iVBORw0KGgo=" x="0" y="0" width="10" height="10"/>
</svg>"""
    assert check_svg(svg) == []


# ---------- 補充：計畫描述外的邊界情況 ----------


def test_tspan_text_counted_with_parent_x_and_font_size():
    # tspan 沒有自己的 x/font-size，應沿用父層 text 的 x=800, font-size=40
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="{EXPECTED_VIEWBOX}">
  <text x="800" y="100" font-size="40"><tspan>This text is way too long!!!</tspan></text>
</svg>"""
    problems = check_svg(svg)
    assert len(problems) == 1
    assert "超出右緣" in problems[0]


def test_tspan_own_x_and_font_size_override_parent():
    # tspan 自帶 x/font-size：父層 text x=0 不會溢出，但 tspan 自己的 x=1200 加寬度會溢出
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="{EXPECTED_VIEWBOX}">
  <text x="0" y="100" font-size="16"><tspan x="1200" font-size="40">Overflowing!!</tspan></text>
</svg>"""
    problems = check_svg(svg)
    assert len(problems) == 1
    assert "超出右緣" in problems[0]


def test_font_size_missing_uses_default_16():
    # 沒有 font-size，預設 16；20 字 * 16 * 0.6 = 192，x=1200 => 1392 > 1280 溢出
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="{EXPECTED_VIEWBOX}">
  <text x="1200" y="100">abcdefghijklmnopqrst</text>
</svg>"""
    problems = check_svg(svg)
    assert len(problems) == 1
    assert "超出右緣" in problems[0]


def test_font_size_with_px_suffix_is_parsed():
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="{EXPECTED_VIEWBOX}">
  <text x="800" y="100" font-size="40px">This text is way too long!!!</text>
</svg>"""
    problems = check_svg(svg)
    assert len(problems) == 1
    assert "超出右緣" in problems[0]


def test_font_size_from_style_attribute_is_parsed():
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="{EXPECTED_VIEWBOX}">
  <text x="800" y="100" style="font-size:40px;fill:#000">This text is way too long!!!</text>
</svg>"""
    problems = check_svg(svg)
    assert len(problems) == 1
    assert "超出右緣" in problems[0]


def test_cjk_text_estimated_as_full_width():
    # 10 個中文字 * font-size 40（全寬 1 倍）= 400，x=900 => 1300 > 1280 溢出
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="{EXPECTED_VIEWBOX}">
  <text x="900" y="100" font-size="40">這是一段測試用的中文文字喔</text>
</svg>"""
    problems = check_svg(svg)
    assert len(problems) == 1
    assert "超出右緣" in problems[0]


def test_xlink_href_namespace_is_checked():
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="{EXPECTED_VIEWBOX}">'
        f'<image xlink:href="http://evil.com/x.png" x="0" y="0" width="10" height="10"/>'
        f"</svg>"
    )
    problems = check_svg(svg)
    assert any("image" in p or "href" in p for p in problems)


def test_relative_parent_path_escape_is_reported():
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="{EXPECTED_VIEWBOX}">
  <image href="../secrets/x.png" x="0" y="0" width="10" height="10"/>
</svg>"""
    problems = check_svg(svg)
    assert any("image" in p or "href" in p for p in problems)


def test_absolute_local_path_is_reported():
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="{EXPECTED_VIEWBOX}">
  <image href="/etc/passwd" x="0" y="0" width="10" height="10"/>
</svg>"""
    problems = check_svg(svg)
    assert any("image" in p or "href" in p for p in problems)


def test_svg_without_namespace_is_still_recognized():
    """裸 SVG（無 xmlns）仍應能正確判斷 root tag 與跑完整檢查。"""
    svg = f'<svg viewBox="{EXPECTED_VIEWBOX}"><text x="40" y="100" font-size="24">Hi</text></svg>'
    assert check_svg(svg) == []


def test_multiple_problems_all_reported():
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 600">
  <image href="https://example.com/pic.png" x="0" y="0" width="10" height="10"/>
</svg>"""
    problems = check_svg(svg)
    assert len(problems) >= 2
