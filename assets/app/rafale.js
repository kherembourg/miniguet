import { grouped, isSnoozed, openQuestions } from "./groups.js"
import { draftFor, makePreview, answerText, PREVIEWS, fieldKey } from "./reply.js"
import { post } from "./api.js"
import { menuCard, sendFrozen, sendWarning, snoozeItem, dismissMany } from "./detail.js"
import { micButton } from "./voice.js"

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
const plural = (n, w) => n + " " + w + (n > 1 ? "s" : "")

// RAF: {cards, i, act, since, other, recap, ss, sent, err}
let RAF = null

function cardsFor(ctx) {
  const now = ctx.nowMs()
  const live = ctx.agents().filter((x) => !isSnoozed(x, now) && !x.source)
  const groups = grouped(live, now, ctx.hidden)
  const menus = []
  const qs = []
  for (const g of groups) {
    for (const x of g.items) {
      if ((g.id === "approve" || g.id === "question") && x.status === "blocked" && x.menu && x.menu.options && x.menu.options.length) menus.push({ type: "menu", a: x.address })
      else if (g.id === "question" && x.status === "done") for (const t of openQuestions(x, now, ctx.hidden)) qs.push({ type: "q", a: x.address, t })
    }
  }
  return [...menus, ...qs]
}

export function openRafale(ctx) {
  RAF = {
    cards: cardsFor(ctx), i: 0, act: {}, other: false, recap: false, ss: [], sent: {}, err: {},
    since: Object.fromEntries(ctx.agents().map((x) => [x.address, x.since_ms])),
  }
  draw(ctx)
  $("raf-dialog").open = true
}

function close(ctx) {
  RAF = null
  $("raf-dialog").open = false
  $("raf-body").replaceChildren()
  ctx.render()
}

function head(ctx, title, left, right, pg) {
  const h = el("div", "rafhead")
  const l = left ? btn(left[0], null, left[1]) : null
  h.append(l ? l.w : el("span"), el("b", null, title))
  if (pg) h.append(el("span", "pg", pg))
  if (right) h.append(btn(right[0], null, right[1]).w)
  return h
}

function next(ctx) {
  RAF.other = false
  if (RAF.i < RAF.cards.length - 1) { RAF.i++; draw(ctx) } else end(ctx)
}

const waiting = (x) => x && x.status === "blocked" && x.menu && x.menu.options && x.menu.options.length

function menuStep(ctx, body, c) {
  const x = ctx.agent(c.a)
  if (!waiting(x)) return next(ctx)   // answered elsewhere or no longer waiting: nothing to show
  body.append(el("div", "hint", name(x) + (x.since_ms ? " · " + ctx.age(x.since_ms) : "")))
  const redraw = () => draw(ctx)
  body.append(menuCard(ctx, x, x.kind === "permission" ? "approve" : "question", {
    full: true,
    redraw,
    // refused (the request changed, or already sent): reload the state, then show what is asked now
    onDone: async (ok) => {
      if (ok) return next(ctx)
      await ctx.tick()
      draw(ctx)
    },
  }))
  const pass = el("div", "btns")
  pass.append(btn("Passer (revient dans 1 h)", null, async () => {
    try { await post("/api/snooze", { address: c.a, until_ms: Date.now() + 36e5 }) } catch (e) { ctx.note(e.message) }
    ctx.tick()
    next(ctx)
  }).w)
  body.append(pass)
}

function questionCard(ctx, body, c) {
  const x = ctx.agent(c.a) || { space: c.a }
  const d = draftFor(c.a)
  const a = d.answers.get(c.t) || { choice: "", text: "" }
  const act = RAF.act[c.a + "\u0001" + c.t]
  body.append(el("div", "hint", name(x) + (x.since_ms ? " · " + ctx.age(x.since_ms) : "")))
  if (act) body.append(el("div", "st", act === "p" ? "Reportée d'1 h" : "Retirée"))
  body.append(el("div", "rafq", c.t))
  const row = el("div", "btns")
  const set = (v) => { d.answers.set(c.t, v); PREVIEWS.delete(c.a); delete RAF.act[c.a + "\u0001" + c.t] }
  for (const o of ["Oui", "Non"]) {
    const { w, b } = btn(o, "opt act", () => { set({ choice: o, text: "" }); next(ctx) })
    if (a.choice === o) b.dataset.pressed = ""
    row.append(w)
  }
  const other = btn("Autre…", "opt act", () => { RAF.other = true; draw(ctx); const i = $("raf-body").querySelector("textarea"); if (i) i.focus() })
  if (a.text) other.b.dataset.pressed = ""
  row.append(other.w)
  body.append(row)
  if (RAF.other || a.text) {
    const f = el("div", "rowinput")
    const ta = el("ui-textarea")
    const t = el("textarea")
    t.value = a.text
    t.dataset.fk = fieldKey("raf", c.a, c.t)
    t.setAttribute("aria-label", "Ta réponse")
    t.addEventListener("input", () => set({ choice: "", text: t.value }))
    ta.append(t)
    f.append(ta)
    const mic = micButton(t, ctx)
    if (mic) f.append(mic)
    body.append(f)
    body.append(btn("Valider", "act", () => { if (t.value.trim()) next(ctx) }).w)
  }
  const rs = el("div", "btns")
  rs.append(
    btn("Passer (revient dans 1 h)", null, () => {
      d.answers.delete(c.t)
      RAF.act[c.a + "\u0001" + c.t] = "p"
      snoozeItem(ctx, c.a, c.t, Date.now() + 36e5)
      next(ctx)
    }).w,
    btn("Plus pertinent", null, () => {
      d.answers.delete(c.t)
      RAF.act[c.a + "\u0001" + c.t] = "d"
      dismissMany(ctx, c.a, [c.t], false, "Retiré : « " + (c.t.length > 60 ? c.t.slice(0, 60) + "…" : c.t) + " »")
      next(ctx)
    }).w,
  )
  body.append(rs)
}

function end(ctx) {
  RAF.recap = true
  RAF.other = false
  RAF.ss = [...new Set(RAF.cards.filter((c) => c.type === "q").map((c) => c.a))]
  for (const a of RAF.ss) {
    // questions from the rafale list, not the live state: a session that started working since keeps its answers
    const qs = RAF.cards.filter((c) => c.a === a && c.type === "q" && answerText(draftFor(a).answers.get(c.t) || {})).map((c) => c.t)
    if (!RAF.sent[a] && !makePreview(a, qs, RAF.since[a])) PREVIEWS.delete(a)
  }
  draw(ctx)
}

async function sendOne(ctx, a) {
  const p = PREVIEWS.get(a)
  if (!p || p.busy) return 0
  p.busy = true
  delete RAF.err[a]
  draw(ctx)
  try {
    const n = await sendFrozen(ctx, p)
    RAF.sent[a] = n
    return n
  } catch (e) {
    p.busy = false
    RAF.err[a] = { text: e.message, stale: !!e.since_ms }
    return 0
  } finally {
    if (RAF) draw(ctx)
  }
}

function recap(ctx, body) {
  const ss = RAF.ss.filter((a) => PREVIEWS.get(a) || RAF.sent[a])
  const todo = ss.filter((a) => !RAF.sent[a])
  const total = ss.reduce((s, a) => s + (RAF.sent[a] || PREVIEWS.get(a).questions.length), 0)
  if (!ss.length) {
    body.append(el("h2", null, "Aucune réponse à envoyer"), el("p", "hint", "Les questions passées reviendront dans 1 h."))
    return
  }
  body.append(el("h2", null, "Envoyer " + plural(total, "réponse") + " à " + plural(ss.length, "session")))
  body.append(el("p", "hint", todo.length < ss.length ? "Les messages restants sont encore modifiables." : "Rien n'est encore parti. Relis et modifie chaque message avant de l'envoyer."))
  for (const a of ss) {
    const x = ctx.agent(a)
    const box = el("div", "box")
    box.append(el("div", "lab", x ? name(x) : a))
    if (RAF.sent[a]) { box.append(el("div", "sok", "✓ Envoyé")); body.append(box); continue }
    const w = x ? sendWarning(x) : "session fermée"
    if (w) box.append(el("div", "warn", "⚠ " + w))
    const p = PREVIEWS.get(a)
    const ta = el("ui-textarea")
    const t = el("textarea")
    t.value = p.text
    t.rows = Math.min(14, p.text.split("\n").length + 1)
    t.setAttribute("aria-label", "Message pour " + (x ? x.space : a))
    t.addEventListener("input", () => { p.text = t.value })
    ta.append(t)
    box.append(ta)
    const err = RAF.err[a]
    if (err) box.append(el("div", "serr", err.text))
    const row = el("div", "btns")
    if (err && err.stale) row.append(btn("Préparer à nouveau", "act", () => {
      const cur = ctx.agent(a)
      const qs = RAF.cards.filter((c) => c.a === a && c.type === "q").map((c) => c.t)
      if (cur && makePreview(a, qs, cur.since_ms)) { delete RAF.err[a]; draw(ctx) }
    }).w)
    const send = btn(p.busy ? "Envoi…" : "Envoyer à " + (x ? x.space : a), "act", () => sendOne(ctx, a))
    send.b.dataset.variant = "solid"
    send.b.dataset.agentConfirm = "Envoie le message à l'agent"
    if (p.busy) send.w.setAttribute("disabled", "")
    row.append(send.w)
    box.append(row)
    body.append(box)
  }
  if (todo.length > 1) {
    const all = btn("Tout envoyer (" + todo.length + ")", "act", async () => {
      for (const a of todo.filter((a) => PREVIEWS.get(a) && !RAF.sent[a])) await sendOne(ctx, a)
    })
    all.b.dataset.variant = "solid"
    all.b.dataset.agentConfirm = "Envoie les messages aux agents"
    body.append(all.w)
  }
}

function draw(ctx) {
  const body = $("raf-body")
  body.replaceChildren()
  if (!RAF) return
  const n = RAF.cards.length
  if (RAF.recap) {
    body.append(head(ctx, "Récapitulatif", ["← Questions", () => { RAF.recap = false; draw(ctx) }], ["Fermer", () => close(ctx)]))
    recap(ctx, body)
    return
  }
  if (!n) {
    body.append(head(ctx, "", null, ["Fermer", () => close(ctx)]), el("p", "none", "Aucune demande en attente."))
    return
  }
  const c = RAF.cards[RAF.i]
  const prev = btn("← Précédente", null, () => { RAF.i = Math.max(0, RAF.i - 1); RAF.other = false; draw(ctx) })
  if (!RAF.i) prev.w.setAttribute("disabled", "")
  const h = el("div", "rafhead")
  h.append(prev.w, el("span", "pg", RAF.i + 1 + "/" + n), btn("Terminer", null, () => end(ctx)).w)
  body.append(h)
  c.type === "menu" ? menuStep(ctx, body, c) : questionCard(ctx, body, c)
}
