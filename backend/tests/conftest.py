"""Shared pytest fixtures for the PPT Generator backend test suite."""


class FakeLLM:
    """依序回傳預錄回應；記錄收到的 prompt 供斷言。"""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def complete(self, messages, system="", max_tokens=4096) -> str:
        self.calls.append({"messages": messages, "system": system})
        return self.responses.pop(0)
