"""Ingest 分派器：依副檔名把來源檔轉成 markdown 或複製為資產。"""

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app.store.project import Project

SUPPORTED = {".md", ".txt", ".xlsx", ".xlsm", ".docx", ".pdf", ".png", ".jpg", ".jpeg"}


class IngestError(Exception):
    """Ingest 過程的使用者可讀錯誤（訊息不含堆疊或內部細節）。"""


class UnsupportedFormatError(IngestError):
    """副檔名不在支援清單內。"""


@dataclass(frozen=True)
class IngestResult:
    src_name: str
    output_type: str  # "markdown" | "asset"
    output_path: Path
    warnings: list[str] = field(default_factory=list)
    # 一對多輸出承載欄位：如 PDF converter（Task 4）一個來源檔
    # 產出 1 個 md ＋ N 張抽取圖片時，圖片路徑放這裡。
    extra_assets: tuple[Path, ...] = ()


def _unique_dest(directory: Path, filename: str) -> Path:
    """同名檔案不覆蓋：chart.png → chart-1.png → chart-2.png …"""
    dest = directory / filename
    if not dest.exists():
        return dest
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    for i in range(1, 1000):
        candidate = directory / f"{stem}-{i}{suffix}"
        if not candidate.exists():
            return candidate
    raise IngestError(f"assets/ 內同名檔案過多：{filename}")


def _copy_asset(src: Path, project: Project) -> IngestResult:
    """圖片複製到 assets/，同名加序號避免覆蓋。"""
    assets_dir = project.path / "assets"
    dest = _unique_dest(assets_dir, src.name)
    try:
        shutil.copy2(src, dest)
    except OSError as exc:
        raise IngestError(f"複製圖片失敗：{src.name}") from exc
    return IngestResult(src_name=src.name, output_type="asset", output_path=dest)


# converter 模組（md/excel）import 本模組取得 IngestResult 等共用型別，
# 故 dispatcher 端延遲 import converter，避免模組層循環依賴。
def _convert_markdown(src: Path, project: Project) -> IngestResult:
    from app.ingest.md_converter import convert_markdown

    return convert_markdown(src, project)


def _convert_excel(src: Path, project: Project) -> IngestResult:
    from app.ingest.excel_converter import convert_excel

    return convert_excel(src, project)


def _convert_docx(src: Path, project: Project) -> IngestResult:
    from app.ingest.docx_converter import convert_docx

    return convert_docx(src, project)


def _convert_pdf(src: Path, project: Project) -> IngestResult:
    from app.ingest.pdf_converter import convert_pdf

    return convert_pdf(src, project)


_CONVERTERS: dict[str, Callable[[Path, Project], IngestResult]] = {
    ".md": _convert_markdown,
    ".txt": _convert_markdown,
    ".xlsx": _convert_excel,
    ".xlsm": _convert_excel,
    ".docx": _convert_docx,
    ".pdf": _convert_pdf,
    ".png": _copy_asset,
    ".jpg": _copy_asset,
    ".jpeg": _copy_asset,
}


def ingest_file(src: Path, project: Project) -> IngestResult:
    """依副檔名分派。輸出 md 到 project/md/<原檔名>.md；圖片複製到 assets/。

    不支援的副檔名 raise UnsupportedFormatError（訊息含支援清單）。
    """
    ext = src.suffix.lower()
    if ext not in SUPPORTED:
        supported = "、".join(sorted(SUPPORTED))
        raise UnsupportedFormatError(
            f"不支援的檔案格式：{ext or src.name}（支援：{supported}）"
        )

    converter = _CONVERTERS.get(ext)
    if converter is None:
        raise IngestError(f"格式 {ext} 已規劃但尚未支援，請等待後續版本")

    return converter(src, project)
