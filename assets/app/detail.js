import { badge, groupOf } from "./groups.js"

const name = (x) => x.space + (x.tab && x.tab !== "1" ? " / " + x.tab : "")

export function renderDetail(agent, thread, el, ctx) {
  el.replaceChildren()
  if (!agent) {
    const p = document.createElement("p")
    p.className = "none"
    p.textContent = "Aucune session."
    el.append(p)
    return
  }
  const h = document.createElement("h2")
  h.textContent = name(agent)
  const chip = document.createElement("span")
  chip.className = "chip"
  chip.textContent = badge(agent, ctx.nowMs(), ctx.hidden).text
  el.append(h, chip)
}
