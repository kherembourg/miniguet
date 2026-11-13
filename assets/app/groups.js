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
export function waitingCount(agents, nowMs, hidden = new Set()) {
  return agents.filter((a) => {
    if (isSnoozed(a, nowMs)) return false
    if (a.status === "error" || a.status === "blocked") return true
    if (a.status !== "done") return false
    return !a.q || a.q.pending || a.q.error || openQuestions(a, nowMs, hidden).length > 0 || openTodos(a, nowMs, hidden).length > 0
  }).length
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
  return a.msg || a.title || ""
}
