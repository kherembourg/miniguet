import { voiceAvailable, transcribe } from "./api.js"

const MAX_MS = 60000
let AVAILABLE = false
// Recording state outlives a re-render of the card: the button is rebuilt from it.
const S = { state: "idle", fk: "", rec: null, stream: null, started: 0, timer: 0, chunks: [] }

export async function initVoice() {
  AVAILABLE = !!(navigator.mediaDevices && window.MediaRecorder) && (await voiceAvailable())
}

const clock = () => {
  const s = Math.floor((Date.now() - S.started) / 1000)
  return "● " + Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0")
}

function paint() {
  document.querySelectorAll("button.mic").forEach((b) => {
    b.dataset.state = S.state
    b.textContent = S.state === "rec" ? clock() : S.state === "busy" ? "…" : "🎙"
    b.setAttribute("aria-label", S.state === "rec" ? "Arrêter la dictée" : "Dicter")
    b.closest("ui-button")?.toggleAttribute("disabled", S.state === "busy")
  })
}

function insert(text, ctx) {
  const t = document.querySelector(`[data-fk="${CSS.escape(S.fk)}"]`)
  if (!t) return ctx.note("Dictée terminée, mais le champ n'est plus affiché : " + text)
  t.value = t.value && !/\s$/.test(t.value) ? t.value + " " + text : t.value + text
  t.dispatchEvent(new Event("input", { bubbles: true }))
  t.focus()
  t.setSelectionRange(t.value.length, t.value.length)
}

async function stop(ctx) {
  clearInterval(S.timer)
  const rec = S.rec
  if (!rec || rec.state === "inactive") return
  rec.stop()
}

async function start(textarea, ctx) {
  try {
    S.stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  } catch (e) {
    return ctx.note("Micro refusé ou introuvable")
  }
  S.fk = textarea.dataset.fk
  S.chunks = []
  S.rec = new MediaRecorder(S.stream)
  S.rec.ondataavailable = (e) => e.data.size && S.chunks.push(e.data)
  S.rec.onstop = async () => {
    S.stream.getTracks().forEach((t) => t.stop())
    clearInterval(S.timer)
    const blob = new Blob(S.chunks, { type: S.rec.mimeType || "audio/mp4" })
    S.state = "busy"
    paint()
    try {
      insert(await transcribe(blob), ctx)
    } catch (e) {
      ctx.note(e.message)
    } finally {
      S.state = "idle"
      paint()
    }
  }
  S.rec.start()
  S.started = Date.now()
  S.state = "rec"
  S.timer = setInterval(() => {
    if (Date.now() - S.started >= MAX_MS) stop(ctx)
    paint()
  }, 500)
  paint()
}

export function micButton(textarea, ctx) {
  if (!AVAILABLE) return null
  const w = document.createElement("ui-button")
  const b = document.createElement("button")
  b.type = "button"
  b.className = "mic icon"
  w.append(b)
  b.addEventListener("click", () => {
    if (S.state === "rec") stop(ctx)
    else if (S.state === "idle") start(textarea, ctx)
  })
  queueMicrotask(paint)
  return w
}
