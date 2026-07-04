from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router as api_router
from app.api.deps import get_llm
from app.config import load_settings
from app.llm.openai_compat import OpenAICompatLLM

_ALLOWED_ORIGINS = ["http://localhost:5173"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """建立長生命週期的 OpenAICompatLLM singleton 並覆寫 get_llm dependency。

    config 延後載入原則：沒設環境變數時 app 仍須可正常啟動（例如測試
    以 dependency_overrides 注入 FakeLLM，根本不需要真的環境變數）；
    只有在真正需要呼叫 LLM 端點、且沒有 override 時，get_llm() 的預設
    實作才會呼叫 load_settings() 並在那個當下報錯。
    """
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


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}
