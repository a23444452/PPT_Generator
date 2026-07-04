import { useEffect, useRef, useState } from 'react'
import { generate, getProgress } from '../api'

const POLL_INTERVAL_MS = 2000

export default function PreviewStep({ projectId, outline, onStageChange }) {
  const [stage, setStage] = useState(null)
  const [slides, setSlides] = useState([])
  const [lastError, setLastError] = useState(null)
  const [loaded, setLoaded] = useState(false)
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState(null)
  const [modalIndex, setModalIndex] = useState(null)
  const timerRef = useRef(null)

  function stopPolling() {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
  }

  function applyProgress(progress) {
    setStage(progress.stage)
    onStageChange?.(progress.stage)
    setSlides(progress.slides || [])
    setLastError(progress.last_error || null)
  }

  async function pollOnce() {
    try {
      const progress = await getProgress(projectId)
      applyProgress(progress)

      if (progress.stage === 'outline' && progress.last_error) {
        // 生成失敗，後端已把 stage 退回 outline：停止輪詢，等使用者重試。
        stopPolling()
      } else if (progress.stage === 'generated') {
        stopPolling()
      }
    } catch (err) {
      setStartError(err.message)
      stopPolling()
    }
  }

  // 掛載時先讀一次進度：若生成仍在進行（例如使用者切到別步再回來、或
  // 頁面重載），自動恢復輪詢；若已完成則直接顯示縮圖格。
  useEffect(() => {
    let cancelled = false
    getProgress(projectId)
      .then((progress) => {
        if (cancelled) return
        applyProgress(progress)
        setLoaded(true)
        if (progress.stage === 'generating') {
          timerRef.current = setInterval(pollOnce, POLL_INTERVAL_MS)
        }
      })
      .catch((err) => {
        if (cancelled) return
        setStartError(err.message)
        setLoaded(true)
      })
    return () => {
      cancelled = true
      stopPolling()
    }
    // 掛載時執行一次即可；pollOnce/applyProgress 為元件內函式，依賴僅 projectId。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  async function handleStart() {
    setStarting(true)
    setStartError(null)
    stopPolling()
    try {
      await generate(projectId)
      // 先啟動輪詢再立即刷新一次；pollOnce 在 stage 到達終態時會自行停止。
      timerRef.current = setInterval(pollOnce, POLL_INTERVAL_MS)
      await pollOnce()
    } catch (err) {
      setStartError(err.message)
      stopPolling()
    } finally {
      setStarting(false)
    }
  }

  const isGenerating = stage === 'generating'
  const hasFailure = stage === 'outline' && Boolean(lastError)
  const totalSlides = outline?.slides?.length ?? slides.length

  return (
    <section className="step-panel">
      <h2>步驟四：生成預覽</h2>

      {!loaded && <p className="hint-text">載入進度中…</p>}

      {loaded && !isGenerating && stage !== 'generated' && !hasFailure && (
        <button type="button" className="btn btn-primary" onClick={handleStart} disabled={starting}>
          {starting ? '啟動中…' : '開始生成'}
        </button>
      )}

      {startError && <p className="error-text">{startError}</p>}

      {hasFailure && (
        <div className="card error-card">
          <p className="error-text">生成失敗：{lastError}</p>
          <button type="button" className="btn btn-primary" onClick={handleStart} disabled={starting}>
            重試
          </button>
        </div>
      )}

      {isGenerating && <p className="hint-text">生成中，每 2 秒自動更新進度…</p>}

      {slides.length > 0 && (
        <div className="thumb-grid">
          {slides.map((s) => (
            <button
              type="button"
              key={s.index}
              className={`thumb-cell thumb-${s.status}`}
              onClick={() => s.status === 'generated' && setModalIndex(s.index)}
            >
              {s.status === 'generated' && (
                <img
                  src={`/api/projects/${projectId}/slides/${s.index}.svg`}
                  alt={`第 ${s.index + 1} 頁預覽`}
                />
              )}
              {s.status === 'pending' && <span className="thumb-placeholder">等待生成</span>}
              {s.status === 'failed' && (
                <span className="thumb-placeholder thumb-failed-label">
                  生成失敗（重試 {s.retries} 次）
                </span>
              )}
              <span className="thumb-index">第 {s.index + 1} 頁</span>
            </button>
          ))}
        </div>
      )}

      {stage === 'generated' && totalSlides > 0 && (
        <p className="hint-text">
          已完成生成，共 {slides.filter((s) => s.status === 'generated').length}／{totalSlides} 頁成功。可進入下一步匯出。
        </p>
      )}

      {modalIndex !== null && (
        <div className="modal-backdrop" onClick={() => setModalIndex(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <img
              src={`/api/projects/${projectId}/slides/${modalIndex}.svg`}
              alt={`第 ${modalIndex + 1} 頁大圖`}
            />
            <button type="button" className="btn btn-secondary" onClick={() => setModalIndex(null)}>
              關閉
            </button>
          </div>
        </div>
      )}
    </section>
  )
}
