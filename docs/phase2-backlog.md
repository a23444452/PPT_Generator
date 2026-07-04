# Phase 2 待辦清單

來源：Phase 1 MVP（feat/mvp 分支）各輪 code review 與最終整合審查（2026-07-05）彙整。

## 功能債

| 項目 | 出處 | 說明 |
|---|---|---|
| 範例 PPT 風格萃取 | 規格 5.2 | Phase 2 主項：python-pptx 程式化抽取＋LLM 語意摘要 → design_spec |
| 場景問答三選一推薦 | 規格 5.3 | Safe/Shifted/Bold 光譜＋真實世界類比 |
| 模式 B 嚴格套版 | 規格 6 | python-pptx 填 layout placeholder＋LibreOffice 預覽 |
| 單頁自然語言重生成／直接編輯 | 規格 7 | Phase 3 |
| PDF 表格抽取與向量圖 rasterize | pdf_converter.py（md 尾註記） | MVP 僅文字＋點陣圖 |
| Excel 截斷上限體驗 | excel_converter.py | 200×30 硬上限，超出僅註記 |
| `spec_locked` 欄位接線或移除 | project.py:100 | 目前為孤兒欄位；prompt 層 spec-lock 已由 slides.py 實作 |
| docx 本地化標題樣式 | docx_converter.py `_HEADING_RE` 註解 | 「標題 1」等非英文樣式名不判為標題；可比對 style_id 放寬 |

## 技術債

| 項目 | 出處 | 說明 |
|---|---|---|
| 並發鎖缺失（TOCTOU） | projects.py:228,316 註解 | 單人本地可接受；多人/多分頁需鎖 |
| 前頁代表色啟發式 | slides.py | 背景 rect 優先、抓不到回 None |
| outline brace fallback 限制 | outline.py:206-220 註解 | JSON 前方帶花括號雜訊仍失敗（fence 為主路徑） |
| repo 根定位假設 | deps.py、catalog.py | 靠掃 styles/ 祖先目錄；打包部署需重驗 |
| `_drop_failed_slides` 正則 XML 處理 | pptx_export.py | 建議改 ElementTree |
| pptx_export.py 455 行 | Task 9 review | 可拆 assembly/fallback/href_guard |
| 上傳無 magic-byte 嗅探 | dispatcher.py | 副檔名白名單；多人上傳前補 |
| 色盤色票為前端示意色 | StyleStep.jsx PALETTE_SWATCHES | 後端色盤檔無 HEX；新增色盤需同步 |
| stale previewStage 一個 round-trip 視窗 | PreviewStep.jsx | 後端 422 保護，Minor |

## 測試債

| 項目 | 出處 | 說明 |
|---|---|---|
| 前端無自動化測試 | frontend/ | 計畫如此；Phase 2 可補元件測試 |
| 真人 PowerPoint 逐元素編輯驗證 | 計畫 Task 12 Step 4 | 需使用者以真實 LLM 走完五步並在 PowerPoint 驗證 |
| `_drop_failed_slides` 全失敗極端路徑 | pptx_export.py:340 | 覆蓋度較薄 |
