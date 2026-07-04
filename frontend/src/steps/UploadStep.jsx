import { useState } from 'react'
import { createProject, upload } from '../api'

export default function UploadStep({ projectId, onProjectCreated }) {
  const [name, setName] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState(null)

  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [results, setResults] = useState([])
  const [uploadError, setUploadError] = useState(null)

  async function handleCreateProject(e) {
    e.preventDefault()
    if (!name.trim()) return
    setCreating(true)
    setCreateError(null)
    try {
      const project = await createProject(name.trim())
      onProjectCreated(project.id)
    } catch (err) {
      setCreateError(err.message)
    } finally {
      setCreating(false)
    }
  }

  async function handleFiles(fileList) {
    const files = Array.from(fileList || [])
    if (files.length === 0 || !projectId) return
    setUploading(true)
    setUploadError(null)
    try {
      const res = await upload(projectId, files)
      setResults((prev) => [...prev, ...(res.results || [])])
    } catch (err) {
      setUploadError(err.message)
    } finally {
      setUploading(false)
    }
  }

  function onDrop(e) {
    e.preventDefault()
    setDragging(false)
    handleFiles(e.dataTransfer.files)
  }

  return (
    <section className="step-panel">
      <h2>步驟一：上傳素材</h2>

      {!projectId && (
        <form className="card" onSubmit={handleCreateProject}>
          <label htmlFor="project-name">專案名稱</label>
          <input
            id="project-name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="請輸入專案名稱"
          />
          <button type="submit" className="btn btn-primary" disabled={creating || !name.trim()}>
            {creating ? '建立中…' : '建立專案'}
          </button>
          {createError && <p className="error-text">{createError}</p>}
        </form>
      )}

      {projectId && (
        <>
          <p className="hint-text">專案已建立（ID：{projectId}），請上傳素材檔案。</p>

          <div
            className={`dropzone ${dragging ? 'dropzone-active' : ''}`}
            onDragOver={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
          >
            <p>將檔案拖放到此處，或</p>
            <label className="btn btn-secondary file-picker">
              選擇檔案
              <input
                type="file"
                multiple
                hidden
                onChange={(e) => handleFiles(e.target.files)}
              />
            </label>
          </div>

          {uploading && <p className="hint-text">上傳中…</p>}
          {uploadError && <p className="error-text">{uploadError}</p>}

          {results.length > 0 && (
            <ul className="file-result-list">
              {results.map((r, i) => (
                <li
                  key={`${r.filename}-${i}`}
                  className={r.success ? 'file-result-ok' : 'file-result-error'}
                >
                  <span className="file-name">{r.filename}</span>
                  {r.success ? (
                    <>
                      <span className="file-status">轉換成功（{r.output_type}）</span>
                      {r.warnings && r.warnings.length > 0 && (
                        <ul className="warning-list">
                          {r.warnings.map((w, wi) => (
                            <li key={wi}>{w}</li>
                          ))}
                        </ul>
                      )}
                    </>
                  ) : (
                    <span className="file-status file-status-error">
                      失敗：{r.error}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  )
}
