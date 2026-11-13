import { getState, getThread } from "./api.js"
import { grouped, waitingCount, groupOf, badge, summary, dlDays, isSnoozed, GROUPS } from "./groups.js"
import { renderDetail } from "./detail.js"

const $ = (id) => document.getElementById(id)
const el = (tag, cls, text) => {
  const e = document.createElement(tag)
  if (cls) e.className = cls
  if (text != null) e.textContent = text
  return e
}

let off = 0
let LAST = null
let SEL = null
let THREAD = { address: null, data: null, at: 0, key: "" }
let okAt = 0
let failed = false
let listSig = ""
let detailSig = ""
let version = 0
const t0 = Date.now()
const OPEN = new Set()
const hidden = new Set()   // "address\u0001text" removed on this page, until the server confirms
const nowMs = () => Date.now() + off

export const ctx = {
  nowMs,
  hidden,
  agent: (a) => (LAST ? LAST.agents.find((x) => x.address === a) : undefined),
  agents: () => (LAST ? LAST.agents : []),
  tick: () => tick(),
  render: () => { version++; if (LAST) render(LAST) },
  note: (msg) => toast(msg),
  undoToast: (msg, undo, ms = 12000) => toast(msg, undo, ms),
}

let toastTimer = null
function toast(msg, undo, ms = 8000) {
  $("tmsg").textContent = msg
  $("tund").style.display = undo ? "" : "none"
  $("tund").onclick = () => { $("toast").style.display = "none"; if (undo) undo() }
  $("toast").style.display = "flex"
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => ($("toast").style.display = "none"), ms)
}
$("tx").onclick = () => { $("toast").style.display = "none"; clearTimeout(toastTimer) }

export function age(ms) {
  const s = Math.max(0, Math.floor((nowMs() - ms) / 1000))
  if (s < 60) return s + " s"
  const m = Math.floor(s / 60)
  if (m < 60) return m + " min"
  const h = Math.floor(m / 60), mm = String(m % 60).padStart(2, "0")
  return h >= 24 ? Math.floor(h / 24) + " j " + (h % 24) + " h " + mm : h + " h " + mm
}

const name = (x) => x.space + (x.tab && x.tab !== "1" ? " / " + x.tab : "")
const dlText = (x) => {
  const n = dlDays(x)
  if (n === null) return ""
  const d = x.deadline.date.split("-").reverse().slice(0, 2).join("/")
  return n < 0 ? "en retard de " + -n + " j (" + d + ")" : n === 0 ? "aujourd'hui" : n === 1 ? "demain" : n < 7 ? "dans " + n + " j (" + d + ")" : d
}
export { dlText, name }

const fmtH = (ms) => new Date(ms).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })

function row(x, g, isNew) {
  const b = el("button", "row" + (isNew ? " flash" : "") + (x.unseen ? " unseen" : ""))
  b.type = "button"
  b.dataset.a = x.address
  b.style.setProperty("--gc", `var(--c-${g})`)
  if (x.address === SEL) b.setAttribute("aria-current", "true")
  const r1 = el("span", "r1")
  const nm = el("b", null, name(x))
  if (x.source) nm.append(el("i", "src", String(x.source).split("-").pop().slice(0, 4)))
  const ag = el("span", "age", x.since_ms ? age(x.since_ms) : "")
  ag.dataset.since = x.since_ms || ""
  r1.append(nm, ag)
  b.append(r1, el("span", "r2", badge(x, nowMs(), hidden).text))
  const s = summary(x, nowMs(), hidden)
  if (s) b.append(el("span", "r3", s))
  if (x.status === "working" && x.stalled_min) b.append(el("span", "r4", "⚠ bloquée ? depuis " + x.stalled_min + " min"))
  if (x.deadline) b.append(el("span", "r4" + (dlDays(x) <= 0 ? " hot" : ""), "⏰ " + dlText(x) + (x.deadline.note ? " · " + x.deadline.note : "")))
  if (g === "snoozed" && x.snooze) b.append(el("span", "r3", x.snooze.until >= 9e12 ? "jusqu'à nouvel ordre" : "jusqu'à " + fmtH(x.snooze.until)))
  return b
}

const PREV = new Map()
let first = true
function renderList(d) {
  const L = $("list")
  const groups = grouped(d.agents, nowMs(), hidden)
  const fresh = []
  const cur = new Map()
  for (const x of d.agents) cur.set(x.address, x.address + ":" + x.since_ms)
  const sig = JSON.stringify([groups.map((g) => [g.id, g.items]), SEL, [...OPEN]])
  if (sig === listSig) return cur
  listSig = sig
  const keep = L.scrollTop
  L.replaceChildren()
  if (!groups.length) L.append(el("p", "none", "Aucune session."))
  for (const g of groups) {
    const sec = el("div", "grp")
    sec.dataset.g = g.id
    const rows = el("div", "rows")
    for (const x of g.items) {
      const isNew = !first && g.id !== "working" && g.id !== "snoozed" && PREV.get(x.address) !== cur.get(x.address)
      if (isNew) fresh.push(x)
      rows.append(row(x, g.id, isNew))
    }
    const label = `${g.label} · ${g.items.length}`
    if (g.id === "working" || g.id === "snoozed") {
      const c = el("ui-collapsible")
      if (OPEN.has(g.id)) c.setAttribute("default-open", "")
      const tr = el("ui-collapsible-trigger")
      const bt = el("button", null, label)
      bt.type = "button"
      tr.append(bt)
      const panel = el("ui-collapsible-panel")
      panel.setAttribute("hidden", "")
      panel.append(rows)
      c.append(tr, panel)
      c.addEventListener("openchange", (e) => { e.detail.value ? OPEN.add(g.id) : OPEN.delete(g.id); listSig = "" })
      sec.append(c)
    } else {
      sec.append(el("h2", null, label), rows)
    }
    L.append(sec)
  }
  L.scrollTop = keep
  ctx.fresh = fresh
  return cur
}

function renderHeader(d) {
  const nw = waitingCount(d.agents, nowMs(), hidden)
  $("n").textContent = nw
  document.title = `(${nw}) Miniguet`
  const ag = d.agents.filter((x) => !isSnoozed(x, nowMs()))
  const late = ag.filter((x) => x.deadline && dlDays(x) <= 0).length
  const lat = ag.filter((x) => x.deadline && dlDays(x) < 0).length
  $("dlp").hidden = !late
  $("dlp").textContent = "⏰ " + late + (lat ? " aujourd'hui ou en retard" : " aujourd'hui")
  const links = $("links")
  links.replaceChildren(...(d.links || []).map((l) => { const a = el("a", null, l[0]); a.href = l[1]; return a }))
  ctx.view = { nw, hot: late > 0 || ag.some((x) => x.status === "error"), agents: d.agents }
}

function ensureSelection(d) {
  if (SEL && d.agents.some((x) => x.address === SEL)) return
  const g = grouped(d.agents, nowMs(), hidden)
  SEL = g.length ? g[0].items[0].address : null
}

async function refreshThread(agent) {
  if (!agent) { THREAD = { address: null, data: null, at: 0, key: "" }; return }
  const key = agent.address + ":" + agent.since_ms + ":" + agent.status
  if (THREAD.address === agent.address && THREAD.key === key && Date.now() - THREAD.at < 6000) return
  const same = THREAD.address === agent.address
  try {
    const data = await getThread(agent.address)
    THREAD = { address: agent.address, data, at: Date.now(), key }
  } catch (e) {
    THREAD = { address: agent.address, data: same ? THREAD.data : null, at: Date.now(), key }
  }
}

function renderDetailPane(d) {
  const x = d.agents.find((a) => a.address === SEL)
  const sig = JSON.stringify([x, THREAD.data, version, [...hidden]])
  if (sig === detailSig) return
  detailSig = sig
  const D = $("detail")
  const ae = document.activeElement
  const fk = ae && D.contains(ae) && ae.dataset ? ae.dataset.fk : null
  const sel = fk && ae.selectionStart != null ? [ae.selectionStart, ae.selectionEnd] : null
  const top = D.scrollTop
  renderDetail(x, x && THREAD.address === x.address ? THREAD.data : null, D, ctx)
  D.scrollTop = top
  if (fk) {
    const n = D.querySelector(`[data-fk="${CSS.escape(fk)}"]`)
    if (n) { n.focus(); if (sel && n.setSelectionRange) n.setSelectionRange(sel[0], sel[1]) }
  }
}

function render(d) {
  LAST = d
  off = d.now_ms - Date.now()
  ensureSelection(d)
  renderHeader(d)
  const cur = renderList(d)
  renderDetailPane(d)
  document.querySelectorAll("[data-since]").forEach((e) => { e.textContent = e.dataset.since ? age(+e.dataset.since) : "" })
  for (const [k, v] of PREV) if (!cur.has(k)) cur.set(k, v)
  PREV.clear(); for (const [k, v] of cur) PREV.set(k, v)
  first = false
  ctx.onRender?.(d)
}

$("list").addEventListener("click", (e) => {
  const b = e.target.closest(".row")
  if (!b) return
  SEL = b.dataset.a
  document.body.classList.add("open")
  listSig = ""
  ctx.render()
  tick()
})
export function closeDetail() { document.body.classList.remove("open") }
ctx.closeDetail = closeDetail

const down = () => failed || Date.now() - (okAt || t0) > 15000
ctx.down = down
let B = null
function banner() {
  const dn = down()
  document.body.classList.toggle("stale", dn)
  if (!dn) { if (B) { B.remove(); B = null } return }
  if (!B) { B = el("div"); B.id = "down"; document.body.prepend(B) }
  B.textContent = "Mac injoignable depuis " + age((okAt || t0) + off) + (okAt ? " — dernière mise à jour " + fmtH(okAt) : "")
}

let busy = false
async function tick() {
  if (busy) return
  busy = true
  try {
    let d
    try { d = await getState() } catch (e) { failed = true; $("err").textContent = "Erreur : " + e.message; return banner() }
    failed = false
    okAt = Date.now()
    ensureSelection(d)
    await refreshThread(d.agents.find((x) => x.address === SEL))
    try { $("err").textContent = ""; render(d) } catch (e) { $("err").textContent = "Erreur : " + e.message }
    banner()
  } finally { busy = false }
}

/* Stats / Daily / Historique open as an overlay so this page, and the music, never unload. */
const OV = ["/stats", "/daily", "/daily/history"]
function showFrame(href) { $("fr").contentWindow.location.replace(href + (href.includes("?") ? "&" : "?") + "embed=1"); $("frame").hidden = false }
function openFrame(href) { history.pushState({ fr: 1, href }, "", href); showFrame(href) }
function closeFrame() { if ($("frame").hidden) return; $("frame").hidden = true; $("fr").contentWindow.location.replace("about:blank") }
function goHome() { closeFrame(); if (location.pathname !== "/") history.pushState(null, "", "/") }
$("links").addEventListener("click", (e) => { const a = e.target.closest("a"); if (!a) return; e.preventDefault(); openFrame(a.getAttribute("href")) })
window.addEventListener("message", (e) => {
  const m = e.data
  if (e.origin !== location.origin || !m) return
  if (m.mg === "close") goHome()
  else if (m.mg === "open" && OV.includes(String(m.href).split("?")[0])) openFrame(m.href)
})
window.addEventListener("popstate", (e) => { const s = e.state; if (s && s.fr) showFrame(s.href); else closeFrame() })
if (OV.includes(location.pathname)) {
  const u = location.pathname + location.search
  history.replaceState(null, "", "/")
  history.pushState({ fr: 1, href: u }, "", u)
  showFrame(u)
}

tick()
setInterval(tick, 2000)
setInterval(() => { banner(); document.querySelectorAll("[data-since]").forEach((e) => { e.textContent = e.dataset.since ? age(+e.dataset.since) : "" }) }, 1000)
