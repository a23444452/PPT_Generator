import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import router as api_router
from app.api.deps import get_llm, get_projects_root
from app.config import load_settings
from app.llm.openai_compat import OpenAICompatLLM
from app.store.project import ProjectNotFoundError, list_projects, load_project

logger = logging.getLogger(__name__)

_ALLOWED_ORIGINS = ["http://localhost:5173"]


def _reset_stale_generating(projects_root: Path) -> None:
    """啟動時清掉上次 process 中斷殘留的 stage=="generating"。

    生成中若被 Ctrl-C/OOM 硬中斷（非 exception，背景任務兜底捕不到），
    project.json 會停在 generating，導致 POST /generate 與 PUT /outline
    永久 409。單 worker 下 startup 時不可能有生成在跑，sweep 安全；
    重設回 outline 後已生成的頁會被續跑邏輯跳過。壞損專案目錄由
    list_projects 跳過，個別專案寫入失敗也不阻擋啟動。
    """
    for summary in list_projects(projects_root):
        if summary.stage != "generating":
            continue
        try:
            project = load_project(projects_root, summary.id)
            project.data["stage"] = "outline"
            project.data["last_error"] = "生成因伺服器重啟而中斷，可重新生成續跑"
            project.save()
            logger.info("已重設中斷殘留的生成狀態（project=%s）", summary.id)
        except (ProjectNotFoundError, OSError):
            logger.exception("重設生成狀態失敗，跳過（project=%s）", summary.id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """建立長生命週期的 OpenAICompatLLM singleton 並覆寫 get_llm dependency。

    config 延後載入原則：沒設環境變數時 app 仍須可正常啟動（例如測試
    以 dependency_overrides 注入 FakeLLM，根本不需要真的環境變數）；
    只有在真正需要呼叫 LLM 端點、且沒有 override 時，get_llm() 的預設
    實作才會呼叫 load_settings() 並在那個當下報錯。
    """
    # 清掉上次 process 中斷殘留的 generating 狀態。projects root 的取得
    # 與請求路徑一致：優先用 dependency override（測試指向 tmp_path，
    # 避免 sweep 掃到開發者的真實 projects/），否則走 get_projects_root
    # 本體（含 PPT_PROJECTS_DIR 環境變數覆寫）。
    projects_root_provider = app.dependency_overrides.get(
        get_projects_root, get_projects_root
    )
    _reset_stale_generating(projects_root_provider())

    llm: OpenAICompatLLM | None = None
    try:
        settings = load_settings()
    except RuntimeError:
        settings = None

    if settings is not None:
        llm = OpenAICompatLLM(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
        )
        app.dependency_overrides[get_llm] = lambda: llm

    try:
        yield
    finally:
        if llm is not None:
            llm.close()
            app.dependency_overrides.pop(get_llm, None)


app = FastAPI(title="PPT Generator", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """統一 422 錯誤格式：detail 一律是友善中文字串（含欄位路徑），
    而非 FastAPI 預設的英文 error dict 清單。
    """
    errors = exc.errors()
    if errors:
        loc = ".".join(str(part) for part in errors[0].get("loc", ()))
        detail = f"請求格式錯誤：{loc}" if loc else "請求格式錯誤"
    else:
        detail = "請求格式錯誤"
    return JSONResponse(status_code=422, content={"detail": detail})


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}
