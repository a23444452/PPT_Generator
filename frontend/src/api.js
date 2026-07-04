// 薄封裝：所有呼叫走 /api 前綴（vite.config.js 已 proxy 到後端 :8000）。
// 非 2xx 一律 throw Error，訊息取自後端回應的 detail 欄位（找不到則用泛用訊息）。

const BASE = '/api'

async function request(path, options = {}) {
  let response
  try {
    response = await fetch(`${BASE}${path}`, {
      headers: options.body instanceof FormData
        ? undefined
        : { 'Content-Type': 'application/json' },
      ...options,
    })
  } catch {
    throw new Error('無法連線至伺服器，請確認後端服務是否啟動')
  }

  if (!response.ok) {
    let detail = `請求失敗（${response.status}）`
    try {
      const data = await response.json()
      if (data && typeof data.detail === 'string' && data.detail) {
        detail = data.detail
      }
    } catch {
      // 回應非 JSON，維持預設訊息
    }
    throw new Error(detail)
  }

  if (response.status === 204) {
    return null
  }
  return response.json()
}

export function createProject(name) {
  return request('/projects', {
    method: 'POST',
    body: JSON.stringify({ name }),
  })
}

export function upload(projectId, files) {
  const formData = new FormData()
  for (const file of files) {
    formData.append('files', file)
  }
  return request(`/projects/${projectId}/upload`, {
    method: 'POST',
    body: formData,
  })
}

export function getStyles() {
  return request('/styles')
}

export function setStyle(projectId, styleId, paletteId) {
  return request(`/projects/${projectId}/style`, {
    method: 'POST',
    body: JSON.stringify({ style_id: styleId, palette_id: paletteId }),
  })
}

export function genOutline(projectId) {
  return request(`/projects/${projectId}/outline`, {
    method: 'POST',
  })
}

export function putOutline(projectId, outline) {
  return request(`/projects/${projectId}/outline`, {
    method: 'PUT',
    body: JSON.stringify(outline),
  })
}

export function generate(projectId) {
  return request(`/projects/${projectId}/generate`, {
    method: 'POST',
  })
}

export function getProgress(projectId) {
  return request(`/projects/${projectId}/progress`)
}

export function exportPptx(projectId) {
  return request(`/projects/${projectId}/export`, {
    method: 'POST',
  })
}
