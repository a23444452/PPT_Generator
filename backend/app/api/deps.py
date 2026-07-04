"""API 層共用依賴：LLM provider 與 projects 根目錄。

LLM 用 FastAPI dependency 注入：app 層以 lifespan 建 singleton
`OpenAICompatLLM`（延後到真正需要時才讀取環境變數，維持 config 延後
載入原則），shutdown 時 close()。測試以 `app.dependency_overrides`
注入 FakeLLM，不需設定任何環境變數。

projects 根目錄：環境變數 `PPT_PROJECTS_DIR` 缺省時，用 repo 根目錄下
的 `projects/`（repo 根定位方式比照 app.styles.catalog：從本檔案往上
找到含 styles/visual 的祖先目錄）。測試以 dependency override 指向
tmp_path，不依賴環境變數。
"""

import os
from pathlib import Path

from fastapi import HTTPException

from app.llm.base import LLMProvider
from app.store.project import Project, ProjectNotFoundError, load_project


class ProjectsRootError(Exception):
    """找不到可用的 projects 根目錄（理論上不應發生，定位邏輯有保底）。"""


def load_project_or_404(root: Path, project_id: str) -> Project:
    """載入專案；不存在或損毀時回 404（各 router 共用）。"""
    try:
        return load_project(root, project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"找不到專案：{project_id}") from exc


def _default_repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "styles" / "visual").is_dir():
            return parent
    # 保底：找不到 styles/ 目錄時（例如打包後的環境），退回目前工作目錄。
    return Path.cwd()


def get_projects_root() -> Path:
    """回傳 projects 根目錄（不存在則建立）。"""
    env_dir = os.environ.get("PPT_PROJECTS_DIR")
    root = Path(env_dir) if env_dir else _default_repo_root() / "projects"
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_llm() -> LLMProvider:
    """預設實作：真正呼叫時才讀取環境變數建立 OpenAICompatLLM。

    正式部署由 app.main 的 lifespan 覆寫為長生命週期 singleton；
    測試一律用 app.dependency_overrides 注入 FakeLLM，不會走到這裡。
    """
    from app.config import load_settings
    from app.llm.openai_compat import OpenAICompatLLM

    settings = load_settings()
    return OpenAICompatLLM(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
    )
