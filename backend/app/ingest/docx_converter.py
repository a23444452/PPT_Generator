"""Docx → markdown converter。

走訪 `document.body` 依序處理段落與表格：
- 段落 `style.name` 含 "Heading N" → 對應層級的 `#`*N 標題
- 其餘段落 → 原文輸出
- 表格 → md 表格（重用 `_table_md` helper）

`.doc`/`.odt` 等舊格式不在 dispatcher 的 SUPPORTED 內，會被自然拒絕，
本模組只需處理「副檔名是 .docx 但檔案本身損壞／非法」的友善錯誤。
"""

import re
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.ingest._table_md import rows_to_markdown_table
from app.ingest.dispatcher import IngestError, IngestResult
from app.store.project import Project

_HEADING_RE = re.compile(r"^Heading (\d+)$")


def _paragraph_to_markdown(paragraph: Paragraph) -> str:
    """段落轉 md：Heading N → `#`*N 標題，其餘原文輸出。"""
    text = paragraph.text
    match = _HEADING_RE.match(paragraph.style.name or "")
    if match:
        level = min(int(match.group(1)), 6)
        return f"{'#' * level} {text}"
    return text


def _table_to_markdown(table: Table) -> str:
    rows = [[cell.text for cell in row.cells] for row in table.rows]
    return rows_to_markdown_table(rows)


def convert_docx(src: Path, project: Project) -> IngestResult:
    """docx 轉 markdown，輸出到 project/md/<原檔名>.md。"""
    try:
        document = Document(src)
    except Exception as exc:
        raise IngestError(f"無法開啟 Word 檔案（檔案可能已損壞）：{src.name}") from exc

    sections: list[str] = []
    try:
        for block in document.element.body.iterchildren():
            tag = block.tag.split("}")[-1]
            if tag == "p":
                paragraph = Paragraph(block, document)
                text = _paragraph_to_markdown(paragraph)
                if text.strip():
                    sections.append(text)
            elif tag == "tbl":
                table = Table(block, document)
                sections.append(_table_to_markdown(table))
    except Exception as exc:
        raise IngestError(f"解析 Word 檔案內容失敗：{src.name}") from exc

    dest = project.path / "md" / f"{src.name}.md"
    try:
        dest.write_text("\n\n".join(sections) + "\n", encoding="utf-8")
    except OSError as exc:
        raise IngestError(f"寫入轉換結果失敗：{dest.name}") from exc

    return IngestResult(src_name=src.name, output_type="markdown", output_path=dest)
