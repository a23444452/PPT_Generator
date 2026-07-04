"""逐頁 SVG 生成：讀 outline.json 逐頁呼叫 LLM 產生 SVG，落盤並更新 project 狀態。

流程：逐頁組 prompt（該頁大綱＋風格全文＋色盤全文，每頁完整重帶＝spec lock；
另附前一頁摘要維持連貫）→ 呼叫 LLM → 抽取 SVG → check_svg 檢查品質 →
通過寫檔並標記 generated；不通過帶問題清單重生一次，仍失敗則標記 failed
繼續下一頁（函式本身不 raise）。

錯誤語意的區分很重要：
- 內容品質問題（check_svg 回報的問題清單）視為「這頁本身有救」，
  重生一次；兩次都不過就記 failed，繼續處理下一頁。
- LLMError（網路逾時、認證失敗等基礎設施錯誤）代表呼叫本身就打不通，
  重試同一頁也無濟於事，因此直接往上 raise，交由 API 層決定如何呈現
  給使用者（例如顯示錯誤並允許稍後重新呼叫 generate_slides 續跑）。

續跑語意：呼叫端可能在任何頁之間中斷後重新呼叫本函式；已是 generated
狀態的頁會被跳過，只處理 pending／failed 的頁。
"""

import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree as ET

from app.generation.quality import EXPECTED_VIEWBOX, check_svg
from app.llm.base import LLMProvider
from app.store.project import Project
from app.styles.catalog import load_palette, load_style

_MAX_ATTEMPTS = 2
_MAX_TOKENS = 8192

OnProgress = Callable[[int, str], None]


def generate_slides(
    llm: LLMProvider, project: Project, on_progress: OnProgress | None = None
) -> None:
    """逐頁生成 SVG，寫入 svg_output/slide_{i:03d}.svg 並更新 project 狀態。

    已是 generated 狀態的頁會跳過（續跑）。每頁最多嘗試 2 次（第一次失敗帶
    問題清單重生 1 次），仍失敗則標記該頁 failed 並繼續下一頁；函式本身
    不會因內容品質問題而 raise。LLMError（基礎設施錯誤）例外：直接往上拋。
    """
    outline = _load_outline(project.path)
    style_body = load_style(project.data["style_id"])
    palette_body = load_palette(project.data["palette_id"])

    svg_output_dir = project.path / "svg_output"
    svg_output_dir.mkdir(parents=True, exist_ok=True)

    previous_summary: str | None = None

    for slide in outline["slides"]:
        index = slide["index"]
        status = _slide_status(project, index)

        if status == "generated":
            previous_summary = _summary_from_existing(svg_output_dir, slide)
            continue

        svg_text, success = _generate_one_slide(
            llm, slide, style_body, palette_body, previous_summary
        )

        if success:
            _write_svg(svg_output_dir, index, svg_text)
            project.set_slide_status(index, "generated")
            previous_summary = _build_summary(slide, svg_text)
        else:
            project.set_slide_status(index, "failed")
            previous_summary = None

        project.save()
        if on_progress is not None:
            on_progress(index, project.data["slides"][index]["status"])

    project.data["stage"] = "generated"
    project.save()


# ---------- 單頁生成（含一次帶錯誤重生） ----------


def _generate_one_slide(
    llm: LLMProvider,
    slide: dict,
    style_body: str,
    palette_body: str,
    previous_summary: str | None,
) -> tuple[str, bool]:
    base_prompt = _build_prompt(slide, style_body, palette_body, previous_summary)

    last_problems: list[str] = []
    last_svg_text = ""

    for _attempt in range(_MAX_ATTEMPTS):
        prompt = base_prompt
        if last_problems:
            prompt = _build_retry_prompt(base_prompt, last_svg_text, last_problems)

        raw = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system="你是一位專業的簡報視覺設計師，擅長以 SVG 製作投影片。",
            max_tokens=_MAX_TOKENS,
        )

        svg_text = _extract_svg(raw)
        if svg_text is None:
            last_problems = ["回應中找不到任何 <svg>...</svg> 內容"]
            last_svg_text = raw
            continue

        problems = check_svg(svg_text)
        if not problems:
            return svg_text, True

        last_problems = problems
        last_svg_text = svg_text

    return last_svg_text, False


# ---------- Prompt 組裝 ----------


def _build_prompt(
    slide: dict,
    style_body: str,
    palette_body: str,
    previous_summary: str | None,
) -> str:
    bullets_text = "\n".join(f"- {b}" for b in slide["bullets"]) or "（無條列內容）"
    assets_text = "\n".join(f"- assets/{a}" for a in slide["assets"]) or "（本頁無可用資產）"

    continuity_section = ""
    if previous_summary is not None:
        continuity_section = f"""
# 前一頁摘要（請維持視覺連貫）

{previous_summary}
"""

    return f"""你是一位專業的簡報視覺設計師，請根據以下大綱與視覺規範，為「這一頁」製作一張 SVG 投影片。

# 本頁大綱

- 標題：{slide['title']}
- 條列內容：
{bullets_text}
- layout_hint：{slide['layout_hint']}
- 可引用資產（僅限下列路徑，不可引用其他檔案）：
{assets_text}

# 視覺風格規範

{style_body}

# 色盤規範

{palette_body}
{continuity_section}
# 輸出要求

請用繁體中文撰寫畫面上的文字內容，並嚴格依照以下規則輸出：

1. 只能輸出「唯一一個」```svg 圍籬（fence）區塊，內容為完整的 `<svg>...</svg>` 原文。
2. 根元素必須有 `viewBox="{EXPECTED_VIEWBOX}"`。
3. 若本頁引用圖片，`<image>` 的 href／xlink:href 只能是上方「可引用資產」清單內的
   `assets/` 相對路徑，不可引用清單外的檔案或外部網址。
4. 除了該唯一的 ```svg 圍籬區塊外，不要輸出其他多餘文字。
"""


def _build_retry_prompt(base_prompt: str, last_svg_text: str, problems: list[str]) -> str:
    problems_text = "\n".join(f"- {p}" for p in problems)
    excerpt = last_svg_text[:500]
    return f"""{base_prompt}

# 上一次回應有誤，請修正

你上一次產生的 SVG 沒有通過品質檢查，問題如下：

{problems_text}

你上一次回應的前 500 字（供參考，請修正上述問題，不要重複相同錯誤）：

{excerpt}

請重新輸出正確的 SVG，仍須遵守前述所有輸出要求。
"""


# ---------- 前一頁摘要 ----------


_FILL_RE = re.compile(r'fill\s*=\s*"([^"]+)"')

# viewBox "0 0 1280 720" 的寬高，用於判定「覆蓋整頁的背景 rect」。
_VIEWBOX_WIDTH, _VIEWBOX_HEIGHT = EXPECTED_VIEWBOX.split()[2:4]


def _build_summary(slide: dict, svg_text: str) -> str:
    """組「前一頁的代表色（背景或首個著色元素）」摘要句供下一頁 prompt 使用。"""
    title = slide["title"]
    color = _representative_fill(svg_text)
    if color is not None:
        return f"前一頁標題為「{title}」，代表色（背景或首個著色元素）為 {color}。"
    return f"前一頁標題為「{title}」。"


def _representative_fill(svg_text: str) -> str | None:
    """取前一頁的代表色：優先找覆蓋整個 viewBox 的背景 <rect> 的 fill；
    找不到才退回文件中第一個 fill（首個著色元素）。啟發式，抓不到回 None。
    """
    background_fill = _background_rect_fill(svg_text)
    if background_fill is not None:
        return background_fill

    fill_match = _FILL_RE.search(svg_text)
    if fill_match:
        return fill_match.group(1)
    return None


def _background_rect_fill(svg_text: str) -> str | None:
    """找第一個覆蓋整個 viewBox 的 <rect>（x/y 為 0 或缺省、width/height
    等於 viewBox 寬高或 100%）並回傳其 fill；輸入來自 LLM，解析失敗回 None。
    """
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError:
        return None

    for elem in root.iter():
        tag = elem.tag.split("}", 1)[-1]  # 去除 namespace 前綴
        if tag != "rect":
            continue
        if not _covers_full_viewbox(elem):
            continue
        fill = elem.get("fill")
        if fill:
            return fill
    return None


def _covers_full_viewbox(rect: ET.Element) -> bool:
    def _is_zero(value: str | None) -> bool:
        if value is None:
            return True
        try:
            return float(value.strip()) == 0.0
        except ValueError:
            return False

    def _is_full(value: str | None, expected: str) -> bool:
        if value is None:
            return False
        value = value.strip()
        if value == "100%":
            return True
        try:
            return float(value) == float(expected)
        except ValueError:
            return False

    return (
        _is_zero(rect.get("x"))
        and _is_zero(rect.get("y"))
        and _is_full(rect.get("width"), _VIEWBOX_WIDTH)
        and _is_full(rect.get("height"), _VIEWBOX_HEIGHT)
    )


def _summary_from_existing(svg_output_dir: Path, slide: dict) -> str | None:
    """續跑時，若這頁已是 generated，從既有檔案重建摘要供下一頁使用。"""
    svg_path = svg_output_dir / f"slide_{slide['index']:03d}.svg"
    if not svg_path.is_file():
        return f"前一頁標題為「{slide['title']}」。"
    svg_text = svg_path.read_text(encoding="utf-8")
    return _build_summary(slide, svg_text)


# ---------- SVG 抽取 ----------


def _extract_svg(raw: str) -> str | None:
    """```svg fence 優先；找不到則 fallback 找 `<svg` 到 `</svg>`。"""
    fence_svg = _extract_svg_fence(raw)
    if fence_svg is not None:
        return fence_svg

    start = raw.find("<svg")
    if start == -1:
        return None
    end = raw.find("</svg>", start)
    if end == -1:
        return None
    end += len("</svg>")
    return raw[start:end].strip()


def _extract_svg_fence(raw: str) -> str | None:
    marker = "```svg"
    start = raw.find(marker)
    if start == -1:
        return None
    start += len(marker)
    end = raw.find("```", start)
    if end == -1:
        return None
    return raw[start:end].strip()


# ---------- 落盤 ----------


def _write_svg(svg_output_dir: Path, index: int, svg_text: str) -> None:
    target = svg_output_dir / f"slide_{index:03d}.svg"
    _atomic_write_text(target, svg_text)


def _atomic_write_text(target: Path, text: str) -> None:
    tmp_path = target.parent / f".{target.name}.{uuid4().hex}.tmp"
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, target)


# ---------- outline / project 狀態輔助 ----------


def _load_outline(project_path: Path) -> dict:
    raw = (project_path / "outline.json").read_text(encoding="utf-8")
    return json.loads(raw)


def _slide_status(project: Project, index: int) -> str:
    slides = project.data["slides"]
    if index < len(slides):
        return slides[index]["status"]
    return "pending"
