"""LLM provider 抽象層。

全系統唯一的 LLM 出口：outline 生成、SVG 生成等上層邏輯只透過
`LLMProvider.complete()` 呼叫，不直接碰 httpx 或特定 provider 的 API 形狀。
"""

from typing import Protocol


class LLMError(Exception):
    """LLM 呼叫失敗，附帶可分類的錯誤種類供上層映射成使用者友善訊息。

    kind:
        - "auth": 認證失敗（401/403），不應重試
        - "rate_limit": 429，可重試
        - "network": 連線錯誤或伺服器端 5xx，重試後仍失敗
        - "bad_response": 回應格式不符預期（如缺少必要欄位）
    """

    def __init__(self, message: str, kind: str):
        super().__init__(message)
        self.kind = kind


class LLMProvider(Protocol):
    def complete(
        self, messages: list[dict], system: str = "", max_tokens: int = 4096
    ) -> str:
        """送出對話並回傳模型產生的文字內容。"""
        ...
