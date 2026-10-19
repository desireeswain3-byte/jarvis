/* Shared by every extra screen (trading, markets, desk). Lets JARVIS appear on this screen when he is called over.
   Set window.SCREEN_NAME before loading this file. Talks to the main window over BroadcastChannel. */
(function () {
  const ME = window.SCREEN_NAME || "screen";
  let bc = null; try { bc = new BroadcastChannel("jarvis-screens"); } catch (e) { /* old browser */ }
  const wrap = document.createElement("div");
  wrap.id = "orb2"; wrap.style.cssText = "position:fixed;right:1.2rem;bottom:1.2rem;width:17rem;text-align:center;display:none;z-index:5000;pointer-events:none";
  wrap.innerHTML = '<style>@keyframes ringspin2{to{transform:rotate(360deg)}}</style>' +
    '<svg viewBox="-100 -100 200 200" style="position:absolute;left:-3.2rem;top:-3.2rem;width:23.4rem;height:23.4rem;animation:ringspin2 90s linear infinite" aria-hidden="true"></svg>' +
    '<canvas id="oc" width="300" height="300" style="width:17rem;height:17rem;display:block;position:relative"></canvas>' +
    '<div id="olab" style="font:700 .6875rem ui-monospace,Menlo,monospace;letter-spacing:.3em;margin-top:.25rem;color:#22d3c5">IDLE</div>';
  document.body.appendChild(wrap);
  if (window.jarvisRingSVG) wrap.querySelector("svg").innerHTML = window.jarvisRingSVG();
  const c = wrap.querySelector("#oc").getContext("2d"), lab = wrap.querySelector("#olab");
  let st = "idle", here = false, tick = 0, rot = 0, smooth = 0;
  function draw() {
    requestAnimationFrame(draw);
    if (!here || !window.drawArmillary) return;
    tick++;
    const every = st === "idle" ? 4 : 2;
    if (tick % every) return;
    const W = 300, col = (window.JARVIS_COLORS || {})[st] || "#0f8f95";
    const target = st === "speaking" ? 0.35 + 0.35 * Math.abs(Math.sin(tick / 5)) : st === "listening" ? 0.3 : 0;
    smooth += (target - smooth) * 0.3;
    rot += 0.016 * every * (st === "thinking" ? 3.5 : st === "idle" ? 1 : 2);
    c.clearRect(0, 0, W, W);
    const g = c.createRadialGradient(W / 2, W / 2, 10, W / 2, W / 2, W / 2);
    g.addColorStop(0, col + "44"); g.addColorStop(1, "#00000000");
    c.fillStyle = g; c.fillRect(0, 0, W, W);
    window.drawArmillary(c, W, rot * 5, st === "listening" || st === "speaking" ? smooth : 0, col);
  }
  draw();
  const btn = document.getElementById("bring");
  function setHere(h) { here = h; wrap.style.display = h ? "block" : "none"; if (btn) btn.textContent = h ? "Send JARVIS back" : "Bring JARVIS here"; }
  function go(target) { setHere(target === ME); if (bc) bc.postMessage({ type: "orb-to", target }); }
  if (btn) btn.addEventListener("click", () => go(here ? "main" : ME));
  if (bc) {
    bc.onmessage = (m) => {
      const d = m.data || {};
      if (d.type === "orb-to") setHere(d.target === ME);
      else if (d.type === "orb-state") { st = d.state; lab.textContent = String(d.state).toUpperCase(); lab.style.color = (window.JARVIS_COLORS || {})[d.state] || "#22d3c5"; }
      else if (d.type === "hello") { bc.postMessage({ type: "screen-open", name: ME }); if (here) bc.postMessage({ type: "orb-to", target: ME }); }
    };
    bc.postMessage({ type: "screen-open", name: ME });
    addEventListener("pagehide", () => bc.postMessage({ type: "screen-closed", name: ME }));
  }
  window.ScreenOrb = { name: ME, here: setHere, go, isHere: () => here };
})();
