"""逐頁 SVG 生成（app.generation.slides）測試。"""

import json

import pytest

from app.generation.quality import EXPECTED_VIEWBOX
from app.generation.slides import generate_slides
from app.llm.base import LLMError
from app.store.project import create_project
from tests.conftest import FakeLLM

OUTLINE = {
    "slides": [
        {
            "index": 0,
            "title": "封面：Q2 營運回顧",
            "bullets": ["2026 年第二季"],
            "layout_hint": "cover",
            "assets": [],
        },
        {
            "index": 1,
            "title": "營收概況",
            "bullets": ["營收成長 12%"],
            "layout_hint": "chart",
            "assets": ["revenue.png"],
        },
        {
            "index": 2,
            "title": "結語",
            "bullets": ["謝謝聆聽"],
            "layout_hint": "closing",
            "assets": [],
        },
    ]
}


def _valid_svg(title: str, fill: str = "#123456") -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{EXPECTED_VIEWBOX}">'
        f'<rect x="0" y="0" width="1280" height="720" fill="{fill}"/>'
        f'<text x="40" y="100" font-size="24">{title}</text>'
        f"</svg>"
    )


def _fence(svg: str) -> str:
    return "這是我產生的投影片：\n```svg\n" + svg + "\n```\n"


def _overflow_svg() -> str:
    # font-size 40，24 個全形字 * 40px + x(800) 遠超過 1280 寬
    long_text = "字" * 24
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{EXPECTED_VIEWBOX}">'
        f'<text x="800" y="100" font-size="40">{long_text}</text>'
        f"</svg>"
    )


def _make_project(tmp_path, style_id="swiss-minimal", palette_id="cool-corporate"):
    project = create_project(tmp_path, "測試專案")
    (project.path / "assets" / "revenue.png").write_bytes(b"fake-png-bytes")
    (project.path / "outline.json").write_text(
        json.dumps(OUTLINE, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    project.data["style_id"] = style_id
    project.data["palette_id"] = palette_id
    project.data["stage"] = "outline"
    for slide in OUTLINE["slides"]:
        project.set_slide_status(slide["index"], "pending")
    project.save()
    return project


def test_generates_all_pending_slides(tmp_path):
    project = _make_project(tmp_path)
    llm = FakeLLM(
        [
            _fence(_valid_svg("封面：Q2 營運回顧")),
            _fence(_valid_svg("營收概況")),
            _fence(_valid_svg("結語")),
        ]
    )

    generate_slides(llm, project)

    assert len(llm.calls) == 3
    for i in range(3):
        svg_path = project.path / "svg_output" / f"slide_{i:03d}.svg"
        assert svg_path.is_file()

    assert [s["status"] for s in project.data["slides"]] == [
        "generated",
        "generated",
        "generated",
    ]
    assert project.data["stage"] == "generated"

    # project.json 也已落盤
    saved = json.loads((project.path / "project.json").read_text(encoding="utf-8"))
    assert saved["stage"] == "generated"

    # 每次 prompt 都含風格檔全文與該頁大綱（spec lock：每頁重帶）
    from app.styles.catalog import load_palette, load_style

    style_body = load_style("swiss-minimal")
    palette_body = load_palette("cool-corporate")
    for i, call in enumerate(llm.calls):
        prompt = call["messages"][0]["content"]
        assert style_body in prompt
        assert palette_body in prompt
        assert OUTLINE["slides"][i]["title"] in prompt
        for bullet in OUTLINE["slides"][i]["bullets"]:
            assert bullet in prompt


def test_resume_skips_generated(tmp_path):
    project = _make_project(tmp_path)
    project.set_slide_status(0, "generated")
    project.save()
    # 已經有一份舊檔（模擬先前中斷前寫過）
    (project.path / "svg_output" / "slide_000.svg").write_text(
        _valid_svg("封面：Q2 營運回顧"), encoding="utf-8"
    )

    llm = FakeLLM(
        [
            _fence(_valid_svg("營收概況")),
            _fence(_valid_svg("結語")),
        ]
    )

    generate_slides(llm, project)

    assert len(llm.calls) == 2
    assert project.data["slides"][0]["status"] == "generated"
    assert project.data["slides"][1]["status"] == "generated"
    assert project.data["slides"][2]["status"] == "generated"


def test_bad_svg_regenerated_with_error_feedback(tmp_path):
    project = _make_project(tmp_path)
    llm = FakeLLM(
        [
            _fence(_overflow_svg()),  # 第 0 頁第一次：溢出
            _fence(_valid_svg("封面：Q2 營運回顧")),  # 第 0 頁重生：合法
            _fence(_valid_svg("營收概況")),
            _fence(_valid_svg("結語")),
        ]
    )

    generate_slides(llm, project)

    assert len(llm.calls) == 4
    assert project.data["slides"][0]["status"] == "generated"

    # 第二次（重生）prompt 內含 quality 的錯誤訊息
    second_call_prompt = llm.calls[1]["messages"][0]["content"]
    assert "超出右緣" in second_call_prompt


def test_twice_bad_marks_failed_and_continues(tmp_path):
    project = _make_project(tmp_path)
    llm = FakeLLM(
        [
            _fence(_overflow_svg()),  # 第 0 頁第一次：壞
            _fence(_overflow_svg()),  # 第 0 頁重生：仍然壞
            _fence(_valid_svg("營收概況")),
            _fence(_valid_svg("結語")),
        ]
    )

    generate_slides(llm, project)  # 不應 raise

    assert len(llm.calls) == 4
    assert project.data["slides"][0]["status"] == "failed"
    assert project.data["slides"][0]["retries"] == 1
    assert project.data["slides"][1]["status"] == "generated"
    assert project.data["slides"][2]["status"] == "generated"
    assert not (project.path / "svg_output" / "slide_000.svg").is_file()
    assert project.data["stage"] == "generated"


def test_on_progress_callback_invoked_per_slide(tmp_path):
    project = _make_project(tmp_path)
    llm = FakeLLM(
        [
            _fence(_valid_svg("封面：Q2 營運回顧")),
            _fence(_valid_svg("營收概況")),
            _fence(_valid_svg("結語")),
        ]
    )
    progress_calls = []

    generate_slides(llm, project, on_progress=lambda i, status: progress_calls.append((i, status)))

    assert progress_calls == [(0, "generated"), (1, "generated"), (2, "generated")]


def test_on_progress_none_is_safe(tmp_path):
    project = _make_project(tmp_path)
    llm = FakeLLM([_fence(_valid_svg("封面：Q2 營運回顧"))])
    project.set_slide_status(1, "generated")
    project.set_slide_status(2, "generated")
    project.save()

    generate_slides(llm, project, on_progress=None)  # 不應丟例外

    assert project.data["slides"][0]["status"] == "generated"


def test_llm_error_propagates_and_stops(tmp_path):
    project = _make_project(tmp_path)

    class ErrorLLM:
        def __init__(self):
            self.calls = []

        def complete(self, messages, system="", max_tokens=4096):
            self.calls.append({"messages": messages, "system": system})
            raise LLMError("連線逾時", kind="network")

    llm = ErrorLLM()

    with pytest.raises(LLMError):
        generate_slides(llm, project)

    # 基礎設施錯誤不應被吞掉標記成 failed，且不應寫入 stage=generated
    assert project.data["slides"][0]["status"] == "pending"
    assert project.data["stage"] != "generated"


def test_extracts_svg_via_bare_tag_fallback_when_no_fence(tmp_path):
    project = _make_project(tmp_path)
    raw_no_fence = "這是我的想法：\n" + _valid_svg("封面：Q2 營運回顧") + "\n謝謝"
    llm = FakeLLM(
        [
            raw_no_fence,
            _fence(_valid_svg("營收概況")),
            _fence(_valid_svg("結語")),
        ]
    )

    generate_slides(llm, project)

    assert len(llm.calls) == 3
    svg_text = (project.path / "svg_output" / "slide_000.svg").read_text(encoding="utf-8")
    assert "<svg" in svg_text
    assert project.data["slides"][0]["status"] == "generated"


def test_previous_slide_summary_included_in_next_prompt(tmp_path):
    project = _make_project(tmp_path)
    llm = FakeLLM(
        [
            _fence(_valid_svg("封面：Q2 營運回顧", fill="#abcdef")),
            _fence(_valid_svg("營收概況")),
            _fence(_valid_svg("結語")),
        ]
    )

    generate_slides(llm, project)

    # 第 0 頁沒有前一頁摘要
    first_prompt = llm.calls[0]["messages"][0]["content"]
    assert "前一頁" not in first_prompt

    # 第 1 頁 prompt 內含前一頁（第 0 頁）的標題與主色摘要
    second_prompt = llm.calls[1]["messages"][0]["content"]
    assert "封面：Q2 營運回顧" in second_prompt
    assert "#abcdef" in second_prompt
