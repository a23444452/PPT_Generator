"""md/txt converter：直收原文，輸出到 project/md/<原檔名>.md。"""

from pathlib import Path

from app.ingest.dispatcher import IngestError, IngestResult
from app.store.project import Project


def convert_markdown(src: Path, project: Project) -> IngestResult:
    """把 md/txt 原文寫入 project/md/<原檔名>.md。"""
    try:
        content = src.read_text(encoding="utf-8")
    except OSError as exc:
        raise IngestError(f"讀取檔案失敗：{src.name}") from exc
    except UnicodeDecodeError as exc:
        raise IngestError(f"檔案不是 UTF-8 文字：{src.name}") from exc

    dest = project.path / "md" / f"{src.name}.md"
    try:
        dest.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise IngestError(f"寫入轉換結果失敗：{dest.name}") from exc
    return IngestResult(src_name=src.name, output_type="markdown", output_path=dest)
