"use strict";
/* Screen control: the note viewer, scrolling, and the orb that moves beside what it shows.
   Depends on app.js (for $, el, graph, dockCtl) and hands.js (HAND_POINTER_MIN). */

const SCROLL_FRACTION = { little: 0.25, some: 0.6, page: 0.9, lot: 1.8 }; // of the visible height
const INERTIA_DECAY = 0.94;      // hand flick: how fast a dragged scroll slows down
const HOLD_REPEAT_MS = 60;       // held scroll button: repeat rate
const HOLD_STEP = 0.12;          // held scroll button: fraction of the height per repeat

/* ---------- small markdown renderer. Builds DOM with textContent only, never innerHTML ---------- */
function renderInline(parent, text, links, onOpen) {
  const rx = /\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]|\*\*([^*]+)\*\*|`([^`]+)`/g;
  let last = 0, m;
  while ((m = rx.exec(text))) {
    if (m.index > last) parent.appendChild(document.createTextNode(text.slice(last, m.index)));
    if (m[1] !== undefined) {
      const title = m[1].trim(), label = (m[2] || title).trim(), id = links[title.toLowerCase()];
      if (id) {
        const b = el("button", "wl", label);
        b.type = "button";
        b.addEventListener("click", () => onOpen(id));
        parent.appendChild(b);
      } else parent.appendChild(el("span", "wl dead", label));
    } else if (m[3] !== undefined) parent.appendChild(el("strong", "", m[3]));
    else parent.appendChild(el("code", "", m[4]));
    last = rx.lastIndex;
  }
  if (last < text.length) parent.appendChild(document.createTextNode(text.slice(last)));
}
function renderMarkdown(root, text, title, links, onOpen) {
  let para = [], first = true;
  const flush = () => {
    if (!para.length) return;
    const p = el("p");
    renderInline(p, para.join(" "), links, onOpen);
    root.appendChild(p);
    para = [];
  };
  text.split("\n").forEach((raw) => {
    const line = raw.replace(/\s+$/, "");
    if (!line.trim()) { flush(); return; }
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) {
      flush();
      if (first && h[1].length === 1 && h[2].trim().toLowerCase() === title.toLowerCase()) { first = false; return; }
      first = false;
      const x = el("h" + Math.min(6, h[1].length + 2));
      renderInline(x, h[2], links, onOpen);
      root.appendChild(x);
      return;
    }
    first = false;
    const li = /^\s*[-*]\s+(.*)$/.exec(line);
    if (li) {
      flush();
      const d = el("div", "li");
      renderInline(d, li[1], links, onOpen);
      root.appendChild(d);
      return;
    }
    if (/^>\s?/.test(line)) {
      flush();
      const q = el("blockquote");
      renderInline(q, line.replace(/^>\s?/, ""), links, onOpen);
      root.appendChild(q);
      return;
    }
    para.push(line.trim());
  });
  flush();
}

/* ---------- the viewer ---------- */
const viewer = (function () {
  const box = $("#viewer"), body = $("#v-body"), bar = $("#v-bar"), wrap = $("#v-wrap");
  let hist = [], pos = -1;

  function updateBar() {
    const vis = body.clientHeight, tot = body.scrollHeight;
    if (tot <= vis + 2) { bar.style.opacity = "0"; return; }
    bar.style.opacity = "0.75";
    const h = Math.max(24, (vis / tot) * vis);
    bar.style.height = h + "px";
    bar.style.top = (body.scrollTop / (tot - vis)) * (vis - h) + "px";
  }
  body.addEventListener("scroll", updateBar);
  window.addEventListener("resize", updateBar);

  function show(n) {
    const links = {};
    n.links.concat(n.backlinks).forEach((r) => { links[r.title.toLowerCase()] = r.id; });
    $("#v-title").textContent = n.title;
    const chip = $("#v-type");
    chip.textContent = n.type;
    chip.style.color = colorOf(n.type);
    $("#v-path").textContent = n.path;
    $("#v-flag").hidden = !n.flag;
    body.textContent = "";
    renderMarkdown(body, n.text, n.title, links, (id) => open(id));
    [["Links", n.links], ["Linked from", n.backlinks]].forEach(([label, list]) => {
      if (!list.length) return;
      body.appendChild(el("h2", "vh", label));
      const w = el("div", "linklist");
      list.forEach((r) => {
        const b = el("button", "", r.title);
        b.type = "button";
        b.addEventListener("click", () => open(r.id));
        w.appendChild(b);
      });
      body.appendChild(w);
    });
    $("#v-back").disabled = pos <= 0;
    $("#v-fwd").disabled = pos >= hist.length - 1;
    box.hidden = false;
    body.scrollTop = 0;
    updateBar();
    if (graph && graph.idToIdx.has(n.id)) graph.focusId(n.id, false);
  }

  async function load(id) {
    const r = await fetch("/api/note?id=" + encodeURIComponent(id));
    if (!r.ok) throw new Error("That note is not in the files any more.");
    return r.json();
  }
  async function open(id) {
    try {
      const n = await load(id);
      hist = hist.slice(0, pos + 1);
      hist.push(id);
      pos = hist.length - 1;
      show(n);
      afterShow();
      return true;
    } catch (e) {
      alertBar("Could not open that note.", e.message);
      return false;
    }
  }
  async function step(d) {
    const np = pos + d;
    if (np < 0 || np >= hist.length) return;
    try { const n = await load(hist[np]); pos = np; show(n); } catch (e) { alertBar("Could not open that note.", e.message); }
  }
  function close() {
    box.hidden = true;
    hist = []; pos = -1;
  }
  return { open, close, back: () => step(-1), forward: () => step(1), isOpen: () => !box.hidden, el: box, body, wrap };
})();

function openNote(id) { return viewer.open(id); }

/* ---------- scrolling ---------- */
function scrollTarget() {
  if (viewer.isOpen()) return viewer.body;
  const cards = Array.from(document.querySelectorAll("#tray .card, body > .card"));
  for (let i = cards.length - 1; i >= 0; i--) if (cards[i].scrollHeight > cards[i].clientHeight + 4) return cards[i];
  return null;
}
function doScroll(dir, amount) {
  const t = scrollTarget();
  if (!t) { panGraph(dir, amount); return; }
  if (dir === "top") t.scrollTo({ top: 0, behavior: "smooth" });
  else if (dir === "bottom") t.scrollTo({ top: t.scrollHeight, behavior: "smooth" });
  else t.scrollBy({ top: (dir === "up" ? -1 : 1) * t.clientHeight * (SCROLL_FRACTION[amount] || SCROLL_FRACTION.some), behavior: "smooth" });
}
function panGraph(dir, amount) {
  if (!graph || !graph.n) return;
  if (dir === "top" || dir === "bottom") { graph.fit(); return; }
  const dy = (dir === "up" ? 1 : -1) * graph.hh * (SCROLL_FRACTION[amount] || SCROLL_FRACTION.some);
  const y0 = graph.view.y, t0 = performance.now();
  (function step(now) {
    const k = Math.min(1, (now - t0) / 350), e = 1 - Math.pow(1 - k, 3);
    graph.view.y = y0 + dy * e;
    if (k < 1) requestAnimationFrame(step);
  })(t0);
}

/* scroll buttons: tap for a step, hold to keep going. Works with a mouse and with a hand pinch. */
function wireScrollButton(btn, dir) {
  let timer = 0, viaPointer = false;
  const stop = () => { clearInterval(timer); timer = 0; setTimeout(() => { viaPointer = false; }, 800); };
  btn.addEventListener("pointerdown", () => {
    viaPointer = true;
    const t = scrollTarget();
    if (!t) return;
    t.scrollBy({ top: (dir === "up" ? -1 : 1) * t.clientHeight * SCROLL_FRACTION.little, behavior: "smooth" });
    clearInterval(timer);
    timer = setInterval(() => { t.scrollBy({ top: (dir === "up" ? -1 : 1) * t.clientHeight * HOLD_STEP }); }, HOLD_REPEAT_MS);
  });
  ["pointerup", "pointercancel", "pointerleave"].forEach((ev) => btn.addEventListener(ev, stop));
  btn.addEventListener("click", () => { if (viaPointer) return; doScroll(dir, "little"); }); // a click with no pointer press first is the keyboard
}
wireScrollButton($("#v-up"), "up");
wireScrollButton($("#v-down"), "down");

/* hand drag-scroll with a little momentum. Real mice keep normal text selection. */
(function () {
  const body = viewer.body;
  let d = null, vel = 0, lastY = 0, lastT = 0, raf = 0;
  const isHand = (e) => e.pointerId > HAND_POINTER_MIN;
  body.addEventListener("pointerdown", (e) => {
    if (!isHand(e)) return;
    cancelAnimationFrame(raf);
    d = { y: e.clientY, top: body.scrollTop };
    lastY = e.clientY; lastT = performance.now(); vel = 0;
  });
  body.addEventListener("pointermove", (e) => {
    if (!d || !isHand(e)) return;
    body.scrollTop = d.top - (e.clientY - d.y);
    const now = performance.now(), dt = Math.max(1, now - lastT);
    vel = 0.7 * vel + 0.3 * ((lastY - e.clientY) / dt) * 16;   // px per frame, finger up = scroll down
    lastY = e.clientY; lastT = now;
  });
  function release(e) {
    if (!d || !isHand(e)) return;
    d = null;
    if (Math.abs(vel) < 0.5) return;
    (function coast() {
      body.scrollTop += vel;
      vel *= INERTIA_DECAY;
      if (Math.abs(vel) > 0.3) raf = requestAnimationFrame(coast);
    })();
  }
  body.addEventListener("pointerup", release);
  body.addEventListener("pointercancel", release);
})();

/* keyboard: arrows, page keys, Home and End scroll the viewer when you are not typing */
document.addEventListener("keydown", (e) => {
  if (!viewer.isOpen()) return;
  const t = e.target;
  if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
  const map = { ArrowUp: ["up", "little"], ArrowDown: ["down", "little"], PageUp: ["up", "page"], PageDown: ["down", "page"], Home: ["top", "page"], End: ["bottom", "page"] };
  if (map[e.key]) { e.preventDefault(); doScroll(map[e.key][0], map[e.key][1]); }
});

/* viewer header buttons */
$("#v-close").addEventListener("click", () => { viewer.close(); screenChanged(); });
$("#v-back").addEventListener("click", () => viewer.back());
$("#v-fwd").addEventListener("click", () => viewer.forward());
makeGrabbable(viewer.el, { handle: "#v-head" });

/* ---------- the orb moves beside what is shown ---------- */
const roam = { on: true };
try { if (localStorage.getItem("jarvis.roam") === "0") roam.on = false; } catch (e) { /* storage unavailable */ }
function paintRoam() { const b = $("#b-roam"); b.textContent = roam.on ? "Roam" : "Still"; b.classList.toggle("muted", !roam.on); }
$("#b-roam").addEventListener("click", () => {
  roam.on = !roam.on;
  try { localStorage.setItem("jarvis.roam", roam.on ? "1" : "0"); } catch (e) { /* ignore */ }
  paintRoam();
  if (!roam.on) dockCtl.home(); else afterShow();
});
paintRoam();

function lastCard() {
  const cards = Array.from(document.querySelectorAll("#tray .card, body > .card"));
  return cards.length ? cards[cards.length - 1] : null;
}
function presentTarget() { return viewer.isOpen() ? viewer.el : lastCard(); }
/* called after anything is put on screen. Skipped if you docked the orb on purpose. */
function afterShow() {
  if (!roam.on || dockCtl.side()) return;
  const t = presentTarget();
  if (t) dockCtl.present(t);
}
/* called after anything is closed. When nothing is left the orb goes back to where it was. */
function screenChanged() {
  if (!presentTarget() && dockCtl.away()) dockCtl.home();
}

function closeScreen(what) {
  const cards = Array.from(document.querySelectorAll("#tray .card, body > .card"));
  if (what === "all") {
    viewer.close();
    cards.forEach((c) => c.remove());
  } else if (viewer.isOpen()) viewer.close();
  else if (cards.length) cards[cards.length - 1].remove();
  screenChanged();   // with nothing left on screen the orb goes back to where it was
}

function orbLayer(to) { if (window.setOrbLayer) window.setOrbLayer(to); }
function orbTo(to) {
  if ((to === "home" || to === "center") && window.orbAtScreen && window.orbAtScreen() !== "main") { window.callOrbTo("main"); if (to === "home") return; }
  if (window.overlayAlive) { try { fetch("/api/orb", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ move: to === "near" ? "center" : to }) }); } catch (e) { /* ignore */ } return; }
  if (to === "near") { const t = presentTarget(); if (t) dockCtl.present(t); else dockCtl.goto("center"); return; }
  dockCtl.goto(to);
}

/* ---------- run what the server asked for ---------- */
async function runActions(actions) {
  for (const a of actions || []) {
    if (a.type === "open_note") await viewer.open(a.id);
    else if (a.type === "scroll") doScroll(a.dir, a.amount);
    else if (a.type === "orb") orbTo(a.to);
    else if (a.type === "layer") orbLayer(a.to);
    else if (a.type === "screen") { if (window.callOrbTo) window.callOrbTo(a.to); }
    else if (a.type === "close") closeScreen(a.what);
    else if (a.type === "audio") {
      const hold = document.getElementById("audio-holder");
      if (hold) hold.textContent = "";
      if (window.Ambience) { if (a.id === "focus" || a.id === "spa") window.Ambience.play(a.id); else window.Ambience.stop(); }
    }
    else if (a.type === "holo") { if (window.Holo) window.Holo.set(!!a.on); }
    else if (a.type === "history") { if (a.dir === "forward") viewer.forward(); else viewer.back(); }
  }
}
