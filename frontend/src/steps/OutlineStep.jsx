import { useEffect, useState } from 'react'
import { genOutline, putOutline } from '../api'

const LAYOUT_HINTS = [
  'cover',
  'section',
  'bullets',
  'two-column',
  'table',
  'chart',
  'image',
  'closing',
]

export default function OutlineStep({ projectId, outline, onOutlineChange }) {
  const [loading, setLoading] = useState(false)
  const [genError, setGenError] = useState(null)
  const [saveError, setSaveError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (outline || !projectId) return
    setLoading(true)
    setGenError(null)
    genOutline(projectId)
      .then((data) => onOutlineChange(data))
      .catch((err) => setGenError(err.message))
      .finally(() => setLoading(false))
  }, [projectId, outline, onOutlineChange])

  function updateSlide(index, patch) {
    const slides = outline.slides.map((s, i) => (i === index ? { ...s, ...patch } : s))
    onOutlineChange({ ...outline, slides })
    setSaved(false)
  }

  function removeSlide(index) {
    const slides = outline.slides.filter((_, i) => i !== index)
    onOutlineChange({ ...outline, slides })
    setSaved(false)
  }

  function moveSlide(index, dir) {
    const target = index + dir
    if (target < 0 || target >= outline.slides.length) return
    const slides = [...outline.slides]
    ;[slides[index], slides[target]] = [slides[target], slides[index]]
    onOutlineChange({ ...outline, slides })
    setSaved(false)
  }

  async function handleSave() {
    setSaving(true)
    setSaveError(null)
    setSaved(false)
    try {
      const result = await putOutline(projectId, outline)
      onOutlineChange(result)
      setSaved(true)
    } catch (err) {
      setSaveError(err.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleRegenerate() {
    setLoading(true)
    setGenError(null)
    try {
      const data = await genOutline(projectId)
      onOutlineChange(data)
      setSaved(false)
    } catch (err) {
      setGenError(err.message)
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <section className="step-panel"><p className="hint-text">大綱生成中，請稍候…</p></section>
  if (genError) {
    return (
      <section className="step-panel">
        <p className="error-text">{genError}</p>
        <button type="button" className="btn btn-primary" onClick={handleRegenerate}>
          重試
        </button>
      </section>
    )
  }
  if (!outline) return null

  return (
    <section className="step-panel">
      <h2>步驟三：編輯大綱</h2>

      <ul className="outline-list">
        {outline.slides.map((slide, i) => (
          <li key={i} className="outline-item">
            <div className="outline-item-header">
              <span className="outline-index">第 {i + 1} 頁</span>
              <div className="outline-item-actions">
                <button type="button" onClick={() => moveSlide(i, -1)} disabled={i === 0}>
                  上移
                </button>
                <button
                  type="button"
                  onClick={() => moveSlide(i, 1)}
                  disabled={i === outline.slides.length - 1}
                >
                  下移
                </button>
                <button type="button" className="btn-danger" onClick={() => removeSlide(i)}>
                  刪除
                </button>
              </div>
            </div>

            <label>標題</label>
            <input
              type="text"
              value={slide.title}
              onChange={(e) => updateSlide(i, { title: e.target.value })}
            />

            <label>要點（每行一項）</label>
            <textarea
              rows={4}
              value={(slide.bullets || []).join('\n')}
              onChange={(e) =>
                updateSlide(i, { bullets: e.target.value.split('\n') })
              }
            />

            <label>版面類型</label>
            <select
              value={slide.layout_hint}
              onChange={(e) => updateSlide(i, { layout_hint: e.target.value })}
            >
              {LAYOUT_HINTS.map((h) => (
                <option key={h} value={h}>
                  {h}
                </option>
              ))}
            </select>
          </li>
        ))}
      </ul>

      <div className="outline-footer">
        <button type="button" className="btn btn-secondary" onClick={handleRegenerate}>
          重新生成大綱
        </button>
        <button type="button" className="btn btn-primary" onClick={handleSave} disabled={saving}>
          {saving ? '儲存中…' : '儲存大綱'}
        </button>
      </div>

      {saveError && <p className="error-text">{saveError}</p>}
      {saved && <p className="hint-text">已儲存，可進入下一步。</p>}
    </section>
  )
}
