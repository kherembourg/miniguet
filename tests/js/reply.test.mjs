import test from "node:test"
import assert from "node:assert/strict"
import { composeMessage, DRAFTS, PREVIEWS, draftFor, makePreview } from "../../assets/app/reply.js"

// expected strings come from running the classic page's compose() in Node
test("yes/no only", () => {
  const a = [{ question: "Q1", choice: "Oui", text: "" }, { question: "Q2", choice: "Non", text: "" }]
  assert.equal(composeMessage("", a), "Réponses :\n1. Q1 → Oui\n2. Q2 → Non")
})
test("free text first, trimmed", () => {
  assert.equal(composeMessage("  Salut  ", [{ question: "Q1", choice: "Oui", text: "" }]), "Salut\n\nRéponses :\n1. Q1 → Oui")
})
test("precision after No", () => {
  assert.equal(composeMessage("", [{ question: "Q2", choice: "Non", text: " parce que X " }]), "Réponses :\n1. Q2 → Non, parce que X")
})
test("text only answer", () => {
  assert.equal(composeMessage("", [{ question: "Q3", choice: "", text: "peut-être" }]), "Réponses :\n1. Q3 → peut-être")
})
test("free text alone", () => assert.equal(composeMessage("seul", []), "seul"))
test("nothing gives empty string", () => assert.equal(composeMessage("", []), ""))

test("drafts survive and are per address", () => {
  const d = draftFor("a")
  d.free = "test"
  assert.equal(draftFor("a").free, "test")
  assert.equal(draftFor("b").free, "")
  assert.ok(DRAFTS.has("a"))
})

test("preview freezes since_ms and answered questions", () => {
  const d = draftFor("p")
  d.answers.set("Q1", { choice: "Oui", text: "" })
  const p = makePreview("p", ["Q1", "Q2"], 111)
  assert.deepEqual(p, { address: "p", text: "Réponses :\n1. Q1 → Oui", questions: ["Q1"], since_ms: 111 })
  assert.equal(PREVIEWS.get("p"), p)
})

test("preview refuses when nothing to send", () => {
  assert.equal(makePreview("empty", ["Q1"], 1), null)
})
