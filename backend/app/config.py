import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    projects_dir: str = "projects"
    max_upload_mb: int = 50


def load_settings() -> Settings:
    missing = [k for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL") if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"缺少必要環境變數：{', '.join(missing)}（請參考 README 設定）")
    return Settings(
        llm_base_url=os.environ["LLM_BASE_URL"],
        llm_api_key=os.environ["LLM_API_KEY"],
        llm_model=os.environ["LLM_MODEL"],
    )
