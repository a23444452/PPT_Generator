"""OpenAI-compatible chat completion adapter。

公司內部 gateway 走 OpenAI-compatible 協定，因此目前只需要這一種 adapter。
"""

import time

import httpx

from app.llm.base import LLMError

_MAX_ATTEMPTS = 3
_TIMEOUT_SECONDS = 120.0


class OpenAICompatLLM:
    """透過 OpenAI-compatible `/chat/completions` 端點呼叫 LLM。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        transport: httpx.BaseTransport | None = None,
        sleep_fn=time.sleep,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._sleep_fn = sleep_fn
        self._client = httpx.Client(transport=transport, timeout=_TIMEOUT_SECONDS)

    def complete(
        self, messages: list[dict], system: str = "", max_tokens: int = 4096
    ) -> str:
        full_messages = list(messages)
        if system:
            full_messages = [{"role": "system", "content": system}] + full_messages

        payload = {
            "model": self._model,
            "messages": full_messages,
            "max_tokens": max_tokens,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        url = f"{self._base_url}/chat/completions"

        last_kind = "network"
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = self._client.post(url, json=payload, headers=headers)
            except httpx.HTTPError:
                last_kind = "network"
                if attempt < _MAX_ATTEMPTS:
                    self._sleep_fn(2 ** (attempt - 1))
                    continue
                raise LLMError("呼叫 LLM 服務失敗，請稍後再試", kind="network") from None

            if response.status_code in (401, 403):
                raise LLMError("API 金鑰無效或無權限", kind="auth")

            if response.status_code == 429:
                last_kind = "rate_limit"
                if attempt < _MAX_ATTEMPTS:
                    self._sleep_fn(2 ** (attempt - 1))
                    continue
                raise LLMError("LLM 服務請求過於頻繁，請稍後再試", kind="rate_limit")

            if response.status_code >= 500:
                last_kind = "network"
                if attempt < _MAX_ATTEMPTS:
                    self._sleep_fn(2 ** (attempt - 1))
                    continue
                raise LLMError("呼叫 LLM 服務失敗，請稍後再試", kind="network")

            if response.status_code >= 400:
                raise LLMError("呼叫 LLM 服務失敗，請稍後再試", kind="bad_response")

            return self._parse_content(response)

        # 理論上不會到這裡（迴圈內每個分支都會 return 或 raise）
        raise LLMError("呼叫 LLM 服務失敗，請稍後再試", kind=last_kind)

    @staticmethod
    def _parse_content(response: httpx.Response) -> str:
        try:
            data = response.json()
        except ValueError:
            raise LLMError("LLM 回應格式無法解析", kind="bad_response") from None

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("LLM 回應缺少必要欄位", kind="bad_response") from None
