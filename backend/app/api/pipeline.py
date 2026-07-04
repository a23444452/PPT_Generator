"""風格目錄與匯出／下載路由。"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.deps import get_projects_root
from app.api.projects import _load_or_404
from app.export import ExportError, export_pptx
from app.styles.catalog import StyleCatalogError, list_palettes, list_styles

router = APIRouter(tags=["pipeline"])


@router.get("/styles")
def list_styles_endpoint() -> dict:
    try:
        styles = list_styles()
        palettes = list_palettes()
    except StyleCatalogError as exc:
        raise HTTPException(status_code=500, detail="風格目錄載入失敗") from exc

    return {"styles": styles, "palettes": palettes}


@router.post("/projects/{project_id}/export")
def export_project_endpoint(
    project_id: str, root: Path = Depends(get_projects_root)
) -> dict:
    project = _load_or_404(root, project_id)

    try:
        result = export_pptx(project)
    except ExportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    filename = result.output_path.name
    return {
        "download_url": f"/api/projects/{project_id}/exports/{filename}",
        "warnings": result.warnings,
        "exported_count": result.exported_count,
        "skipped_count": result.skipped_count,
    }


@router.get("/projects/{project_id}/exports/{filename}")
def download_export_endpoint(
    project_id: str, filename: str, root: Path = Depends(get_projects_root)
) -> FileResponse:
    project = _load_or_404(root, project_id)

    # 防路徑逃逸：filename 必須是純檔名（無分隔符），且 resolve 後仍在
    # exports/ 之下——雙重防護，前者擋掉大多數 traversal payload，
    # 後者擋掉 resolve 後仍脫出的邊界情況。
    if "/" in filename or "\\" in filename or filename in (".", ".."):
        raise HTTPException(status_code=404, detail="找不到匯出檔案")

    exports_dir = (project.path / "exports").resolve()
    candidate = (exports_dir / filename).resolve()
    try:
        candidate.relative_to(exports_dir)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="找不到匯出檔案") from exc

    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="找不到匯出檔案")

    return FileResponse(
        path=candidate,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=filename,
    )
