"""Ingest：把來源資料檔統一轉成 md/ 下的 markdown，圖片複製到 assets/。"""

from app.ingest.dispatcher import (
    SUPPORTED,
    IngestError,
    IngestResult,
    UnsupportedFormatError,
    ingest_file,
)

__all__ = [
    "SUPPORTED",
    "IngestError",
    "IngestResult",
    "UnsupportedFormatError",
    "ingest_file",
]
