"""SVG 品質檢查：純函式，供 Task 8 逐頁生成後呼叫，問題清單會直接餵回 LLM 重生 prompt。

檢查項目：
1. XML 可解析（xml.etree）且根元素為 svg。
2. 有 viewBox 且等於 EXPECTED_VIEWBOX（"0 0 1280 720"）。
3. 文字溢出啟發式：估算每個 <text>（含 <tspan>）的寬度，x + 估寬 超出 viewBox 寬度即回報。
4. 禁用元素：<image> 的 href／xlink:href 必須是 assets/ 相對路徑或 data URI，防止外連。

因此訊息措辭刻意具體（哪個元素、超出多少 px），方便 LLM 依訊息重生。
"""

import re
from xml.etree import ElementTree as ET

EXPECTED_VIEWBOX = "0 0 1280 720"
DEFAULT_FONT_SIZE = 16.0
_TEXT_EXCERPT_LEN = 10

_SVG_NS = "http://www.w3.org/2000/svg"
_XLINK_NS = "http://www.w3.org/1999/xlink"

# 全形字元判定：基本漢字區 + 全形標點兩段。
_CJK_PATTERN = re.compile(
    "["
    "一-鿿"  # 一-鿿：基本漢字區
    "　-〿"  # 　-〿：全形標點（CJK Symbols and Punctuation）
    "＀-￯"  # ＀-￯：全形字元與半形片假名區
    "]"
)

# 收緊為「整數或單一小數點」且錨定結尾（僅允許可選 px 單位），
# 讓 "40.5.5px" 這類畸形值整體匹配失敗而走 fallback，而非部分解析。
_FONT_SIZE_ATTR_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:px)?\s*$")
_FONT_SIZE_STYLE_RE = re.compile(r"font-size\s*:\s*(\d+(?:\.\d+)?)\s*(?:px)?\s*(?:;|$)")


def check_svg(svg_text: str) -> list[str]:
    """回傳問題清單（空 = 通過）。"""
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError as exc:
        return [f"XML 解析失敗：{exc}"]

    problems: list[str] = []

    if _local_name(root.tag) != "svg":
        problems.append(f"根元素應為 svg，實際為「{_local_name(root.tag)}」")

    viewbox_problem = _check_viewbox(root)
    if viewbox_problem is not None:
        problems.append(viewbox_problem)

    problems.extend(_check_text_overflow(root))
    problems.extend(_check_image_href(root))

    return problems


# ---------- 根元素 / viewBox ----------


def _local_name(tag: str) -> str:
    """去除 namespace 前綴（"{http://www.w3.org/2000/svg}svg" -> "svg"）。"""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def _check_viewbox(root: ET.Element) -> str | None:
    viewbox = root.get("viewBox")
    if viewbox is None:
        return f"缺少 viewBox 屬性（應為「{EXPECTED_VIEWBOX}」）"
    if viewbox.strip() != EXPECTED_VIEWBOX:
        return f"viewBox 應為「{EXPECTED_VIEWBOX}」，實際為「{viewbox}」"
    return None


def _viewbox_width(root: ET.Element) -> float:
    viewbox = root.get("viewBox")
    if viewbox is None:
        return float(EXPECTED_VIEWBOX.split()[2])
    parts = viewbox.split()
    if len(parts) != 4:
        return float(EXPECTED_VIEWBOX.split()[2])
    try:
        return float(parts[2])
    except ValueError:
        return float(EXPECTED_VIEWBOX.split()[2])


# ---------- 文字溢出 ----------


def _parse_font_size(elem: ET.Element, inherited: float) -> float:
    """取得元素自身的 font-size；取不到或無法解析則回傳繼承值（與 _parse_x 行為對稱）。

    已知限制：僅支援純數字＋可選 px 單位（"24"、"24px"、"24.5px"）；
    em/%/科學記號等其他寫法會匹配失敗而走 fallback（inherited/預設值）。
    輸入來自不可信的 LLM 輸出，任何畸形值都不得拋例外。
    """
    attr = elem.get("font-size")
    if attr is not None:
        match = _FONT_SIZE_ATTR_RE.match(attr.strip())
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass  # 防禦性保底：regex 已保證格式，仍不讓畸形值炸掉檢查

    style = elem.get("style")
    if style:
        match = _FONT_SIZE_STYLE_RE.search(style)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass

    return inherited


def _parse_x(elem: ET.Element, inherited: float) -> float:
    x_attr = elem.get("x")
    if x_attr is None:
        return inherited
    try:
        return float(x_attr.strip())
    except ValueError:
        return inherited


def _estimate_text_width(text: str, font_size: float) -> float:
    width = 0.0
    for ch in text:
        if _CJK_PATTERN.match(ch):
            width += font_size
        else:
            width += font_size * 0.6
    return width


def _check_text_overflow(root: ET.Element) -> list[str]:
    problems: list[str] = []
    viewbox_width = _viewbox_width(root)

    for text_elem in _iter_elements_by_local_name(root, "text"):
        # text-anchor="middle"/"end" 時，x 並非左緣起點，估算會偏保守（已知限制，MVP 不精算）。
        text_x = _parse_x(text_elem, 0.0)
        text_font_size = _parse_font_size(text_elem, DEFAULT_FONT_SIZE)

        # text 自身的直接文字內容（不含 tspan）。
        if text_elem.text and text_elem.text.strip():
            problem = _check_segment_overflow(
                text_elem.text, text_x, text_font_size, viewbox_width
            )
            if problem:
                problems.append(problem)

        for tspan in _iter_elements_by_local_name(text_elem, "tspan"):
            tspan_x = _parse_x(tspan, text_x)
            tspan_font_size = _parse_font_size(tspan, text_font_size)
            content = "".join(tspan.itertext())
            if content.strip():
                problem = _check_segment_overflow(
                    content, tspan_x, tspan_font_size, viewbox_width
                )
                if problem:
                    problems.append(problem)

    return problems


def _check_segment_overflow(
    text: str, x: float, font_size: float, viewbox_width: float
) -> str | None:
    estimated_width = _estimate_text_width(text, font_size)
    right_edge = x + estimated_width
    if right_edge > viewbox_width:
        overflow_px = round(right_edge - viewbox_width)
        excerpt = text[:_TEXT_EXCERPT_LEN]
        return f"text「{excerpt}」超出右緣 {overflow_px}px"
    return None


# ---------- image href 檢查 ----------


def _check_image_href(root: ET.Element) -> list[str]:
    problems: list[str] = []
    for image_elem in _iter_elements_by_local_name(root, "image"):
        href = image_elem.get("href")
        if href is None:
            href = image_elem.get(f"{{{_XLINK_NS}}}href")
        if href is None:
            problems.append("image 元素缺少 href／xlink:href 屬性")
            continue

        if not _is_allowed_href(href):
            problems.append(f"image 的 href「{href}」不合法，只允許 assets/ 相對路徑或 data URI")

    return problems


def _is_allowed_href(href: str) -> bool:
    """格式白名單檢查（assets/ 前綴或 data URI），非路徑安全邊界；
    任何實際讀檔的消費者（如 Task 9 匯出）必須自行做路徑正規化。"""
    href = href.strip()
    if href.startswith("data:"):
        return True
    if href.startswith("assets/"):
        return True
    return False


# ---------- 共用工具 ----------


def _iter_elements_by_local_name(root: ET.Element, local_name: str):
    """遞迴尋找子孫元素，容忍有無 namespace 前綴兩種情況。"""
    for elem in root.iter():
        if elem is root:
            continue
        if _local_name(elem.tag) == local_name:
            yield elem
