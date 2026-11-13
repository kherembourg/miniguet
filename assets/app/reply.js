// Drafts live here, not in the DOM, so a refresh of the list never loses them.
export const DRAFTS = new Map()
export const PREVIEWS = new Map()

export function draftFor(address) {
  if (!DRAFTS.has(address)) DRAFTS.set(address, { free: "", answers: new Map() })
  return DRAFTS.get(address)
}

export function answerText(a) {
  const t = (a.text || "").trim()
  return a.choice && t ? a.choice + ", " + t : a.choice || t
}

export function composeMessage(free, answers) {
  const lines = answers.map((a, i) => i + 1 + ". " + a.question + " → " + answerText(a))
  return [(free || "").trim(), lines.length ? "Réponses :\n" + lines.join("\n") : ""].filter(Boolean).join("\n\n")
}

export function answeredOf(address, questions) {
  const d = draftFor(address)
  return questions
    .map((question) => ({ question, ...(d.answers.get(question) || { choice: "", text: "" }) }))
    .filter(answerText)
}

// Frozen on purpose: since_ms is the one the person saw, never the current one.
export function makePreview(address, questions, since_ms) {
  const answers = answeredOf(address, questions)
  const text = composeMessage(draftFor(address).free, answers)
  if (!text) return null
  const p = { address, text, questions: answers.map((a) => a.question), since_ms }
  PREVIEWS.set(address, p)
  return p
}

export function clearDraft(address) {
  DRAFTS.delete(address)
  PREVIEWS.delete(address)
}

// Key of a text field that voice input can fill: per session (and per question in the rafale).
export const fieldKey = (kind, address, question = "") => kind + "\u0001" + address + "\u0001" + question
