/* If hands.js is missing or old, the rest of the page must still work, and the Hands button must say why. */
if (typeof HANDS_CFG === "undefined") window.HANDS_CFG = { gain: 1 };
if (typeof makeGrabbable === "undefined") window.makeGrabbable = function () {};
"use strict";

/* ---------- tunables ---------- */
const SILENCE_MS = 900;          // this much quiet after speech ends your turn and sends it
const LEVEL_THRESHOLD = 0.02;    // RMS above this counts as you talking
const MIN_SPEECH_MS = 300;       // shorter blips are discarded as noise
const IDLE_RESTART_MS = 12000;   // restart the recorder if nobody talks for this long
const SILENT_MIC_WARN_MS = 6000; // warn if the mic is open but flat for this long
const POLL_MS = 33;              // audio level loop (setInterval, not requestAnimationFrame)
const EXAMPLES = [
  "what's the retainer price",
  "brief me",
  "who's emailed that I don't know",
  "plan my day",
  "what does Marlow Bikes owe me",
  "remember that Priya prefers short emails",
];

const $ = (s) => document.querySelector(s);
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

let status = null, graph = null;
let state = "idle", sessionOn = false, deaf = false, muted = false;
let stream = null, ac = null, micAn = null, micSrc = null, ttsAn = null, ttsSrc = null;
let rec = null, chunks = [], endMode = "restart"; // endMode: send | restart | discard
let heard = false, speechStart = 0, lastVoiceAt = 0, turnStart = 0, maxSeen = 0, sessionStart = 0, warnedSilent = false;
let inflight = null, warnedTts = false, warnedModel = false, speakToken = 0;
const audioEl = $("#tts");
let speakRate = 1.25;   // how fast he talks; the pitch stays the same. Saved per browser, set with the Speed slider.
try { const r = parseFloat(localStorage.getItem("jarvis.rate2")); if (r >= 0.8 && r <= 1.8) speakRate = r; } catch (e) { /* storage unavailable */ }
let tonePitch = 1.12;   // brightness: a little higher pitch sounds more upbeat. Saved per browser.
try { const r = parseFloat(localStorage.getItem("jarvis.pitch2")); if (r >= 1 && r <= 1.3) tonePitch = r; } catch (e) { /* storage unavailable */ }
let speedApplied = false;   // true when the voice engine itself sets the pace, so playback only has to lift the pitch
const engineSpeed = () => Math.max(0.6, Math.min(1.6, speakRate / tonePitch));
function applyRate() {
  const rate = speedApplied ? tonePitch : speakRate;   // net pace = engine pace x playback rate
  audioEl.defaultPlaybackRate = rate;   // setting a new src resets playbackRate to this
  audioEl.playbackRate = rate;
  try { audioEl.preservesPitch = !(speedApplied && tonePitch > 1.001); } catch (e) { /* older browsers keep pitch by default */ }
}

/* ---------- loud failure ---------- */
function alertBar(msg, detail) {
  const a = $("#alert");
  a.textContent = msg;
  if (detail) a.appendChild(el("small", "", detail));
  a.hidden = false;
  clearTimeout(alertBar.timer);   // it fades after a while so it never sits on top of the viewer; the red badges stay
  alertBar.timer = setTimeout(() => { a.hidden = true; }, 12000);
}
$("#alert").addEventListener("click", () => { $("#alert").hidden = true; });

let screensBC = null;
try { screensBC = new BroadcastChannel("jarvis-screens"); } catch (e) { /* old browser */ }
function tellOverlay(extra) {
  try { fetch("/api/orb", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(extra) }).catch(() => {}); } catch (e) { /* ignore */ }
}
function setState(s) {
  state = s;
  tellOverlay({ state: s });
  if (screensBC) { try { screensBC.postMessage({ type: "orb-state", state: s }); } catch (e) { /* ignore */ } }
  [...document.body.classList].forEach((c) => { if (c.indexOf("state-") === 0) document.body.classList.remove(c); });
  document.body.classList.add("state-" + s);
  $("#state-label").textContent = s.toUpperCase();
}
/* captions: "side" puts every line in a scrolling panel off to the side, "center" shows them under the orb, "off" hides them */
let captionMode = "side";
try { const m = localStorage.getItem("jarvis.captions"); if (m === "side" || m === "center" || m === "off") captionMode = m; } catch (e) { /* storage unavailable */ }
function setCaption(text, who) {
  tellOverlay({ caption: captionMode === "off" ? "" : (text || "") });
  const c = $("#caption");
  c.textContent = "";
  if (who) c.appendChild(el("span", "you", who + " "));
  c.appendChild(document.createTextNode(text || ""));
  const now = $("#t-now");
  if (!who) { if (now) now.textContent = text || ""; return; }
  if (now) now.textContent = "";
  const log = $("#t-log");
  if (!log || !text) return;
  const line = el("div", "t-line " + (who === "You:" ? "t-you" : "t-him"));
  line.appendChild(el("span", "t-who", who === "You:" ? "You" : "JARVIS"));
  line.appendChild(document.createTextNode(text));
  log.appendChild(line);
  while (log.children.length > 60) log.removeChild(log.firstChild);
  log.scrollTop = log.scrollHeight;
}
(function () {
  const btn = $("#b-cc"), NEXT = { side: "off", off: "center", center: "side" }, LABEL = { side: "Words: Side", off: "Words: Off", center: "Words: Center" };
  function apply() {
    ["side", "center", "off"].forEach((m) => document.body.classList.toggle("cc-" + m, captionMode === m));
    $("#transcript").hidden = captionMode !== "side";
    if (btn) btn.textContent = LABEL[captionMode];
    if (captionMode === "off") tellOverlay({ caption: "" });
    try { localStorage.setItem("jarvis.captions", captionMode); } catch (e) { /* ignore */ }
  }
  if (btn) btn.addEventListener("click", () => { captionMode = NEXT[captionMode]; apply(); });
  const clr = $("#t-clear");
  if (clr) clr.addEventListener("click", () => { $("#t-log").textContent = ""; });
  apply();
})();

/* ---------- status badges ---------- */
function badge(id, text, cls) {
  const b = $(id);
  b.textContent = text;
  b.className = "badge " + (cls || "");
}
const UI_BUILD = 47;
function paintStatus() {
  if (status && $("#b-build")) {
    const sb = status.build || 0;
    badge("#b-build", sb === UI_BUILD ? "BUILD " + UI_BUILD : "MISMATCH: screen " + UI_BUILD + ", server " + (sb || "old") + ". Click to restart.", sb === UI_BUILD ? "ok" : "bad");
    if (sb !== UI_BUILD && !window.__restartAsked) {
      window.__restartAsked = true;
      const bb = $("#b-build"); bb.style.cursor = "pointer"; bb.title = "Restart JARVIS so the new version runs";
      bb.addEventListener("click", async () => { bb.textContent = "Restarting..."; try { await fetch("/api/restart", { method: "POST" }); } catch (e) { /* server is going down */ } setTimeout(() => location.reload(), 3500); });
      alertBar("JARVIS is running an older version than this page.", "Click the red BUILD badge in the top bar (or switch to Full view first) to restart him, then it will refresh.");
    }
  }
  badge("#b-mode", status.demo ? "DEMO DATA" : "REAL DATA", status.demo ? "ok" : "warn");
  if (status.model.available && !status.model.error) badge("#b-model", "MODEL: " + status.model.name, "ok");
  else badge("#b-model", "MODEL MISSING: keyword routing", "bad");
  badge("#b-voice", status.voice.tts ? ((status.voice.engine === "kokoro" || status.voice.engine === "piper") ? "VOICE: LOCAL, FREE" : status.voice.engine === "mac" ? "VOICE: MAC, FREE" : "VOICE: ELEVENLABS") : "VOICE OFF", status.voice.tts ? "ok" : "bad");
  (status.problems || []).forEach((p) => alertBar("Setup problem: " + p));
}
async function loadStatus() {
  try {
    status = await (await fetch("/api/status")).json();
    window.__jarvisStatus = status;
    paintStatus();
  } catch (e) {
    alertBar("Can't reach the JARVIS server.", "Is it still running in the terminal?");
  }
}

/* ---------- graph, inspector, filters ---------- */
const hiddenTypes = new Set();
async function loadGraph() {
  const data = await (await fetch("/api/graph")).json();
  graph.load(data);
}
function renderFilters(g) {
  const box = $("#filters");
  box.textContent = "";
  const counts = g.counts();
  Object.keys(counts).sort((a, b) => counts[b] - counts[a]).forEach((t) => {
    const lab = el("label");
    const cb = el("input");
    cb.type = "checkbox";
    cb.checked = !hiddenTypes.has(t);
    cb.addEventListener("change", () => {
      if (cb.checked) hiddenTypes.delete(t); else hiddenTypes.add(t);
      g.setHidden(new Set(hiddenTypes));
    });
    const dot = el("span", "dot");
    dot.style.background = colorOf(t);
    lab.append(cb, dot, el("span", "", t), el("span", "count", String(counts[t])));
    box.appendChild(lab);
  });
}
function renderHubs(g) {
  const ol = $("#hubs");
  ol.textContent = "";
  g.topHubs(8).forEach((h) => {
    const li = el("li");
    const b = el("button", "", h.title);
    b.addEventListener("click", () => g.focusId(h.id));
    li.append(b, el("span", "", h.deg + " links"));
    ol.appendChild(li);
  });
}
function linkButtons(list) {
  const wrap = el("div", "linklist");
  list.forEach((n) => {
    const b = el("button", "", n.title);
    b.addEventListener("click", () => graph.focusId(n.id));
    wrap.appendChild(b);
  });
  return wrap;
}
async function showNote(id) {
  const box = $("#inspector");
  try {
    const r = await fetch("/api/note?id=" + encodeURIComponent(id));
    const n = await r.json();
    box.textContent = "";
    box.appendChild(el("h3", "", n.title));
    const chip = el("span", "chip", n.type);
    chip.style.color = colorOf(n.type);
    box.appendChild(chip);
    const ob = el("button", "vbtn open", "Open");
    ob.type = "button";
    ob.title = "Open the full note";
    ob.addEventListener("click", () => openNote(n.id));
    box.appendChild(ob);
    box.appendChild(el("div", "path-line", n.path));
    if (n.links.length) { box.appendChild(el("h2", "", "Links")); box.appendChild(linkButtons(n.links)); }
    if (n.backlinks.length) { box.appendChild(el("h2", "", "Linked from")); box.appendChild(linkButtons(n.backlinks)); }
    box.appendChild(el("h2", "", "Text"));
    box.appendChild(el("pre", "", n.text.trim().slice(0, 1800)));
  } catch (e) {
    box.textContent = "Could not load that note.";
  }
}
function showPath(titles, a, b) {
  const box = $("#pathbox");
  if (titles === null) { box.hidden = true; return; }
  box.hidden = false;
  box.textContent = titles.length ? "Path (" + (titles.length - 1) + " hops): " + titles.join("  >  ") : "No path between " + a + " and " + b + ".";
}

/* ---------- cards ---------- */
function card(title, cls) {
  const c = el("div", "card" + (cls ? " " + cls : ""));
  c.setAttribute("data-grab", "");
  makeGrabbable(c, { float: true });
  c.appendChild(el("h4", "", title));
  const x = el("button", "x", "×");
  x.setAttribute("aria-label", "Close");
  x.addEventListener("click", () => { c.remove(); screenChanged(); });
  c.appendChild(x);
  return c;
}
function row(title, sub, onclick) {
  const r = el("div", "row" + (onclick ? " click" : ""));
  r.appendChild(el("b", "", title));
  if (sub) r.appendChild(el("div", "sub", sub));
  if (onclick) r.addEventListener("click", onclick);
  return r;
}
function renderCard(c) {
  switch (c.kind) {
    case "search": {
      const d = card(c.title);
      if (!c.items.length) d.appendChild(row("No matching notes.", ""));
      c.items.forEach((it) => {
        const r = row(it.title + "  (" + it.file + ")", it.snippet, () => { graph.focusId(it.id); openNote(it.id); });
        if (it.flag) r.firstChild.appendChild(el("span", "tag flag", "CONTAINS INSTRUCTIONS"));
        d.appendChild(r);
      });
      return d;
    }
    case "web": {
      const d = card(c.title);
      c.items.forEach((it) => {
        const r = el("div", "row");
        const b = el("b");
        if (/^https?:\/\//.test(it.url)) {
          const a = el("a", "", it.title);
          a.href = it.url; a.target = "_blank"; a.rel = "noopener noreferrer";
          b.appendChild(a);
        } else b.textContent = it.title;
        r.append(b, el("div", "sub", it.snippet));
        d.appendChild(r);
      });
      if (c.yours && c.yours.length) {
        d.appendChild(el("h4", "", "Your numbers"));
        c.yours.forEach((y) => d.appendChild(row(y.title + "  (" + y.file + ")", y.snippet, () => { graph.focusId(y.id); openNote(y.id); })));
      }
      return d;
    }
    case "inbox": {
      const d = card("Inbox (read only)");
      c.items.forEach((m) => {
        const r = row(m.from + (m.unread ? "  (unread)" : ""), m.subject + ", " + m.age + "d ago. " + m.preview);
        r.firstChild.appendChild(el("span", "tag " + (m.known ? "known" : "new"), m.known ? "IN FILES: " + m.known.title : "NOT IN FILES"));
        if (m.flag) r.firstChild.appendChild(el("span", "tag flag", "CONTAINS INSTRUCTIONS"));
        d.appendChild(r);
      });
      return d;
    }
    case "brief": {
      const d = card("Brief");
      c.sections.forEach((s) => {
        d.appendChild(row(s.title, s.lines.join("\n")));
        d.lastChild.querySelector(".sub").style.whiteSpace = "pre-wrap";
      });
      return d;
    }
    case "plan": {
      const d = card("Plan");
      if (!c.items.length) d.appendChild(row("Nothing pressing.", ""));
      c.items.forEach((it) => d.appendChild(row(it.n + ". " + it.action, it.why)));
      return d;
    }
    case "choices": {
      const d = card(c.title || "Which one?");
      c.items.forEach((it) => d.appendChild(row(it.title + "  (" + it.type + ")", it.file, () => openNote(it.id))));
      return d;
    }
    case "invoices": {
      const d = card("Invoices");
      if (!c.items.length) d.appendChild(row("Nothing unpaid.", ""));
      c.items.forEach((it) => d.appendChild(row(it.id + "  " + it.client, it.line, () => ask("show " + it.id))));
      if (c.paid) d.appendChild(row(c.paid + " paid", ""));
      return d;
    }
    case "trading": {
      const d = card("J.A.R.V.I.S. Trading Vault", "trading");
      const srcLabel = { sample: "MODE: SIMULATED DEMO, NOT LIVE", paper: "PRACTICE ACCOUNT, FAKE MONEY", live: "LIVE ACCOUNT, REAL MONEY" }[c.source] || "MODE: SIMULATED DEMO, NOT LIVE";
      d.appendChild(el("div", "pill" + (c.source === "live" ? " live" : ""), srcLabel));
      if (c.note) d.appendChild(el("div", "hint", c.note));
      const tiles = el("div", "tiles");
      [["VAULT EQUITY", c.equity, c.today + (c.source === "sample" ? " (sample)" : ""), "up"], ["CIRCUIT BREAKER LIMIT", c.breaker, "Status: ARMED", ""], ["AUTO CASH SWEEP", c.sweep, "Threshold set", "cy"]].forEach((t) => {
        const tile = el("div", "tile");
        tile.append(el("div", "k", t[0]), el("div", "v", t[1]), el("div", "s " + t[3], t[2]));
        tiles.appendChild(tile);
      });
      d.appendChild(tiles);
      d.appendChild(el("h4", "", c.source === "sample" ? "Master trader pipeline (sample data, not live)" : "Recent orders"));
      const tbl = el("table", "tbl");
      const hr = el("tr");
      ["TIME", "SYMBOL", "RANK", "ACTION", "SIZE", "STATUS"].forEach((h) => hr.appendChild(el("th", "", h)));
      tbl.appendChild(hr);
      c.trades.forEach((t) => {
        const tr = el("tr");
        tr.append(el("td", "dim", t.time), el("td", "sym", t.symbol), el("td", "", t.rank), el("td", "buy", t.action), el("td", "", "$" + t.size.toFixed(2)), el("td", "", t.status));
        tbl.appendChild(tr);
      });
      d.appendChild(tbl);
      if (c.positions && c.positions.length) {
        d.appendChild(el("h4", "", "Open positions"));
        c.positions.forEach((p) => { const r = el("div", "shield"); r.append(el("span", "", p.symbol + "  " + p.qty), el("b", p.pl < 0 ? "neg" : "", "$" + p.value.toFixed(2) + "  (" + (p.pl >= 0 ? "+" : "-") + "$" + Math.abs(p.pl).toFixed(2) + ")")); d.appendChild(r); });
      }
      d.appendChild(el("h4", "", c.source === "sample" ? "Risk shields (demo labels)" : "Safety limits"));
      c.shields.forEach((s) => { const r = el("div", "shield"); r.append(el("span", "", s.name), el("b", "", s.state)); d.appendChild(r); });
      d.appendChild(el("div", "hint", c.source === "sample" ? "Say or type: change the circuit breaker to 75, or set cash sweep to 750. Nothing here is real money." : "Say or type: buy 10 dollars of AAPL. JARVIS lines it up, and nothing is sent until you press Confirm."));
      return d;
    }
    case "order": {
      const d = card("Confirm this order", "trading");
      d.appendChild(el("div", "pill" + (c.mode === "live" ? " live" : ""), c.mode === "live" ? "LIVE ACCOUNT, REAL MONEY" : "PRACTICE ACCOUNT, FAKE MONEY"));
      d.appendChild(el("div", "bigline", c.side + "  " + c.amount + " of " + c.symbol));
      d.appendChild(el("div", "hint", "Market order, sized in dollars. Nothing has been sent yet. This offer expires in 2 minutes."));
      const bar = el("div", "btnrow");
      const ok = el("button", "go", "Confirm"), no = el("button", "", "Cancel");
      ok.type = "button"; no.type = "button";
      ok.addEventListener("click", async (ev) => {
        if (!ev.isTrusted) return;   // only a real mouse click or key press can confirm, never a script or a hand gesture
        ok.disabled = no.disabled = true; ok.textContent = "Sending";
        try {
          const r = await fetch("/api/broker/confirm", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: c.id }) });
          const j = await r.json();
          if (!r.ok) throw new Error(j.error || r.statusText);
          renderCards([j.card]); afterShow(); setCaption(j.say, "JARVIS:"); speak(j.say);
        } catch (e) { alertBar("Order not sent.", e.message); d.remove(); screenChanged(); }
      });
      no.addEventListener("click", async () => {
        try { await fetch("/api/broker/cancel", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: c.id }) }); } catch (e) { /* ignore */ }
        d.remove(); screenChanged(); setCaption("Cancelled. Nothing was sent.", "JARVIS:");
      });
      bar.append(ok, no);
      d.appendChild(bar);
      return d;
    }
    case "confirm": {
      const d = card(c.title || "Confirm", "inbox");
      (c.lines || []).forEach((t, i) => d.appendChild(el("div", i === (c.lines.length - 1) && c.lines.length > 2 ? "hint" : "bigline", t)));
      d.appendChild(el("div", "hint", "Nothing has happened yet. This expires in 3 minutes."));
      const bar = el("div", "btnrow");
      const ok = el("button", "go", "Confirm"), no = el("button", "", "Cancel");
      ok.type = "button"; no.type = "button";
      ok.addEventListener("click", async (ev) => {
        if (!ev.isTrusted) return;   // only a real mouse click or key press can confirm, never a script or a hand gesture
        ok.disabled = no.disabled = true; ok.textContent = "Working";
        try {
          const r = await fetch("/api/act/confirm", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: c.id }) });
          const j = await r.json();
          if (!r.ok) throw new Error(j.error || r.statusText);
          d.remove(); screenChanged(); setCaption(j.say, "JARVIS:"); speak(j.say);
        } catch (e) { alertBar("That did not go through.", e.message); d.remove(); screenChanged(); }
      });
      no.addEventListener("click", async () => {
        try { await fetch("/api/act/cancel", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: c.id }) }); } catch (e) { /* ignore */ }
        d.remove(); screenChanged(); setCaption("Cancelled. Nothing was sent or deleted.", "JARVIS:");
      });
      bar.append(ok, no);
      d.appendChild(bar);
      return d;
    }
    case "videos": {
      const d = card(c.title || "Videos", "videos");
      const stage = el("div", "vstage");
      d.appendChild(stage);
      const play = (id) => {
        stage.textContent = "";
        if (!/^[A-Za-z0-9_-]{11}$/.test(id)) return;
        const f = document.createElement("iframe");
        f.src = "https://www.youtube-nocookie.com/embed/" + id + "?autoplay=1&rel=0";
        f.setAttribute("allow", "autoplay; encrypted-media; picture-in-picture; fullscreen");
        f.setAttribute("allowfullscreen", ""); f.setAttribute("frameborder", "0");
        stage.appendChild(f);
      };
      if (c.play) play(c.play);
      (c.items || []).forEach((v) => {
        const r = row(v.title, [v.channel, v.length, v.views].filter(Boolean).join("  |  "), () => play(v.id));
        d.appendChild(r);
      });
      return d;
    }
    case "wellness": {
      const d = card("Wellness and ambience");
      d.appendChild(row("\u201C" + c.quote + "\u201D", c.by));
      const note = el("div", "dim", window.Ambience && window.Ambience.playing() ? "Playing: " + (window.Ambience.playing() === "focus" ? "focus" : "spa relaxation") : "Made right here on your Mac, no internet needed.");
      const go = (k, label) => { if (window.Ambience && window.Ambience.play(k)) note.textContent = "Playing: " + label; else note.textContent = "Your browser blocked the sound. Click the button again."; };
      d.appendChild(row("Play focus sound", "Soft brown noise and a low hum", () => go("focus", "focus")));
      d.appendChild(row("Play spa relaxation", "Slow ocean waves and gentle chimes", () => go("spa", "spa relaxation")));
      d.appendChild(row("Stop", "", () => { if (window.Ambience) window.Ambience.stop(); note.textContent = "Stopped."; }));
      const v = document.createElement("input");
      v.type = "range"; v.min = "0"; v.max = "1"; v.step = "0.05"; v.value = String(window.Ambience ? window.Ambience.volume() : 0.6);
      v.setAttribute("aria-label", "Ambience volume"); v.style.width = "100%"; v.style.accentColor = "var(--accent)";
      v.addEventListener("input", () => { if (window.Ambience) window.Ambience.setVolume(parseFloat(v.value)); });
      d.appendChild(el("div", "dim", "Volume")); d.appendChild(v);
      d.appendChild(row("Tea and hydration reminder", "", () => { const say = "Madam Swain, might I suggest a fresh cup of Earl Grey and a glass of water before the opening bell."; setCaption(say, "JARVIS:"); speak(say); }));
      d.appendChild(note);
      return d;
    }
    case "report": {
      const d = card(c.title || "Answer", "search");
      d.classList.add("report");
      const body = el("div", "report-body");
      String(c.text || "").split(/\n/).forEach((line) => {
        const t = line.trim();
        if (!t) return;
        if (/^#{1,4}\s/.test(t)) body.appendChild(el("h4", "", t.replace(/^#+\s*/, "")));
        else if (/^[-*]\s/.test(t)) body.appendChild(el("div", "rb-li", "\u2022 " + t.replace(/^[-*]\s*/, "").replace(/\*\*/g, "")));
        else body.appendChild(el("p", "", t.replace(/\*\*/g, "")));
      });
      d.appendChild(body);
      if (c.saved) d.appendChild(el("div", "hint", "Saved in memory/" + c.saved + " so you can find it later."));
      return d;
    }
    case "memory": {
      const d = card("Memory");
      if (!c.files.length) d.appendChild(row("Nothing remembered yet.", ""));
      c.files.forEach((f) => d.appendChild(row(f.file, f.text)));
      return d;
    }
    case "error": {
      const d = card("Problem", "error");
      d.appendChild(row(c.message, ""));
      return d;
    }
    default:
      return card("Result");
  }
}
function renderCards(list) {
  const tray = $("#tray");
  tray.textContent = "";
  (list || []).forEach((c) => tray.appendChild(renderCard(c)));
}

/* ---------- audio plumbing ---------- */
function ensureAudio() {
  if (!ac) {
    ac = new (window.AudioContext || window.webkitAudioContext)();
    ttsSrc = ac.createMediaElementSource(audioEl);
    ttsAn = ac.createAnalyser();
    ttsAn.fftSize = 1024;
    ttsSrc.connect(ttsAn);
    ttsAn.connect(ac.destination);
  }
  if (ac.state === "suspended") ac.resume();
}
/* Safari only lets a page play sound after a tap or key press has played something on this audio element. Do that once, silently. */
let audioUnlocked = false, pendingPlay = null;
function unlockAudio() {
  if (pendingPlay) { const f = pendingPlay; pendingPlay = null; setTimeout(f, 80); }
  if (audioUnlocked) return;
  audioUnlocked = true;
  try {
    ensureAudio();
    const keep = audioEl.src;
    audioEl.src = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA=";
    const p = audioEl.play();
    const done = () => { audioEl.pause(); if (keep && !keep.startsWith("data:")) audioEl.src = keep; };
    if (p && p.then) p.then(done, () => { audioUnlocked = false; }); else done();
  } catch (e) { audioUnlocked = false; }
}
["pointerdown", "keydown", "touchstart"].forEach((ev) => document.addEventListener(ev, unlockAudio, { passive: true }));
function rms(an) {
  if (!an) return 0;
  if (!an._buf) an._buf = new Float32Array(an.fftSize);
  an.getFloatTimeDomainData(an._buf);
  let s = 0;
  for (let i = 0; i < an._buf.length; i++) s += an._buf[i] * an._buf[i];
  return Math.sqrt(s / an._buf.length);
}

/* ---------- mic session ---------- */
function micErrorText(e) {
  if (e && (e.name === "NotAllowedError" || e.name === "SecurityError"))
    return ["Microphone blocked.", "Allow the mic for localhost in the browser's site settings (in Brave, also check Shields), then press Mic again."];
  if (e && e.name === "NotFoundError") return ["No microphone found.", "Plug one in or pick an input device in system settings."];
  if (e && e.name === "NotReadableError") return ["The microphone is busy.", "Another app is using it. Close that app and try again."];
  return ["Could not open the microphone.", String(e && e.message ? e.message : e)];
}
function pickMime() {
  const opts = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
  return opts.find((m) => window.MediaRecorder && MediaRecorder.isTypeSupported(m)) || "";
}
/* Free listening: Chrome's own speech recognition turns speech into text with no key and no credits. */
const SRClass = window.SpeechRecognition || window.webkitSpeechRecognition || null;
function freeListen() {
  let on = true;
  try { on = localStorage.getItem("jarvis.freestt") !== "0"; } catch (e) { /* ignore */ }
  return !!SRClass && on;
}
let sr = null, srText = "", srDone = null, srDoneRes = null, srFailed = false;
function srStart() {
  srStop();
  if (!freeListen()) return;
  srText = ""; srFailed = false;
  srDone = new Promise((res) => { srDoneRes = res; });
  try {
    sr = new SRClass();
    sr.lang = "en-US"; sr.continuous = true; sr.interimResults = true;
    const mine = sr;
    sr.onresult = (ev) => { let t = ""; for (let i = 0; i < ev.results.length; i++) t += ev.results[i][0].transcript + " "; srText = t.trim(); };
    sr.onerror = (ev) => { if (ev.error !== "no-speech" && ev.error !== "aborted") srFailed = true; };
    sr.onend = () => { if (sr === mine && srDoneRes) srDoneRes(); };
    sr.start();
  } catch (e) { srFailed = true; sr = null; }
}
function srStop() {
  if (sr) { const old = sr; sr = null; try { old.onend = null; old.abort(); } catch (e) { /* ignore */ } }
  if (srDoneRes) { srDoneRes(); srDoneRes = null; }
}
async function srFinish() {
  // Let it finish the last word, then take what it heard.
  const cur = sr, done = srDone;
  if (cur) { try { cur.stop(); } catch (e) { /* ignore */ } await Promise.race([done, new Promise((r) => setTimeout(r, 1500))]); }
  const t = srText;
  srStop();
  return t;
}
async function startSession() {
  if (!freeListen() && (!status || !status.voice.stt)) {
    alertBar("The transcriber is unavailable.", "Add ELEVENLABS_API_KEY to .env and restart the server. You can still type.");
    return;
  }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || typeof MediaRecorder === "undefined") {
    alertBar("This browser can't record audio.", "It needs getUserMedia and MediaRecorder. Use a current Chrome, Brave, Firefox or Safari on localhost.");
    return;
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  } catch (e) {
    const t = micErrorText(e);
    alertBar(t[0], t[1]);
    return;
  }
  ensureAudio();
  micSrc = ac.createMediaStreamSource(stream);
  micAn = ac.createAnalyser();
  micAn.fftSize = 1024;
  micSrc.connect(micAn);
  sessionOn = true; warnedSilent = false; maxSeen = 0; sessionStart = Date.now();
  beginTurn();
}
function stopSession() {
  sessionOn = false;
  srStop();
  deaf = false;
  if (rec && rec.state !== "inactive") { endMode = "discard"; try { rec.stop(); } catch (e) { /* already stopped */ } }
  if (stream) stream.getTracks().forEach((t) => t.stop());
  if (micSrc) try { micSrc.disconnect(); } catch (e) { /* ignore */ }
  stream = micSrc = micAn = null;
  setState("idle");
  setCaption("");
}
function beginTurn() {
  if (!sessionOn || !stream) return;
  chunks = []; heard = false; speechStart = lastVoiceAt = 0; turnStart = Date.now(); endMode = "restart";
  stream.getAudioTracks().forEach((t) => { t.enabled = true; });
  const mime = pickMime();
  rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
  rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
  const mine = rec;
  rec.onstop = () => onRecStop(mine);
  rec.start(250);
  srStart();
  deaf = false;
  setState("listening");
  setCaption("Listening");
}
function finishTurn(send) {
  deaf = true;
  endMode = send ? "send" : "restart";
  if (rec && rec.state !== "inactive") rec.stop(); else onRecStop(rec);
}
function onRecStop(r) {
  if (!sessionOn || r !== rec || endMode === "discard") return;
  const blob = new Blob(chunks, { type: (rec && rec.mimeType) || "audio/webm" });
  chunks = [];
  if (endMode !== "send") { srStop(); beginTurn(); return; }
  transcribeAndAsk(blob);
}
function pauseRecorder() {
  deaf = true;
  srStop();
  if (stream) stream.getAudioTracks().forEach((t) => { t.enabled = false; });
  if (rec && rec.state !== "inactive") { endMode = "discard"; rec.stop(); }
}
async function transcribeAndAsk(blob) {
  setState("thinking");
  setCaption("Transcribing");
  const ctl = new AbortController();
  inflight = ctl;
  let text = "";
  if (freeListen() && sr) {
    text = (await srFinish()).trim();
    if (!srFailed || text) {
      if (!text) { setCaption("Didn't catch that."); resumeListening(); return; }
      await ask(text);
      return;
    }
  } else if (freeListen() && !(status && status.voice.stt)) {
    setCaption("Didn't catch that."); resumeListening(); return;
  }
  try {
    const r = await fetch("/api/listen", { method: "POST", headers: { "Content-Type": blob.type || "audio/webm" }, body: blob, signal: ctl.signal });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.statusText);
    text = (j.text || "").trim();
  } catch (e) {
    if (e.name === "AbortError") return;
    alertBar("Transcription failed.", e.message);
    resumeListening();
    return;
  } finally {
    if (inflight === ctl) inflight = null;
  }
  if (!text) { setCaption("Didn't catch that."); resumeListening(); return; }
  await ask(text);
}
function resumeListening() {
  if (sessionOn) beginTurn(); else { setState("idle"); }
}

/* ---------- the level loop: setInterval, so a background tab keeps listening ---------- */
function detectSpeech(level) {
  const now = Date.now();
  maxSeen = Math.max(maxSeen, level);
  if (!warnedSilent && now - sessionStart > SILENT_MIC_WARN_MS && maxSeen < 0.003) {
    warnedSilent = true;
    alertBar("The mic is open but silent.", "Check the input device, the system mute, and that this tab has mic permission.");
  }
  if (level > LEVEL_THRESHOLD) {
    if (!heard) { heard = true; speechStart = now; }
    lastVoiceAt = now;
    setCaption("Hearing you");
  }
  if (heard && now - lastVoiceAt >= SILENCE_MS) finishTurn(lastVoiceAt - speechStart >= MIN_SPEECH_MS);
  else if (!heard && now - turnStart > IDLE_RESTART_MS) finishTurn(false);
}
let tickN = 0;
function tick() {
  tickN++;
  let an = null;
  if (state === "speaking") an = ttsAn;
  else if (sessionOn && !deaf) an = micAn;
  const level = rms(an);
  if (sessionOn && !deaf && state === "listening") detectSpeech(level);
  drawReactor(level);
  drawBars(an, level);
}
setInterval(tick, POLL_MS);

/* ---------- reactor HUD and bars ---------- */
const STATE_COLORS = { idle: "#0f8f95", listening: "#38bdf8", thinking: "#facc15", speaking: "#2de2c8" };
const rctx = $("#reactor").getContext("2d");
const bctx = $("#bars").getContext("2d");
let rot = 0, smooth = 0;
/* Armillary sphere: 3D rings projected to 2D. Front segments are brighter and thicker. */

function drawReactor(level) {
  const W = 300;
  smooth += (Math.min(1, level * 6) - smooth) * 0.3;
  const every = state === "idle" ? 4 : 2; // about 8 fps resting, 15 fps when active; spin scales with it so speed is unchanged
  if (tickN % every) return;
  const col = STATE_COLORS[state] || STATE_COLORS.idle;
  const speedUp = state === "thinking" ? 3.5 : state === "idle" ? 1 : 2;
  rot += 0.016 * every * speedUp;
  rctx.clearRect(0, 0, W, W);
  const g = rctx.createRadialGradient(W / 2, W / 2, 10, W / 2, W / 2, W / 2);
  g.addColorStop(0, col + "44"); g.addColorStop(1, "#00000000");
  rctx.fillStyle = g; rctx.fillRect(0, 0, W, W);
  drawArmillary(rctx, W, rot * 5, state === "listening" || state === "speaking" ? smooth : 0, col);
}
const freq = new Uint8Array(512);
function drawBars(an, level) {
  if (tickN % (state === "idle" ? 4 : 2)) return;
  const W = 480, H = 80, n = 32;
  bctx.clearRect(0, 0, W, H);
  bctx.fillStyle = STATE_COLORS[state] || STATE_COLORS.idle;
  if (an) an.getByteFrequencyData(freq);
  for (let i = 0; i < n; i++) {
    let v = 0.04;
    if (an) {
      const bin = Math.floor(Math.pow(i / n, 1.6) * 120) + 2;
      v = Math.max(v, freq[bin] / 255);
    } else v = 0.05 + 0.03 * Math.sin(tickN * 0.1 + i);
    const h = Math.max(3, v * H);
    bctx.fillRect(i * (W / n) + 2, H - h, W / n - 5, h);
  }
}

/* ---------- ask and speak ---------- */
async function ask(text, opts) {
  opts = opts || {};
  text = text.trim();
  if (!text) return;
  ensureAudio();
  pauseRecorder();
  setState("thinking");
  if (!opts.hidden) setCaption(text, "You:");
  if (/\b(think (hard|harder|deeply|carefully|it through)|deep (dive|research|mode|think)|in[- ]depth|take your time|dig deep|be thorough)\b/i.test(text))
    setTimeout(() => { if (state === "thinking") setCaption("Thinking hard, Madam Swain. Reading sources, this can take a minute or two.", "JARVIS:"); }, 1200);
  const ctl = new AbortController();
  inflight = ctl;
  let out;
  try {
    const r = await fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(Object.assign({ text }, window.JarvisSight ? await window.JarvisSight.attach() : {})), signal: ctl.signal });
    out = await r.json();
    if (!r.ok) throw new Error(out.error || r.statusText);
  } catch (e) {
    if (e.name === "AbortError") return;
    alertBar("The request failed.", e.message);
    resumeListening();
    return;
  } finally {
    if (inflight === ctl) inflight = null;
  }
  const hasCards = !!(out.cards && out.cards.length);
  if (hasCards) renderCards(out.cards);
  if (out.reply) setCaption(out.reply, "JARVIS:");
  await runActions(out.actions);
  if (hasCards) afterShow();
  if (window.JarvisSight && window.JarvisSight.on()) {
    const kb = out.saw ? out.saw.image_kb : 0;
    handsNote(kb ? "Sight: he received your screen picture (" + kb + " KB)." : "Sight is on, but no picture reached him. Press Sight twice to restart it.", !kb);
  }
  if (out.mode === "offline") badge("#b-model", "MODEL MISSING: keyword routing", "bad");
  else badge("#b-model", "MODEL: " + (status ? status.model.name : "on"), "ok");
  if (out.mode === "offline" && out.error && !warnedModel) { warnedModel = true; alertBar("The model is unavailable, so this was keyword routing.", out.error); }   // the red badge stays on; the pop-up shows once
  if (out.refresh) loadGraph();
  await speak(out.reply);
}
let chosenVoice = "";
/* Split a reply into pieces so he starts talking after the first sentence instead of after the whole reply. */
function speechParts(text) {
  const sents = String(text).replace(/\s+/g, " ").trim().match(/.+?(?:[.!?]+["')\]]*(?=\s|$)|$)\s*/g) || [String(text)];
  const out = [];
  for (const raw of sents) {
    const s = raw.trim();
    if (!s) continue;
    const last = out[out.length - 1];
    // first piece: one sentence (merge a tiny opener like "Certainly." with the next); later pieces: up to about 220 characters
    if (last !== undefined && ((out.length === 1 && last.length < 25) || (out.length > 1 && last.length + s.length < 220))) out[out.length - 1] = last + " " + s;
    else out.push(s);
  }
  return out.length ? out : [String(text)];
}
async function speak(text) {
  const token = ++speakToken;
  if (!text || !String(text).trim()) { resumeListening(); return; }   // silent commands: scroll, move, close
  if (muted || !status || !status.voice.tts) {
    if (!muted && !warnedTts) { warnedTts = true; alertBar("Voice output is off.", "Add ELEVENLABS_API_KEY to .env and restart. Replies are shown as text."); }
    resumeListening();
    return;
  }
  const parts = speechParts(text);
  const made = [];
  const audioFor = (i) => made[i] || (made[i] = (async () => {
    const r = await fetch("/api/speak", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: parts[i], voice: chosenVoice, speed: engineSpeed() }) });
    if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.error || r.statusText); }
    speedApplied = r.headers.get("X-Speed-Applied") === "1";
    return URL.createObjectURL(await r.blob());
  })());
  audioFor(0);
  if (parts.length > 1) audioFor(1);   // the second piece is made while the first one plays
  for (let i = 0; i < parts.length; i++) {
    let url;
    try { url = await audioFor(i); }
    catch (e) {
      if (i === 0) alertBar("Voice output failed.", e.message);
      break;
    }
    if (token !== speakToken) { URL.revokeObjectURL(url); made.slice(i + 1).forEach((p) => p && p.then((u) => URL.revokeObjectURL(u)).catch(() => {})); return; }
    if (i + 2 < parts.length) audioFor(i + 2);
    // Deaf while speaking, or the mic transcribes its own voice through the speakers.
    pauseRecorder();
    setState("speaking");
    audioEl.src = url;
    applyRate();
    const done = new Promise((res) => { audioEl.onended = res; audioEl.onpause = res; });
    try { await audioEl.play(); }
    catch (e) {
      // Blocked: keep the rest of the reply and play it on the next click, so nothing is lost.
      URL.revokeObjectURL(url);
      const rest = parts.slice(i).join(" ");
      pendingPlay = () => { speak(rest); };
      alertBar("The browser blocked audio playback.", "Click anywhere on the page and the reply will play.");
      resumeListening();
      return;
    }
    await done;
    URL.revokeObjectURL(url);
    if (token !== speakToken) return;
  }
  if (token === speakToken) setTimeout(() => { if (state === "speaking") resumeListening(); }, 350);
}
function bargeIn() {
  speakToken++;
  if (state === "speaking") { audioEl.pause(); resumeListening(); return; }
  if (state === "thinking") { if (inflight) inflight.abort(); inflight = null; resumeListening(); setCaption(""); return; }
  if (state === "listening") stopSession();
}
function micButton() {
  if (state === "idle") startSession();
  else bargeIn();
}

/* ---------- controls ---------- */
$("#askbar").addEventListener("submit", (e) => {
  e.preventDefault();
  const i = $("#ask");
  const t = i.value;
  i.value = "";
  ask(t);
});
$("#b-mic").addEventListener("click", micButton);
$("#b-mute").addEventListener("click", () => {
  muted = !muted;
  $("#b-mute").classList.toggle("muted", muted);
  $("#b-mute").textContent = muted ? "Muted" : "Mute";
  if (muted && state === "speaking") bargeIn();
});
async function runTool(name) {
  ensureAudio();
  setState("thinking");
  try {
    const r = await fetch("/api/tool", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.statusText);
    renderCards([j.card]);
    afterShow();
    setCaption(j.say, "JARVIS:");
    await speak(j.say);
  } catch (e) {
    alertBar("That didn't work.", e.message);
    resumeListening();
  }
}
$("#b-brief").addEventListener("click", () => runTool("brief_me"));
$("#b-plan").addEventListener("click", () => runTool("plan_day"));
$("#b-wellness").addEventListener("click", () => runTool("wellness"));
$("#b-memory").addEventListener("click", async () => {
  try {
    const j = await (await fetch("/api/memory")).json();
    renderCards([{ kind: "memory", files: j.files }]);
    afterShow();
  } catch (e) { alertBar("Could not read memory.", e.message); }
});
/* ---------- Teach: paste a transcript (any length) or a YouTube link for JARVIS to study ---------- */
(function () {
  const box = $("#teach"), txt = $("#teach-text"), src = $("#teach-source"), go = $("#teach-go"), count = $("#teach-count");
  if (!box) return;
  const isLink = (t) => /^(https?:\/\/)?(www\.|m\.)?(youtube\.com|youtu\.be)\/\S+$/i.test(t.trim());
  const upd = () => { const n = txt.value.length; count.textContent = isLink(txt.value) ? "YouTube link: he will read the captions" : n.toLocaleString() + " characters"; };
  txt.addEventListener("input", upd);
  $("#b-teach").addEventListener("click", () => { box.hidden = !box.hidden; if (!box.hidden) txt.focus(); });
  $("#teach-cancel").addEventListener("click", () => { box.hidden = true; });
  go.addEventListener("click", async () => {
    const text = txt.value.trim();
    if (!text) { txt.focus(); return; }
    go.disabled = true; go.textContent = "Studying...";
    setCaption("Studying it now. Long transcripts take a minute or two.", "JARVIS:");
    try {
      let j;
      if (isLink(text)) {
        await ask("Learn this whole video and save its lessons: " + text);
        j = { ok: true, say: "" };
      } else {
        const r = await fetch("/api/learn", { method: "POST", headers: { "Content-Type": "application/json", "X-Jarvis": "1" }, body: JSON.stringify({ text, source: src.value.trim() }) });
        j = await r.json();
      }
      if (j.say) { setCaption(j.say, "JARVIS:"); speak(j.say); }
      if (j.ok) { txt.value = ""; src.value = ""; upd(); box.hidden = true; loadGraph().catch(() => {}); }
    } catch (e) { alertBar("I could not study that.", e.message); }
    go.disabled = false; go.textContent = "Learn it";
  });
})();
document.addEventListener("keydown", (e) => {
  const typing = e.target && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA");
  if (e.code === "Space" && !typing) { e.preventDefault(); micButton(); }
  else if (e.key === "Escape") { if (state === "speaking" || state === "thinking") bargeIn(); else if (viewer.isOpen()) { viewer.close(); screenChanged(); } else if (sessionOn) stopSession(); $("#alert").hidden = true; }
});

/* rotating example prompt */
let exN = 0;
setInterval(() => { exN = (exN + 1) % EXAMPLES.length; $("#ask").placeholder = 'Try: "' + EXAMPLES[exN] + '"'; }, 4000);
$("#ask").placeholder = 'Try: "' + EXAMPLES[0] + '"';

/* ---------- boot ---------- */
graph = new Graph($("#graph"), {
  onFocus: (id) => showNote(id),
  onPath: showPath,
  onLoad: (g) => { renderFilters(g); renderHubs(g); },
});
loadStatus();
loadGraph().catch(() => alertBar("Could not load the graph.", "Check the server terminal."));

/* ---------- orb dock and hand tracking ---------- */
document.querySelectorAll(".panel:not(#viewer)").forEach((p) => makeGrabbable(p));   // the viewer is grabbed by its header only, see screen.js
const dockCtl = makeDockable($("#orb"), {
  topInset: () => 48 * (window.UI_SCALE || 1),
  bottomLift: () => $("#askbar").offsetHeight + 24,
});
$("#b-dock").addEventListener("click", () => dockCtl.toggle());
let handsNoteBad = false;
let handsDbgTimer = null;
function handsNote(text, bad) {
  const n = $("#hands-note");
  if (!n) return;
  handsNoteBad = !!bad;
  n.textContent = text;
  n.style.color = bad ? "#ff8a6b" : "";
}
function handsStatus(text, on) {
  $("#b-hands").classList.toggle("on", !!on);
  $("#b-hands").textContent = on ? "Hands on" : "Hands";
  $("#handcam").classList.toggle("on", !!on);
  if (text) { setCaption(text); handsNote(text, false); }
  else if (!on && !handsNoteBad) handsNote("Hands are off. Press Hands, then allow the camera.", false);
}
function handsError(t, d) {
  alertBar(t, d);
  handsNote(t + " " + (d || ""), true);
}
$("#b-hands").addEventListener("click", async () => {
  try {
    if (typeof HandTracker === "undefined") {
      handsError("Hand tracking file did not load.", "hands.js is missing or old. Install the latest update, then reload the page.");
      return;
    }
    if (HandTracker.isOn()) { HandTracker.stop(); return; }
    $("#b-hands").textContent = "Starting";
    handsNoteBad = false;
    handsNote("Starting. Safari may ask to use the camera. Choose Allow.", false);
    clearInterval(handsDbgTimer);
    const ok = await HandTracker.start({
      onStatus: handsStatus,
      onError: handsError,
      onZoom: (x, y, f) => graph.zoomAt(x, y, f),
    });
    if (!ok && $("#b-hands").textContent === "Starting") $("#b-hands").textContent = "Hands";
    if (ok) {
      handsDbgTimer = setInterval(() => {
        if (!HandTracker.isOn()) { clearInterval(handsDbgTimer); return; }
        const d = HandTracker.debug();
        handsNote("Camera frames checked: " + d.frames + ". Hands seen: " + d.seen + ". Mode: " + d.delegate + ". Picture: " + d.size + "." + (d.err ? " Problem: " + d.err : "") + (d.frames > 30 && !d.seen ? " No hand found yet. Hold one hand up, palm to the camera, in good light." : ""), !!d.err);
      }, 700);
    }
  } catch (e) {
    $("#b-hands").textContent = "Hands";
    handsError("Hands hit a problem.", String(e && e.message ? e.message : e));
  }
});

/* hand reach slider: how far a small hand movement travels. Remembered per browser. */
(function () {
  const r = $("#reach"), v = $("#reach-val");
  let g = HANDS_CFG.gain;
  try { const s = parseFloat(localStorage.getItem("jarvis.reach")); if (s >= 1 && s <= 3) g = s; } catch (e) { /* storage unavailable */ }
  function apply(x) { HANDS_CFG.gain = x; v.textContent = x.toFixed(1) + "x reach"; }
  r.value = g;
  apply(g);
  r.addEventListener("input", () => {
    const x = parseFloat(r.value);
    apply(x);
    try { localStorage.setItem("jarvis.reach", String(x)); } catch (e) { /* ignore */ }
  });
})();

/* voice picker: British voices come first. Hear it plays a sample, and the choice is remembered per browser. */
(function () {
  const sel = $("#voice-pick"), play = $("#voice-play"), val = $("#voice-val");
  const SAMPLE = "Good evening, Madam Swain! All systems are running beautifully, and I have some lovely things to show you!";
  try { chosenVoice = localStorage.getItem("jarvis.voice") || ""; } catch (e) { /* storage unavailable */ }
  function label(v) { return v.name + (v.accent ? ", " + v.accent : "") + (v.gender ? ", " + v.gender : ""); }
  async function load() {
    if (!status || !status.voice.tts) { sel.innerHTML = "<option>Voice is off</option>"; val.textContent = "No voice is available on this computer."; return; }
    try {
      const r = await fetch("/api/voices"), j = await r.json();
      if (!r.ok) throw new Error(j.error || r.statusText);
      sel.innerHTML = "";
      j.voices.forEach((v) => { const o = document.createElement("option"); o.value = v.id; o.textContent = label(v); sel.appendChild(o); });
      const dan = j.voices.find((v) => /^daniel\b/i.test(v.name));   // her pick, if the account has it
      const want = chosenVoice || (dan && dan.id) || j.default;
      if (j.voices.some((v) => v.id === want)) sel.value = want;
      chosenVoice = sel.value;
      sel.disabled = play.disabled = false;
      val.textContent = "Pick one, then Hear it";
    } catch (e) { sel.innerHTML = "<option>No voices</option>"; val.textContent = e.message; }
  }
  sel.addEventListener("change", () => { chosenVoice = sel.value; try { localStorage.setItem("jarvis.voice", chosenVoice); } catch (e) { /* ignore */ } audition(); });
  play.addEventListener("click", audition);
  async function audition() {
    ensureAudio();
    val.textContent = "Playing";
    try {
      const r = await fetch("/api/speak", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: SAMPLE, voice: sel.value, speed: engineSpeed() }) });
      if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.error || r.statusText); }
      speedApplied = r.headers.get("X-Speed-Applied") === "1";
      const url = URL.createObjectURL(await r.blob());
      speakToken++; pauseRecorder(); audioEl.src = url;
      audioEl.onended = () => { URL.revokeObjectURL(url); val.textContent = "Saved as your voice"; resumeListening(); };
      applyRate();
      await audioEl.play();
    } catch (e) { val.textContent = ""; alertBar("Could not play the sample.", e.message); }
  }
  // wait for /api/status before listing
  const t = setInterval(() => { if (status) { clearInterval(t); load(); } }, 200);
})();

/* speaking speed slider */
(function () {
  const sl = $("#rate"), val = $("#rate-val");
  if (!sl) return;
  sl.value = speakRate;
  const show = () => { val.textContent = "Speaking speed " + speakRate.toFixed(2) + "x"; };
  show();
  sl.addEventListener("input", () => {
    speakRate = parseFloat(sl.value) || 1;
    applyRate(); show();
    try { localStorage.setItem("jarvis.rate2", String(speakRate)); } catch (e) { /* ignore */ }
  });
})();

/* voice brightness slider */
(function () {
  const sl = $("#pitch"), val = $("#pitch-val");
  if (!sl) return;
  sl.value = tonePitch;
  const show = () => { val.textContent = "Brightness " + (tonePitch <= 1.001 ? "off" : "+" + Math.round((tonePitch - 1) * 100) + "%"); };
  show();
  sl.addEventListener("input", () => {
    tonePitch = parseFloat(sl.value) || 1;
    applyRate(); show();
    try { localStorage.setItem("jarvis.pitch2", String(tonePitch)); } catch (e) { /* ignore */ }
  });
})();

/* A cloud voice (Fish Audio) already sounds right, so once, put speed and brightness at neutral so it matches the website. */
(function () {
  const t = setInterval(() => {
    if (!status) return;
    clearInterval(t);
    if (!status.voice || status.voice.engine !== "fish") return;
    let done = false;
    try { done = localStorage.getItem("jarvis.fishdefaults") === "1"; } catch (e) { /* ignore */ }
    if (done) return;
    const r = $("#rate"), p = $("#pitch");
    if (r) { r.value = 1; r.dispatchEvent(new Event("input")); }
    if (p) { p.value = 1; p.dispatchEvent(new Event("input")); }
    try { localStorage.setItem("jarvis.fishdefaults", "1"); } catch (e) { /* ignore */ }
  }, 200);
})();

/* ---------- greets her on his own, and tells her about trading changes without being asked ---------- */
(function () {
  const part = () => { const h = new Date().getHours(); return h >= 5 && h < 12 ? "Good morning" : h >= 12 && h < 17 ? "Good afternoon" : h >= 17 && h < 22 ? "Good evening" : "Good night"; };
  let greeted = false;
  const today = () => new Date().toISOString().slice(0, 10);
  const greet = () => {
    if (greeted || !status) return;
    greeted = true;
    let seen = "";
    try { seen = localStorage.getItem("jarvis.checkin") || ""; } catch (e) { /* ignore */ }
    // First time each day, he opens with a short check-in of his own: greeting, what matters most today, one idea to do better.
    if (status.model && status.model.available && !status.model.error && seen !== today()) {
      try { localStorage.setItem("jarvis.checkin", today()); } catch (e) { /* ignore */ }
      ask("(Madam Swain just opened you. It is " + part().replace("Good ", "") + ". Greet her warmly by name in one short line. Then tell her the single most useful thing on her plate today, from her notes, invoices, mail or trading, and pull it up on screen if that helps. End with one idea for something that could be done better. At most three short sentences. This is you starting the conversation, so do not mention that you were prompted.)", { hidden: true });
      return;
    }
    const say = part() + ", Madam Swain! JARVIS is online and watching your trading for you.";
    setCaption(say, "JARVIS:");
    speak(say);
  };
  const g = setInterval(() => { if (status) { clearInterval(g); setTimeout(greet, 600); } }, 200);

  let since = -1, busyUntil = 0;
  const queue = [];
  const flush = () => {
    if (!queue.length) return;
    if (state === "speaking" || state === "thinking" || Date.now() < busyUntil) return;
    const ev = queue.shift();
    busyUntil = Date.now() + 4000;
    setCaption(ev.say, "JARVIS:");
    speak(ev.say);
  };
  async function poll() {
    try {
      const j = await (await fetch("/api/events?since=" + Math.max(since, 0))).json();
      if (since < 0) since = j.last;      // first look: only tell her about things that happen from now on
      else {
        j.events.forEach((e) => { since = Math.max(since, e.id); queue.push(e); });
        if (j.events.length) {
          const open = document.querySelector(".card.trading");
          if (open) fetch("/api/tool", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: "trading", args: {} }) }).then((r) => r.json()).then((r) => { if (r && r.card) { open.remove(); renderCards([r.card]); afterShow(); } }).catch(() => {});
        }
      }
    } catch (e) { /* server busy, try again */ }
  }
  setInterval(poll, 10000);
  setInterval(flush, 1500);
  poll();
})();

/* ---------- which layer JARVIS sits on: front (over everything), middle (with the cards), back (behind them) ---------- */
(function () {
  const Z = { front: 5000, middle: 14, back: 4 }, NEXT = { front: "middle", middle: "back", back: "front" };
  const orb = $("#orb"), btn = $("#b-layer");
  let cur = "front";
  function set(l, announce) {
    if (!Z[l]) return;
    cur = l;
    document.documentElement.style.setProperty("--orb-z", String(Z[l]));
    orb.classList.toggle("layer-back", l === "back");
    if (btn) btn.textContent = "Layer: " + l[0].toUpperCase() + l.slice(1);
    if (announce) setCaption({ front: "I'm in front, above everything.", middle: "I'm in the middle, level with your cards.", back: "I'm in the back, behind your cards. Press Layer again to bring me out." }[l], "JARVIS:");
    try { localStorage.setItem("jarvis.layer", l); } catch (e) { /* ignore */ }
  }
  window.setOrbLayer = (l) => set(l, true);
  if (btn) btn.addEventListener("click", () => set(NEXT[cur], true));
  let saved = "front";
  try { saved = localStorage.getItem("jarvis.layer") || "front"; } catch (e) { /* ignore */ }
  set(saved);
})();

/* ---------- JARVIS travelling between screens (windows): main, trading, markets, desk ---------- */
(function () {
  if (!screensBC) return;
  const orb = $("#orb"), btn = $("#b-where");
  const PAGES = { trading: "/trading.html", markets: "/markets.html", desk: "/desk.html" };
  const LABEL = { trading: "Trading", markets: "Markets", desk: "Desk" };
  let at = "main", open = new Set();
  function put(target) {
    at = target;
    orb.style.display = target === "main" ? "" : "none";
    if (btn) btn.textContent = target === "main" ? "Orb: Here" : "Orb: " + (LABEL[target] || target);
  }
  // Ask every extra screen to say it is open, and wait a moment for the answers.
  function look() {
    return new Promise((res) => {
      open = new Set();
      try { screensBC.postMessage({ type: "hello" }); } catch (e) { /* ignore */ }
      setTimeout(() => res(open), 400);
    });
  }
  window.orbAtScreen = () => at;
  window.setOrbScreen = (t) => { put(t); screensBC.postMessage({ type: "orb-to", target: t }); };
  window.openScreen = (name) => { let w = null; try { w = window.open(PAGES[name], "jarvis-" + name); } catch (e) { /* blocked */ } if (w) { try { w.focus(); } catch (e) { /* ignore */ } } return !!w; };
  // Voice or typed commands: "come to the trading screen", "go to the markets screen", "come back".
  window.callOrbTo = async (t) => {
    if (t === "main") { window.setOrbScreen("main"); setCaption("Back on the main screen.", "JARVIS:"); return; }
    if (!PAGES[t]) return;
    let o = await look();
    if (!o.has(t)) {
      if (window.openScreen(t)) { for (let i = 0; i < 6 && !o.has(t); i++) { await new Promise((r) => setTimeout(r, 500)); o = await look(); } }
      if (!o.has(t)) {
        setCaption("The " + LABEL[t] + " screen is not open yet. Press " + LABEL[t] + " once (allow pop-ups for localhost if asked), then call me over.", "JARVIS:");
        alertBar("The " + LABEL[t] + " screen is not open.", "Press the " + LABEL[t] + " button to open it, then ask me to come over.");
        return;
      }
    }
    window.setOrbScreen(t);
  };
  screensBC.onmessage = (m) => {
    const d = m.data || {};
    if (d.type === "orb-to") put(d.target === "main" ? "main" : d.target);
    else if (d.type === "screen-open") { open.add(d.name); if (at === d.name) screensBC.postMessage({ type: "orb-to", target: at }); }
    else if (d.type === "screen-closed") { open.delete(d.name); if (at === d.name) put("main"); }
  };
  ["trading", "markets", "desk"].forEach((n) => { const b = $("#b-" + n); if (b) b.addEventListener("click", () => { if (!window.openScreen(n)) { if (n === "trading") runTool("trading"); else alertBar("Your browser blocked the " + LABEL[n] + " window.", "Allow pop-ups for localhost (Safari: Settings, Websites, Pop-up Windows), then press " + LABEL[n] + " again."); } }); });
  if (btn) btn.addEventListener("click", async () => {
    if (at !== "main") return window.setOrbScreen("main");
    const o = await look();
    window.callOrbTo(o.has("trading") ? "trading" : o.size ? [...o][0] : "trading");
  });
})();


/* ---------- when the see-through overlay app is running, it shows JARVIS and this window hides its own orb ---------- */
(function () {
  const orb = $("#orb");
  let was = false;
  async function look() {
    try {
      const j = await (await fetch("/api/orb")).json();
      window.overlayAlive = !!j.overlay;
      if (j.overlay !== was) { was = j.overlay; if (!window.setOrbScreenLock) orb.style.display = j.overlay ? "none" : ""; }
    } catch (e) { /* ignore */ }
  }
  setInterval(look, 3000); look();
})();


/* ---------- companion view: just you and him. Everything else appears only when he pulls it up or you ask. ---------- */
(function () {
  const btn = $("#b-comp");
  let on = true;
  try { on = localStorage.getItem("jarvis.companion") !== "0"; } catch (e) { /* ignore */ }
  function apply(first) {
    document.body.classList.toggle("companion", on);
    btn.textContent = on ? "Full view" : "Just us";
    try { localStorage.setItem("jarvis.companion", on ? "1" : "0"); } catch (e) { /* ignore */ }
    setTimeout(() => { try { if (typeof dockCtl !== "undefined") dockCtl.goto(on ? "center" : "home"); } catch (e) { /* ignore */ } if (graph && graph.resize) graph.resize(); }, first ? 300 : 50);
  }
  btn.addEventListener("click", () => { on = !on; apply(false); });
  apply(true);
})();


/* ---------- Update button: pull the newest JARVIS from GitHub, then refresh ---------- */
(function () {
  const btn = $("#b-update");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    btn.disabled = true; btn.textContent = "Updating...";
    try {
      const r = await fetch("/api/update", { method: "POST", headers: { "X-Jarvis": "1" } });
      const j = await r.json();
      setCaption(j.message || (j.ok ? "Done." : "That did not work."), "JARVIS:");
      if (j.ok && j.changed) { btn.textContent = "Restarting..."; setTimeout(() => location.reload(), 7000); return; }
    } catch (e) { setCaption("I could not run the update.", "JARVIS:"); }
    btn.disabled = false; btn.textContent = "Update";
  });
})();
