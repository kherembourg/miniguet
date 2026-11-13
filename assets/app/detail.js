import { badge, groupOf, openQuestions, openTodos, isSnoozed, dlDays } from "./groups.js"
import { post } from "./api.js"
import { draftFor, makePreview, clearDraft, PREVIEWS } from "./reply.js"
import { micButton } from "./voice.js"

const KEY = "\u0001"
const INF = 9e12
const isInf = (ms) => ms >= INF
const $ = (id) => document.getElementById(id)

function el(tag, cls, text) {
  const e = document.createElement(tag)
  if (cls) e.className = cls
  if (text != null) e.textContent = text
  return e
}
function btn(text, cls, onclick) {
  const w = el("ui-button")
  const b = el("button", cls, text)
  b.type = "button"
  if (onclick) b.addEventListener("click", onclick)
  w.append(b)
  return { w, b }
}
const name = (x) => x.space + (x.tab && x.tab !== "1" ? " / " + x.tab : "")
const ik = (a, t) => a + KEY + t

// ---- dates (ported from the classic page) ----
const pad2 = (n) => String(n).padStart(2, "0")
const iso = (d) => d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate())
const addDays = (n) => { const d = new Date(); d.setDate(d.getDate() + n); return iso(d) }
const fmtD = (ms) => new Date(ms).toLocaleDateString("fr-FR", { weekday: "short", day: "2-digit", month: "2-digit" })
const fmtH = (ms) => new Date(ms).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })
const when = (ms) => (new Date(ms).toDateString() === new Date().toDateString() ? "à " + fmtH(ms) : "le " + fmtD(ms) + " à " + fmtH(ms))
const until$ = (ms) => (isInf(ms) ? "jusqu'à nouvel ordre" : "jusqu'au " + fmtD(ms))
const at10 = (n) => { const d = new Date(); d.setDate(d.getDate() + n); d.setHours(10, 0, 0, 0); return +d }
const todayAt = (h) => { const d = new Date(); d.setHours(h, 0, 0, 0); return +d }
const localIso = (ms) => { const d = new Date(ms); return iso(d) + "T" + pad2(d.getHours()) + ":" + pad2(d.getMinutes()) }
const parseLocal = (v) => { const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(v || ""); return m ? +new Date(+m[1], m[2] - 1, +m[3], +m[4], +m[5]) : 0 }
const dflt = () => { const t = todayAt(10); return localIso(t > Date.now() + 6e5 ? t : t + 864e5) }
const mon10 = () => at10((8 - new Date().getDay()) % 7 || 7)
const short = (t) => (t.length > 60 ? t.slice(0, 60) + "…" : t)
const dlText = (x) => {
  const n = dlDays(x)
  if (n === null) return ""
  const d = x.deadline.date.split("-").reverse().slice(0, 2).join("/")
  return n < 0 ? "en retard de " + -n + " j (" + d + ")" : n === 0 ? "aujourd'hui" : n === 1 ? "demain" : n < 7 ? "dans " + n + " j (" + d + ")" : d
}
function since(ms) {
  if (!ms) return "date inconnue"
  const m = Math.max(1, Math.floor((Date.now() - ms) / 6e4))
  const t = m < 60 ? m + " min" : m < 1440 ? Math.floor(m / 60) + " h " + pad2(m % 60) : Math.floor(m / 1440) + " j " + Math.floor((m % 1440) / 60) + " h"
  return "il y a " + t + " (" + fmtD(ms) + " " + fmtH(ms) + ")"
}

// ---- page state that must survive a re-render ----
const EXPANDED = new Set()      // "Voir tout" opened: address|me / address|agent / address|menu
const SENDING = new Set()       // menu answers in flight: address
const SZV = {}, ITV = {}        // date-time being chosen, per session / per point
const LATER = new Set(), OPENI = new Set(), INFO = new Map()
const RES = new Map(), RESOPEN = new Set()
let MOREOPEN = false
const SN = new Map()            // point key -> until, optimistic until the next /api/state

const sendWarn = (x) =>
  x.status === "working" ? "la session travaille : l'envoi sera refusé tant qu'elle n'a pas fini"
  : x.status !== "done" ? "session « " + x.status + " » : envoi impossible"
  : x.q && x.q.draft ? "une réponse est tapée dans la session : l'envoi sera refusé" : ""

const plural = (n, w) => n + " " + w + (n > 1 ? "s" : "")

async function run(ctx, fn, okMsg) {
  try {
    const r = await fn()
    if (okMsg) ctx.note(okMsg)
    return r
  } catch (e) {
    ctx.note(e.message)
  } finally {
    ctx.tick()
  }
}

// ---- menu answers (autorisation / choix) ----
const ROLE_LABEL = { approve: "Approuver", always: "Toujours", deny: "Refuser" }

export async function chooseOption(ctx, agent, opt, since_ms) {
  const m = agent.menu
  if (SENDING.has(agent.address)) return false
  SENDING.add(agent.address)
  ctx.render()
  try {
    await post("/api/choose", { address: agent.address, key: opt.key, menu_hash: m.menu_hash, since_ms })
    ctx.note("Envoyé : " + opt.label)
    return true
  } catch (e) {
    ctx.note(e.message)
    return false
  } finally {
    SENDING.delete(agent.address)
    ctx.tick()
    ctx.render()
  }
}

export function menuButtons(ctx, agent, container, onSent) {
  const m = agent.menu
  const since_ms = agent.since_ms
  const busy = SENDING.has(agent.address)
  const manyAlways = m.options.filter((o) => o.role === "always").length > 1
  for (const opt of m.options) {
    // two "always" options would read the same: keep the start of the real label so each one says what it does
    const text = m.kind !== "permission" || !ROLE_LABEL[opt.role] ? opt.label
      : opt.role === "always" && manyAlways ? "Toujours : " + opt.label.replace(/^Yes,?\s*(and\s+)?/i, "").slice(0, 40) : ROLE_LABEL[opt.role]
    const { w, b } = btn(text, "opt act")
    b.dataset.role = opt.role
    b.dataset.agentConfirm = "Répond au menu dans le terminal"
    if (busy) w.setAttribute("disabled", "")
    b.addEventListener("click", async () => { if (await chooseOption(ctx, agent, opt, since_ms) && onSent) onSent() })
    container.append(w)
  }
}

function menuCard(ctx, x, g) {
  const m = x.menu
  const card = el("div", "actioncard")
  card.dataset.g = g
  card.style.setProperty("--gc", `var(--c-${g})`)
  if (!m || !m.options || !m.options.length) {
    card.append(el("h3", null, m && m.kind === "permission" ? "Autorisation demandée" : "Question posée"))
    if (m && (m.question || m.detail)) card.append(el("div", "cmd", m.detail || m.question))
    card.append(el("p", "hint", "Réponds dans le terminal : menu non reconnu"))
    return card
  }
  card.append(el("h3", null, m.kind === "permission" ? "Autorisation demandée" + (m.tool ? " · " + m.tool : "") : m.question || "Question"))
  if (m.kind === "permission" && m.question) card.append(el("p", "hint", m.question))
  if (m.kind === "permission" || m.detail) {
    const k = x.address + "|menu"
    const full = EXPANDED.has(k) && m.truncated
    card.append(el("div", "cmd", full ? m.full : m.detail))
    if (m.truncated) {
      const t = el("button", "more", full ? "Réduire" : "Voir tout")
      t.type = "button"
      t.addEventListener("click", () => { full ? EXPANDED.delete(k) : EXPANDED.add(k); ctx.render() })
      card.append(t)
    }
  }
  const row = el("div", "btns")
  menuButtons(ctx, x, row)
  card.append(row)
  for (const o of m.options.filter((o) => o.role === "always")) card.append(el("p", "hint", "Toujours = " + o.label))
  if (m.free_text) card.append(el("p", "hint", "Pour une réponse libre : réponds dans le terminal"))
  return card
}

// ---- answers by text: Oui/Non per question, free field, preview ----
function fieldWithMic(ctx, x, d) {
  const f = el("ui-field")
  const lab = el("ui-field-label", null, "Message libre (optionnel)")
  const ta = el("ui-textarea")
  const t = el("textarea")
  t.value = d.free
  t.dataset.fk = "free"
  t.setAttribute("autocapitalize", "sentences")
  t.addEventListener("input", () => { d.free = t.value; PREVIEWS.delete(x.address) })
  ta.append(t)
  f.append(lab, ta)
  const row = el("div", "rowinput")
  row.append(f)
  const mic = micButton(t, ctx)
  if (mic) row.append(mic)
  return row
}

function answerCard(ctx, x, questions) {
  const card = el("div", "actioncard")
  card.dataset.g = questions.length ? "question" : "review"
  card.style.setProperty("--gc", questions.length ? "var(--c-question)" : "var(--c-review)")
  const d = draftFor(x.address)
  if (x.q && x.q.draft) card.append(el("div", "draftnote", "Réponse tapée, non envoyée : « " + x.q.draft + " »"))
  card.append(el("h3", null, questions.length ? "À décider · " + questions.length : "Répondre"))
  questions.forEach((q, i) => {
    const box = el("div", "rq")
    box.append(el("div", "qt", i + 1 + ". " + q))
    const g = el("ui-toggle-group")
    g.setAttribute("aria-label", q)
    const cur = (d.answers.get(q) || {}).choice
    if (cur) g.setAttribute("default-value", cur)
    for (const v of ["Oui", "Non"]) {
      const t = el("ui-toggle")
      t.setAttribute("value", v)
      const b = el("button", null, v)
      b.type = "button"
      t.append(b)
      g.append(t)
    }
    g.addEventListener("valuechange", (e) => {
      const val = e.detail.value
      const choice = Array.isArray(val) ? val[val.length - 1] || "" : val || ""
      const a = d.answers.get(q) || { choice: "", text: "" }
      a.choice = choice
      d.answers.set(q, a)
      PREVIEWS.delete(x.address)
    })
    box.append(g)
    card.append(box)
  })
  card.append(fieldWithMic(ctx, x, d))
  const w = sendWarn(x)
  if (w) card.append(el("div", "warn", "⚠ " + w))
  const { w: pw, b: pb } = btn("Aperçu et envoi", "act")
  pb.dataset.agentConfirm = "Envoie le message à l'agent"
  pb.addEventListener("click", () => openPreview(ctx, x.address, questions))
  const row = el("div", "btns")
  row.append(pw)
  card.append(row)
  return card
}

// ---- preview dialog: lives in index.html, so a refresh never closes it ----
const PVQ = new Map()   // address -> questions the preview was made from
function openPreview(ctx, address, questions) {
  const x = ctx.agent(address)
  if (!x) return
  const p = makePreview(address, questions, x.since_ms)
  if (!p) return ctx.note("Rien à envoyer : réponds à au moins une question ou écris un message")
  PVQ.set(address, questions)
  drawPreview(ctx, address, "", false)
  $("pv-dialog").open = true
}

function drawPreview(ctx, address, err, stale, busy) {
  const p = PREVIEWS.get(address)
  const body = $("pv-body")
  body.replaceChildren()
  if (!p) return
  const x = ctx.agent(address)
  const w = x ? sendWarn(x) : "session fermée"
  if (w) body.append(el("div", "warn", "⚠ " + w))
  const ta = el("ui-textarea")
  const t = el("textarea")
  t.value = p.text
  t.rows = Math.min(14, p.text.split("\n").length + 1)
  t.setAttribute("aria-label", "Message modifiable")
  t.addEventListener("input", () => { p.text = t.value })
  ta.append(t)
  body.append(ta)
  if (err) body.append(el("div", "serr", err))
  const row = el("div", "btns")
  const close = el("ui-dialog-close")
  const cb = el("button", null, "Annuler")
  cb.type = "button"
  close.append(cb)
  row.append(close)
  if (stale) {
    const { w: rw, b: rb } = btn("Préparer à nouveau", "act")
    rb.addEventListener("click", () => {
      const cur = ctx.agent(address)
      if (!cur) return
      if (!makePreview(address, PVQ.get(address) || [], cur.since_ms)) return ctx.note("Rien à envoyer")
      drawPreview(ctx, address, "", false)
    })
    row.append(rw)
  }
  const { w: sw, b: sb } = btn(busy ? "Envoi…" : "Envoyer à " + (x ? x.space : address), "act")
  sb.dataset.variant = "solid"
  sb.dataset.agentConfirm = "Envoie le message à l'agent"
  if (busy) sw.setAttribute("disabled", "")
  sb.addEventListener("click", () => sendPreview(ctx, address))
  row.append(sw)
  body.append(row)
}

// The only call that types into an agent. It posts the frozen preview, never the current since_ms.
// Throws the server's message (with since_ms when the session moved on).
export async function sendFrozen(ctx, p) {
  await post("/api/send", { address: p.address, text: p.text, questions: p.questions, since_ms: p.since_ms })
  const n = p.questions.length
  clearDraft(p.address)
  await dismissMany(ctx, p.address, p.questions, false, null)
  return n || 1
}

async function sendPreview(ctx, address) {
  const p = PREVIEWS.get(address)
  if (!p || p.busy) return
  p.busy = true
  drawPreview(ctx, address, "", false, true)
  let n
  try {
    n = await sendFrozen(ctx, p)
  } catch (e) {
    p.busy = false
    drawPreview(ctx, address, e.message, !!e.since_ms)
    return
  }
  const x = ctx.agent(address)
  $("pv-dialog").open = false
  ctx.note((p.questions.length ? plural(n, "réponse") + " envoyée" + (n > 1 ? "s" : "") : "Message envoyé") + " à " + (x ? x.space : address))
  ctx.render()
}
export const sendWarning = sendWarn

// ---- "Plus" ----
export async function dismissMany(ctx, a, ts, undo, msg) {
  for (const t of ts) { const k = ik(a, t); undo ? ctx.hidden.delete(k) : ctx.hidden.add(k) }
  ctx.render()
  await Promise.all(ts.map((t) => post("/api/dismiss", { address: a, text: t, undo }).catch(() => {})))
  ctx.tick()
  if (!undo && msg) ctx.undoToast(msg, () => dismissMany(ctx, a, ts, true))
}

export async function snoozeItem(ctx, a, t, until) {
  const k = ik(a, t)
  LATER.delete(k)
  if (until) ctx.hidden.add(k); else ctx.hidden.delete(k)
  SN.set(k, until)
  ctx.render()
  await post("/api/snooze-item", { address: a, text: t, until_ms: until || null }).catch(() => {})
  await ctx.tick()
  SN.delete(k)
  ctx.hidden.delete(k)
  if (until) ctx.undoToast("Reporté " + when(until) + " : « " + short(t) + " »", () => snoozeItem(ctx, a, t, 0))
}

function snoozedList(x, now) {
  const m = new Map((x.snoozed || []).map((s) => [s.text, s.until]))
  const p = x.address + KEY
  for (const [k, u] of SN) if (k.startsWith(p)) m.set(k.slice(p.length), u)
  return [...m].filter(([, u]) => u > now)
}

function toggleInfo(ctx, a, t) {
  const k = ik(a, t)
  if (OPENI.has(k)) { OPENI.delete(k); return ctx.render() }
  OPENI.add(k)
  const r = INFO.get(k)
  if (!r || r.error || (!r.loading && Date.now() - (r._t || 0) > 6e5)) {
    INFO.set(k, { loading: true })
    post("/api/info", { address: a, text: t }).then((j) => { j._t = Date.now(); INFO.set(k, j); ctx.render() }).catch((e) => { INFO.set(k, { error: e.message }); ctx.render() })
  }
  ctx.render()
}

function infoBox(a, t) {
  const k = ik(a, t)
  if (!OPENI.has(k)) return null
  const r = INFO.get(k)
  const box = el("div", "info")
  if (!r || r.loading) { box.append(el("i", null, "Lecture de la conversation…")); return box }
  if (r.error) { box.textContent = "Impossible : " + r.error; return box }
  box.append(el("b", "vd", r.verdict || "incertain"), el("p", null, r.contexte || ""))
  if (r.depuis) box.append(el("p", null, "Depuis : " + r.depuis))
  if (r.preuve) box.append(el("p", "none", "« " + r.preuve + " »"))
  return box
}

function point(ctx, x, t, now) {
  const li = el("div", "pt")
  const s = el("span", null, t)
  s.append(el("small", null, since(((x.q || {}).ts || {})[t])))
  const ib = infoBox(x.address, t)
  if (ib) s.append(ib)
  if (LATER.has(ik(x.address, t))) {
    const lat = el("div", "lat")
    lat.append(el("span", null, "Revenir :"))
    for (const [v, l] of [["h", "Dans 1 h"], ["1", "Demain 10 h"], ["3", "Dans 3 j"], ["i", "Indéfiniment"]])
      lat.append(btn(l, null, () => snoozeItem(ctx, x.address, t, v === "h" ? Date.now() + 36e5 : v === "i" ? INF : at10(+v))).w)
    const inp = el("input")
    inp.type = "datetime-local"
    inp.min = localIso(Date.now())
    inp.value = ITV[ik(x.address, t)] || dflt()
    inp.setAttribute("aria-label", "Date et heure de retour")
    inp.addEventListener("input", () => { ITV[ik(x.address, t)] = inp.value })
    lat.append(inp, btn("OK", null, () => {
      const u = parseLocal(inp.value)
      if (!u || u <= Date.now() + 6e4) return ctx.note("Choisis une heure à venir")
      delete ITV[ik(x.address, t)]
      snoozeItem(ctx, x.address, t, u)
    }).w)
    s.append(lat)
  }
  const acts = el("span", "acts")
  acts.append(
    btn(OPENI.has(ik(x.address, t)) ? "Masquer" : "Plus d'infos", null, () => toggleInfo(ctx, x.address, t)).w,
    btn("Plus tard", null, () => { const k = ik(x.address, t); LATER.has(k) ? LATER.delete(k) : LATER.add(k); ctx.render() }).w,
    btn("Plus pertinent", null, () => dismissMany(ctx, x.address, [t], false, "Retiré : « " + short(t) + " »")).w,
  )
  li.append(s, acts)
  return li
}

function pointList(ctx, x, label, list, key, now) {
  if (!list.length) return null
  const box = el("div", "box")
  const head = el("div", "btns")
  head.append(el("span", "lab", label + " · " + list.length))
  head.append(btn("Tout retirer", null, () => dismissMany(ctx, x.address, list, false, list.length + (key === "open" ? " questions retirées" : " tâches retirées"))).w)
  box.append(head)
  for (const t of list) box.append(point(ctx, x, t, now))
  return box
}

function loadRes(ctx, a) {
  const r = RES.get(a)
  if (r && (r.loading || (!r.error && Date.now() - r._t < 6e5))) return ctx.render()
  RES.set(a, { loading: true })
  ctx.render()
  post("/api/resume", { address: a }).then((j) => { j._t = Date.now(); RES.set(a, j); ctx.render() }).catch((e) => { RES.set(a, { error: e.message }); ctx.render() })
}

function resumeBox(ctx, x) {
  const a = x.address, o = RESOPEN.has(a), r = RES.get(a)
  const box = el("div", "box res")
  box.append(btn(o ? "Masquer le fil" : "Reprendre le fil", null, () => { if (o) { RESOPEN.delete(a); ctx.render() } else { RESOPEN.add(a); loadRes(ctx, a) } }).w)
  if (o) {
    if (!r || r.loading) box.append(el("div", "info", "Lecture de la conversation…"))
    else if (r.error) box.append(el("div", "info", "Impossible : " + r.error))
    else {
      const dl = el("dl")
      for (const [l, k] of [["Objectif", "objectif"], ["Fait", "avancement"], ["Bloque", "bloquant"], ["Ensuite", "prochaine_etape"]]) dl.append(el("dt", null, l), el("dd", null, r[k] || ""))
      box.append(dl)
    }
  }
  return box
}

async function snoozeSession(ctx, a, until) {
  await run(ctx, () => post("/api/snooze", { address: a, until_ms: until }))
}

function snoozeBox(ctx, x, now) {
  const a = x.address
  const box = el("div", "box")
  box.append(el("div", "lab", "Reporter"))
  if (isSnoozed(x, now)) box.append(el("div", "big", "💤 " + (isInf(x.snooze.until) ? until$(x.snooze.until) : until$(x.snooze.until) + " à " + fmtH(x.snooze.until))))
  else box.append(el("div", "none", "Caché tout en bas, sans bip, jusqu'à la date choisie"))
  const b = el("div", "btns")
  const add = (l, u) => b.append(btn(l, null, () => snoozeSession(ctx, a, u())).w)
  add("Dans 1 h", () => Date.now() + 36e5)
  for (const k of [10, 14, 18]) if (todayAt(k) > Date.now() + 3e5) add("Aujourd'hui " + k + " h", () => todayAt(k))
  add("Demain 10 h", () => at10(1))
  add("Dans 3 j", () => at10(3))
  add("Lundi 10 h", mon10)
  add("Indéfiniment", () => INF)
  box.append(b)
  const p = el("div", "btns")
  p.append(el("span", "none", "Ou un jour et une heure précis :"))
  const inp = el("input")
  inp.type = "datetime-local"
  inp.min = localIso(Date.now())
  inp.value = SZV[a] || dflt()
  inp.setAttribute("aria-label", "Date et heure du report")
  inp.addEventListener("input", () => { SZV[a] = inp.value })
  p.append(inp, btn("Reporter", null, () => {
    const u = parseLocal(inp.value)
    if (!u || u <= Date.now() + 6e4) return ctx.note("Choisis une heure à venir")
    delete SZV[a]
    snoozeSession(ctx, a, u)
  }).w)
  if (isSnoozed(x, now)) p.append(btn("Réactiver", null, () => snoozeSession(ctx, a, null)).w)
  box.append(p)
  return box
}

async function saveDeadline(ctx, a, date, note) {
  await run(ctx, () => post("/api/deadline", { address: a, date, note }))
}

function deadlineBox(ctx, x) {
  const dl = x.deadline, a = x.address
  const box = el("div", "box")
  box.append(el("div", "lab", "Échéance"))
  const n = dlDays(x)
  if (dl) box.append(el("div", "big" + (n <= 0 ? " hot" : n <= 1 ? " soon" : ""), "⏰ " + dlText(x)))
  else box.append(el("div", "none", "Aucune date attendue"))
  const note = el("input")
  note.placeholder = "Note ou lien (ex. réponse à Slack)"
  note.value = dl ? dl.note || "" : ""
  note.setAttribute("aria-label", "Note de l'échéance")
  const date = el("input")
  date.type = "date"
  date.value = dl ? dl.date : ""
  date.setAttribute("aria-label", "Date de l'échéance")
  date.addEventListener("change", () => { if (date.value) saveDeadline(ctx, a, date.value, note.value) })
  const b = el("div", "btns")
  for (const [l, d] of [["Aujourd'hui", 0], ["Demain", 1], ["Dans 2 j", 2], ["Dans 1 sem.", 7]]) b.append(btn(l, null, () => saveDeadline(ctx, a, addDays(d), note.value)).w)
  b.append(date)
  if (dl) b.append(btn("Effacer", null, () => saveDeadline(ctx, a, "", "")).w)
  box.append(b, note)
  return box
}

function moreSection(ctx, x, now) {
  const c = el("ui-collapsible")
  c.className = "more-sec"
  if (MOREOPEN) c.setAttribute("default-open", "")
  const tr = el("ui-collapsible-trigger")
  const tb = el("button", null, "Plus")
  tb.type = "button"
  tr.append(tb)
  const panel = el("ui-collapsible-panel")
  panel.setAttribute("hidden", "")
  c.addEventListener("openchange", (e) => { MOREOPEN = !!e.detail.value })
  const q = x.q
  if (x.status === "done" && q && !q.pending && !q.error) {
    const a = pointList(ctx, x, "À décider", openQuestions(x, now, ctx.hidden), "open", now)
    const b = pointList(ctx, x, "À faire", openTodos(x, now, ctx.hidden), "todo", now)
    if (a) panel.append(a)
    if (b) panel.append(b)
    if ((q.answered || []).length) {
      const box = el("div", "box")
      box.append(el("div", "lab", "Déjà traité"))
      for (const t of q.answered) box.append(el("div", "none", t))
      panel.append(box)
    }
  } else if (q && q.carry) {
    const it = [...(q.carry.open || []), ...(q.carry.todo || [])]
    if (it.length) {
      const box = el("div", "box")
      box.append(el("div", "lab", "Restait ouvert avant ce tour"))
      for (const t of it) box.append(el("div", "none", t))
      panel.append(box)
    }
  }
  const sn = snoozedList(x, now)
  if (sn.length) {
    const box = el("div", "box")
    box.append(el("div", "lab", "Reportés · " + sn.length))
    for (const [t, u] of sn) {
      const r = el("div", "pt")
      const s = el("span", null, t)
      s.append(el("small", null, isInf(u) ? "jusqu'à nouvel ordre" : "revient " + when(u)))
      r.append(s, btn("Remettre maintenant", null, () => snoozeItem(ctx, x.address, t, 0)).w)
      box.append(r)
    }
    panel.append(box)
  }
  const back = [...ctx.hidden].filter((k) => k.startsWith(x.address + KEY) && !SN.has(k)).map((k) => k.slice(k.indexOf(KEY) + 1))
  const all = [...new Set([...(x.dismissed || []), ...back])]
  if (all.length) {
    const box = el("div", "box")
    box.append(el("div", "lab", "Retirées · " + all.length))
    for (const t of all) {
      const r = el("div", "pt")
      r.append(el("span", null, t), btn("Remettre", null, () => dismissMany(ctx, x.address, [t], true)).w)
      box.append(r)
    }
    panel.append(box)
  }
  panel.append(resumeBox(ctx, x), snoozeBox(ctx, x, now), deadlineBox(ctx, x))
  const subs = Object.entries(x.subagents || {}).map(([k, v]) => v + " " + k).join(" · ")
  if (subs) panel.append(el("div", "none", "sous-agents : " + subs))
  c.append(tr, panel)
  return c
}

// ---- thread ----
function bubble(ctx, x, which, m) {
  const b = el("div", "bubble" + (which === "me" ? " me" : ""))
  b.append(el("small", null, which === "me" ? "Toi" : m.screen ? "Agent (écran)" : "Agent"))
  const k = x.address + "|" + which
  const full = EXPANDED.has(k)
  b.append(document.createTextNode(full ? m.full : m.text))
  if (m.truncated) {
    const t = el("button", "more", full ? "Réduire" : "Voir tout")
    t.type = "button"
    t.addEventListener("click", () => { full ? EXPANDED.delete(k) : EXPANDED.add(k); ctx.render() })
    b.append(t)
  }
  return b
}

export function renderDetail(agent, thread, el0, ctx) {
  el0.replaceChildren()
  if (!agent) { el0.append(el("p", "none", "Aucune session.")); return }
  const now = ctx.nowMs()
  const g = groupOf({ ...agent, snooze: null }, now, ctx.hidden)
  const root = el("div", "dd")
  root.dataset.g = g

  const back = btn("← Sessions", "back", () => ctx.closeDetail())
  root.append(back.w)

  const dh = el("div", "dh")
  const h = el("h2", null, name(agent))
  if (agent.source) h.append(el("i", "src", String(agent.source).split("-").pop().slice(0, 4)))
  const age = el("span", "age")
  age.dataset.since = agent.since_ms || ""
  dh.append(h, age)
  root.append(dh, el("div", "sub", agent.title || agent.msg || agent.cwd || ""))
  const chips = el("div")
  const bd = badge(agent, now, ctx.hidden)
  const chip = el("span", "chip", bd.text)
  chip.style.setProperty("--gc", `var(--c-${g})`)
  chips.append(chip)
  if (isSnoozed(agent, now)) chips.append(el("span", "chip", "💤 reportée " + (isInf(agent.snooze.until) ? until$(agent.snooze.until) : until$(agent.snooze.until) + " à " + fmtH(agent.snooze.until))))
  root.append(chips)
  if (agent.status === "working" && agent.stalled_min) root.append(el("div", "stall", "⚠ bloquée ? depuis " + agent.stalled_min + " min"))

  if (thread && (thread.me || thread.agent)) {
    const bs = el("div", "bubbles")
    if (thread.me) bs.append(bubble(ctx, agent, "me", thread.me))
    if (thread.agent) bs.append(bubble(ctx, agent, "agent", thread.agent))
    root.append(bs)
  }

  if (agent.source) {
    root.append(el("p", "none", "Répondre : ancien herdr, non supporté"))
  } else if (agent.status === "blocked" && agent.kind === "auth") {
    root.append(el("p", "hint", "Connexion requise. Réponds dans le terminal."))
  } else if (agent.status === "error") {
    root.append(el("p", "hint", "Réponds dans le terminal."))
  } else if (agent.status === "blocked") {
    root.append(menuCard(ctx, agent, g === "approve" ? "approve" : "question"))
  } else if (agent.status === "done") {
    const q = agent.q
    if (q && q.pending) root.append(el("p", "none", "Lecture du dernier message…"))
    else if (q && q.error) root.append(el("p", "none", "Analyse impossible : " + q.error))
    else root.append(answerCard(ctx, agent, openQuestions(agent, now, ctx.hidden)))
  } else {
    root.append(el("p", "none", "Travaille…"))
  }
  root.append(moreSection(ctx, agent, now))
  el0.append(root)
  el0.querySelectorAll("[data-since]").forEach((e) => { e.textContent = e.dataset.since ? ctx.age(+e.dataset.since) : "" })
}
