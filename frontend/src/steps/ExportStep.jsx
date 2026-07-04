import { useState } from 'react'
import { exportPptx } from '../api'

export default function ExportStep({ projectId }) {
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  async function handleExport() {
    setExporting(true)
    setError(null)
    try {
      const data = await exportPptx(projectId)
      setResult(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setExporting(false)
    }
  }

  return (
    <section className="step-panel">
      <h2>步驟五：匯出</h2>

      {!result && (
        <button type="button" className="btn btn-primary" onClick={handleExport} disabled={exporting}>
          {exporting ? '匯出中…' : '匯出簡報'}
        </button>
      )}

      {error && <p className="error-text">{error}</p>}

      {result && (
        <div className="card">
          <p>
            已匯出 {result.exported_count} 頁
            {result.skipped_count > 0 && `（跳過 ${result.skipped_count} 頁）`}
          </p>

          {result.skipped_count > 0 && (
            <p className="error-text">
              有 {result.skipped_count} 頁生成失敗未納入匯出結果。
            </p>
          )}

          {result.warnings && result.warnings.length > 0 && (
            <ul className="warning-list">
              {result.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          )}

          <a className="btn btn-primary" href={result.download_url} download>
            下載簡報
          </a>
        </div>
      )}
    </section>
  )
}
