import test from "node:test"
import assert from "node:assert/strict"
import { gateCheck } from "../../assets/app/groups.js"

test("the first sight of a key disables for 1 s then enables, and flags the change once", () => {
  const s = {}
  assert.deepEqual(gateCheck(s, "panel", "a|1", 0), { disabled: true, changed: true })
  assert.deepEqual(gateCheck(s, "panel", "a|1", 999), { disabled: true, changed: false })
  assert.deepEqual(gateCheck(s, "panel", "a|1", 1050), { disabled: false, changed: false })
})

test("two views alternating different keys never disable each other beyond 1 s", () => {
  const s = {}
  gateCheck(s, "panel", "t2|1", 0)
  gateCheck(s, "rafale", "t3|1", 10)
  for (let t = 100; t < 1000; t += 100) {
    assert.equal(gateCheck(s, "panel", "t2|1", t).changed, false)
    assert.equal(gateCheck(s, "rafale", "t3|1", t).changed, false)
  }
  assert.equal(gateCheck(s, "panel", "t2|1", 1050).disabled, false)
  assert.equal(gateCheck(s, "rafale", "t3|1", 1060).disabled, false)
})

test("a view showing the other view's last key still gets its own 1 s window, then enables", () => {
  const s = {}
  gateCheck(s, "panel", "t2|1", 0)
  assert.deepEqual(gateCheck(s, "rafale", "t2|1", 2000), { disabled: true, changed: true })
  assert.equal(gateCheck(s, "rafale", "t2|1", 3050).disabled, false)
})

test("the same key within one view stays enabled after 1 s", () => {
  const s = {}
  gateCheck(s, "rafale", "a|1", 0)
  assert.equal(gateCheck(s, "rafale", "a|1", 1500).disabled, false)
  assert.equal(gateCheck(s, "rafale", "a|1", 9000).disabled, false)
})

test("a new key in one view restarts only that view's window", () => {
  const s = {}
  gateCheck(s, "panel", "a|1", 0)
  gateCheck(s, "rafale", "b|1", 0)
  assert.deepEqual(gateCheck(s, "rafale", "c|1", 5000), { disabled: true, changed: true })
  assert.equal(gateCheck(s, "panel", "a|1", 5000).disabled, false)
})
