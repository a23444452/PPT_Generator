"""API 層（app.api）整合測試：TestClient + FakeLLM dependency override。"""

import io
import time

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_llm, get_projects_root
from app.llm.base import LLMError
from app.main import app
from app.store.project import load_project
from tests.conftest import FakeLLM

_OUTLINE_JSON = """```json
{"slides": [
  {"index": 0, "title": "封面：Q2 營運回顧", "bullets": ["2026 年第二季"], "layout_hint": "cover", "assets": []},
  {"index": 1, "title": "結語", "bullets": ["謝謝聆聽"], "layout_hint": "closing", "assets": []}
]}
```"""


def _svg(title: str) -> str:
    return (
        "```svg\n"
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">'
        '<rect x="0" y="0" width="1280" height="720" fill="#123456"/>'
        f'<text x="40" y="100" font-size="24">{title}</text>'
        "</svg>\n```"
    )


@pytest.fixture
def projects_root(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    return root


@pytest.fixture
def client(projects_root):
    app.dependency_overrides[get_projects_root] = lambda: projects_root
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_projects_root, None)
    app.dependency_overrides.pop(get_llm, None)


def _override_llm(responses: list[str]) -> FakeLLM:
    fake = FakeLLM(responses)
    app.dependency_overrides[get_llm] = lambda: fake
    return fake


def _poll_progress(client, project_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/projects/{project_id}/progress")
        assert resp.status_code == 200
        data = resp.json()
        if data["stage"] == "generated":
            return data
        time.sleep(0.02)
    raise AssertionError("generation did not complete in time")


# ---------- happy path ----------


def test_full_happy_path(client):
    # 1. 建立專案
    resp = client.post("/api/projects", json={"name": "測試簡報"})
    assert resp.status_code == 200, resp.text
    project = resp.json()
    project_id = project["id"]
    assert project["name"] == "測試簡報"

    # GET list / detail
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    assert any(p["id"] == project_id for p in resp.json())

    resp = client.get(f"/api/projects/{project_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == project_id

    # 2. 上傳 md
    files = {"files": ("source.md", io.BytesIO("# 標題\n內容".encode("utf-8")), "text/markdown")}
    resp = client.post(f"/api/projects/{project_id}/upload", files=files)
    assert resp.status_code == 200, resp.text
    upload_result = resp.json()
    assert upload_result["results"][0]["success"] is True

    # 3. 取得風格目錄
    resp = client.get("/api/styles")
    assert resp.status_code == 200
    catalog = resp.json()
    assert len(catalog["styles"]) >= 1
    assert len(catalog["palettes"]) >= 1
    style_id = catalog["styles"][0]["id"]
    palette_id = catalog["palettes"][0]["id"]

    # 4. 選風格
    resp = client.post(
        f"/api/projects/{project_id}/style",
        json={"style_id": style_id, "palette_id": palette_id},
    )
    assert resp.status_code == 200, resp.text

    # 5. 產生 outline（FakeLLM）
    _override_llm([_OUTLINE_JSON])
    resp = client.post(f"/api/projects/{project_id}/outline")
    assert resp.status_code == 200, resp.text
    outline = resp.json()
    assert len(outline["slides"]) == 2

    # 6. PUT outline（使用者編輯後整份覆寫）
    edited = {
        "slides": [
            {
                "index": 0,
                "title": "封面：編輯後標題",
                "bullets": ["編輯後內容"],
                "layout_hint": "cover",
                "assets": [],
            },
            {
                "index": 1,
                "title": "結語",
                "bullets": ["謝謝聆聽"],
                "layout_hint": "closing",
                "assets": [],
            },
        ]
    }
    resp = client.put(f"/api/projects/{project_id}/outline", json=edited)
    assert resp.status_code == 200, resp.text
    assert resp.json()["slides"][0]["title"] == "封面：編輯後標題"

    # 檢查 slides 狀態表已重建為 2 頁 pending
    resp = client.get(f"/api/projects/{project_id}")
    assert resp.status_code == 200
    detail = resp.json()
    assert len(detail["slides"]) == 2
    assert all(s["status"] == "pending" for s in detail["slides"])

    # 7. 觸發生成（背景任務）
    _override_llm([_svg("封面"), _svg("結語")])
    resp = client.post(f"/api/projects/{project_id}/generate")
    assert resp.status_code == 202, resp.text

    # 8. 輪詢 progress 至完成
    progress = _poll_progress(client, project_id)
    assert progress["stage"] == "generated"
    assert all(s["status"] == "generated" for s in progress["slides"])

    # 9. 取 slide SVG
    resp = client.get(f"/api/projects/{project_id}/slides/0.svg")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in resp.text

    # 10. export
    resp = client.post(f"/api/projects/{project_id}/export")
    assert resp.status_code == 200, resp.text
    export_result = resp.json()
    assert export_result["exported_count"] == 2
    assert export_result["skipped_count"] == 0
    assert export_result["download_url"]

    # 11. 下載
    resp = client.get(export_result["download_url"])
    assert resp.status_code == 200
    assert resp.headers["content-type"] in (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/octet-stream",
    )
    assert len(resp.content) > 0


def _setup_project_with_outline(client, name: str) -> str:
    """建專案→上傳 md→選風格→產生 outline（FakeLLM），回傳 project_id。"""
    resp = client.post("/api/projects", json={"name": name})
    project_id = resp.json()["id"]

    files = {"files": ("source.md", io.BytesIO("# 標題\n內容".encode("utf-8")), "text/markdown")}
    client.post(f"/api/projects/{project_id}/upload", files=files)

    styles = client.get("/api/styles").json()
    client.post(
        f"/api/projects/{project_id}/style",
        json={
            "style_id": styles["styles"][0]["id"],
            "palette_id": styles["palettes"][0]["id"],
        },
    )

    _override_llm([_OUTLINE_JSON])
    resp = client.post(f"/api/projects/{project_id}/outline")
    assert resp.status_code == 200, resp.text
    return project_id


def _poll_last_error(client, project_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        progress = client.get(f"/api/projects/{project_id}/progress").json()
        if progress.get("last_error"):
            return progress
        time.sleep(0.02)
    raise AssertionError("last_error was never reported")


def test_generate_llm_error_recorded_in_progress(client):
    project_id = _setup_project_with_outline(client, "LLM 失敗測試")

    class _FailingLLM:
        def complete(self, messages, system="", max_tokens=4096):
            raise LLMError("模擬逾時", kind="network")

    app.dependency_overrides[get_llm] = lambda: _FailingLLM()
    resp = client.post(f"/api/projects/{project_id}/generate")
    assert resp.status_code == 202

    progress = _poll_last_error(client, project_id)
    assert progress["last_error"] == "無法連線至 LLM 服務"
    # 失敗後 stage 回復 outline，讓使用者可修正後重試
    assert progress["stage"] == "outline"


def test_generate_unexpected_error_recorded_in_progress(client):
    project_id = _setup_project_with_outline(client, "非預期錯誤測試")

    class _ExplodingLLM:
        def complete(self, messages, system="", max_tokens=4096):
            raise ValueError("內部爆炸，非 LLMError")

    app.dependency_overrides[get_llm] = lambda: _ExplodingLLM()
    resp = client.post(f"/api/projects/{project_id}/generate")
    assert resp.status_code == 202

    progress = _poll_last_error(client, project_id)
    assert progress["last_error"] == "生成過程發生未預期錯誤"
    assert progress["stage"] == "outline"


def test_generate_conflict_while_generating_409(client, projects_root):
    project_id = _setup_project_with_outline(client, "併發生成測試")

    # 模擬生成進行中：直接把 stage 寫成 generating（背景任務在 TestClient
    # 下與回應同步完成，無法靠真的併發請求製造這個狀態）。
    project = load_project(projects_root, project_id)
    project.data["stage"] = "generating"
    project.save()

    resp = client.post(f"/api/projects/{project_id}/generate")
    assert resp.status_code == 409
    assert "生成進行中" in resp.json()["detail"]


def test_put_outline_conflict_while_generating_409(client, projects_root):
    project_id = _setup_project_with_outline(client, "生成中編輯測試")

    project = load_project(projects_root, project_id)
    project.data["stage"] = "generating"
    project.save()

    edited = {
        "slides": [
            {
                "index": 0,
                "title": "編輯",
                "bullets": [],
                "layout_hint": "cover",
                "assets": [],
            }
        ]
    }
    resp = client.put(f"/api/projects/{project_id}/outline", json=edited)
    assert resp.status_code == 409
    assert "生成進行中" in resp.json()["detail"]


# ---------- 錯誤情境 ----------


def test_create_project_missing_name_422(client):
    resp = client.post("/api/projects", json={})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    # 全域 RequestValidationError handler：統一中文格式、附欄位路徑
    assert isinstance(detail, str)
    assert detail.startswith("請求格式錯誤：")
    assert "name" in detail


def test_project_not_found_404(client):
    resp = client.get("/api/projects/doesnotexist")
    assert resp.status_code == 404
    assert "detail" in resp.json()


def test_upload_bad_extension_reports_failure_per_file(client):
    resp = client.post("/api/projects", json={"name": "壞副檔名"})
    project_id = resp.json()["id"]

    files = {"files": ("evil.exe", io.BytesIO(b"binary"), "application/octet-stream")}
    resp = client.post(f"/api/projects/{project_id}/upload", files=files)
    assert resp.status_code == 200  # 逐檔回報，整體請求成功
    result = resp.json()["results"][0]
    assert result["success"] is False
    assert result["error"]  # 友善錯誤訊息在 error 欄位


def test_upload_file_too_large_413(client):
    resp = client.post("/api/projects", json={"name": "超大檔"})
    project_id = resp.json()["id"]

    big_content = b"a" * (51 * 1024 * 1024)  # 51MB > 50MB 上限
    files = {"files": ("big.md", io.BytesIO(big_content), "text/markdown")}
    resp = client.post(f"/api/projects/{project_id}/upload", files=files)
    assert resp.status_code == 413
    assert "detail" in resp.json()


def test_upload_project_not_found_404(client):
    files = {"files": ("a.md", io.BytesIO(b"# hi"), "text/markdown")}
    resp = client.post("/api/projects/doesnotexist/upload", files=files)
    assert resp.status_code == 404


def test_style_unknown_id_404(client):
    resp = client.post("/api/projects", json={"name": "測試"})
    project_id = resp.json()["id"]

    resp = client.post(
        f"/api/projects/{project_id}/style",
        json={"style_id": "does-not-exist", "palette_id": "does-not-exist"},
    )
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    # KeyError 訊息不應殘留 Python repr 的引號
    assert not detail.startswith("'")
    assert not detail.endswith("'")


def test_put_outline_validation_error_422(client):
    resp = client.post("/api/projects", json={"name": "測試"})
    project_id = resp.json()["id"]

    bad_outline = {"slides": [{"title": "", "bullets": [], "layout_hint": "bad", "assets": []}]}
    resp = client.put(f"/api/projects/{project_id}/outline", json=bad_outline)
    assert resp.status_code == 422
    assert "detail" in resp.json()


def test_slide_svg_not_found_404(client):
    resp = client.post("/api/projects", json={"name": "測試"})
    project_id = resp.json()["id"]

    resp = client.get(f"/api/projects/{project_id}/slides/0.svg")
    assert resp.status_code == 404


def test_export_no_generated_pages_error(client):
    resp = client.post("/api/projects", json={"name": "沒有頁面"})
    project_id = resp.json()["id"]

    resp = client.post(f"/api/projects/{project_id}/export")
    assert resp.status_code in (400, 422)
    assert "detail" in resp.json()


def test_download_path_escape_404(client):
    resp = client.post("/api/projects", json={"name": "測試"})
    project_id = resp.json()["id"]

    resp = client.get(f"/api/projects/{project_id}/exports/..%2F..%2Fetc%2Fpasswd")
    assert resp.status_code == 404

    resp = client.get(f"/api/projects/{project_id}/exports/nonexistent.pptx")
    assert resp.status_code == 404


def test_download_project_not_found_404(client):
    resp = client.get("/api/projects/doesnotexist/exports/foo.pptx")
    assert resp.status_code == 404
