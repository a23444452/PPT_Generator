import { useEffect, useState } from 'react'
import { getStyles, setStyle } from '../api'

// 後端目錄只提供 name_zh／tagline_zh（色盤正文是給 LLM 看的行為描述，不含
// HEX 值），故色票僅為前端示意用色，非最終出稿實際配色。未知的 palette id
// 用預設灰階兜底，避免新增色盤時畫面壞掉。
const PALETTE_SWATCHES = {
  'cool-corporate': ['#1E3A5F', '#F8F9FA', '#D4AF37'],
  'editorial-classic': ['#22242A', '#F2EFE9', '#8C1D18'],
  'mono-ink': ['#111111', '#FFFFFF', '#7A7A7A'],
}
const DEFAULT_SWATCH = ['#4B5563', '#E5E7EB', '#9CA3AF']

export default function StyleStep({ projectId, styleId, paletteId, onSelect }) {
  const [styles, setStyles] = useState([])
  const [palettes, setPalettes] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const [saveError, setSaveError] = useState(null)
  const [saving, setSaving] = useState(false)
  // 本地暫存選取值：style 與 palette 各自單選、互不影響對方；只有兩者都
  // 選定後才呼叫後端（palette_id 為必填欄位，過早送出會被 422 拒絕）。
  const [pendingStyleId, setPendingStyleId] = useState(styleId)
  const [pendingPaletteId, setPendingPaletteId] = useState(paletteId)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getStyles()
      .then((data) => {
        if (cancelled) return
        setStyles(data.styles || [])
        setPalettes(data.palettes || [])
      })
      .catch((err) => {
        if (!cancelled) setLoadError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function pick(nextStyleId, nextPaletteId) {
    setPendingStyleId(nextStyleId)
    setPendingPaletteId(nextPaletteId)

    if (!projectId || !nextStyleId || !nextPaletteId) return

    setSaving(true)
    setSaveError(null)
    try {
      await setStyle(projectId, nextStyleId, nextPaletteId)
      onSelect(nextStyleId, nextPaletteId)
    } catch (err) {
      setSaveError(err.message)
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <section className="step-panel"><p className="hint-text">載入風格中…</p></section>
  if (loadError) return <section className="step-panel"><p className="error-text">{loadError}</p></section>

  return (
    <section className="step-panel">
      <h2>步驟二：選擇風格</h2>

      <h3>視覺風格</h3>
      <div className="card-grid">
        {styles.map((s) => (
          <button
            type="button"
            key={s.id}
            className={`style-card ${pendingStyleId === s.id ? 'style-card-selected' : ''}`}
            onClick={() => pick(s.id, pendingPaletteId)}
            disabled={saving}
          >
            <strong>{s.name_zh}</strong>
            <span>{s.tagline_zh}</span>
          </button>
        ))}
      </div>

      <h3>色盤</h3>
      <div className="card-grid">
        {palettes.map((p) => (
          <button
            type="button"
            key={p.id}
            className={`style-card ${pendingPaletteId === p.id ? 'style-card-selected' : ''}`}
            onClick={() => pick(pendingStyleId, p.id)}
            disabled={saving}
          >
            <div className="swatch-row">
              {(PALETTE_SWATCHES[p.id] || DEFAULT_SWATCH).map((hex, i) => (
                <span key={i} className="swatch" style={{ background: hex }} />
              ))}
            </div>
            <strong>{p.name_zh}</strong>
            <span>{p.tagline_zh}</span>
          </button>
        ))}
      </div>

      {saving && <p className="hint-text">儲存中…</p>}
      {saveError && <p className="error-text">{saveError}</p>}
      {styleId && paletteId && !saving && (
        <p className="hint-text">已選擇風格與色盤，可進入下一步。</p>
      )}
    </section>
  )
}
