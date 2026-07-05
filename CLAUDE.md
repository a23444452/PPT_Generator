# PPT Generator — 專案指引（給 Claude Code 與開發者）

本機單人 PPT 產生器：上傳資料檔（pdf/word/md/excel/圖片）→ LLM 生成大綱與逐頁 SVG → 瀏覽器預覽調整 → 匯出**逐元素可編輯**的 .pptx。設計參考 [hugohe3/ppt-master](https://github.com/hugohe3/ppt-master)（MIT）。

## 目前狀態（2026-07-05）

- **Phase 1 MVP 已完成**並合入 main（137 個測試綠、前端 build 過、經 13 輪雙重 code review）。
- **尚未做真人驗收**：開發機無 LLM 金鑰，全部測試用 FakeLLM。第一件事見下方「驗收流程」。
- **Phase 2 未開工**：範例 PPT 風格萃取（規格 5.2）、場景問答三選一推薦（規格 5.3）、模式 B 嚴格套版（規格 6）。

## 關鍵文件

| 文件 | 內容 |
|---|---|
| `docs/superpowers/specs/2026-07-04-ppt-generator-design.md` | 完整設計規格（Phase 1–3 全貌），已與使用者確認 |
| `docs/superpowers/plans/2026-07-04-ppt-generator-mvp.md` | Phase 1 實作計畫（已全部執行完） |
| `docs/phase2-backlog.md` | Phase 2 待辦：功能債/技術債/測試債，各項附出處 |
| `vendor/NOTICE` | ppt-master MIT attribution |

## 驗收流程（在有 LLM 與範例 PPT 的機器上）

1. 環境變數（公司 gateway 為 OpenAI-compatible）：
   ```bash
   export LLM_BASE_URL=https://<gateway>/v1   # 不含 /chat/completions
   export LLM_API_KEY=<key>
   export LLM_MODEL=<model>
   ```
2. 啟動：`cd backend && uv sync && uv run uvicorn app.main:app --port 8000`；另開終端 `cd frontend && npm install && npm run dev`；瀏覽器開 http://localhost:5173
3. 上傳真實資料檔走完五步，PowerPoint 開 `projects/<id>/exports/` 下的 .pptx，確認文字/形狀可逐元素編輯。
4. 結果（成功或問題）記錄到 `docs/phase2-backlog.md` 頂部或告知 Claude Code。

## 開發慣例（沿用 Phase 1）

- **測試一律 `cd backend && uv run pytest`**（系統 python 缺套件會誤報失敗）。前端驗證：`npm run build && npm run lint`。
- **TDD**：先紅後綠；修 bug 先寫重現測試。
- **`vendor/` 不可修改**：來自 ppt-master，升級整包替換；需要不同行為時在 `backend/app/export/pptx_export.py` 的 adapter 層處理。
- **commit**：`<type>: <繁中描述>`，atomic，git add 指定檔案。
- 檔案 IO 用 tmp+`os.replace` 原子寫入（見 `store/project.py`、`generation/outline.py` 慣例）。

## 架構速覽與易踩的坑

- `backend/app/`：`store/`（檔案系統持久層，無 DB）→ `ingest/`（格式轉 md）→ `generation/`（outline.py 大綱、slides.py 逐頁 SVG、quality.py 檢查）→ `export/`（vendored 轉換器 adapter）→ `api/`（FastAPI）；`llm/` 是唯一 LLM 出口。
- **`stage == "generated"` 只代表生成迴圈跑完，不代表每頁成功**——判斷成品要看 `project.json` 的 `slides[].status`；匯出自動跳過 failed 頁。
- stage 狀態機：`ingest → outline → generating → generated`；失敗回退 `outline`；server 重啟時 lifespan sweep 會清 stale `generating`（main.py）。
- 並發限制：單人單 worker 假設，同專案併發 generate 由 409 擋（有已知 TOCTOU 小窗口，見 backlog）。
- SVG 的 image href 僅允許 `assets/` 相對路徑或 data URI；quality.py 只做格式白名單，**實際讀檔的匯出層才做路徑正規化**（pptx_export.py `_guard_image_hrefs`）。
- 使用者專案資料在 repo 根 `projects/`（gitignored），可用 `PPT_PROJECTS_DIR` 覆寫。

## Phase 2 開工指引

1. 先讀規格 5.2/5.3/6 節與 `docs/phase2-backlog.md`。
2. 沿用 Phase 1 流程：寫實作計畫 → 逐 task 實作＋spec/品質雙審查。
3. 風格萃取的設計原則（規格已定）：先 python-pptx 程式化抽硬資料（色票/字型/版面統計），再 LLM 語意摘要成 design_spec——不要整段丟給 LLM 自由發揮。
