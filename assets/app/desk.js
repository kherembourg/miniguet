import { grouped, waitingAgents, dlDays } from "./groups.js"

const $ = (id) => document.getElementById(id)
let DESK = false
try { DESK = localStorage.getItem("desk") === "1" } catch (e) {}

export const deskOn = () => DESK

export function toggleDesk(ctx) { setDesk(!DESK, ctx) }

function setDesk(v, ctx) {
  DESK = v
  try { v ? localStorage.setItem("desk", "1") : localStorage.removeItem("desk") } catch (e) {}
  renderDesk(ctx)
}

const dlText = (x) => {
  const n = dlDays(x)
  return n < 0 ? "en retard" : n === 0 ? "aujourd'hui" : n === 1 ? "demain" : x.deadline.date
}

// Big number readable from afar; colour = most urgent non-empty group. A tap closes it.
export function renderDesk(ctx) {
  const D = $("desk")
  D.hidden = !DESK
  D.onclick = () => setDesk(false, ctx)
  if (!DESK) return
  const now = ctx.nowMs()
  const ag = ctx.agents()
  const wait = waitingAgents(ag, now, ctx.hidden)
  const nw = wait.length
  const groups = grouped(wait, now, ctx.hidden)
  const names = groups.flatMap((g) => g.items).slice(0, 3)
  const hot = groups.some((g) => g.id === "error") || ag.some((x) => x.deadline && dlDays(x) <= 0)
  const h = new Date().getHours()
  D.classList.toggle("night", h >= 22 || h < 7)
  D.dataset.c = hot ? "hot" : nw ? "amb" : "ok"
  const html = JSON.stringify([nw, names.map((x) => [x.address, x.space, x.tab, x.since_ms, x.deadline])])
  if (D.dataset.h === html) return
  D.dataset.h = html
  D.replaceChildren()
  const n = document.createElement("div"); n.className = "dn"; n.textContent = nw
  const t = document.createElement("div"); t.className = "dt"; t.textContent = nw ? "à toi" : "rien ne t'attend"
  const ul = document.createElement("ul")
  for (const x of names) {
    const li = document.createElement("li")
    li.textContent = x.space + (x.tab && x.tab !== "1" ? " / " + x.tab : "")
    const s = document.createElement("span")
    s.textContent = (x.since_ms ? ctx.age(x.since_ms) : "") + (x.deadline ? " · ⏰ " + dlText(x) : "")
    li.append(s)
    ul.append(li)
  }
  D.append(n, t, ul)
}

let WL = null
async function wake() {
  try {
    if (document.visibilityState === "visible" && !WL) {
      WL = await navigator.wakeLock.request("screen")
      WL.addEventListener("release", () => { WL = null })
    }
  } catch (e) { WL = null }
}
document.addEventListener("visibilitychange", wake)
document.addEventListener("click", wake)
wake()
