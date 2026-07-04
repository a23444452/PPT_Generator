# PPT Generator 設計規格

日期：2026-07-04
狀態：已與使用者確認核准

## 1. 目標與背景

公司內部經常需要製作簡報。本專案要做一個**本機單人使用的 PPT 產生器 GUI**：

- 使用者上傳「範例 PPT」與「資料檔」（pdf / word / md / excel / 圖片）
- 系統以範例 PPT 的風格為預設，或透過場景問答推薦設計風格
- GUI 內即時預覽產出的簡報，可自然語言或直接編輯調整
- 最終匯出**可在 PowerPoint 中逐元素編輯的 .pptx**

設計大量借鏡 [hugohe3/ppt-master](https://github.com/hugohe3/ppt-master)（MIT License）：SVG 中介格式、`svg_to_pptx` 轉換器、風格/色彩解耦目錄、Safe-Shifted-Bold 三選一推薦光譜、範例 PPT 風格萃取流程。ppt-master 本身是跑在 AI IDE 內的 agent workflow，本專案將其流程**服務化**為程式化呼叫 LLM API 的本機 Web 應用。

## 2. 已確認的關鍵決策

| 決策點 | 結論 |
|---|---|
| 部署形態 | 本機單人 Web 工具（localhost，非內網多人服務、非桌面打包） |
| 輸出 | HTML/SVG 即時預覽 ＋ 匯出可編輯 .pptx，兩者都要 |
| LLM | 公司內部模型，provider 層可抽換；預設 OpenAI-compatible 介面（`base_url`/`api_key`/`model` 環境變數），另留 Anthropic 原生 adapter |
| 技術棧 | Python 3.12（uv 管理）、FastAPI 後端、瀏覽器前端 |
| 架構 | 方案 A（SVG 中介、重新設計）為主幹 ＋ 方案 B（嚴格套版）為附屬模式 |
| 風格推薦 | 場景問答 → Safe/Shifted/Bold 三選一光譜；另保留「瀏覽全部風格」入口 |

## 3. 系統架構

```
瀏覽器 GUI（SPA）
   │  HTTP (localhost)
FastAPI 後端
   ├── ingest/        資料檔 → Markdown ＋ 資產庫
   ├── style/         風格萃取、風格目錄、場景推薦
   ├── generation/    大綱生成、逐頁 SVG 生成（模式 A）、套版填充（模式 B）
   ├── export/        svg_to_pptx（vendored from ppt-master, MIT）
   ├── llm/           provider 抽象層（OpenAI-compatible 預設 / Anthropic adapter）
   └── projects/      檔案系統專案儲存（無資料庫）
```

### 3.1 專案儲存（檔案系統）

```
projects/<專案名>/
  source/          原始上傳檔
  md/              轉換後 markdown ＋ 抽取的表格
  assets/          抽取與上傳的圖片
  design_spec.md   風格規格（萃取或推薦產出）
  outline.md       確認後的大綱
  svg_output/      每頁一個 SVG
  exports/         匯出的 .pptx（帶時間戳）
  project.json     狀態、選定風格、pipeline 進度
```

`project.json` 至少記錄：目前 pipeline 階段（ingest / style / outline / generate / done）、選定模式（A/B）、選定風格與色盤 id、design_spec 是否已鎖定，以及**每頁生成狀態表**（`slides: [{index, status: pending|generated|failed, retries}]`）——這是 4.3 節「中斷可續跑」的依據。

無帳號、無資料庫；重開服務後專案仍在。

### 3.2 LLM Provider 層

- 介面：`complete(messages, system, max_tokens) -> str`，統一 retry with backoff、逾時、錯誤分類。
- 預設 adapter 走 OpenAI-compatible `/chat/completions`（涵蓋多數公司 gateway）；另附 Anthropic Messages API adapter。
- 設定來源：環境變數或 `config.toml`（`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`）。缺 key 直接啟動時報錯，不硬編碼。

## 4. 核心 Pipeline（模式 A：重新設計）

```
上傳資料檔 → 轉 Markdown → 大綱生成（可編輯）→ 逐頁 SVG 生成 → 預覽/調整 → 匯出 .pptx
上傳範例 PPT → 風格萃取 → design_spec ────────────┘（全程約束生成）
```

### 4.1 資料轉換（ingest）

依副檔名分派到專門 converter（借鏡 ppt-master 的 `source_to_md` dispatcher）：

| 格式 | 函式庫 | 重點 |
|---|---|---|
| PDF | PyMuPDF | 表格抽取轉 md、依字級推斷標題層級、向量圖表 rasterize 成 PNG、圖片 MD5 去重 |
| Excel | openpyxl (`data_only=True`) | 合併儲存格、型別格式化、行列數上限截斷 |
| Word | python-docx | .docx 原生處理；舊格式不支援（提示使用者另存 .docx） |
| Markdown | 直收 | — |
| 圖片 | 存入 assets/ | 供排版引用 |

### 4.2 大綱生成

LLM 讀 md ＋ design_spec ＋ 溝通模式，產出結構化大綱（頁序、每頁標題、要點、建議版型類型、引用的資產）。**使用者在 GUI 中可增刪改頁面後才進入生成**——在便宜的階段收斂，省 token 也省重生成。

### 4.3 逐頁 SVG 生成

- 每頁一次 LLM 呼叫，prompt 帶入：該頁大綱、design_spec 全文、選定視覺風格的規則檔、色盤、已生成前頁的縮要（維持連貫）。
- **spec lock**：design_spec 在生成期間唯讀鎖定，每頁 prompt 完整重帶，抵抗風格漂移（對應 ppt-master 的 spec_lock 機制）。
- 循序生成、逐頁落盤，中斷可續跑。

### 4.4 匯出

- Vendor ppt-master 的 `svg_to_pptx` 套件（MIT，保留版權聲明於 `vendor/` 目錄與 NOTICE 檔）：SVG → 原生 DrawingML shape / 原生表格與圖表，逐元素可編輯。
- 個別元素轉換失敗 → 該元素降級為點陣圖嵌入並記錄警告，不讓整份匯出失敗。

## 5. 風格系統

### 5.1 目錄結構：風格與色彩解耦

- `styles/visual/`：視覺風格庫，先移植 ppt-master 20 種中適合公司場景的 8–10 種（swiss-minimal、soft-rounded、glassmorphism、dark-tech、editorial、data-journalism、blueprint、sketch-notes 等），每種一個 md 規則檔＋一張 SVG 預覽縮圖。
- `styles/palettes/`：色盤庫，與風格正交組合。**支援鎖定公司品牌色**——鎖定後同事只挑版面風格，顏色不走鐘。
- 風格檔不含具體色值，只定義色彩的部署方式（60-30-10、飽和度、對比策略）。

### 5.2 範例 PPT 風格萃取（預設路徑）

兩段式，確定性優先：

1. **程式化抽取**（python-pptx）：theme 色票、字型配對、版面統計（每頁元素數、圖文比、留白比例）→ 硬資料 JSON。
2. **LLM 語意摘要**：讀取硬資料＋master/layout 結構，產出 `design_spec.md`（品牌色部署、招牌裝飾元素、頁面性格、留白節奏）。

GUI 顯示萃取結果（色票、字型、風格描述）供使用者確認或修正後才鎖定。

### 5.3 場景問答推薦（無範例或想換風格）

1. 問 2–3 題：給誰看／簡報目的／正式程度。
2. LLM 對照風格目錄索引，回傳 **Safe / Shifted / Bold** 三個候選：
   - Safe＝產業常規、Shifted＝同調性但更有表現力、Bold＝大膽但貼合內容
   - 每個候選附預覽縮圖＋一句真實世界類比（如「像 The Economist 的專題報導」）
3. 保留「瀏覽全部風格」入口，縮圖牆自選。

## 6. 模式 B：嚴格套版

使用者勾選「完全沿用範例版型」時：

- python-pptx 解析範例 master/layout placeholder → LLM 只生成文字內容對應填入 → 直接產出 pptx，不經 SVG pipeline。
- 預覽：LibreOffice headless 轉頁面圖片（若未安裝 LibreOffice，降級為「無預覽、直接下載」並提示）。
- 適合月報、週報等格式固定場景。

## 7. GUI 流程與預覽調整

單頁 SPA，五步精靈式流程，可回上一步：

1. **建立專案**：上傳資料檔＋（可選）範例 PPT，勾選模式 A/B。
2. **風格**：有範例 PPT 時預設進「萃取結果確認」，不跳問答；使用者可主動切換到「場景問答三選一」或「縮圖牆自選」（三個入口以分頁籤並列）。
3. **大綱**：檢視、增刪改、排序後確認。
4. **預覽調整**：縮圖格總覽＋單頁放大。調整兩條路——
   - 自然語言指令單頁重生成（「這頁改兩欄」），不動其他頁；
   - 輕量直接編輯：點文字改字、拖曳移動元素、Ctrl+Z（借鏡 ppt-master svg_editor 的 client 暫存＋按存檔才落盤模型）。
5. **匯出**：產出 .pptx 到 exports/ 並提供下載。

前端以輕量為原則（Vite + 單一框架即可），所有狀態存後端 project.json，重整不丟失。

## 8. 錯誤處理

- 上傳：類型白名單、單檔大小上限（預設 50MB）、損壞檔友善提示；錯誤訊息不洩內部堆疊。
- SVG 品質檢查：生成後程式化驗證（XML 合法、viewBox 正確、文字溢出啟發式偵測），不合格自動重生 1 次；**重生 prompt 必須附上前次失敗的具體原因**（如「第 3 個 text 元素超出 viewBox 右緣 40px」），不是重跑同一個 prompt。再失敗則標記該頁待人工處理，不阻塞其他頁。
- LLM：retry with backoff（3 次）、逾時中止、錯誤分類（額度/網路/內容）對應提示。
- 匯出：元素級降級（見 4.4）。

## 9. 測試策略（標準級）

- 各格式 converter 單元測試（附樣本檔）。
- SVG 驗證器單元測試（合法/溢出/壞檔案例）。
- provider 層 mock 測試（retry、錯誤分類）。
- Smoke E2E：一份樣本 md → 大綱 → SVG（mock LLM 固定輸出）→ pptx 匯出成功且可被 python-pptx 重新打開。

## 10. 建置順序

1. **Phase 1 — MVP**：ingest → 大綱 → SVG 生成 → 預覽 → 匯出 pptx（風格從內建目錄手選）。
2. **Phase 2 — 風格系統**：範例 PPT 萃取 ＋ 場景問答三選一推薦。
3. **Phase 3 — 編輯強化**：自然語言單頁重生成、直接編輯、模式 B 套版。

## 11. 授權與合規

- ppt-master 為 MIT：vendor `svg_to_pptx` 與移植風格檔時保留原始版權聲明（NOTICE 檔），不使用其第三方品牌樣板（如 `templates/brands/anthropic/`）。
- API key 一律環境變數/設定檔，不進版控。
