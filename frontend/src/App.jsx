import { useState } from 'react'
import './App.css'
import UploadStep from './steps/UploadStep'
import StyleStep from './steps/StyleStep'
import OutlineStep from './steps/OutlineStep'
import PreviewStep from './steps/PreviewStep'
import ExportStep from './steps/ExportStep'

const STEP_LABELS = ['上傳素材', '選擇風格', '編輯大綱', '生成預覽', '匯出']

function App() {
  const [step, setStep] = useState(1)
  const [projectId, setProjectId] = useState(null)
  const [styleId, setStyleId] = useState(null)
  const [paletteId, setPaletteId] = useState(null)
  const [outline, setOutline] = useState(null)

  const canGoNext = {
    1: Boolean(projectId),
    2: Boolean(styleId && paletteId),
    3: Boolean(outline && outline.slides && outline.slides.length > 0),
    4: true,
    5: false,
  }[step]

  function goNext() {
    if (canGoNext && step < 5) setStep(step + 1)
  }

  function goPrev() {
    if (step > 1) setStep(step - 1)
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>PPT Generator</h1>
        <ol className="step-indicator">
          {STEP_LABELS.map((label, i) => {
            const n = i + 1
            const status = n === step ? 'active' : n < step ? 'done' : 'todo'
            return (
              <li key={label} className={`step-item step-${status}`}>
                <span className="step-num">{n}</span>
                <span className="step-label">{label}</span>
              </li>
            )
          })}
        </ol>
      </header>

      <main className="app-main">
        {step === 1 && (
          <UploadStep
            projectId={projectId}
            onProjectCreated={setProjectId}
          />
        )}
        {step === 2 && (
          <StyleStep
            projectId={projectId}
            styleId={styleId}
            paletteId={paletteId}
            onSelect={(s, p) => {
              setStyleId(s)
              setPaletteId(p)
            }}
          />
        )}
        {step === 3 && (
          <OutlineStep
            projectId={projectId}
            outline={outline}
            onOutlineChange={setOutline}
          />
        )}
        {step === 4 && (
          <PreviewStep projectId={projectId} outline={outline} />
        )}
        {step === 5 && <ExportStep projectId={projectId} />}
      </main>

      <footer className="app-footer">
        <button
          type="button"
          className="btn btn-secondary"
          onClick={goPrev}
          disabled={step === 1}
        >
          上一步
        </button>
        {step < 5 && (
          <button
            type="button"
            className="btn btn-primary"
            onClick={goNext}
            disabled={!canGoNext}
          >
            下一步
          </button>
        )}
      </footer>
    </div>
  )
}

export default App
