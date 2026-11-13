import test from "node:test"
import assert from "node:assert/strict"
import { fieldKey } from "../../assets/app/reply.js"

test("free field key differs per session", () => assert.notEqual(fieldKey("free", "t1"), fieldKey("free", "t2")))
test("rafale key differs per question of the same session", () => assert.notEqual(fieldKey("raf", "t1", "Q1"), fieldKey("raf", "t1", "Q2")))
test("free and rafale keys of the same session never collide", () => assert.notEqual(fieldKey("free", "t1"), fieldKey("raf", "t1", "")))
test("same inputs give the same key", () => assert.equal(fieldKey("raf", "t1", "Q"), fieldKey("raf", "t1", "Q")))
