import test from "node:test"
import assert from "node:assert/strict"
import { waitingAgents, waitingCount, watching, summary } from "../../assets/app/groups.js"

const NOW = 1_700_000_000_000

test("waitingAgents is the set behind waitingCount", () => {
  const ag = [
    { address: "a", status: "done", q: { open: [], todo: ["t"] } },
    { address: "b", status: "working" },
    { address: "c", status: "blocked", kind: "permission" },
    { address: "d", status: "done", q: { open: [], todo: [] } },
  ]
  assert.deepEqual(waitingAgents(ag, NOW).map((a) => a.address), ["a", "c"])
  assert.equal(waitingCount(ag, NOW), 2)
})

test("a finished session with background tasks is watching", () => {
  const a = { status: "done", q: { open: [], todo: [], bg: { monitors: 2, shells: 1 } } }
  assert.equal(watching(a, NOW), "surveille (2 monitors, 1 shell)")
  assert.equal(summary(a, NOW), "surveille (2 monitors, 1 shell)")
})

test("a finished session with something open is not watching", () => {
  assert.equal(watching({ status: "done", q: { open: ["x"], bg: { monitors: 1, shells: 0 } } }, NOW), "")
})

test("no background task, not watching", () => {
  assert.equal(watching({ status: "done", q: { open: [], bg: { monitors: 0, shells: 0 } } }, NOW), "")
  assert.equal(watching({ status: "working", q: { bg: { monitors: 1, shells: 0 } } }, NOW), "")
})
