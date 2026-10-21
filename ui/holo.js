/* Hologram view: the camera becomes the background, glass bubbles float with live numbers, and 3D objects hover.
   Grab with a pinch (hand tracking) or the mouse, flick to throw, tap a bubble to open it. Two hands (or two
   fingers) on a 3D object stretch or shrink it. Any .glb model dropped into ui/props floats here too.
   three.js is loaded from jsdelivr only when the view is first switched on. */
const Holo = (function () {
  const S = () => window.UI_SCALE || 1;
  let on = false, layer = null, raf = 0, lastT = 0, refreshTimer = null, hint = null;
  let bubbles = [];
  const grabs = new Map();          // pointerId -> {kind: "bubble"|"prop", ...}
  let T = null;                     // three.js world once loaded

  /* ---------- bubbles ---------- */
  function radiusFor(b) { return (b.id === "trading" ? 92 : b.id === "brain" ? 64 : 76) * S(); }
  function makeBubble(data, i, n) {
    const el = document.createElement("div");
    el.className = "holo-bubble" + (data.tone ? " " + data.tone : "");
    const r = radiusFor(data);
    el.style.width = el.style.height = (2 * r) + "px";
    el.innerHTML = '<div class="hb-label"></div><div class="hb-big"></div><div class="hb-sub"></div>';
    layer.appendChild(el);
    const a = (i / n) * Math.PI * 2;
    const b = { data, el, r, x: innerWidth / 2 + Math.cos(a) * innerWidth * 0.3, y: innerHeight / 2 + Math.sin(a) * innerHeight * 0.28,
                vx: (Math.random() - 0.5) * 40, vy: (Math.random() - 0.5) * 40, phase: Math.random() * 6.28, held: null, card: null };
    fill(b);
    el.addEventListener("pointerdown", (e) => grabBubble(b, e));
    el.addEventListener("pointermove", (e) => moveGrab(e));
    el.addEventListener("pointerup", (e) => endGrab(e));
    el.addEventListener("pointercancel", (e) => endGrab(e, true));
    return b;
  }
  function fill(b) {
    b.el.querySelector(".hb-label").textContent = b.data.label;
    b.el.querySelector(".hb-big").textContent = b.data.big;
    b.el.querySelector(".hb-sub").textContent = b.data.sub || "";
    b.el.classList.toggle("up", b.data.tone === "up");
    b.el.classList.toggle("down", b.data.tone === "down");
  }
  function grabBubble(b, e) {
    e.preventDefault(); e.stopPropagation();
    try { b.el.setPointerCapture(e.pointerId); } catch (err) { /* hand pointers are synthetic */ }
    b.held = e.pointerId;
    b.el.classList.add("held");
    grabs.set(e.pointerId, { kind: "bubble", b, ox: e.clientX - b.x, oy: e.clientY - b.y, sx: e.clientX, sy: e.clientY, travel: 0, hist: [[e.clientX, e.clientY, performance.now()]] });
  }
  function moveGrab(e) {
    const g = grabs.get(e.pointerId);
    if (!g) return false;
    e.stopPropagation();
    const now = performance.now();
    g.hist.push([e.clientX, e.clientY, now]);
    while (g.hist.length > 2 && now - g.hist[0][2] > 90) g.hist.shift();
    g.travel = Math.max(g.travel, Math.hypot(e.clientX - g.sx, e.clientY - g.sy));
    if (g.kind === "bubble") { g.b.x = e.clientX - g.ox; g.b.y = e.clientY - g.oy; g.b.vx = g.b.vy = 0; }
    else if (T) T.dragProp(g, e);
    return true;
  }
  function flick(g) {
    const h = g.hist, a = h[0], z = h[h.length - 1], dt = Math.max(16, z[2] - a[2]) / 1000;
    const cap = 2600 * S();
    return [Math.max(-cap, Math.min(cap, (z[0] - a[0]) / dt)), Math.max(-cap, Math.min(cap, (z[1] - a[1]) / dt))];
  }
  function endGrab(e, cancelled) {
    const g = grabs.get(e.pointerId);
    if (!g) return false;
    grabs.delete(e.pointerId);
    e.stopPropagation();
    if (g.kind === "bubble") {
      g.b.held = null; g.b.el.classList.remove("held");
      if (!cancelled && g.travel < 10) openCard(g.b);
      else { const v = flick(g); g.b.vx = v[0]; g.b.vy = v[1]; }
    } else if (T) T.releaseProp(g, flick(g));
    return true;
  }

  function openCard(b) {
    if (b.card) { b.card.remove(); b.card = null; return; }
    const c = document.createElement("div");
    c.className = "holo-card";
    const head = document.createElement("div");
    head.className = "hc-head";
    head.textContent = b.data.label + "  " + b.data.big + " " + (b.data.sub || "");
    const x = document.createElement("button");
    x.type = "button"; x.className = "x"; x.textContent = "×";
    x.addEventListener("click", () => { c.remove(); b.card = null; });
    head.appendChild(x);
    c.appendChild(head);
    const items = b.data.items || [];
    if (!items.length) c.appendChild(Object.assign(document.createElement("div"), { className: "hc-empty", textContent: "Nothing here yet." }));
    items.forEach((it) => {
      const row = document.createElement("div");
      row.className = "hc-row";
      const t = document.createElement("b"); t.textContent = it.title;
      const s = document.createElement("span"); s.textContent = it.text;
      row.append(t, s);
      c.appendChild(row);
    });
    c.style.left = Math.min(innerWidth - 340 * S(), Math.max(12, b.x + b.r + 12)) + "px";
    c.style.top = Math.min(innerHeight - 260 * S(), Math.max(60, b.y - b.r)) + "px";
    layer.appendChild(c);
    if (window.makeGrabbable) makeGrabbable(c);
    b.card = c;
  }

  function step(t) {
    raf = requestAnimationFrame(step);
    const dt = Math.min(0.05, (t - (lastT || t)) / 1000);
    lastT = t;
    const W = innerWidth, H = innerHeight, top = 56 * S(), bottom = H - 96 * S();
    bubbles.forEach((b) => {
      if (b.held != null) return;
      b.phase += dt * 0.6;
      b.vx += Math.cos(b.phase * 1.3) * 6 * dt * 60 * 0.05;   // a slow drift so they feel alive
      b.vy += Math.sin(b.phase) * 6 * dt * 60 * 0.05;
      const fr = Math.pow(0.45, dt);                          // air: a flick glides, then settles
      b.vx *= fr; b.vy *= fr;
      b.x += b.vx * dt; b.y += b.vy * dt;
      if (b.x < b.r) { b.x = b.r; b.vx = Math.abs(b.vx) * 0.8; }
      if (b.x > W - b.r) { b.x = W - b.r; b.vx = -Math.abs(b.vx) * 0.8; }
      if (b.y < top + b.r) { b.y = top + b.r; b.vy = Math.abs(b.vy) * 0.8; }
      if (b.y > bottom - b.r) { b.y = bottom - b.r; b.vy = -Math.abs(b.vy) * 0.8; }
    });
    for (let i = 0; i < bubbles.length; i++) for (let j = i + 1; j < bubbles.length; j++) {
      const a = bubbles[i], c = bubbles[j], dx = c.x - a.x, dy = c.y - a.y, d = Math.hypot(dx, dy) || 1, min = a.r + c.r + 8;
      if (d < min) {
        const push = (min - d) / 2, nx = dx / d, ny = dy / d;
        if (a.held == null) { a.x -= nx * push; a.y -= ny * push; a.vx -= nx * 30; a.vy -= ny * 30; }
        if (c.held == null) { c.x += nx * push; c.y += ny * push; c.vx += nx * 30; c.vy += ny * 30; }
      }
    }
    bubbles.forEach((b) => { b.el.style.transform = "translate(" + (b.x - b.r) + "px," + (b.y - b.r) + "px)"; });
    if (T) T.frame(dt);
  }

  async function load() {
    try {
      const j = await (await fetch("/api/holo")).json();
      const list = j.bubbles || [];
      list.forEach((d, i) => {
        const have = bubbles.find((b) => b.data.id === d.id);
        if (have) { have.data = d; fill(have); }
        else bubbles.push(makeBubble(d, i, list.length));
      });
      if (T && j.props) T.loadProps(j.props);
      return j;
    } catch (e) { return null; }
  }

  /* ---------- 3D objects ---------- */
  async function load3D() {
    if (T) return T;
    let THREE, GLTF;
    try {
      THREE = await import("three");
      GLTF = (await import("three/addons/loaders/GLTFLoader.js")).GLTFLoader;
    } catch (e) {
      if (window.alertBar) alertBar("The 3D objects could not load.", "They need internet to fetch three.js from jsdelivr.net. The bubbles still work.");
      return null;
    }
    const canvas = document.createElement("canvas");
    canvas.id = "holo-3d";
    document.body.appendChild(canvas);
    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1));
    const scene = new THREE.Scene();
    const cam = new THREE.PerspectiveCamera(40, innerWidth / innerHeight, 0.1, 100);
    cam.position.set(0, 0, 12);
    scene.add(new THREE.AmbientLight(0x9ff5ec, 1.2));
    const sun = new THREE.DirectionalLight(0xffffff, 1.4); sun.position.set(3, 5, 6); scene.add(sun);
    const TEAL = 0x22d3c5;
    const glow = (o) => new THREE.LineBasicMaterial({ color: TEAL, transparent: true, opacity: o, blending: THREE.AdditiveBlending });
    const props = [];
    const ray = new THREE.Raycaster();

    function size() { renderer.setSize(innerWidth, innerHeight, false); cam.aspect = innerWidth / innerHeight; cam.updateProjectionMatrix(); }
    addEventListener("resize", size); size();

    function toWorld(px, py) {
      const v = new THREE.Vector3((px / innerWidth) * 2 - 1, -(py / innerHeight) * 2 + 1, 0.5).unproject(cam);
      const dir = v.sub(cam.position).normalize();
      return cam.position.clone().add(dir.multiplyScalar(-cam.position.z / dir.z));
    }
    function toScreen(p) { const v = p.clone().project(cam); return [(v.x + 1) / 2 * innerWidth, (1 - v.y) / 2 * innerHeight]; }
    function screenRadius(o) {
      const c = toScreen(o.position), e = toScreen(o.position.clone().add(new THREE.Vector3(o.userData.radius * o.scale.x, 0, 0)));
      return Math.hypot(e[0] - c[0], e[1] - c[1]);
    }
    function add(obj, radius, px, py) {
      const g = new THREE.Group();
      g.add(obj);
      g.userData = { radius, vx: 0, vy: 0, spinX: 0.15, spinY: 0.35, held: 0 };
      g.position.copy(toWorld(px, py));
      scene.add(g);
      props.push(g);
      return g;
    }
    function wire(geo, o) { return new THREE.LineSegments(new THREE.EdgesGeometry(geo), glow(o)); }

    // Built-in: an armillary sphere, a crystal and a globe
    const arm = new THREE.Group();
    [0, 1, 2].forEach((k) => {
      const ring = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(Array.from({ length: 96 }, (_, i) => new THREE.Vector3(Math.cos(i / 96 * 6.283), Math.sin(i / 96 * 6.283), 0))), glow(0.95));
      ring.rotation.set(k === 1 ? Math.PI / 2 : 0.4 * k, k === 2 ? Math.PI / 2 : 0, 0.3 * k);
      arm.add(ring);
    });
    arm.add(new THREE.Mesh(new THREE.SphereGeometry(0.22, 24, 16), new THREE.MeshBasicMaterial({ color: 0x9ff5ec, transparent: true, opacity: 0.9 })));
    add(arm, 1, innerWidth * 0.2, innerHeight * 0.32);

    const crystal = new THREE.Group();
    crystal.add(wire(new THREE.IcosahedronGeometry(0.9, 0), 0.95));
    crystal.add(new THREE.Mesh(new THREE.IcosahedronGeometry(0.88, 0), new THREE.MeshBasicMaterial({ color: TEAL, transparent: true, opacity: 0.12 })));
    add(crystal, 0.9, innerWidth * 0.8, innerHeight * 0.3);

    const globe = new THREE.Group();
    globe.add(new THREE.LineSegments(new THREE.WireframeGeometry(new THREE.SphereGeometry(0.85, 18, 12)), glow(0.45)));
    const band = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(Array.from({ length: 96 }, (_, i) => new THREE.Vector3(Math.cos(i / 96 * 6.283) * 1.25, 0, Math.sin(i / 96 * 6.283) * 1.25))), glow(0.9));
    band.rotation.z = 0.35;
    globe.add(band);
    add(globe, 1.25, innerWidth * 0.75, innerHeight * 0.68);

    const loaded = new Set();
    function loadProps(names) {
      const loader = new GLTF();
      (names || []).forEach((n, i) => {
        if (loaded.has(n)) return;
        loaded.add(n);
        loader.load("/props/" + encodeURIComponent(n), (gltf) => {
          const m = gltf.scene;
          const box = new THREE.Box3().setFromObject(m), s = box.getSize(new THREE.Vector3()), c = box.getCenter(new THREE.Vector3());
          const k = 1.8 / Math.max(s.x, s.y, s.z || 1, 0.001);
          m.scale.setScalar(k); m.position.sub(c.multiplyScalar(k));
          add(m, 0.95, innerWidth * (0.3 + 0.15 * (i % 3)), innerHeight * 0.75);
        }, undefined, () => { /* a broken model is skipped */ });
      });
    }

    function hit(px, py) {
      let best = null, bd = 1e9;
      props.forEach((o) => {
        const c = toScreen(o.position), r = Math.max(36, screenRadius(o)), d = Math.hypot(px - c[0], py - c[1]);
        if (d < r && d < bd) { bd = d; best = o; }
      });
      return best;
    }

    // Grabbing happens before anything else on the page sees the press, but never over a bubble, card or button.
    function down(e) {
      if (!on || (e.target && e.target.closest && e.target.closest(".holo-bubble,.holo-card,button,input,textarea,#askbar,#orb,.panel"))) return;
      const o = hit(e.clientX, e.clientY);
      if (!o) return;
      e.stopPropagation(); e.preventDefault();
      const w = toWorld(e.clientX, e.clientY);
      o.userData.held++;
      grabs.set(e.pointerId, { kind: "prop", o, off: o.position.clone().sub(w), lx: e.clientX, ly: e.clientY, sx: e.clientX, sy: e.clientY, travel: 0, hist: [[e.clientX, e.clientY, performance.now()]], scale0: o.scale.x });
    }
    function dragProp(g, e) {
      const both = [...grabs.values()].filter((x) => x.kind === "prop" && x.o === g.o);
      if (both.length === 2) {   // two hands: stretch or shrink
        const [a, b] = both;
        const d = Math.hypot(a.lx - b.lx, a.ly - b.ly);
        g.lx = e.clientX; g.ly = e.clientY;
        const d2 = Math.hypot(a.lx - b.lx, a.ly - b.ly);
        if (d > 0) g.o.scale.setScalar(Math.max(0.3, Math.min(4, g.o.scale.x * d2 / d)));
        return;
      }
      const dx = e.clientX - g.lx, dy = e.clientY - g.ly;
      g.lx = e.clientX; g.ly = e.clientY;
      g.o.position.copy(toWorld(e.clientX, e.clientY).add(g.off));
      g.o.rotation.y += dx * 0.012; g.o.rotation.x += dy * 0.012;   // it turns as you carry it
    }
    function releaseProp(g, v) {
      g.o.userData.held = Math.max(0, g.o.userData.held - 1);
      const k = 1 / (innerWidth / 2) * (cam.position.z * Math.tan(cam.fov * Math.PI / 360)) * cam.aspect;
      g.o.userData.vx = v[0] * k; g.o.userData.vy = -v[1] * k;
      g.o.userData.spinY = 0.35 + v[0] * 0.002; g.o.userData.spinX = 0.15 + v[1] * 0.002;
    }
    addEventListener("pointerdown", down, true);
    addEventListener("pointermove", (e) => { const g = grabs.get(e.pointerId); if (g && g.kind === "prop") moveGrab(e); }, true);
    addEventListener("pointerup", (e) => { const g = grabs.get(e.pointerId); if (g && g.kind === "prop") endGrab(e); }, true);
    addEventListener("pointercancel", (e) => { const g = grabs.get(e.pointerId); if (g && g.kind === "prop") endGrab(e, true); }, true);

    function frame(dt) {
      if (!on) return;
      const half = cam.position.z * Math.tan(cam.fov * Math.PI / 360), hx = half * cam.aspect;
      props.forEach((o) => {
        const u = o.userData;
        if (!u.held) {
          const fr = Math.pow(0.4, dt);
          u.vx *= fr; u.vy *= fr;
          u.spinX += (0.15 - u.spinX) * dt * 0.5; u.spinY += (0.35 - u.spinY) * dt * 0.5;
          o.position.x += u.vx * dt; o.position.y += u.vy * dt;
          const r = u.radius * o.scale.x;
          if (o.position.x < -hx + r) { o.position.x = -hx + r; u.vx = Math.abs(u.vx) * 0.7; }
          if (o.position.x > hx - r) { o.position.x = hx - r; u.vx = -Math.abs(u.vx) * 0.7; }
          if (o.position.y < -half + r) { o.position.y = -half + r; u.vy = Math.abs(u.vy) * 0.7; }
          if (o.position.y > half - r) { o.position.y = half - r; u.vy = -Math.abs(u.vy) * 0.7; }
          o.rotation.x += u.spinX * dt; o.rotation.y += u.spinY * dt;
        }
      });
      renderer.render(scene, cam);
    }
    T = { frame, loadProps, dragProp, releaseProp, canvas };
    return T;
  }

  /* ---------- on and off ---------- */
  async function set(v) {
    if (v === on) return;
    on = v;
    document.body.classList.toggle("holo", on);
    const btn = document.getElementById("b-holo");
    if (btn) { btn.classList.toggle("on", on); btn.textContent = on ? "Holo on" : "Holo"; }
    if (!on) {
      cancelAnimationFrame(raf); raf = 0; lastT = 0;
      clearInterval(refreshTimer);
      if (layer) layer.remove();
      layer = null; bubbles = []; grabs.clear();
      if (T) T.canvas.style.display = "none";
      return;
    }
    layer = document.createElement("div");
    layer.id = "holo-layer";
    document.body.appendChild(layer);
    hint = document.createElement("div");
    hint.className = "holo-hint";
    hint.textContent = "Pinch or click to grab. Flick to throw. Tap a bubble to open it. Two hands on a 3D object to stretch it.";
    layer.appendChild(hint);
    setTimeout(() => { if (hint) hint.classList.add("fade"); }, 6000);
    raf = requestAnimationFrame(step);
    // the camera is the backdrop, so switch hands on if they are off
    const hb = document.getElementById("b-hands");
    if (hb && typeof HandTracker !== "undefined" && !HandTracker.isOn()) hb.click();
    const t3 = await load3D();
    if (t3) t3.canvas.style.display = "";
    await load();
    refreshTimer = setInterval(load, 60000);
  }

  return { set, isOn: () => on, toggle: () => set(!on) };
})();
window.Holo = Holo;
document.addEventListener("DOMContentLoaded", () => {
  const b = document.getElementById("b-holo");
  if (b) b.addEventListener("click", () => Holo.toggle());
});
