/* The orb: drag it anywhere, dock it to a side, and let JARVIS move it.
   Drag and release near a screen edge and it slides to the side, leaving part of it visible so it keeps
   animating and speaking. Tap it while docked to slide back.
   JARVIS can also move it: goto('left'), present(element) to glide beside whatever it is showing,
   and home() to return to where it was before it wandered off. */
function makeDockable(el, opts) {
  opts = opts || {};
  const SHOW = 0.4;   // fraction of the orb still visible when docked
  const SNAP = 110;   // px from an edge that triggers docking
  const MARGIN = 16;
  const GAP = 14;
  const SLIDE = 'left .28s cubic-bezier(.2,.9,.2,1), top .28s cubic-bezier(.2,.9,.2,1)';
  const GLIDE_MS = 380;
  const GLIDE = 'left ' + GLIDE_MS + 'ms cubic-bezier(.22,.8,.2,1), top ' + GLIDE_MS + 'ms cubic-bezier(.22,.8,.2,1)';
  const AVOID = opts.avoid || '.panel, .card, #askbar, #topbar, #caption, #viewer';
  let side = null, drag = null, home = null, glideTimer = 0;
  const r0 = el.getBoundingClientRect();
  const restGap = { r: Math.max(0, window.innerWidth - r0.right), b: Math.max(0, window.innerHeight - r0.bottom) }; // where the page put it: the default home
  const topInset = () => (typeof opts.topInset === 'function' ? opts.topInset() : opts.topInset || 0);
  const bottomLift = () => (typeof opts.bottomLift === 'function' ? opts.bottomLift() : opts.bottomLift || 0); // keeps 'bottom' clear of the ask bar

  function toLeftTop() {
    const r = el.getBoundingClientRect();
    el.style.transition = 'none';
    el.style.left = r.left + 'px';
    el.style.top = r.top + 'px';
    el.style.right = 'auto';
    el.style.bottom = 'auto';
    void el.offsetWidth; // flush so the next change animates
  }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  function clampTop(y) { return clamp(y, MARGIN + topInset(), window.innerHeight - el.offsetHeight - MARGIN); }
  function clampLeft(x) { return clamp(x, MARGIN, window.innerWidth - el.offsetWidth - MARGIN); }
  function setSide(s) {
    side = s;
    el.classList.toggle('docked', !!s);
    el.classList.toggle('docked-left', s === 'left');
    el.classList.toggle('docked-right', s === 'right');
  }
  function dock(s) {
    toLeftTop();
    const w = el.offsetWidth;
    el.style.transition = SLIDE;
    el.style.left = (s === 'left' ? -w * (1 - SHOW) : window.innerWidth - w * SHOW) + 'px';
    el.style.top = clampTop(parseFloat(el.style.top)) + 'px';
    setSide(s);
  }
  function undock() {
    if (!side) return;
    toLeftTop();
    const w = el.offsetWidth;
    el.style.transition = SLIDE;
    el.style.left = (side === 'left' ? MARGIN : window.innerWidth - w - MARGIN) + 'px';
    setSide(null);
  }
  function current() { const r = el.getBoundingClientRect(); return { left: r.left, top: r.top, side: side }; }

  /* ---- moves made by JARVIS ---- */
  function glide(l, t) {
    toLeftTop();
    setSide(null);
    el.style.transition = GLIDE;
    el.style.left = clampLeft(l) + 'px';
    el.style.top = clampTop(t) + 'px';
    clearTimeout(glideTimer);
    return new Promise((res) => { glideTimer = setTimeout(res, GLIDE_MS + 40); });
  }
  function named(name) {
    const W = window.innerWidth, H = window.innerHeight, w = el.offsetWidth, h = el.offsetHeight;
    const L = MARGIN, R = W - w - MARGIN, T = MARGIN + topInset(), B = H - h - MARGIN;
    const cx = (W - w) / 2, cy = (H - h) / 2;
    return ({
      'left': [L, cy], 'right': [R, cy], 'top': [cx, T], 'bottom': [cx, B - bottomLift()], 'center': [cx, cy],
      'top-left': [L, T], 'top-right': [R, T], 'bottom-left': [L, B], 'bottom-right': [R, B]
    })[name] || null;
  }
  function goto(name) {
    if (name === 'dock') { const r = el.getBoundingClientRect(); dock(r.left + r.width / 2 < window.innerWidth / 2 ? 'left' : 'right'); home = null; return Promise.resolve(); }
    if (name === 'home') return goHome();
    const p = named(name);
    if (!p) return Promise.resolve();
    home = null;                       // an explicit move picks a new resting place
    el.classList.remove('presenting');
    return glide(p[0], p[1]);
  }
  function goHome() {
    el.classList.remove('presenting');
    const h = home;
    home = null;
    if (h && h.side) { dock(h.side); return Promise.resolve(); }
    if (h) return glide(h.left, h.top);
    return glide(window.innerWidth - el.offsetWidth - restGap.r, window.innerHeight - el.offsetHeight - restGap.b);
  }
  function overlap(a, b) {
    const w = Math.min(a.right, b.right) - Math.max(a.left, b.left), h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    return w > 0 && h > 0 ? w * h : 0;
  }
  /* Glide beside an element, choosing the spot that covers the least of anything else on screen. */
  function present(target) {
    if (!target || !target.getClientRects().length) return Promise.resolve();
    if (!home) home = current();       // remember where to come back to
    const w = el.offsetWidth, h = el.offsetHeight, t = target.getBoundingClientRect();
    const W = window.innerWidth, H = window.innerHeight;
    const cand = [];
    [t.top, t.top + (t.height - h) / 2, t.bottom - h].forEach((y) => { cand.push([t.right + GAP, y]); cand.push([t.left - GAP - w, y]); });
    [t.left, t.left + (t.width - w) / 2, t.right - w].forEach((x) => { cand.push([x, t.top - GAP - h]); cand.push([x, t.bottom + GAP]); });
    cand.push([MARGIN, MARGIN + topInset()], [W - w - MARGIN, MARGIN + topInset()], [MARGIN, H - h - MARGIN], [W - w - MARGIN, H - h - MARGIN]);
    const others = Array.from(document.querySelectorAll(AVOID)).filter((n) => n !== target && !n.contains(target) && !target.contains(n) && n.getClientRects().length);
    const rects = others.map((n) => n.getBoundingClientRect());
    let best = null, bs = 1e18;
    cand.forEach(([x, y]) => {
      const cx = clampLeft(x), cy = clampTop(y), box = { left: cx, top: cy, right: cx + w, bottom: cy + h };
      let s = overlap(box, t) * 4;
      rects.forEach((r) => { s += overlap(box, r); });
      s += Math.hypot(cx + w / 2 - (t.left + t.width / 2), cy + h / 2 - (t.top + t.height / 2)) * 40;
      if (s < bs) { bs = s; best = [cx, cy]; }
    });
    el.classList.add('presenting');
    return glide(best[0], best[1]);
  }

  /* ---- user drag, tap and snap ---- */
  el.addEventListener('pointerdown', (e) => {
    if (e.button) return;
    toLeftTop();
    drag = { x: e.clientX, y: e.clientY, l: parseFloat(el.style.left), t: parseFloat(el.style.top), moved: false };
    try { el.setPointerCapture(e.pointerId); } catch (err) { /* synthetic pointer from hand tracking */ }
  });
  el.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (!drag.moved && Math.abs(dx) + Math.abs(dy) < 6) return;
    drag.moved = true;
    const w = el.offsetWidth;
    el.style.transition = 'none';
    el.style.left = Math.max(-w * (1 - SHOW), Math.min(window.innerWidth - w * SHOW, drag.l + dx)) + 'px';
    el.style.top = clampTop(drag.t + dy) + 'px';
  });
  el.addEventListener('pointerup', () => {
    if (!drag) return;
    const d = drag;
    drag = null;
    if (!d.moved) {
      if (side) undock(); else if (opts.onTap) opts.onTap();
      return;
    }
    home = null;                       // the user chose a new spot, so that is home now
    el.classList.remove('presenting');
    const l = parseFloat(el.style.left), w = el.offsetWidth;
    if (l < SNAP) dock('left');
    else if (window.innerWidth - (l + w) < SNAP) dock('right');
    else setSide(null);
  });
  el.addEventListener('pointercancel', () => { drag = null; });
  window.addEventListener('resize', () => { if (side) dock(side); });

  return {
    dock, undock, goto, present, home: goHome,
    toggle: () => (side ? undock() : dock('right')),
    side: () => side,
    away: () => !!home,
  };
}
