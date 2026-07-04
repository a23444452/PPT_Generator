"""大綱生成：呼叫 LLM 產生投影片大綱，驗證後寫入 outline.json / outline.md。

流程：組 prompt（含來源 md 全文、資產清單、風格與色盤全文）→ 呼叫 LLM →
解析回應中的 JSON → 手寫驗證 → 失敗重試一次（附上次錯誤原因）→ 成功後
落盤並更新 project 狀態。
"""

import json
from pathlib import Path

from app.llm.base import LLMProvider
from app.store.project import Project
from app.styles.catalog import load_palette, load_style

LAYOUT_HINTS = (
    "cover",
    "section",
    "bullets",
    "two-column",
    "table",
    "chart",
    "image",
    "closing",
)

_MAX_ATTEMPTS = 2
_MAX_TOKENS = 8192
_ERROR_EXCERPT_LEN = 500


class OutlineError(Exception):
    """大綱生成失敗（LLM 回應連續兩次無法解析或驗證失敗）。"""


def generate_outline(
    llm: LLMProvider, project: Project, style_id: str, palette_id: str
) -> dict:
    """呼叫 LLM 產生大綱，驗證成功後寫入 outline.json/outline.md 並更新 project。

    失敗（JSON 解析或內容驗證出錯）時重試一次，附上前一次的錯誤原因；
    兩次都失敗則 raise OutlineError。
    """
    md_text = _collect_md_text(project.path / "md")
    asset_names = _collect_asset_names(project.path / "assets")
    style_body = load_style(style_id)
    palette_body = load_palette(palette_id)

    base_prompt = _build_prompt(md_text, asset_names, style_body, palette_body)

    last_error: str | None = None
    last_raw: str | None = None
    outline: dict | None = None

    for _attempt in range(_MAX_ATTEMPTS):
        prompt = base_prompt
        if last_error is not None:
            prompt = _build_retry_prompt(base_prompt, last_raw or "", last_error)

        raw = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system="你是一位專業的簡報策略師。",
            max_tokens=_MAX_TOKENS,
        )

        try:
            parsed = _parse_json_response(raw)
            outline = _validate_outline(parsed, asset_names)
            break
        except OutlineError as exc:
            last_error = str(exc)
            last_raw = raw
            continue

    if outline is None:
        raise OutlineError(
            f"大綱生成失敗（已重試 {_MAX_ATTEMPTS} 次）：{last_error}"
        )

    _write_outline_files(project.path, outline)

    project.data["stage"] = "outline"
    for slide in outline["slides"]:
        project.set_slide_status(slide["index"], "pending")
    project.save()

    return outline


# ---------- Prompt 組裝 ----------


def _collect_md_text(md_dir: Path) -> str:
    if not md_dir.is_dir():
        return "（無來源文件）"

    parts = []
    for path in sorted(md_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        parts.append(f"## {path.name}\n\n{text}")
    if not parts:
        return "（無來源文件）"
    return "\n\n".join(parts)


def _collect_asset_names(assets_dir: Path) -> list[str]:
    if not assets_dir.is_dir():
        return []
    return sorted(p.name for p in assets_dir.iterdir() if p.is_file())


def _build_prompt(
    md_text: str, asset_names: list[str], style_body: str, palette_body: str
) -> str:
    assets_list = "\n".join(f"- {name}" for name in asset_names) or "（無可用資產）"
    layout_hints = "、".join(LAYOUT_HINTS)

    return f"""你是一位專業的簡報策略師，請根據以下來源文件與視覺規範，設計一份簡報大綱。

# 來源文件內容

{md_text}

# 可用資產清單（assets/ 目錄）

{assets_list}

# 視覺風格規範

{style_body}

# 色盤規範

{palette_body}

# 輸出要求

請用繁體中文撰寫，並嚴格依照以下規則輸出：

1. 只能輸出「唯一一個」```json 圍籬（fence）區塊，內容為 JSON 物件，格式如下：

```json
{{"slides": [{{"index": 0, "title": "封面：...", "bullets": ["..."], "layout_hint": "cover", "assets": []}}]}}
```

2. 每一頁投影片都必須包含 `index`（從 0 開始依序遞增的整數）、`title`（非空字串）、
   `bullets`（字串陣列）、`layout_hint`（必須是以下其中之一：{layout_hints}）、
   `assets`（字串陣列，可為空；若引用資產，檔名必須完全符合上方資產清單中的檔名）。
3. 除了該唯一的 ```json 圍籬區塊外，不要輸出其他多餘文字。
"""


def _build_retry_prompt(base_prompt: str, last_raw: str, last_error: str) -> str:
    excerpt = last_raw[:_ERROR_EXCERPT_LEN]
    return f"""{base_prompt}

# 上一次回應有誤，請修正

你上一次的回應無法通過驗證，錯誤原因如下：

{last_error}

你上一次回應的前 {_ERROR_EXCERPT_LEN} 字（供參考，請勿重複相同錯誤）：

{excerpt}

請重新輸出正確的大綱，仍須遵守前述所有輸出要求。
"""


# ---------- 解析 ----------


def _parse_json_response(raw: str) -> dict:
    """找第一個 ```json fence；找不到則 fallback 找第一個 `{` 到最後一個 `}`。"""
    fence_json = _extract_json_fence(raw)
    candidate = fence_json if fence_json is not None else _extract_brace_fallback(raw)

    if candidate is None:
        raise OutlineError("回應中找不到任何 JSON 內容")

    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise OutlineError(f"JSON 解析失敗：{exc}") from exc


def _extract_json_fence(raw: str) -> str | None:
    marker = "```json"
    start = raw.find(marker)
    if start == -1:
        return None
    start += len(marker)
    end = raw.find("```", start)
    if end == -1:
        return None
    return raw[start:end].strip()


def _extract_brace_fallback(raw: str) -> str | None:
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    return raw[start : end + 1].strip()


# ---------- 驗證 ----------


def _validate_outline(parsed: dict, asset_names: list[str]) -> dict:
    if not isinstance(parsed, dict):
        raise OutlineError("頂層內容必須是 JSON 物件")

    slides = parsed.get("slides")
    if not isinstance(slides, list) or len(slides) == 0:
        raise OutlineError("缺少 slides 欄位，或 slides 為空清單")

    asset_set = set(asset_names)
    validated_slides = []

    for i, slide in enumerate(slides):
        if not isinstance(slide, dict):
            raise OutlineError(f"第 {i} 頁不是合法的物件")

        title = slide.get("title")
        if not isinstance(title, str) or not title.strip():
            raise OutlineError(f"第 {i} 頁缺少非空的 title 欄位")

        bullets = slide.get("bullets")
        if not isinstance(bullets, list) or not all(
            isinstance(b, str) for b in bullets
        ):
            raise OutlineError(f"第 {i} 頁的 bullets 必須是字串陣列")

        layout_hint = slide.get("layout_hint")
        if layout_hint not in LAYOUT_HINTS:
            raise OutlineError(
                f"第 {i} 頁的 layout_hint「{layout_hint}」不合法，"
                f"必須是以下其中之一：{'、'.join(LAYOUT_HINTS)}"
            )

        assets = slide.get("assets", [])
        if not isinstance(assets, list) or not all(isinstance(a, str) for a in assets):
            raise OutlineError(f"第 {i} 頁的 assets 必須是字串陣列")

        for asset_name in assets:
            if asset_name not in asset_set:
                raise OutlineError(
                    f"第 {i} 頁引用了不存在的資產檔名：「{asset_name}」"
                )

        validated_slides.append(
            {
                "title": title,
                "bullets": bullets,
                "layout_hint": layout_hint,
                "assets": assets,
            }
        )

    # index 由 LLM 給或沒給都不算驗證錯誤：一律依 slides 陣列順序重新編號。
    for idx, slide in enumerate(validated_slides):
        slide["index"] = idx

    return {"slides": validated_slides}


# ---------- 落盤 ----------


def _write_outline_files(project_path: Path, outline: dict) -> None:
    outline_json_path = project_path / "outline.json"
    outline_json_path.write_text(
        json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    outline_md_path = project_path / "outline.md"
    outline_md_path.write_text(_render_outline_md(outline), encoding="utf-8")


def _render_outline_md(outline: dict) -> str:
    lines = ["# 簡報大綱\n"]
    for slide in outline["slides"]:
        lines.append(f"## {slide['index'] + 1}. {slide['title']}")
        lines.append(f"（layout: {slide['layout_hint']}）\n")
        for bullet in slide["bullets"]:
            lines.append(f"- {bullet}")
        if slide["assets"]:
            lines.append("")
            lines.append(f"資產：{', '.join(slide['assets'])}")
        lines.append("")
    return "\n".join(lines)
