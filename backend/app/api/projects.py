"""專案生命週期路由：建立／清單／上傳／風格／outline／生成／進度／slide SVG。"""

import json
import logging
import os
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from app.api.deps import get_llm, get_projects_root, load_project_or_404
from app.generation import OutlineError, generate_outline, generate_slides, validate_outline
from app.ingest import IngestError, ingest_file
from app.llm.base import LLMError, LLMProvider
from app.store.project import Project, ProjectNotFoundError, create_project, list_projects, load_project
from app.styles.catalog import StyleCatalogError, load_palette, load_style

logger = logging.getLogger(__name__)

router = APIRouter(tags=["projects"])

_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
_UPLOAD_CHUNK_SIZE = 1024 * 1024

_LLM_ERROR_MESSAGES = {
    "auth": "API 金鑰無效，請檢查 LLM_API_KEY 設定",
    "rate_limit": "已達 API 用量限制，請稍後再試",
    "network": "無法連線至 LLM 服務",
    "bad_response": "LLM 回應格式異常",
}


def _friendly_llm_message(exc: LLMError) -> str:
    return _LLM_ERROR_MESSAGES.get(exc.kind, "呼叫 LLM 服務時發生錯誤")


# ---------- 請求／回應 model ----------


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1)


class StyleSelectionRequest(BaseModel):
    style_id: str
    palette_id: str


class OutlineSlide(BaseModel):
    index: int | None = None
    title: str
    bullets: list[str]
    layout_hint: str
    assets: list[str] = Field(default_factory=list)


class OutlinePayload(BaseModel):
    slides: list[OutlineSlide]


# ---------- 共用輔助 ----------


def _project_detail(project: Project) -> dict:
    return {
        "id": project.data["id"],
        "name": project.data["name"],
        "created_at": project.data["created_at"],
        "stage": project.data["stage"],
        "mode": project.data.get("mode"),
        "style_id": project.data.get("style_id"),
        "palette_id": project.data.get("palette_id"),
        "slides": project.data.get("slides", []),
        "last_error": project.data.get("last_error"),
    }


# ---------- 專案 CRUD ----------


@router.post("/projects")
def create_project_endpoint(
    payload: CreateProjectRequest, root: Path = Depends(get_projects_root)
) -> dict:
    project = create_project(root, payload.name)
    return _project_detail(project)


@router.get("/projects")
def list_projects_endpoint(root: Path = Depends(get_projects_root)) -> list[dict]:
    summaries = list_projects(root)
    return [
        {
            "id": s.id,
            "name": s.name,
            "created_at": s.created_at,
            "stage": s.stage,
        }
        for s in summaries
    ]


@router.get("/projects/{project_id}")
def get_project_endpoint(project_id: str, root: Path = Depends(get_projects_root)) -> dict:
    project = load_project_or_404(root, project_id)
    return _project_detail(project)


# ---------- 上傳 ----------


@router.post("/projects/{project_id}/upload")
async def upload_files_endpoint(
    project_id: str,
    files: list[UploadFile],
    root: Path = Depends(get_projects_root),
) -> dict:
    project = load_project_or_404(root, project_id)
    source_dir = project.path / "source"
    source_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for upload in files:
        filename = upload.filename or "unnamed"
        try:
            data = await _read_upload_within_limit(upload)
        except _UploadTooLargeError as exc:
            raise HTTPException(
                status_code=413,
                detail=f"檔案「{filename}」超過 {_MAX_UPLOAD_BYTES // (1024 * 1024)}MB 上限",
            ) from exc

        dest = source_dir / filename
        try:
            dest.write_bytes(data)
            ingest_result = ingest_file(dest, project)
            results.append(
                {
                    "filename": filename,
                    "success": True,
                    "output_type": ingest_result.output_type,
                    "warnings": ingest_result.warnings,
                }
            )
        except IngestError as exc:
            results.append({"filename": filename, "success": False, "error": str(exc)})

    return {"results": results}


class _UploadTooLargeError(Exception):
    pass


async def _read_upload_within_limit(upload: UploadFile) -> bytes:
    chunks = []
    total = 0
    while True:
        chunk = await upload.read(_UPLOAD_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > _MAX_UPLOAD_BYTES:
            raise _UploadTooLargeError()
        chunks.append(chunk)
    return b"".join(chunks)


# ---------- 風格選擇 ----------


@router.post("/projects/{project_id}/style")
def select_style_endpoint(
    project_id: str,
    payload: StyleSelectionRequest,
    root: Path = Depends(get_projects_root),
) -> dict:
    project = load_project_or_404(root, project_id)

    try:
        load_style(payload.style_id)
        load_palette(payload.palette_id)
    except StyleCatalogError as exc:
        raise HTTPException(status_code=500, detail="風格目錄載入失敗") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc

    project.data["style_id"] = payload.style_id
    project.data["palette_id"] = payload.palette_id
    project.save()
    return _project_detail(project)


# ---------- Outline ----------


@router.post("/projects/{project_id}/outline")
def generate_outline_endpoint(
    project_id: str,
    root: Path = Depends(get_projects_root),
    llm: LLMProvider = Depends(get_llm),
) -> dict:
    project = load_project_or_404(root, project_id)

    style_id = project.data.get("style_id")
    palette_id = project.data.get("palette_id")
    if not style_id or not palette_id:
        raise HTTPException(status_code=422, detail="請先選擇風格與色盤")

    try:
        outline = generate_outline(llm, project, style_id, palette_id)
    except OutlineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=_friendly_llm_message(exc)) from exc

    return outline


@router.put("/projects/{project_id}/outline")
def update_outline_endpoint(
    project_id: str,
    payload: OutlinePayload,
    root: Path = Depends(get_projects_root),
) -> dict:
    project = load_project_or_404(root, project_id)
    if project.data["stage"] == "generating":
        raise HTTPException(status_code=409, detail="生成進行中，無法編輯大綱")

    assets_dir = project.path / "assets"
    asset_names = (
        sorted(p.name for p in assets_dir.iterdir() if p.is_file())
        if assets_dir.is_dir()
        else []
    )

    raw = payload.model_dump()
    try:
        outline = validate_outline(raw, asset_names)
    except OutlineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    _write_outline_files(project.path, outline)

    # 重建 slides 狀態表：使用者編輯後頁數／順序可能改變，整份覆寫回 pending。
    project.data["slides"] = [
        {"index": slide["index"], "status": "pending", "retries": 0}
        for slide in outline["slides"]
    ]
    project.data["stage"] = "outline"
    project.save()

    return outline


def _atomic_write_text(target: Path, text: str) -> None:
    tmp_path = target.parent / f".{target.name}.{uuid4().hex}.tmp"
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, target)


def _write_outline_files(project_path: Path, outline: dict) -> None:
    """PUT /outline 只覆寫 outline.json（沿用與 generate_outline 相同的原子寫入
    慣例）；outline.md 是產給人看的附加輸出，使用者手動編輯後不強制同步重繪，
    避免在此重複 app.generation.outline 的 markdown 排版邏輯。
    """
    _atomic_write_text(
        project_path / "outline.json",
        json.dumps(outline, ensure_ascii=False, indent=2),
    )


# ---------- 生成與進度 ----------


def _run_generation(project_id: str, root: Path, llm: LLMProvider) -> None:
    """背景任務進入點：任何例外都要落地成 last_error，讓 progress 端點可回報。

    裸拋只會進 log，前端輪詢會永遠卡在 generating。失敗時把 stage 回復
    為 outline，讓使用者可修正（如重新編輯大綱、檢查金鑰）後重試。
    """
    try:
        project = load_project(root, project_id)
    except ProjectNotFoundError:
        return

    try:
        generate_slides(llm, project)
    except LLMError as exc:
        _record_generation_failure(project, _friendly_llm_message(exc))
    except Exception:  # noqa: BLE001 — 兜底：outline 損毀、風格目錄錯誤、磁碟 IO 等
        logger.exception("生成背景任務發生未預期錯誤（project=%s）", project_id)
        _record_generation_failure(project, "生成過程發生未預期錯誤")


def _record_generation_failure(project: Project, message: str) -> None:
    project.data["last_error"] = message
    project.data["stage"] = "outline"
    try:
        project.save()
    except OSError:
        # save 本身失敗只能進 log；此時磁碟已有問題，無法再寫入任何狀態。
        logger.exception("寫入生成失敗狀態時發生 IO 錯誤（project=%s）", project.id)


@router.post("/projects/{project_id}/generate", status_code=202)
def start_generate_endpoint(
    project_id: str,
    background_tasks: BackgroundTasks,
    root: Path = Depends(get_projects_root),
    llm: LLMProvider = Depends(get_llm),
) -> dict:
    project = load_project_or_404(root, project_id)
    if project.data["stage"] == "generating":
        raise HTTPException(status_code=409, detail="生成進行中，請等待完成")

    project.data["last_error"] = None
    project.data["stage"] = "generating"
    project.save()

    background_tasks.add_task(_run_generation, project_id, root, llm)
    return {"status": "started"}


@router.get("/projects/{project_id}/progress")
def get_progress_endpoint(project_id: str, root: Path = Depends(get_projects_root)) -> dict:
    project = load_project_or_404(root, project_id)
    return {
        "stage": project.data["stage"],
        "slides": project.data.get("slides", []),
        "last_error": project.data.get("last_error"),
    }


# ---------- Slide SVG ----------


@router.get("/projects/{project_id}/slides/{index}.svg")
def get_slide_svg_endpoint(
    project_id: str, index: int, root: Path = Depends(get_projects_root)
) -> Response:
    project = load_project_or_404(root, project_id)
    svg_path = project.path / "svg_output" / f"slide_{index:03d}.svg"
    if not svg_path.is_file():
        raise HTTPException(status_code=404, detail=f"找不到第 {index} 頁的 SVG")
    return Response(content=svg_path.read_text(encoding="utf-8"), media_type="image/svg+xml")
