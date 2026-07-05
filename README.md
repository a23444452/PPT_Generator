# PPT Generator

本機單人 PPT 產生器：上傳文件（Markdown／docx／PDF／Excel），選擇視覺風格與色盤，交給 LLM 生成大綱與逐頁 SVG，最後匯出成可編輯的 PPTX。FastAPI 後端 + React 前端，無需資料庫，單人本地使用。

## 功能特色（五步流程）

1. **上傳文件**：支援 `.md`／`.txt`／`.docx`／`.pdf`／`.xlsx`／`.xlsm`，自動轉換為 Markdown 作為生成素材；也可直接上傳圖片（`.png`／`.jpg`／`.jpeg`）進專案素材庫，文件內嵌的圖片會抽取到專案 `assets/` 目錄供後續引用。
2. **選擇風格與色盤**：從內建視覺風格（如 swiss-minimal、soft-rounded、dark-tech、editorial）與色盤中挑選一組，決定整份簡報的視覺語言。
3. **產生大綱**：LLM 根據上傳內容與所選風格，生成分頁大綱（標題／條列重點／版型提示），使用者可在前端編輯後再送出。
4. **逐頁生成 SVG**：後端依大綱逐頁呼叫 LLM 產生 SVG 投影片，並跑品質檢查（尺寸、文字溢出、外部資源引用）；不通過會自動帶著問題清單重生一次，仍失敗則該頁標記失敗但不中斷其餘頁面。
5. **匯出 PPTX**：把每頁 SVG 轉換為原生 PowerPoint DrawingML 圖形（非純圖片，仍可在 PowerPoint 中編輯），單頁轉換失敗會降級為圖片並提示警告，不影響其他頁匯出。

## 環境需求

- **Python 3.12+** 與 [uv](https://docs.astral.sh/uv/)（後端套件管理與執行）
- **Node.js 18+** 與 npm（前端）
- 一組 **LLM API**（OpenAI 相容介面即可，例如 OpenAI、Azure OpenAI 相容代理、或任何實作 `/chat/completions` 的服務）

## 環境變數設定

後端啟動時需要以下環境變數，缺少任一個會直接報錯並提示「請參考 README 設定」：

| 變數 | 必要 | 說明 |
|---|---|---|
| `LLM_BASE_URL` | 是 | LLM API 的 base URL（OpenAI 相容介面，例如 `https://api.openai.com/v1`） |
| `LLM_API_KEY` | 是 | LLM API 金鑰 |
| `LLM_MODEL` | 是 | 呼叫的模型名稱（例如 `gpt-4o`） |
| `PPT_PROJECTS_DIR` | 否 | 專案資料存放目錄，預設為 repo 根目錄下的 `projects/` |

設定範例（**直接在 shell export 或寫入 `~/.zshrc`**；注意：後端不會自動載入 `.env` 檔，把變數寫在 `.env` 是無效的）：

```bash
export LLM_BASE_URL="https://api.openai.com/v1"   # 公司 gateway 則填其 base URL（不含 /chat/completions）
export LLM_API_KEY="sk-..."
export LLM_MODEL="gpt-4o"
```

## 首次安裝

```bash
git clone https://github.com/a23444452/PPT_Generator.git
cd PPT_Generator
cd backend && uv sync          # 建立虛擬環境並安裝後端依賴
cd ../frontend && npm install  # 安裝前端依賴
```

## 啟動方式

後端：

```bash
cd backend && uv run uvicorn app.main:app --port 8000
```

前端：

```bash
cd frontend && npm install && npm run dev
```

瀏覽器開啟 http://localhost:5173 即可使用；前端會呼叫本機 `:8000` 的後端 API。

## 目錄結構簡表

```
PPT_Generator/
├── backend/                  # FastAPI 後端
│   ├── app/
│   │   ├── api/              # 路由層（projects / pipeline / deps）
│   │   ├── ingest/           # 文件轉換（md / docx / pdf / xlsx）
│   │   ├── generation/       # 大綱生成、逐頁 SVG 生成、品質檢查
│   │   ├── export/           # SVG -> PPTX 匯出（薄 adapter，包裝 vendor）
│   │   ├── llm/               # LLM provider（OpenAI 相容介面）
│   │   ├── store/            # 專案狀態持久化（JSON 檔案）
│   │   ├── styles/           # 視覺風格／色盤目錄載入
│   │   └── config.py         # 環境變數設定
│   └── tests/                # pytest 測試（含 smoke E2E）
├── frontend/                  # React + Vite 前端（五步精靈 UI）
│   └── src/steps/             # 五步流程的各步驟元件
├── styles/                    # 視覺風格與色盤規則文件（改編自 ppt-master，見下方授權說明）
├── vendor/                    # 第三方程式碼（ppt-master 的 svg_to_pptx 轉換器，原封不動複製）
└── projects/                  # 執行期產生的專案資料（預設位置，可用 PPT_PROJECTS_DIR 覆寫）
```

## vendor 授權說明

`vendor/` 與 `styles/` 目錄部分內容改編／複製自第三方專案 [ppt-master](https://github.com/hugohe3/ppt-master)（MIT License，Copyright (c) 2025-2026 Hugo He）。

- `styles/visual/`、`styles/palettes/` 下的規則文件僅在檔案頂部加入 YAML frontmatter（供前端風格卡片顯示），原始內容逐字保留、未經翻譯或改寫。
- `vendor/svg_to_pptx/`、`vendor/svg_finalize/`、`vendor/console_encoding.py`、`vendor/resource_paths.py` 原封不動複製自 ppt-master 的 `scripts/`，未修改任何一行；`backend/app/export/pptx_export.py` 是薄 adapter，組合這些模組的既有函式，不修改 vendor 原始碼。

完整引用範圍與修改細節請見 `vendor/NOTICE`；原始 MIT 授權條文見 `vendor/svg_to_pptx/LICENSE`。

## 已知限制

誠實列出目前 MVP 階段尚未處理或刻意簡化的部分：

- **docx 標題辨識只認英文樣式名**：只有段落樣式名稱符合 `Heading N`（Word 內建英文樣式）才會轉為 Markdown 標題；本地化樣式名（如「標題 1」）不會被辨識，會被當成一般段落處理。
- **PDF 表格可能遺漏**：MVP 尚未實作表格抽取，PDF 轉換只處理文字與圖片，原始表格如有需要請人工確認轉換結果（輸出的 Markdown 檔尾會附註提醒）。
- **SVG 文字溢出檢查是啟發式估算**：依字元寬度粗略估算文字是否超出畫布右緣（中日韓文字視為全形寬度、其他視為半形 0.6 倍），非精確排版引擎的計算結果，可能有少量誤判或漏判。
- **假設單人單 worker**：專案狀態以本地 JSON 檔案儲存、無鎖機制，同一專案的併發生成／編輯請求可能有 TOCTOU 競態；MVP 定位為本機單人使用，不處理多使用者併發。
- **色盤色票為前端示意色**：風格選擇畫面上顯示的色票僅供選擇時參考觀感，非精確對應最終生成 SVG 使用的實際顏色（實際顏色由 LLM 依色盤規則文件生成，可能有些微落差）。
- **`stage == "generated"` 不代表每一頁都成功**：此狀態只表示逐頁生成流程已跑完（所有頁面都嘗試過），實際成功與否要看每頁各自的 `status`（`generated` / `failed`）；匯出時會跳過 `failed` 的頁面並回報 `skipped_count`。

## 執行測試

```bash
cd backend && uv run pytest -v
```

## 專案狀態與相關文件

Phase 1 MVP 已完成（2026-07-05）；範例 PPT 風格萃取、場景問答推薦、嚴格套版模式屬 Phase 2，尚未開工。

| 文件 | 內容 |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | 開發交接指引：驗收流程、開發慣例、架構速覽、Phase 2 入口 |
| [`docs/superpowers/specs/2026-07-04-ppt-generator-design.md`](docs/superpowers/specs/2026-07-04-ppt-generator-design.md) | 完整設計規格（Phase 1–3） |
| [`docs/phase2-backlog.md`](docs/phase2-backlog.md) | Phase 2 待辦清單（功能債／技術債／測試債） |
