"use strict";

const TYPE_COLORS = {
  client: "#f97316", project: "#facc15", person: "#22d3ee", invoice: "#4ade80", meeting: "#a78bfa",
  idea: "#f472b6", process: "#60a5fa", hub: "#fb7185", memory: "#2dd4bf", document: "#e5e7eb", note: "#9ca3af",
};
const colorOf = (t) => TYPE_COLORS[t] || TYPE_COLORS.note;

// Physics knobs. Repulsion only looks at nodes within REPEL_CUTOFF, via a spatial grid,
// so the cost stays close to linear instead of n squared.
const REPEL_CUTOFF = 90;
const REPEL = 1400;
const SPRING_LEN = 46;
const SPRING_K = 0.06;
const GRAVITY = 0.014;
const DAMP = 0.78;
const ALPHA_FLOOR = 0.03; // never fully cools, so the graph keeps breathing
const DIM = 0.1;

class Graph {
  constructor(canvas, handlers) {
    this.c = canvas;
    this.ctx = canvas.getContext("2d");
    this.h = handlers || {};
    this.view = { x: 0, y: 0, k: 1 };
    this.n = 0;
    this.hover = -1;
    this.focus = -1;
    this.pathNodes = new Set();
    this.pathEdges = new Set();
    this.hidden = new Set();
    this.pulses = [];
    this.alpha = 1;
    this.ticks = 0;
    this.fitted = false;
    this.drag = null;
    this.idToIdx = new Map();
    this.lw = [];
    this.resize();
    window.addEventListener("resize", () => this.resize());
    this.bind();
    setInterval(() => this.spawnPulse(), 6000);
    requestAnimationFrame(() => this.frame());
  }

  resize() {
    const dpr = Math.min(1, window.devicePixelRatio || 1);
    this.dpr = dpr;
    this.ui = window.UI_SCALE || 1;
    this.lw = new Array(this.n || 0).fill(0);
    this.w = window.innerWidth;
    this.hh = window.innerHeight;
    this.c.width = this.w * dpr;
    this.c.height = this.hh * dpr;
    // Words get their own canvas at full sharpness. The dots and lines stay light, so the Mac stays fast.
    if (!this.lc) {
      this.lc = document.createElement("canvas");
      this.lc.id = "graph-labels";
      this.lc.setAttribute("aria-hidden", "true");
      this.c.insertAdjacentElement("afterend", this.lc);
      this.lctx = this.lc.getContext("2d");
    }
    this.ldpr = Math.min(2, window.devicePixelRatio || 1);
    this.lc.width = this.w * this.ldpr;
    this.lc.height = this.hh * this.ldpr;
    if (!this.view.x && !this.view.y) { this.view.x = this.w / 2; this.view.y = this.hh / 2; }
  }

  load(data) {
    const prev = new Map();
    for (let i = 0; i < this.n; i++) prev.set(this.id[i], [this.x[i], this.y[i]]);
    const n = data.nodes.length;
    this.n = n;
    this.id = data.nodes.map((d) => d.id);
    this.title = data.nodes.map((d) => d.title);
    this.type = data.nodes.map((d) => d.type);
    this.idToIdx = new Map(this.id.map((v, i) => [v, i]));
    this.x = new Float32Array(n); this.y = new Float32Array(n);
    this.vx = new Float32Array(n); this.vy = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      const p = prev.get(this.id[i]);
      if (p) { this.x[i] = p[0]; this.y[i] = p[1]; }
      else { const r = 26 * Math.sqrt(i + 1), a = i * 2.39996 + Math.random() * 0.3; this.x[i] = Math.cos(a) * r; this.y[i] = Math.sin(a) * r; }
    }
    this.edges = data.edges;
    this.adj = Array.from({ length: n }, () => []);
    for (const [a, b] of this.edges) { this.adj[a].push(b); this.adj[b].push(a); }
    this.deg = this.adj.map((a) => a.length);
    this.order = Array.from({ length: n }, (_, i) => i).sort((a, b) => this.deg[b] - this.deg[a]);
    this.lw = new Array(n).fill(0);
    this.alpha = prev.size ? 0.4 : 1;
    this.ticks = 0;
    this.fitted = prev.size > 0;
    this.hover = -1;
    this.focus = -1;
    this.clearPath();
    if (this.h.onLoad) this.h.onLoad(this);
  }

  vis(i) { return !this.hidden.has(this.type[i]); }
  radius(i) { return 3 + Math.sqrt(this.deg[i]) * 2.4; }

  /* ---------- physics ---------- */
  tick() {
    const n = this.n;
    if (!n) return;
    this.ticks++;
    this.alpha = Math.max(ALPHA_FLOOR, this.alpha * 0.985);
    const a = this.alpha, x = this.x, y = this.y, vx = this.vx, vy = this.vy;
    const grid = new Map();
    for (let i = 0; i < n; i++) {
      if (!this.vis(i)) continue;
      const key = (Math.floor(x[i] / REPEL_CUTOFF) + 5000) * 10007 + (Math.floor(y[i] / REPEL_CUTOFF) + 5000);
      let cell = grid.get(key);
      if (!cell) grid.set(key, (cell = []));
      cell.push(i);
    }
    const cut2 = REPEL_CUTOFF * REPEL_CUTOFF;
    for (let i = 0; i < n; i++) {
      if (!this.vis(i)) continue;
      const cx = Math.floor(x[i] / REPEL_CUTOFF) + 5000, cy = Math.floor(y[i] / REPEL_CUTOFF) + 5000;
      for (let ox = -1; ox <= 1; ox++) for (let oy = -1; oy <= 1; oy++) {
        const cell = grid.get((cx + ox) * 10007 + (cy + oy));
        if (!cell) continue;
        for (const j of cell) {
          if (j <= i) continue;
          let dx = x[i] - x[j], dy = y[i] - y[j], d2 = dx * dx + dy * dy;
          if (d2 > cut2) continue;
          if (d2 < 0.01) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; d2 = dx * dx + dy * dy + 0.01; }
          const d = Math.sqrt(d2), f = (REPEL / (d2 + 40)) * a, fx = (dx / d) * f, fy = (dy / d) * f;
          vx[i] += fx; vy[i] += fy; vx[j] -= fx; vy[j] -= fy;
        }
      }
    }
    for (const [p, q] of this.edges) {
      if (!this.vis(p) || !this.vis(q)) continue;
      const dx = x[q] - x[p], dy = y[q] - y[p], d = Math.sqrt(dx * dx + dy * dy) || 1;
      const f = (d - SPRING_LEN) * SPRING_K * a, fx = (dx / d) * f, fy = (dy / d) * f;
      vx[p] += fx; vy[p] += fy; vx[q] -= fx; vy[q] -= fy;
    }
    const breathe = a <= ALPHA_FLOOR * 1.2 ? 0.05 : 0;
    for (let i = 0; i < n; i++) {
      if (!this.vis(i)) continue;
      if (this.drag && this.drag.mode === "node" && this.drag.moved && this.drag.i === i) { vx[i] = vy[i] = 0; continue; }
      vx[i] -= x[i] * GRAVITY * a; vy[i] -= y[i] * GRAVITY * a;
      if (breathe) { vx[i] += (Math.random() - 0.5) * breathe; vy[i] += (Math.random() - 0.5) * breathe; }
      vx[i] *= DAMP; vy[i] *= DAMP;
      x[i] += vx[i]; y[i] += vy[i];
    }
    if (!this.fitted && this.ticks > 120) { this.fit(); this.fitted = true; }
  }

  fit() {
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9, any = false;
    for (let i = 0; i < this.n; i++) {
      if (!this.vis(i)) continue;
      any = true;
      x0 = Math.min(x0, this.x[i]); x1 = Math.max(x1, this.x[i]); y0 = Math.min(y0, this.y[i]); y1 = Math.max(y1, this.y[i]);
    }
    if (!any) return;
    const bw = Math.max(80, x1 - x0), bh = Math.max(80, y1 - y0);
    const usableW = Math.max(300, this.w - 700 * this.ui), usableH = Math.max(300, this.hh - 260 * this.ui);
    this.view.k = Math.max(0.2, Math.min(6, Math.min(usableW / bw, usableH / bh)));
    this.view.x = this.w / 2 - ((x0 + x1) / 2) * this.view.k;
    this.view.y = this.hh / 2 - 40 - ((y0 + y1) / 2) * this.view.k;
  }

  /* ---------- drawing ---------- */
  sx(i) { return this.x[i] * this.view.k + this.view.x; }
  sy(i) { return this.y[i] * this.view.k + this.view.y; }
  rad(i) { return this.radius(i) * this.ui * Math.min(1.5, Math.max(0.7, Math.sqrt(this.view.k))); }

  frame() {
    // When nothing is moving or being touched, stop drawing completely and just check a few times a second.
    const calm = this.alpha <= ALPHA_FLOOR * 1.2 && !this.drag && this.hover < 0 && !this.pulses.length && !this.pathEdges.size;
    const v = this.view, sig = [v.x, v.y, v.k, this.focus, this.pathNodes.size, this.w, this.hh, this.n].join("|");
    this.calmN = calm && sig === this.sig ? (this.calmN || 0) + 1 : 0;
    this.sig = sig;
    if (this.calmN > 45) { setTimeout(() => this.frame(), 150); return; }
    const steps = this.alpha > 0.1 ? 2 : 1;
    for (let s = 0; s < steps; s++) this.tick();
    this.draw();
    requestAnimationFrame(() => this.frame());
  }

  draw() {
    const ctx = this.ctx;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, this.w, this.hh);
    if (!this.n) { if (this.lctx) this.lctx.clearRect(0, 0, this.lc.width, this.lc.height); return; }
    const hv = this.hover;
    const act = hv >= 0 ? new Set([hv, ...this.adj[hv]]) : null;

    const base = [], hot = [], path = [];
    for (let e = 0; e < this.edges.length; e++) {
      const [a, b] = this.edges[e];
      if (!this.vis(a) || !this.vis(b)) continue;
      if (this.pathEdges.has(a + "-" + b)) path.push(e);
      else if (hv >= 0 && (a === hv || b === hv)) hot.push(e);
      else base.push(e);
    }
    const stroke = (list, color, alpha, width) => {
      if (!list.length) return;
      ctx.beginPath();
      for (const e of list) {
        const [a, b] = this.edges[e];
        ctx.moveTo(this.sx(a), this.sy(a));
        ctx.lineTo(this.sx(b), this.sy(b));
      }
      ctx.globalAlpha = alpha; ctx.strokeStyle = color; ctx.lineWidth = width; ctx.stroke();
    };
    stroke(base, "#1fb5b5", hv >= 0 ? DIM * 0.4 : 0.22, 1);
    stroke(hot, colorOf(this.type[hv]), 0.95, 1.6);
    stroke(path, "#fde68a", 1, 2.6);
    ctx.globalAlpha = 1;

    // pulses travel a random link while idle
    const now = performance.now();
    this.pulses = this.pulses.filter((p) => now - p.t0 < 1300);
    for (const p of this.pulses) {
      const [a, b] = this.edges[p.e];
      if (!this.vis(a) || !this.vis(b)) continue;
      const t = (now - p.t0) / 1300;
      const px = this.sx(a) + (this.sx(b) - this.sx(a)) * t, py = this.sy(a) + (this.sy(b) - this.sy(a)) * t;
      ctx.globalAlpha = (hv >= 0 ? 0.2 : 0.85) * Math.sin(Math.PI * t);
      ctx.fillStyle = "#a7fff5"; ctx.shadowColor = "#22d3c5"; ctx.shadowBlur = 10;
      ctx.beginPath(); ctx.arc(px, py, 2.6, 0, 6.283); ctx.fill();
      ctx.shadowBlur = 0;
    }
    ctx.globalAlpha = 1;

    // nodes: small first so hubs sit on top
    for (let k = this.n - 1; k >= 0; k--) {
      const i = this.order[k];
      if (!this.vis(i)) continue;
      const dim = act && !act.has(i);
      let r = this.rad(i);
      if (i === hv) r *= 1.4;
      ctx.globalAlpha = dim ? DIM : 1;
      ctx.fillStyle = colorOf(this.type[i]);
      if (i === hv) { ctx.shadowColor = colorOf(this.type[i]); ctx.shadowBlur = 18; }
      ctx.beginPath(); ctx.arc(this.sx(i), this.sy(i), r, 0, 6.283); ctx.fill();
      ctx.shadowBlur = 0;
      if (i === this.focus || this.pathNodes.has(i)) {
        ctx.globalAlpha = 1; ctx.strokeStyle = this.pathNodes.has(i) ? "#fde68a" : "#fff"; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(this.sx(i), this.sy(i), r + 4, 0, 6.283); ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;
    this.drawLabels(act);
  }

  // Most-connected first. A label whose box collides with one already placed is skipped.
  drawLabels(act) {
    const ctx = this.lctx;
    ctx.setTransform(this.ldpr, 0, 0, this.ldpr, 0, 0);
    ctx.clearRect(0, 0, this.w, this.hh);
    ctx.font = (11 * this.ui) + "px Inter, system-ui, sans-serif";
    ctx.textBaseline = "middle";
    const placed = [];
    const hv = this.hover;
    const tryLabel = (i, force) => {
      if (!this.vis(i)) return;
      const x = this.sx(i), y = this.sy(i);
      if (x < -50 || y < -20 || x > this.w + 50 || y > this.hh + 20) return;
      if (!this.lw[i]) this.lw[i] = ctx.measureText(this.title[i]).width + 8;
      const r = this.rad(i) * (i === hv ? 1.4 : 1);
      const box = { x: x + r + 3, y: y - 8 * this.ui, w: this.lw[i], h: 16 * this.ui };
      if (!force) {
        for (const p of placed) if (box.x < p.x + p.w && box.x + box.w > p.x && box.y < p.y + p.h && box.y + box.h > p.y) return;
      }
      placed.push(box);
      ctx.fillStyle = "rgba(2,10,12,0.72)";
      ctx.fillRect(box.x - 2, box.y, box.w, box.h);
      ctx.fillStyle = i === hv || i === this.focus ? "#fff" : "#e9ddd2";
      ctx.fillText(this.title[i], box.x + 2, y);
    };
    if (hv >= 0) tryLabel(hv, true);
    if (this.focus >= 0) tryLabel(this.focus, true);
    for (const i of this.pathNodes) tryLabel(i, true);
    if (act) { for (const i of this.adj[hv]) tryLabel(i, false); return; }
    const limit = Math.min(this.n, 450);
    for (let k = 0; k < limit; k++) tryLabel(this.order[k], false);
  }

  /* ---------- interaction ---------- */
  bind() {
    const c = this.c;
    const pt = (e) => { const r = c.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
    c.addEventListener("pointerdown", (e) => {
      try { c.setPointerCapture(e.pointerId); } catch (err) { /* synthetic pointer from hand tracking */ }
      const [px, py] = pt(e), i = this.pick(px, py);
      this.drag = { mode: i >= 0 ? "node" : "pan", i, sx: px, sy: py, ox: this.view.x, oy: this.view.y, moved: false, shift: e.shiftKey };
    });
    c.addEventListener("pointermove", (e) => {
      const [px, py] = pt(e);
      const d = this.drag;
      if (!d) { this.hover = this.pick(px, py); c.style.cursor = this.hover >= 0 ? "pointer" : "grab"; return; }
      const dx = px - d.sx, dy = py - d.sy;
      if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
      if (!d.moved) return;
      if (d.mode === "node") {
        this.x[d.i] = (px - this.view.x) / this.view.k;
        this.y[d.i] = (py - this.view.y) / this.view.k;
        this.alpha = Math.max(this.alpha, 0.3);
      } else { this.view.x = d.ox + dx; this.view.y = d.oy + dy; }
    });
    c.addEventListener("pointerup", () => {
      const d = this.drag;
      this.drag = null;
      if (!d || d.moved || d.i < 0) return;
      if (d.shift && this.focus >= 0 && this.focus !== d.i) this.tracePath(this.focus, d.i);
      else this.setFocus(d.i);
    });
    c.addEventListener("pointerleave", () => { if (!this.drag) this.hover = -1; });
    c.addEventListener("pointercancel", () => { this.drag = null; });
    c.addEventListener("wheel", (e) => {
      e.preventDefault();
      const [px, py] = pt(e), k0 = this.view.k;
      const k1 = Math.max(0.1, Math.min(6, k0 * Math.exp(-e.deltaY * 0.0012)));
      this.view.x = px - ((px - this.view.x) / k0) * k1;
      this.view.y = py - ((py - this.view.y) / k0) * k1;
      this.view.k = k1;
    }, { passive: false });
  }

  pick(px, py) {
    let best = -1, bd = 1e9;
    for (let i = 0; i < this.n; i++) {
      if (!this.vis(i)) continue;
      const dx = this.sx(i) - px, dy = this.sy(i) - py, d = Math.sqrt(dx * dx + dy * dy), r = this.rad(i) + 4;
      if (d < r && d < bd) { best = i; bd = d; }
    }
    return best;
  }

  spawnPulse() {
    if (!this.edges || !this.edges.length || this.hover >= 0) return;
    for (let t = 0; t < 8; t++) {
      const e = Math.floor(Math.random() * this.edges.length), [a, b] = this.edges[e];
      if (this.vis(a) && this.vis(b)) { this.pulses.push({ e, t0: performance.now() }); return; }
    }
  }

  /* ---------- public API ---------- */
  setFocus(i) {
    this.focus = i;
    this.clearPath();
    if (this.h.onFocus) this.h.onFocus(this.id[i]);
  }

  focusId(id, pan) {
    const i = this.idToIdx.get(id);
    if (i === undefined) return;
    this.setFocus(i);
    if (pan === false) return;
    this.view.x = this.w / 2 - this.x[i] * this.view.k;
    this.view.y = this.hh / 2 - 40 - this.y[i] * this.view.k;
  }

  clearPath() {
    this.pathNodes = new Set();
    this.pathEdges = new Set();
    if (this.h.onPath) this.h.onPath(null);
  }

  tracePath(a, b) {
    const prev = new Map([[a, -1]]);
    const q = [a];
    while (q.length && !prev.has(b)) {
      const cur = q.shift();
      for (const nx of this.adj[cur]) if (!prev.has(nx)) { prev.set(nx, cur); q.push(nx); }
    }
    this.pathNodes = new Set();
    this.pathEdges = new Set();
    if (!prev.has(b)) { if (this.h.onPath) this.h.onPath([], this.title[a], this.title[b]); return; }
    const path = [];
    for (let cur = b; cur !== -1; cur = prev.get(cur)) path.push(cur);
    path.reverse();
    path.forEach((n) => this.pathNodes.add(n));
    for (let k = 0; k < path.length - 1; k++) this.pathEdges.add(Math.min(path[k], path[k + 1]) + "-" + Math.max(path[k], path[k + 1]));
    if (this.h.onPath) this.h.onPath(path.map((n) => this.title[n]));
  }

  zoomAt(px, py, f) {
    const k0 = this.view.k, k1 = Math.max(0.1, Math.min(6, k0 * f));
    this.view.x = px - ((px - this.view.x) / k0) * k1;
    this.view.y = py - ((py - this.view.y) / k0) * k1;
    this.view.k = k1;
  }

  setHidden(set) { this.hidden = set; this.alpha = Math.max(this.alpha, 0.3); }

  counts() {
    const out = {};
    for (let i = 0; i < this.n; i++) out[this.type[i]] = (out[this.type[i]] || 0) + 1;
    return out;
  }

  topHubs(k) {
    return this.order.slice(0, k).map((i) => ({ id: this.id[i], title: this.title[i], deg: this.deg[i] }));
  }
}
