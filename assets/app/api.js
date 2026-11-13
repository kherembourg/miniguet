async function json(path, init) {
  let r
  try {
    r = await fetch(path, init)
  } catch (e) {
    throw new Error("Mac injoignable : " + e.message)
  }
  const d = await r.json()
  if (d && d.error) {
    const err = new Error(d.error)
    if (d.since_ms) err.since_ms = d.since_ms
    throw err
  }
  return d
}

export const getState = () => json("/api/state")
export const getThread = (address) => json("/api/thread?address=" + encodeURIComponent(address))
export const post = (path, body) => json(path, { method: "POST", body: JSON.stringify(body) })

export async function voiceAvailable() {
  try {
    return !!(await json("/api/voice")).available
  } catch (e) {
    return false
  }
}

function toBase64(blob) {
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve(String(r.result).split(",")[1] || "")
    r.onerror = () => reject(new Error("lecture de l'audio impossible"))
    r.readAsDataURL(blob)
  })
}

export async function transcribe(blob) {
  const audio = await toBase64(blob)
  return (await post("/api/transcribe", { audio, type: blob.type || "audio/mp4" })).text
}
