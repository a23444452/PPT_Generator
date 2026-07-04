"""大綱生成（app.generation.outline）測試。"""

import json

import pytest

from app.generation.outline import OutlineError, generate_outline, validate_outline
from app.store.project import create_project
from tests.conftest import FakeLLM

VALID_OUTLINE = {
    "slides": [
        {
            "index": 0,
            "title": "封面：Q2 營運回顧",
            "bullets": ["2026 年第二季", "營運與財務重點回顧"],
            "layout_hint": "cover",
            "assets": [],
        },
        {
            "index": 1,
            "title": "營收概況",
            "bullets": ["營收成長 12%", "毛利率維持穩定"],
            "layout_hint": "chart",
            "assets": ["revenue.png"],
        },
    ]
}


def _fence(obj: dict) -> str:
    return "```json\n" + json.dumps(obj, ensure_ascii=False) + "\n```"


def _make_project(tmp_path, with_md=True, with_asset=True):
    project = create_project(tmp_path, "測試專案")
    if with_md:
        (project.path / "md" / "report.md").write_text(
            "# Q2 報告\n\n營收成長 12%。\n", encoding="utf-8"
        )
    if with_asset:
        (project.path / "assets" / "revenue.png").write_bytes(b"fake-png-bytes")
    return project


def test_outline_happy_path(tmp_path):
    project = _make_project(tmp_path)
    llm = FakeLLM([_fence(VALID_OUTLINE)])

    result = generate_outline(llm, project, "swiss-minimal", "cool-corporate")

    assert result["slides"][0]["title"] == "封面：Q2 營運回顧"
    assert len(llm.calls) == 1

    # prompt 內含來源 md 內容與風格名稱
    call = llm.calls[0]
    prompt_text = json.dumps(call["messages"], ensure_ascii=False) + call["system"]
    assert "營收成長 12%" in prompt_text
    assert "swiss-minimal" in prompt_text or "Swiss" in prompt_text or "瑞士" in prompt_text

    # 寫入 outline.json 與 outline.md
    outline_json_path = project.path / "outline.json"
    outline_md_path = project.path / "outline.md"
    assert outline_json_path.is_file()
    assert outline_md_path.is_file()
    on_disk = json.loads(outline_json_path.read_text(encoding="utf-8"))
    assert on_disk == result

    md_text = outline_md_path.read_text(encoding="utf-8")
    assert "封面：Q2 營運回顧" in md_text
    assert "營收成長 12%" in md_text

    # project 狀態更新
    assert project.data["stage"] == "outline"
    assert len(project.data["slides"]) == 2
    assert all(s["status"] == "pending" for s in project.data["slides"])

    # project.json 也已落盤（save() 被呼叫）
    saved = json.loads((project.path / "project.json").read_text(encoding="utf-8"))
    assert saved["stage"] == "outline"


def test_outline_bad_json_retries_once(tmp_path):
    project = _make_project(tmp_path)
    llm = FakeLLM(["這不是 JSON，只是垃圾文字", _fence(VALID_OUTLINE)])

    result = generate_outline(llm, project, "swiss-minimal", "cool-corporate")

    assert result["slides"][0]["title"] == "封面：Q2 營運回顧"
    assert len(llm.calls) == 2

    # 第二次 prompt 需含上一次錯誤說明
    second_call = llm.calls[1]
    prompt_text = json.dumps(second_call["messages"], ensure_ascii=False) + second_call["system"]
    assert "這不是 JSON" in prompt_text or "垃圾文字" in prompt_text


def test_outline_bad_json_twice_raises(tmp_path):
    project = _make_project(tmp_path)
    llm = FakeLLM(["垃圾一", "垃圾二"])

    with pytest.raises(OutlineError):
        generate_outline(llm, project, "swiss-minimal", "cool-corporate")

    assert len(llm.calls) == 2
    # 失敗不應寫檔
    assert not (project.path / "outline.json").exists()


# ---------- Edge cases ----------


def test_outline_parses_json_without_fence_fallback(tmp_path):
    """LLM 沒用 ```json fence 包裹，但整體是合法 JSON 物件時應能靠 fallback 解析。"""
    project = _make_project(tmp_path)
    raw = "這是我的想法：\n" + json.dumps(VALID_OUTLINE, ensure_ascii=False) + "\n謝謝"
    llm = FakeLLM([raw])

    result = generate_outline(llm, project, "swiss-minimal", "cool-corporate")

    assert result["slides"][0]["title"] == "封面：Q2 營運回顧"
    assert len(llm.calls) == 1


def test_outline_asset_reference_not_found_is_validation_error(tmp_path):
    """assets 引用了 assets/ 目錄下不存在的檔名，應視為驗證錯誤而重試，兩次都錯則 raise。"""
    project = _make_project(tmp_path)
    bad_outline = {
        "slides": [
            {
                "index": 0,
                "title": "封面",
                "bullets": ["內容"],
                "layout_hint": "cover",
                "assets": ["not_exist.png"],
            }
        ]
    }
    llm = FakeLLM([_fence(bad_outline), _fence(bad_outline)])

    with pytest.raises(OutlineError) as excinfo:
        generate_outline(llm, project, "swiss-minimal", "cool-corporate")

    assert "not_exist.png" in str(excinfo.value)
    assert len(llm.calls) == 2


def test_outline_missing_or_out_of_order_index_is_fixed_not_error(tmp_path):
    """LLM 沒給 index，或給的 index 不連續／亂序，應自動補上／重排，不算驗證錯誤。"""
    project = _make_project(tmp_path)
    outline_no_index = {
        "slides": [
            {"title": "封面", "bullets": ["a"], "layout_hint": "cover", "assets": []},
            {"title": "結尾", "bullets": ["b"], "layout_hint": "closing", "assets": []},
        ]
    }
    llm = FakeLLM([_fence(outline_no_index)])

    result = generate_outline(llm, project, "swiss-minimal", "cool-corporate")

    assert len(llm.calls) == 1
    assert [s["index"] for s in result["slides"]] == [0, 1]
    assert result["slides"][0]["title"] == "封面"
    assert result["slides"][1]["title"] == "結尾"


def test_outline_out_of_order_index_is_resequenced(tmp_path):
    outline_weird_index = {
        "slides": [
            {"index": 5, "title": "A", "bullets": ["x"], "layout_hint": "bullets", "assets": []},
            {"index": 1, "title": "B", "bullets": ["y"], "layout_hint": "bullets", "assets": []},
        ]
    }
    project = _make_project(tmp_path)
    llm = FakeLLM([_fence(outline_weird_index)])

    result = generate_outline(llm, project, "swiss-minimal", "cool-corporate")

    assert [s["index"] for s in result["slides"]] == [0, 1]
    # 保留原本的相對順序（依 slides 陣列順序重排，而非依原 index 排序）
    assert result["slides"][0]["title"] == "A"
    assert result["slides"][1]["title"] == "B"


def test_outline_invalid_layout_hint_raises_after_two_tries(tmp_path):
    project = _make_project(tmp_path)
    bad_outline = {
        "slides": [
            {
                "index": 0,
                "title": "封面",
                "bullets": ["內容"],
                "layout_hint": "not-a-real-hint",
                "assets": [],
            }
        ]
    }
    llm = FakeLLM([_fence(bad_outline), _fence(bad_outline)])

    with pytest.raises(OutlineError) as excinfo:
        generate_outline(llm, project, "swiss-minimal", "cool-corporate")

    assert "layout_hint" in str(excinfo.value)
    assert len(llm.calls) == 2


def test_outline_empty_slides_list_is_validation_error(tmp_path):
    project = _make_project(tmp_path)
    llm = FakeLLM([_fence({"slides": []}), _fence({"slides": []})])

    with pytest.raises(OutlineError):
        generate_outline(llm, project, "swiss-minimal", "cool-corporate")

    assert len(llm.calls) == 2


def test_outline_fallback_ignores_trailing_text_after_json(tmp_path):
    """fallback 解析用 raw_decode 前綴解析：JSON 後面跟著多話（甚至含花括號）不會被誤吞。"""
    project = _make_project(tmp_path)
    raw = (
        json.dumps(VALID_OUTLINE, ensure_ascii=False)
        + "\n\n以上就是大綱，補充說明：{這段} 不是 JSON 的一部分}}"
    )
    llm = FakeLLM([raw])

    result = generate_outline(llm, project, "swiss-minimal", "cool-corporate")

    assert result["slides"][0]["title"] == "封面：Q2 營運回顧"
    assert len(llm.calls) == 1


def test_collect_md_text_truncates_overlong_source(tmp_path):
    """來源 md 超過長度上限時應截斷，且 prompt 內含截斷註記。"""
    from app.generation.outline import _MAX_SOURCE_CHARS, _TRUNCATION_NOTE

    project = _make_project(tmp_path, with_md=False)
    (project.path / "md" / "huge.md").write_text(
        "頭部標記。" + "很長的內容。" * (_MAX_SOURCE_CHARS // 6 + 1000),
        encoding="utf-8",
    )
    llm = FakeLLM([_fence(VALID_OUTLINE)])

    generate_outline(llm, project, "swiss-minimal", "cool-corporate")

    prompt = llm.calls[0]["messages"][0]["content"]
    assert "頭部標記。" in prompt
    assert _TRUNCATION_NOTE in prompt
    # 來源區塊確實被截斷：prompt 總長遠小於原始來源長度
    huge_len = len((project.path / "md" / "huge.md").read_text(encoding="utf-8"))
    assert len(prompt) < huge_len


# ---------- validate_outline（公開 API，供 PUT /outline 重用） ----------


def test_validate_outline_is_public_and_normalizes(tmp_path):
    outline = {
        "slides": [
            {"title": "封面", "bullets": ["a"], "layout_hint": "cover", "assets": []},
        ]
    }
    result = validate_outline(outline, [])
    assert result["slides"][0]["index"] == 0

    with pytest.raises(OutlineError):
        validate_outline({"slides": []}, [])


def test_validate_outline_exported_from_package():
    from app.generation import validate_outline as exported

    assert exported is validate_outline
