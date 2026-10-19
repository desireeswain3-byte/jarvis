/* The look from the reference video: a tick ring around the orb, systems on the left, the clock and your numbers on the right.
   Only visible in the companion (just us) view. Cheap on purpose: one small fetch every 30 seconds, one clock tick a second. */
(function () {
  const $ = (s) => document.querySelector(s);
  const ring = $("#orb-ring"), L = $("#hud-left"), R = $("#hud-right");
  if (!ring || !L || !R) return;
  // tick ring (turns slowly with CSS, which costs the Mac almost nothing)
  let svg = '<circle r="96" fill="none" stroke="rgba(34,211,197,.35)" stroke-width=".6"/><circle r="88" fill="none" stroke="rgba(34,211,197,.18)" stroke-width=".4" stroke-dasharray="1.5 3"/>';
  for (let i = 0; i < 90; i++) {
    const a = (i / 90) * Math.PI * 2, big = i % 5 === 0, r1 = 96, r2 = big ? 90 : 93;
    svg += '<line x1="' + (Math.cos(a) * r1).toFixed(2) + '" y1="' + (Math.sin(a) * r1).toFixed(2) + '" x2="' + (Math.cos(a) * r2).toFixed(2) + '" y2="' + (Math.sin(a) * r2).toFixed(2) + '" stroke="rgba(34,211,197,' + (big ? ".8" : ".4") + ')" stroke-width="' + (big ? ".8" : ".5") + '"/>';
  }
  ring.innerHTML = svg;

  const row = (k, v, cls) => '<div class="hr"><span>' + k + '</span><b class="' + (cls || "") + '">' + v + "</b></div>";
  const money = (n) => "$" + Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  let acct = null, last = "", alerts = 0, since = -1;
  function nyOpen() {
    try {
      const p = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", weekday: "short", hour: "numeric", minute: "numeric", hour12: false }).formatToParts(new Date());
      const g = (t) => (p.find((x) => x.type === t) || {}).value;
      const m = parseInt(g("hour"), 10) * 60 + parseInt(g("minute"), 10);
      return !["Sat", "Sun"].includes(g("weekday")) && m >= 570 && m < 960;
    } catch (e) { return false; }
  }
  function paint() {
    if (!document.body.classList.contains("companion")) return;
    const st = window.__jarvisStatus || null;
    const now = new Date();
    const mode = st && st.trading ? st.trading.mode : "demo";
    L.innerHTML = '<h5>SYSTEMS</h5>' +
      row("MODEL", st && st.model && st.model.available && !st.model.error ? "ONLINE" : "OFFLINE", st && st.model && st.model.available && !st.model.error ? "ok" : "bad") +
      row("VOICE", st && st.voice ? (st.voice.engine === "off" ? "OFF" : String(st.voice.engine).toUpperCase()) : "...") +
      row("MARKET", nyOpen() ? "OPEN" : "CLOSED", nyOpen() ? "ok" : "") +
      row("ACCOUNT", mode === "paper" ? "PRACTICE" : mode === "live" ? "LIVE" : "DEMO", mode === "live" ? "bad" : "") +
      row("PROFIT GUARD", st && st.trading && st.trading.guard ? "ON" : "OFF", st && st.trading && st.trading.guard ? "ok" : "") +
      row("BUILD", st && st.build ? st.build : "?");
    const up = acct && !String(acct.today).startsWith("-");
    R.innerHTML = '<div class="clock">' + now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) + '</div><div class="date">' + now.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" }) + "</div>" +
      (acct ? row("EQUITY", acct.equity) + row("TODAY", String(acct.today).replace(" today", ""), up ? "ok" : "bad") + row("MODE", acct.src) : row("TRADING", "...")) +
      row("ALERTS TODAY", String(alerts)) +
      (last ? '<h5>LATEST UPDATE</h5><div class="upd">' + last.replace(/[<>&]/g, "") + "</div>" : "");
  }
  async function pull() {
    if (!document.body.classList.contains("companion")) return;
    try {
      const r = await (await fetch("/api/tool", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: "trading" }) })).json();
      const c = r.card; if (c) acct = { equity: c.equity, today: c.today, src: c.source === "paper" ? "PRACTICE" : c.source === "live" ? "LIVE" : "DEMO" };
    } catch (e) { /* ignore */ }
    try {
      const j = await (await fetch("/api/events?since=0")).json();
      const t0 = new Date(); t0.setHours(0, 0, 0, 0);
      const real = j.events.filter((e) => e.t * 1000 >= t0.getTime());
      alerts = real.length; if (j.events.length) last = j.events[j.events.length - 1].say;
    } catch (e) { /* ignore */ }
    paint();
  }
  const wait = setInterval(() => { if (window.__jarvisStatus) { clearInterval(wait); pull(); } }, 300);
  setInterval(pull, 30000);
  setInterval(paint, 1000);
})();
