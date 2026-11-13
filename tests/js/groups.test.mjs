import test from "node:test"
import assert from "node:assert/strict"
import { groupOf, grouped, waitingCount, badge, summary, GROUPS } from "../../assets/app/groups.js"

const NOW = 1_700_000_000_000

test("permission goes to approve", () => assert.equal(groupOf({ status: "blocked", kind: "permission" }, NOW), "approve"))
test("auth goes to error", () => assert.equal(groupOf({ status: "blocked", kind: "auth" }, NOW), "error"))
test("error status goes to error", () => assert.equal(groupOf({ status: "error" }, NOW), "error"))
test("done with open question", () => assert.equal(groupOf({ status: "done", q: { open: ["x"] } }, NOW), "question"))
test("blocked question goes to question", () => assert.equal(groupOf({ status: "blocked", kind: "question" }, NOW), "question"))
test("blocked without kind goes to question", () => assert.equal(groupOf({ status: "blocked" }, NOW), "question"))
test("done without question", () => assert.equal(groupOf({ status: "done", q: { open: [], todo: ["t"] } }, NOW), "review"))
test("snooze wins", () => assert.equal(groupOf({ status: "done", q: { open: ["x"] }, snooze: { until: NOW + 1e6 } }, NOW), "snoozed"))
test("expired snooze does not count", () => assert.equal(groupOf({ status: "done", q: { open: ["x"] }, snooze: { until: NOW - 1 } }, NOW), "question"))
test("idle goes to working", () => assert.equal(groupOf({ status: "idle" }, NOW), "working"))
test("working goes to working", () => assert.equal(groupOf({ status: "working" }, NOW), "working"))
test("snoozed open points are not visible", () => {
  const a = { status: "done", q: { open: ["x"] }, snoozed: [{ text: "x", until: NOW + 5e5 }] }
  assert.equal(groupOf(a, NOW), "review")
})
test("hidden points are not visible", () => {
  const a = { address: "a", status: "done", q: { open: ["x"] } }
  assert.equal(groupOf(a, NOW, new Set(["a\u0001x"])), "review")
})

test("grouped keeps GROUPS order and drops empty groups", () => {
  const ag = [
    { address: "w", status: "working", since_ms: 1 },
    { address: "e", status: "error", since_ms: 1 },
  ]
  assert.deepEqual(grouped(ag, NOW).map((g) => g.id), ["error", "working"])
  assert.equal(GROUPS.length, 6)
})

test("deadline today first in group, then most recent first", () => {
  const today = new Date()
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
  const ag = [
    { address: "new", status: "error", since_ms: 300 },
    { address: "old", status: "error", since_ms: 100 },
    { address: "dl", status: "error", since_ms: 50, deadline: { date: iso(today), note: "" } },
  ]
  const g = grouped(ag, NOW).find((x) => x.id === "error")
  assert.deepEqual(g.items.map((a) => a.address), ["dl", "new", "old"])
})

test("waitingCount excludes working and snoozed", () => {
  const ag = [
    { status: "working" },
    { status: "done", q: { open: ["x"] }, snooze: { until: NOW + 1e6 } },
    { status: "error" },
    { status: "blocked", kind: "permission" },
  ]
  assert.equal(waitingCount(ag, NOW), 2)
})

test("done analysed with nothing open is review but not counted", () => {
  const a = { status: "done", q: { open: [], todo: [] } }
  assert.equal(groupOf(a, NOW), "review")
  assert.equal(waitingCount([a], NOW), 0)
})

test("done with analysis pending or failed is counted", () => {
  assert.equal(waitingCount([{ status: "done", q: { pending: true } }, { status: "done", q: { error: "x" } }, { status: "done" }], NOW), 3)
})

test("badge labels", () => {
  assert.equal(badge({ status: "blocked", kind: "permission" }, NOW).text, "AUTORISATION")
  assert.equal(badge({ status: "blocked", kind: "question" }, NOW).text, "QUESTION")
  assert.equal(badge({ status: "blocked", kind: "auth" }, NOW).text, "CONNEXION REQUISE")
  assert.equal(badge({ status: "done", q: { open: ["a", "b"] } }, NOW).text, "2 QUESTIONS")
  assert.equal(badge({ status: "done", q: { open: [] } }, NOW).text, "TERMINÉ")
  assert.equal(badge({ status: "error" }, NOW).text, "ERREUR")
  assert.equal(badge({ status: "working" }, NOW).text, "TRAVAILLE")
})

test("summary prefers menu, then first open question, then msg", () => {
  assert.equal(summary({ status: "blocked", menu: { detail: "ls /tmp", question: "Do?" } }), "ls /tmp")
  assert.equal(summary({ status: "blocked", menu: { question: "Which?" } }), "Which?")
  assert.equal(summary({ status: "done", q: { open: ["première"] }, msg: "m" }), "première")
  assert.equal(summary({ status: "working", msg: "m" }), "m")
})
