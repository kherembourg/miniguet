import test from "node:test"
import assert from "node:assert/strict"
import { detectFresh } from "../../assets/app/groups.js"

const NOW = 1_700_000_000_000
const A = (o) => ({ address: "a", since_ms: 1, ...o })
const run = (agents, prev = new Map(), first = false) => detectFresh(agents, prev, NOW, new Set(), first)

test("nothing is fresh on the first load", () => assert.equal(run([A({ status: "error" })], new Map(), true).fresh.size, 0))
test("a new error is fresh and rings as error", () => {
  const r = run([A({ status: "error" })])
  assert.deepEqual([...r.fresh], ["a"]); assert.equal(r.kind, "error")
})
test("a permission request is fresh", () => assert.equal(run([A({ status: "blocked", kind: "permission" })]).fresh.size, 1))
test("a finished turn with nothing open (review) is fresh", () => assert.equal(run([A({ status: "done", q: { open: [] } })]).fresh.size, 1))
test("a finished turn with analysis pending is fresh", () => assert.equal(run([A({ status: "done", q: { pending: true } })]).fresh.size, 1))
test("working is never fresh", () => assert.equal(run([A({ status: "working" })]).fresh.size, 0))
test("same address:since_ms is not fresh twice", () => {
  const first = run([A({ status: "done" })])
  assert.equal(run([A({ status: "done" })], first.cur).fresh.size, 0)
})
test("a later since_ms is fresh again", () => {
  const first = run([A({ status: "done" })])
  assert.equal(run([A({ status: "done", since_ms: 2 })], first.cur).fresh.size, 1)
})
test("a snoozed session is not fresh and wakes up as fresh", () => {
  const z = run([A({ status: "done", snooze: { until: NOW + 1e6 } })])
  assert.equal(z.fresh.size, 0)
  assert.equal(run([A({ status: "done" })], z.cur).fresh.size, 1)
})
test("deadline today rings as deadline", () => {
  const d = new Date(); const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
  assert.equal(run([A({ status: "done", deadline: { date: iso } })]).kind, "deadline")
})
test("a session missing for one poll is remembered", () => {
  const first = run([A({ status: "done" })])
  const gone = run([], first.cur)
  assert.equal(run([A({ status: "done" })], gone.cur).fresh.size, 0)
})
