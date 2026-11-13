export const GROUPS = [
  { id: "error", label: "En erreur" },
  { id: "approve", label: "Attend ton feu vert" },
  { id: "question", label: "Te pose une question" },
  { id: "review", label: "A fini, à relire" },
  { id: "working", label: "Travaille" },
  { id: "snoozed", label: "Reportées" },
]

const KEY = "\u0001"

export const isSnoozed = (a, nowMs) => !!a.snooze && a.snooze.until > nowMs

// points snoozed on one session and still asleep
export function snoozedPoints(a, nowMs) {
  return (a.snoozed || []).filter((s) => s.until > nowMs).map((s) => s.text)
}

// `hidden` holds "address\u0001text" keys removed on this page but not yet confirmed by the server
function visible(a, list, nowMs, hidden) {
  const asleep = new Set(snoozedPoints(a, nowMs))
  return (list || []).filter((t) => !hidden.has(a.address + KEY + t) && !asleep.has(t))
}

export const openQuestions = (a, nowMs, hidden = new Set()) => visible(a, a.q && a.q.open, nowMs, hidden)
export const openTodos = (a, nowMs, hidden = new Set()) => visible(a, a.q && a.q.todo, nowMs, hidden)

export function groupOf(a, nowMs, hidden = new Set()) {
  if (isSnoozed(a, nowMs)) return "snoozed"
  if (a.status === "error") return "error"
  if (a.status === "blocked") {
    if (a.kind === "auth") return "error"
    if (a.kind === "permission") return "approve"
    return "question"
  }
  if (a.status === "done") return openQuestions(a, nowMs, hidden).length ? "question" : "review"
  return "working"
}

export function dlDays(a) {
  if (!a.deadline) return null
  const [y, m, d] = a.deadline.date.split("-").map(Number)
  const t = new Date()
  return Math.round((new Date(y, m - 1, d) - new Date(t.getFullYear(), t.getMonth(), t.getDate())) / 864e5)
}

const urgent = (a) => {
  const n = dlDays(a)
  return n !== null && n <= 0
}

export function grouped(agents, nowMs, hidden = new Set()) {
  return GROUPS.map((g) => ({
    ...g,
    items: agents
      .filter((a) => groupOf(a, nowMs, hidden) === g.id)
      .sort((x, y) => Number(urgent(y)) - Number(urgent(x)) || (y.since_ms || 0) - (x.since_ms || 0)),
  })).filter((g) => g.items.length)
}

// same rule as the classic counter, plus every blocked session
export function waitingAgents(agents, nowMs, hidden = new Set()) {
  return agents.filter((a) => {
    if (isSnoozed(a, nowMs)) return false
    if (a.status === "error" || a.status === "blocked") return true
    if (a.status !== "done") return false
    return !a.q || a.q.pending || a.q.error || openQuestions(a, nowMs, hidden).length > 0 || openTodos(a, nowMs, hidden).length > 0
  })
}

export const waitingCount = (agents, nowMs, hidden = new Set()) => waitingAgents(agents, nowMs, hidden).length

// "surveille (2 monitors, 1 shell)": a finished session with nothing to answer but background tasks still running
export function watching(a, nowMs, hidden = new Set()) {
  const bg = a.status === "done" && a.q && a.q.bg
  if (!bg || !(bg.monitors + bg.shells)) return ""
  if (waitingAgents([a], nowMs, hidden).length) return ""
  const p = []
  if (bg.monitors) p.push(bg.monitors + " monitor" + (bg.monitors > 1 ? "s" : ""))
  if (bg.shells) p.push(bg.shells + " shell" + (bg.shells > 1 ? "s" : ""))
  return "surveille (" + p.join(", ") + ")"
}

export function badge(a, nowMs, hidden = new Set()) {
  if (a.status === "error") return { text: "ERREUR", tone: "error" }
  if (a.status === "blocked") {
    if (a.kind === "auth") return { text: "CONNEXION REQUISE", tone: "error" }
    if (a.kind === "permission") return { text: "AUTORISATION", tone: "approve" }
    return { text: "QUESTION", tone: "question" }
  }
  if (a.status === "done") {
    const n = openQuestions(a, nowMs, hidden).length
    if (n) return { text: n > 1 ? `${n} QUESTIONS` : "1 QUESTION", tone: "question" }
    return { text: "TERMINÉ", tone: "review" }
  }
  return { text: "TRAVAILLE", tone: "working" }
}

export function summary(a, nowMs = 0, hidden = new Set()) {
  if (a.menu && (a.menu.detail || a.menu.question)) return a.menu.detail || a.menu.question
  const open = a.status === "done" ? openQuestions(a, nowMs, hidden) : []
  if (open.length) return open[0]
  const w = watching(a, nowMs, hidden)
  if (w) return w
  return a.msg || a.title || ""
}

// A session is fresh when it newly enters a waiting group (error, approve, question, review),
// keyed on address:since_ms, so every finished turn rings once. `prev` is the map returned last time.
export function detectFresh(agents, prev, nowMs, hidden, first) {
  const cur = new Map()
  const fresh = new Set()
  let kind = "new"
  for (const x of agents) {
    const key = x.address + ":" + x.since_ms
    const asleep = isSnoozed(x, nowMs)
    cur.set(x.address, asleep ? "z" : key)
    if (first || asleep || prev.get(x.address) === key) continue
    if (!["error", "approve", "question", "review"].includes(groupOf(x, nowMs, hidden))) continue
    fresh.add(x.address)
    const n = dlDays(x)
    const k = x.status === "error" ? "error" : n !== null && n <= 1 ? "deadline" : "new"
    if (k === "error" || (k === "deadline" && kind === "new")) kind = k
  }
  for (const [k, v] of prev) if (!cur.has(k)) cur.set(k, v)  // blinking out of the list for a moment is not new on return
  return { fresh, kind: fresh.size ? kind : null, cur }
}
