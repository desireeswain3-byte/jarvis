/* What JARVIS can see.
   1. Every question carries "screen": the text of what the page is showing (open note, cards, inspector, which
      buttons are on). It is small and needs no permission.
   2. Sight (opt in): shares the screen through the browser's own picker. One downscaled picture is taken per question
      and sent with it. The browser shows its sharing indicator the whole time, and the stream stops on a second press. */
(function () {
  const $ = (s) => document.querySelector(s);
  const txt = (el, n) => (el ? (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim().slice(0, n) : "");
  let stream = null, vid = null;

  function say(msg, bad) {
    const n = $("#hands-note");
    if (n) { n.textContent = msg; n.style.color = bad ? "#ff8a6b" : ""; }
    if (typeof setCaption === "function") setCaption(msg);
  }

  function state() {
    const s = { page: "JARVIS dashboard", window: innerWidth + "x" + innerHeight };
    const viewer = $("#viewer");
    if (viewer && !viewer.hidden) {
      s.open_note = { title: txt($("#v-title"), 120), kind: txt($("#v-type"), 30), text: txt($("#v-body"), 2600) };
    }
    const cards = Array.from(document.querySelectorAll("#tray .card")).slice(0, 4).map((c) => txt(c, 800)).filter(Boolean);
    if (cards.length) s.cards_showing = cards;
    const insp = txt($("#inspector"), 500);
    if (insp && !/^Click a node/.test(insp)) s.selected_node = insp;
    const path = $("#pathbox");
    if (path && !path.hidden) s.traced_path = txt(path, 300);
    const cap = txt($("#caption"), 200);
    if (cap) s.caption = cap;
    const orb = $("#orb");
    s.orb = { where: orb ? (orb.classList.contains("docked-left") ? "docked left" : orb.classList.contains("docked-right") ? "docked right" : "free") : "", mode: txt($("#state-label"), 20) };
    s.buttons_on = Array.from(document.querySelectorAll("#askbar button.on")).map((b) => b.textContent.trim());
    s.hands_note = txt($("#hands-note"), 160);
    s.badges = [txt($("#b-mode"), 40), txt($("#b-model"), 40), txt($("#b-voice"), 40)].filter(Boolean);
    s.sight = stream ? "on, a screenshot is attached" : "off, no screenshot";
    if (!s.open_note && !s.cards_showing) s.top_hubs = txt($("#hubs"), 300);
    return s;
  }

  function shrink(src, sw, sh) {
    const w = Math.min(1280, sw), h = Math.round(sh * (w / sw));
    const c = document.createElement("canvas");
    c.width = w; c.height = h;
    c.getContext("2d").drawImage(src, 0, 0, w, h);
    return c.toDataURL("image/jpeg", 0.6);
  }

  async function frame() {
    if (!stream) return null;
    try { // best: ask the screen track for its newest frame directly
      const track = stream.getVideoTracks()[0];
      if (track && window.ImageCapture) {
        const bmp = await new ImageCapture(track).grabFrame();
        if (bmp && bmp.width) return shrink(bmp, bmp.width, bmp.height);
      }
    } catch (e) { /* fall back to the video element */ }
    if (vid && vid.readyState >= 2 && vid.videoWidth) return shrink(vid, vid.videoWidth, vid.videoHeight);
    return null;
  }

  async function attach() {
    const out = { screen: state() };
    const img = await frame();
    if (img) out.image = img;
    return out;
  }

  function stop(note) {
    if (stream) stream.getTracks().forEach((t) => { try { t.stop(); } catch (e) { /* already stopped */ } });
    stream = null;
    if (vid) { vid.srcObject = null; vid.remove(); vid = null; }
    const b = $("#b-sight");
    if (b) { b.classList.remove("on"); b.textContent = "Sight"; }
    if (note) say(note, false);
  }

  async function start() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) { say("This browser cannot share the screen. Use Chrome.", true); return; }
    const b = $("#b-sight");
    b.textContent = "Choosing";
    try {
      stream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: { ideal: 2, max: 5 } }, audio: false });
    } catch (e) {
      stream = null; b.textContent = "Sight";
      const mac = /Permission|NotAllowed/i.test(String(e && e.name));
      say(mac ? "Sight was not allowed. If Chrome never asked, open System Settings, Privacy and Security, Screen Recording, and turn on Google Chrome." : "Sight did not start: " + (e && e.message), true);
      return;
    }
    vid = document.createElement("video");
    vid.muted = true; vid.playsInline = true; vid.srcObject = stream;
    vid.style.cssText = "position:fixed;width:160px;height:90px;opacity:0.01;pointer-events:none;left:0;top:0;z-index:-1";
    document.body.appendChild(vid);
    try { await vid.play(); } catch (e) { /* frames still arrive once it plays */ }
    stream.getVideoTracks()[0].addEventListener("ended", () => stop("Sight stopped."));
    b.classList.add("on"); b.textContent = "Sight on";
    say("Sight is on. I take one picture of your screen with each question. Press Sight again to stop.", false);
  }

  window.JarvisSight = { state, attach, frame, stop, on: () => !!stream };
  document.addEventListener("DOMContentLoaded", () => {
    const b = $("#b-sight");
    if (b) b.addEventListener("click", () => { if (stream) stop("Sight is off."); else start(); });
  });
  if (document.readyState !== "loading") { const b = $("#b-sight"); if (b && !b.dataset.w) { b.dataset.w = 1; b.addEventListener("click", () => { if (stream) stop("Sight is off."); else start(); }); } }
})();
