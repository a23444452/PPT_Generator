# PPT Generator Phase 1 MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 本機單人 Web 工具——上傳資料檔，選內建風格，LLM 生成大綱與逐頁 SVG，瀏覽器預覽，匯出可編輯 .pptx。

**Architecture:** FastAPI 後端＋檔案系統專案儲存（無資料庫）；資料檔轉 Markdown → LLM 生成大綱（JSON）→ 逐頁 SVG（spec 約束、逐頁落盤可續跑）→ vendored `svg_to_pptx`（ppt-master, MIT）轉可編輯 pptx。前端 Vite + React 五步精靈。

**Tech Stack:** Python 3.12 + uv、FastAPI、PyMuPDF、openpyxl、python-docx、python-pptx、httpx、pytest；前端 Vite + React。

**Spec:** `docs/superpowers/specs/2026-07-04-ppt-generator-design.md`（本計畫只涵蓋 Phase 1；風格萃取/場景推薦/模式 B 屬 Phase 2/3）

**慣例（所有 task 適用）：**
- 在 `feat/mvp` 分支上工作（Task 0 建立）。
- 測試指令一律 `uv run pytest <path> -v`。
- 每個 task 結尾 commit，訊息格式 `<type>: <描述>`，並附 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。
- LLM 相關測試一律用 `FakeLLM`（Task 2 建立），不打真實 API。

---

## File Structure（全案地圖）

```
backend/
  app/
    main.py                 FastAPI app、路由掛載、靜態檔服務
    config.py               環境變數載入（LLM_BASE_URL/LLM_API_KEY/LLM_MODEL）
    llm/
      base.py               LLMProvider 介面 + LLMError 分類
      openai_compat.py      OpenAI-compatible adapter（含 retry/backoff）
    store/
      project.py            專案目錄 CRUD、project.json 讀寫、slide 狀態表
    ingest/
      dispatcher.py         副檔名 → converter 分派
      md_converter.py       markdown 直收
      excel_converter.py    openpyxl → md 表格
      docx_converter.py     python-docx → md
      pdf_converter.py      PyMuPDF → md ＋圖片抽取
    styles/
      catalog.py            風格/色盤目錄載入
    generation/
      outline.py            大綱生成（LLM → JSON 驗證）
      slides.py             逐頁 SVG 生成、spec lock、續跑
      quality.py            SVG 驗證（XML/viewBox/文字溢出）＋帶錯誤原因重生
    export/
      pptx_export.py        vendored svg_to_pptx 的 adapter
    api/
      projects.py           專案 CRUD ＋上傳
      pipeline.py           ingest/outline/generate/export 路由＋進度查詢
  tests/
    conftest.py             tmp 專案目錄 fixture、FakeLLM
    fixtures/               樣本檔（sample.xlsx / sample.docx / sample.pdf / sample.md / sample.svg）
    test_*.py               對應各模組
vendor/
  svg_to_pptx/              從 ppt-master vendor（保留 LICENSE）
  NOTICE                    MIT attribution
styles/
  visual/*.md               移植的視覺風格規則檔（MVP 4 種）
  palettes/*.md             色盤檔（MVP 3 種）
frontend/                   Vite + React 五步精靈
  src/App.jsx, src/api.js, src/steps/*.jsx
projects/                   使用者資料（gitignored）
```

分工原則：`generation/` 只依賴 `llm/` 與 `store/`；`export/` 只依賴 vendor；API 層薄、邏輯全在模組內，讓每個模組可獨立測試。

---

### Task 0: 專案腳手架

**Files:**
- Create: `backend/pyproject.toml`（uv 管理）、`backend/app/main.py`、`backend/app/config.py`、`backend/tests/conftest.py`、`README.md`

- [ ] **Step 1: 開分支**

```bash
git checkout -b feat/mvp
```

- [ ] **Step 2: 初始化 Python 專案**

```bash
cd backend && uv init --name ppt-generator --python 3.12
uv add fastapi "uvicorn[standard]" httpx pymupdf openpyxl python-docx python-pptx pillow
uv add --dev pytest pytest-asyncio
```

- [ ] **Step 3: 寫 config 的失敗測試**

`backend/tests/test_config.py`：

```python
import pytest
from app.config import load_settings

def test_load_settings_from_env(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://gw.local/v1")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_MODEL", "m")
    s = load_settings()
    assert s.llm_base_url == "http://gw.local/v1"

def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "x")
    monkeypatch.setenv("LLM_MODEL", "m")
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        load_settings()
```

- [ ] **Step 4: 跑測試確認失敗**（`uv run pytest tests/test_config.py -v`，Expected: ImportError/FAIL）

- [ ] **Step 5: 實作 `app/config.py`**

```python
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
```

- [ ] **Step 6: 建最小 FastAPI app**（`app/main.py`：`FastAPI()` 實例＋`GET /api/health` 回 `{"ok": true}`；config 延後到路由內載入，避免 import 時就要求環境變數）

- [ ] **Step 7: 跑測試通過後 commit**（`chore: 專案腳手架與設定載入`）

---

### Task 1: 專案儲存（project store）

**Files:**
- Create: `backend/app/store/project.py`
- Test: `backend/tests/test_project_store.py`

專案目錄結構與 `project.json` 欄位依規格 3.1 節。核心 API：

```python
create_project(root: Path, name: str) -> Project          # 建目錄骨架 + 初始 project.json
load_project(root: Path, project_id: str) -> Project
list_projects(root: Path) -> list[ProjectSummary]
Project.save() -> None                                     # 原子寫入（tmp+rename）
Project.set_slide_status(index: int, status: str) -> None  # pending|generated|failed，含 retries 累加
```

- [ ] **Step 1: 寫失敗測試**

```python
def test_create_and_reload(tmp_path):
    p = create_project(tmp_path, "月報")
    assert (tmp_path / p.id / "source").is_dir()
    assert (tmp_path / p.id / "svg_output").is_dir()
    p.set_slide_status(0, "generated")
    p.save()
    p2 = load_project(tmp_path, p.id)
    assert p2.data["slides"][0]["status"] == "generated"
    assert p2.data["stage"] == "ingest"

def test_slide_retry_counter(tmp_path):
    p = create_project(tmp_path, "x")
    p.set_slide_status(0, "failed")
    p.set_slide_status(0, "failed")
    assert p.data["slides"][0]["retries"] == 2
```

- [ ] **Step 2: 跑測試確認失敗**
- [ ] **Step 3: 實作**（`project.json` 初始欄位：`{"id", "name", "created_at", "stage": "ingest", "mode": "A", "style_id": null, "palette_id": null, "spec_locked": false, "slides": []}`；`id` 用 `uuid4().hex[:8]`；子目錄 `source/ md/ assets/ svg_output/ exports/`；寫入用 tmp 檔＋`os.replace` 原子替換）
- [ ] **Step 4: 跑測試通過**
- [ ] **Step 5: Commit**（`feat: 專案檔案系統儲存與 slide 狀態表`）

---

### Task 2: LLM provider 層

**Files:**
- Create: `backend/app/llm/base.py`、`backend/app/llm/openai_compat.py`
- Test: `backend/tests/test_llm.py`；`conftest.py` 加 `FakeLLM`

**介面（規格 3.2）：**

```python
# base.py
class LLMError(Exception):
    def __init__(self, message: str, kind: str):  # kind: "auth" | "rate_limit" | "network" | "bad_response"
        ...

class LLMProvider(Protocol):
    def complete(self, messages: list[dict], system: str = "", max_tokens: int = 4096) -> str: ...
```

- [ ] **Step 1: 寫失敗測試**（用 `httpx.MockTransport`）

```python
def test_complete_returns_text():        # 正常回應解析 choices[0].message.content
def test_retry_on_5xx_then_success():    # 前兩次 500、第三次 200 → 成功且呼叫 3 次
def test_auth_error_no_retry():          # 401 → 立即 LLMError(kind="auth")，只呼叫 1 次
def test_gives_up_after_3_retries():     # 連續 500 → LLMError(kind="network")
```

- [ ] **Step 2: 跑測試確認失敗**
- [ ] **Step 3: 實作 `openai_compat.py`**

要點：POST `{base_url}/chat/completions`；payload `{"model", "messages": [{"role":"system"...}] + messages, "max_tokens"}`；retry 3 次、backoff `1s * 2^n`（測試中以可注入的 `sleep_fn` 跳過等待）；401/403 → `auth` 不重試；429/5xx/連線錯 → 重試；JSON 缺欄位 → `bad_response`。timeout 120s。

- [ ] **Step 4: 在 `conftest.py` 加 `FakeLLM`**

```python
class FakeLLM:
    """依序回傳預錄回應；記錄收到的 prompt 供斷言。"""
    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[dict] = []
    def complete(self, messages, system="", max_tokens=4096) -> str:
        self.calls.append({"messages": messages, "system": system})
        return self.responses.pop(0)
```

- [ ] **Step 5: 跑測試通過後 commit**（`feat: LLM provider 抽象層與 OpenAI-compatible adapter`）

---

### Task 3: Ingest — dispatcher、md、excel

**Files:**
- Create: `backend/app/ingest/dispatcher.py`、`md_converter.py`、`excel_converter.py`
- Test: `backend/tests/test_ingest_basic.py`、fixture `tests/fixtures/sample.xlsx`（用 openpyxl 在 conftest 動態產生：兩欄三列含合併儲存格與數字）

**Dispatcher 介面：**

```python
SUPPORTED = {".md", ".txt", ".xlsx", ".xlsm", ".docx", ".pdf", ".png", ".jpg", ".jpeg"}

def ingest_file(src: Path, project: Project) -> IngestResult:
    """依副檔名分派。輸出 md 到 project/md/<原檔名>.md；圖片複製到 assets/。
    不支援的副檔名 raise UnsupportedFormatError（訊息含支援清單）。"""
```

- [ ] **Step 1: 寫失敗測試**（unsupported 副檔名報錯、md 直收原文、xlsx 轉出 markdown 表格且數字保留、圖片進 assets/ 並回傳資產路徑）
- [ ] **Step 2: 跑測試確認失敗**
- [ ] **Step 3: 實作**（excel：`load_workbook(data_only=True)`，每個 sheet 一段 `## <sheet名>` ＋ md 表格；合併儲存格取左上值、其餘補空；上限 200 列 × 30 欄，截斷時在 md 尾註記「已截斷」）
- [ ] **Step 4: 跑測試通過後 commit**（`feat: ingest dispatcher 與 md/excel 轉換`）

---

### Task 4: Ingest — docx 與 pdf

**Files:**
- Create: `backend/app/ingest/docx_converter.py`、`pdf_converter.py`
- Test: `backend/tests/test_ingest_docs.py`、fixtures 在 conftest 動態產生（docx 用 python-docx 寫入標題＋段落＋表格；pdf 用 PyMuPDF 新建一頁含大字標題與內文）

- [ ] **Step 1: 寫失敗測試**（docx：Heading 1 → `#`、表格 → md 表格；pdf：字級最大的行成為 `#` 標題、內文保留、嵌入圖片被抽到 assets/ 且 md 內有 `![](assets/...)` 引用）
- [ ] **Step 2: 跑測試確認失敗**
- [ ] **Step 3: 實作**

docx：走訪 `document.body` 依序處理段落（`style.name` 含 "Heading N" → `#`*N）與表格。`.doc`/`.odt` 等舊格式 → `UnsupportedFormatError("請先另存為 .docx")`。

pdf：`fitz.open` 逐頁 `get_text("dict")` 取 span；以「字級 ≥ 頁面最常見字級 × 1.3」判定標題；`page.get_images()` 抽圖存 assets/（MD5 去重、跳過 < 100×100 的小圖）。MVP 不做向量圖 rasterize 與表格抽取（Phase 2 再加，於 md 尾註記「PDF 表格可能遺漏」）。

- [ ] **Step 4: 跑測試通過後 commit**（`feat: docx 與 pdf 轉 markdown`）

---

### Task 5: 風格目錄與移植

**Files:**
- Create: `styles/visual/`（4 檔）、`styles/palettes/`（3 檔）、`vendor/NOTICE`、`backend/app/styles/catalog.py`
- Test: `backend/tests/test_styles.py`

- [ ] **Step 1: 取得 ppt-master 原始檔**

```bash
git clone --depth 1 https://github.com/hugohe3/ppt-master /tmp/ppt-master-src
ls /tmp/ppt-master-src/skills/ppt-master/references/visual-styles/
```

- [ ] **Step 2: 移植 4 種風格＋3 種色盤**

複製 `swiss-minimal.md`、`soft-rounded.md`、`dark-tech.md`、`editorial.md` 到 `styles/visual/`；從 `references/image-palettes/` 挑 `cool-corporate` 等 3 種到 `styles/palettes/`。每檔加 YAML frontmatter：`id`、`name_zh`、`tagline_zh`（一句中文類比，顯示於 GUI）。建 `vendor/NOTICE` 註明來源 repo、MIT 授權與版權聲明。

- [ ] **Step 3: 寫 catalog 失敗測試**（`list_styles()` 回傳 4 筆含 id/name_zh；`load_style("swiss-minimal")` 回傳全文；不存在的 id raise KeyError）
- [ ] **Step 4: 實作 `catalog.py`**（啟動時掃描目錄、解析 frontmatter，快取於模組層）
- [ ] **Step 5: 跑測試通過後 commit**（`feat: 視覺風格與色盤目錄（移植自 ppt-master, MIT）`）

---### Task 6: 大綱生成

**Files:**
- Create: `backend/app/generation/outline.py`
- Test: `backend/tests/test_outline.py`

**輸出格式（存 `outline.md` 旁另存結構化 `outline.json`）：**

```json
{"slides": [{"index": 0, "title": "封面：Q2 營運回顧", "bullets": ["..."], "layout_hint": "cover", "assets": []}]}
```

`layout_hint` ∈ `cover|section|bullets|two-column|table|chart|image|closing`。

- [ ] **Step 1: 寫失敗測試**

```python
def test_outline_happy_path(fake_llm_outline):
    # FakeLLM 回傳合法 JSON（包在 ```json fence 裡）→ 解析成功、寫入 outline.json
    # 斷言 prompt 內含來源 md 內容與風格名稱
def test_outline_bad_json_retries_once():
    # 第一次回垃圾、第二次合法 → 成功且 FakeLLM.calls == 2，第二次 prompt 含錯誤說明
def test_outline_bad_json_twice_raises():
    # 兩次都壞 → raise OutlineError
```

- [ ] **Step 2: 跑測試確認失敗**
- [ ] **Step 3: 實作**

`generate_outline(llm, project, style_id, palette_id) -> dict`：組 prompt（角色：簡報策略師；輸入：全部 md 檔內容＋資產清單＋風格檔全文；要求：繁體中文、輸出唯一 ```json fence、每頁一個 layout_hint）；解析用「找第一個 ```json fence，fallback 找第一個 `{` 到最後一個 `}`」；用手寫驗證函式檢查欄位與 layout_hint 枚舉（不引入 jsonschema 依賴）；失敗重試 1 次並附錯誤原因。成功後寫 `outline.json` 與人類可讀 `outline.md`，`project.stage = "outline"`，並依頁數初始化 `slides` 狀態表（全 `pending`）。

- [ ] **Step 4: 跑測試通過後 commit**（`feat: 大綱生成與 JSON 驗證`）

---

### Task 7: SVG 品質檢查

**Files:**
- Create: `backend/app/generation/quality.py`
- Test: `backend/tests/test_quality.py`

```python
def check_svg(svg_text: str) -> list[str]:
    """回傳問題清單（空 = 通過）。檢查：
    1. XML 可解析（xml.etree）且根元素為 svg
    2. 有 viewBox 且為 "0 0 1280 720"
    3. 文字溢出啟發式：每個 <text> 估寬 = Σ(CJK字元×font_size + 其他×font_size×0.6)，
       x + 估寬 > viewBox 寬 → 回報「text『<前10字>』超出右緣 <n>px」
    4. 禁用元素：<image> 的 href 必須是 assets/ 相對路徑或 data URI（防外連）
    """
```

- [ ] **Step 1: 寫失敗測試**（合法 SVG → `[]`；壞 XML → 含 "XML"；溢出 text → 訊息含估算像素；外連 image → 被抓出）
- [ ] **Step 2: 跑測試確認失敗 → 實作 → 通過**
- [ ] **Step 3: Commit**（`feat: SVG 品質檢查器`）

---

### Task 8: 逐頁 SVG 生成（含續跑與帶錯誤重生）

**Files:**
- Create: `backend/app/generation/slides.py`
- Test: `backend/tests/test_slides_gen.py`

- [ ] **Step 1: 寫失敗測試**

```python
def test_generates_all_pending_slides():
    # 3 頁大綱、FakeLLM 回 3 個合法 SVG → svg_output/ 有 slide_000~002.svg，狀態全 generated
    # 斷言每次 prompt 都含風格檔全文（spec lock：每頁重帶）與該頁大綱
def test_resume_skips_generated():
    # 第 0 頁已 generated → 只生成 1,2 頁（FakeLLM.calls == 2）
def test_bad_svg_regenerated_with_error_feedback():
    # 第一次回溢出 SVG、第二次合法 → 成功；第二次 prompt 內含 quality 錯誤訊息
def test_twice_bad_marks_failed_and_continues():
    # 某頁連兩次壞 → 該頁 status=failed，後續頁照常生成，函式不 raise
```

- [ ] **Step 2: 跑測試確認失敗**
- [ ] **Step 3: 實作**

`generate_slides(llm, project, on_progress=None) -> None`：讀 `outline.json` 與選定風格/色盤全文；逐頁循序：組 prompt（該頁大綱＋風格全文＋色盤＋「前一頁 SVG 的標題與主色」摘要以維持連貫＋固定約束：`viewBox="0 0 1280 720"`、繁體中文、僅輸出一個 ```svg fence 或 `<svg>` 原文、圖片僅可引用 assets/ 清單內路徑）→ 抽取 SVG → `check_svg` → 通過則寫 `svg_output/slide_{i:03d}.svg` 並 `set_slide_status(i,"generated")`＋`save()`（逐頁落盤=續跑依據）→ 不通過帶問題清單重生 1 次 → 仍失敗記 `failed` 繼續下一頁。全部跑完 `stage="generated"`。`on_progress(i, status)` callback 供 API 層記進度。

- [ ] **Step 4: 跑測試通過後 commit**（`feat: 逐頁 SVG 生成、spec lock、續跑與帶錯誤重生`）

---

### Task 9: Vendor svg_to_pptx 與匯出

**Files:**
- Create: `vendor/svg_to_pptx/`（複製自 ppt-master）、`backend/app/export/pptx_export.py`
- Modify: `vendor/NOTICE`
- Test: `backend/tests/test_export.py`

- [ ] **Step 1: Vendor 套件**

```bash
cp -R /tmp/ppt-master-src/skills/ppt-master/scripts/svg_to_pptx vendor/svg_to_pptx
cp /tmp/ppt-master-src/LICENSE vendor/svg_to_pptx/LICENSE
```

- [ ] **Step 2: 讀懂它的進入點**

閱讀 `vendor/svg_to_pptx/` 的 `__init__.py` / CLI 進入檔，確認「多個 SVG 檔 → 一個 pptx」的呼叫方式與參數（頁面尺寸、輸出路徑），把發現記在 `pptx_export.py` 的 module docstring。**若其依賴 ppt-master 專案目錄結構，寫最薄的 adapter 補齊它要的輸入，不修改 vendor 內部檔案**（升級可替換）。

- [ ] **Step 3: 寫失敗測試**

```python
def test_export_produces_editable_pptx(tmp_path, sample_svgs):
    # 2 個簡單 SVG（矩形+text）→ export_pptx() → 檔案存在
    # python-pptx 重新打開：len(prs.slides)==2，第一頁至少一個 shape 的 text 含預期字串
def test_failed_slide_skipped_with_warning():
    # 1 個合法 + 1 個 status=failed 的頁 → pptx 只含合法頁，回傳警告清單
```

- [ ] **Step 4: 實作 `export_pptx(project) -> ExportResult`**（收集 `status=="generated"` 的 SVG 依序轉換；輸出 `exports/<name>_<YYYYMMDD_HHMMSS>.pptx`；單頁轉換 exception → 該頁降級：用 PyMuPDF 把該 SVG rasterize 成 PNG 塞成整頁圖片並記警告，全失敗才 raise）
- [ ] **Step 5: 跑測試通過後 commit**（`feat: vendored svg_to_pptx 匯出與元素級降級`）

**風險註記：** vendor 套件的 API 形狀是本計畫最大未知數。若 Step 2 發現它與 agent 流程深度耦合、無法在 30 分鐘內 adapter 化，停下來回報，改走備案：MVP 先用「SVG rasterize 成整頁 PNG 的 pptx」（PyMuPDF + python-pptx，可編輯性留到 Phase 2 解），並在 README 標注限制。

---

### Task 10: API 層

**Files:**
- Create: `backend/app/api/projects.py`、`backend/app/api/pipeline.py`
- Modify: `backend/app/main.py`（掛路由、CORS localhost、掛 `projects/` 靜態檔）
- Test: `backend/tests/test_api.py`（`TestClient`，LLM 以 dependency override 注入 FakeLLM）

**路由（全部 `/api` 前綴）：**

| Method | Path | 行為 |
|---|---|---|
| POST | `/projects` | `{name}` → 建專案 |
| GET | `/projects` / `/projects/{id}` | 清單／詳情（含 slides 狀態表） |
| POST | `/projects/{id}/upload` | multipart 多檔；白名單＋50MB 上限，逐檔 ingest，回每檔成功/失敗 |
| GET | `/styles` | 風格＋色盤目錄（id、name_zh、tagline_zh） |
| POST | `/projects/{id}/style` | `{style_id, palette_id}` 寫入 project.json |
| POST | `/projects/{id}/outline` | 同步呼叫 generate_outline，回 outline.json |
| PUT | `/projects/{id}/outline` | 使用者編輯後整份覆寫（驗證同 Task 6）＋重建 slides 狀態表 |
| POST | `/projects/{id}/generate` | `BackgroundTasks` 啟動 generate_slides，立即回 202 |
| GET | `/projects/{id}/progress` | 回 slides 狀態表（前端輪詢） |
| GET | `/projects/{id}/slides/{n}.svg` | 回 SVG 原文（`image/svg+xml`） |
| POST | `/projects/{id}/export` | 匯出，回 `{download_url, warnings}` |
| GET | `/projects/{id}/exports/{filename}` | 下載 pptx |

- [ ] **Step 1: 寫失敗測試**（建立→上傳 md→選風格→outline（FakeLLM）→generate→輪詢 progress 至全 generated→取 slide SVG→export 下載檔案 status 200；另測：超大檔 413、壞副檔名 422、對不存在專案 404）
- [ ] **Step 2: 跑測試確認失敗 → 實作 → 通過**（錯誤回應統一 `{"detail": "<友善中文訊息>"}`，不含堆疊；LLMError 依 kind 對應訊息如「API 金鑰無效，請檢查 LLM_API_KEY」）
- [ ] **Step 3: Commit**（`feat: FastAPI 路由層`）

---

### Task 11: 前端五步精靈

**Files:**
- Create: `frontend/`（Vite React 腳手架）、`src/api.js`、`src/App.jsx`、`src/steps/UploadStep.jsx`、`StyleStep.jsx`、`OutlineStep.jsx`、`PreviewStep.jsx`、`ExportStep.jsx`

- [ ] **Step 1: 腳手架**

```bash
cd frontend && npm create vite@latest . -- --template react && npm install
```

`vite.config.js` 加 `server.proxy: {"/api": "http://localhost:8000"}`。

- [ ] **Step 2: `src/api.js`**（thin wrapper：`createProject/upload/getStyles/setStyle/genOutline/putOutline/generate/getProgress/exportPptx`，非 2xx 一律 throw `detail` 訊息）

- [ ] **Step 3: `App.jsx` 步驟骨架**（state：`projectId`、`step`(1-5)、頂部步驟指示器、上一步/下一步；每步完成條件達成才可下一步）

- [ ] **Step 4: 各步驟元件**

- `UploadStep`：專案名輸入＋多檔拖放/選擇，逐檔顯示轉換結果與錯誤。
- `StyleStep`：風格卡片（name_zh＋tagline_zh）與色盤色票列，單選。
- `OutlineStep`：呼叫 genOutline 後以可編輯清單呈現（每頁：標題 input、bullets textarea、layout_hint select、刪除鈕、拖曳排序用上下移按鈕即可），儲存＝PUT outline。
- `PreviewStep`：按「開始生成」→ 每 2 秒輪詢 progress，縮圖格用 `<img src="/api/projects/{id}/slides/{n}.svg">` 逐頁點亮；failed 頁顯示紅框＋「生成失敗」；點縮圖開大圖 modal。
- `ExportStep`：匯出鈕→顯示 warnings→下載連結。

介面文案全繁體中文；樣式用素 CSS（單檔 `App.css`），不引 UI 庫（YAGNI，Phase 3 再說）。

- [ ] **Step 5: 手動驗證**（見 Task 12 的 E2E 環境）＋ commit（`feat: 五步精靈前端`）

---

### Task 12: Smoke E2E 與收尾

**Files:**
- Create: `backend/tests/test_e2e_smoke.py`、`backend/app/llm/fake_server.py`（可選）、`README.md` 補啟動說明

- [ ] **Step 1: 後端 E2E 測試**（TestClient＋FakeLLM 預錄「大綱 JSON＋N 頁 SVG」：上傳 sample.md → 全流程 → 匯出的 pptx 用 python-pptx 打開頁數正確。這是規格 9 節的 smoke E2E）
- [ ] **Step 2: 全測試套件跑綠**（`uv run pytest -v`，全部 PASS）
- [ ] **Step 3: README 補齊**（環境變數設定、`uvicorn app.main:app` ＋ `npm run dev` 啟動、目錄結構、vendor 授權說明）
- [ ] **Step 4: 真人手動走一遍**（設好真實 LLM 環境變數，上傳一份真 md，五步走完，PowerPoint 開啟匯出檔驗證可逐元素編輯——此步需使用者參與，記錄結果）
- [ ] **Step 5: Commit**（`docs: README 與 smoke E2E`）＋回報使用者，依 superpowers:finishing-a-development-branch 決定合併方式

---

## 驗收條件（對照規格）

1. 上傳 md/xlsx/docx/pdf/圖片 → 正確轉換或友善報錯（規格 4.1、8）
2. 大綱可在 GUI 編輯後才生成（規格 4.2）
3. 逐頁 SVG 生成可中斷續跑；壞頁不阻塞（規格 4.3、8）
4. 瀏覽器即時預覽 SVG（規格 7）
5. 匯出 .pptx 可被 PowerPoint/python-pptx 打開且文字可編輯（規格 4.4）
6. 全程無硬編碼金鑰；測試不打真實 API（規格 3.2、11）
