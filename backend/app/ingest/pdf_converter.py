"""PDF → markdown converter。

逐頁以 `get_text("dict")` 取出 span，依字級判斷標題；`get_images` 抽出
內嵌圖片存到 assets/（MD5 去重、跳過過小的圖）。

MVP 不做向量圖 rasterize 與表格抽取（Phase 2 再加），於 md 尾註記
「PDF 表格可能遺漏」，避免使用者誤以為原始表格已完整轉出。
"""

import hashlib
from pathlib import Path

import fitz

from app.ingest.dispatcher import IngestError, IngestResult, unique_dest
from app.store.project import Project

# 字級 ≥ 頁面最常見字級 × 此倍率 → 視為標題
HEADING_SIZE_RATIO = 1.3
# 寬或高小於此像素視為裝飾用小圖，跳過抽取
MIN_IMAGE_SIZE = 100

_TABLE_NOTE = "（PDF 表格可能遺漏：MVP 尚未支援表格抽取，如原檔含表格請人工確認）"


def _most_common_size(sizes: list[float]) -> float:
    """頁面最常見的字級（用出現次數最多的 size 當作「內文字級」基準）。"""
    if not sizes:
        return 0.0
    counts: dict[float, int] = {}
    for size in sizes:
        rounded = round(size, 1)
        counts[rounded] = counts.get(rounded, 0) + 1
    return max(counts, key=lambda size: counts[size])


def _page_lines(page: "fitz.Page") -> list[tuple[float, str]]:
    """取出頁面所有文字行，回傳 (字級, 文字) 列表，依原順序排列。"""
    lines: list[tuple[float, str]] = []
    text_dict = page.get_text("dict")
    for block in text_dict.get("blocks", []):
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            text = "".join(span.get("text", "") for span in spans).strip()
            if not text:
                continue
            size = max(span.get("size", 0) for span in spans)
            lines.append((size, text))
    return lines


def _lines_to_markdown(lines: list[tuple[float, str]], base_size: float) -> list[str]:
    threshold = base_size * HEADING_SIZE_RATIO
    out: list[str] = []
    for size, text in lines:
        if base_size > 0 and size >= threshold:
            out.append(f"# {text}")
        else:
            out.append(text)
    return out


def _extract_images(
    doc: "fitz.Document", src: Path, project: Project
) -> tuple[list[Path], dict[str, str]]:
    """抽取全文件內嵌圖片，回傳 (資產路徑清單, md5->相對路徑 對照表)。

    MD5 對 bytes 去重（同一張圖多次引用只存一份）；
    寬或高 < MIN_IMAGE_SIZE 的小圖（裝飾用）跳過。
    """
    assets_dir = project.path / "assets"
    stem = Path(src.name).stem

    saved: list[Path] = []
    md5_to_rel: dict[str, str] = {}
    counter = 0

    for page in doc:
        for img in page.get_images(full=True):
            xref, _smask, width, height, *_rest = img
            if width < MIN_IMAGE_SIZE or height < MIN_IMAGE_SIZE:
                continue

            try:
                info = doc.extract_image(xref)
            except Exception:
                continue

            data = info["image"]
            digest = hashlib.md5(data).hexdigest()
            if digest in md5_to_rel:
                continue

            counter += 1
            ext = info.get("ext", "png")
            filename = f"{stem}_img{counter}.{ext}"
            dest = unique_dest(assets_dir, filename)
            try:
                dest.write_bytes(data)
            except OSError as exc:
                raise IngestError(f"寫入圖片失敗：{dest.name}") from exc

            saved.append(dest)
            md5_to_rel[digest] = f"assets/{dest.name}"

    return saved, md5_to_rel


def convert_pdf(src: Path, project: Project) -> IngestResult:
    """PDF 轉 markdown，輸出到 project/md/<原檔名>.md；內嵌圖片抽到 assets/。"""
    try:
        doc = fitz.open(src)
    except Exception as exc:
        raise IngestError(f"無法開啟 PDF 檔案（檔案可能已損壞）：{src.name}") from exc

    try:
        saved_assets, md5_to_rel = _extract_images(doc, src, project)

        page_sections: list[str] = []
        for page in doc:
            lines = _page_lines(page)
            base_size = _most_common_size([size for size, _ in lines])
            md_lines = _lines_to_markdown(lines, base_size)
            if md_lines:
                page_sections.append("\n\n".join(md_lines))

        for rel_path in md5_to_rel.values():
            page_sections.append(f"![]({rel_path})")
    finally:
        doc.close()

    warnings = [_TABLE_NOTE]
    content = "\n\n".join(page_sections) + f"\n\n{_TABLE_NOTE}\n"

    dest = project.path / "md" / f"{src.name}.md"
    try:
        dest.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise IngestError(f"寫入轉換結果失敗：{dest.name}") from exc

    return IngestResult(
        src_name=src.name,
        output_type="markdown",
        output_path=dest,
        warnings=warnings,
        extra_assets=tuple(saved_assets),
    )
