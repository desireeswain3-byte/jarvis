/* The orb drawing, shared by the main screen and every extra screen so he looks the same everywhere. */
function drawArmillary(ctx, W, t, amp, col) {
  const TAU = Math.PI * 2, cx = W / 2, cy = W / 2, S = W * 0.38, k = W / 220;
  const gy = t * 0.9, gx = 0.42 + 0.14 * Math.sin(t * 0.8);
  const cY = Math.cos(gy), sY = Math.sin(gy), cX = Math.cos(gx), sX = Math.sin(gx);
  const pulse = 1 + amp * 0.05 * Math.sin(t * 9);

  function project(x, y, z, spin) {
    if (spin) { const x2 = x * cY + z * sY; z = -x * sY + z * cY; x = x2; }
    const y2 = y * cX - z * sX, z2 = y * sX + z * cX;
    const f = 1 + z2 * 0.1;
    return [cx + x * S * f * pulse, cy + y2 * S * f * pulse, z2];
  }
  // Ring in its own plane: radius R, offset yoff along its axis, tilted about X, then turned about Y.
  function point(R, th, tilt, roll, yoff) {
    const x = R * Math.cos(th), z = R * Math.sin(th);
    const y1 = yoff * Math.cos(tilt) - z * Math.sin(tilt), z1 = yoff * Math.sin(tilt) + z * Math.cos(tilt);
    return [x * Math.cos(roll) + z1 * Math.sin(roll), y1, -x * Math.sin(roll) + z1 * Math.cos(roll)];
  }
  function ring(o) {
    const N = 48, spin = o.spin !== false;
    let prev = null;
    for (let i = 0; i <= N; i++) {
      const th = (i / N) * TAU;
      const p = point(o.R, th, o.tilt || 0, o.roll || 0, o.y || 0);
      const q = project(p[0], p[1], p[2], spin);
      if (prev) {
        const d = Math.max(0, Math.min(1, (((q[2] + prev[2]) / 2) + 1.2) / 2.4));
        ctx.globalAlpha = (o.a || 0.9) * (0.22 + 0.78 * d);
        ctx.lineWidth = o.w * k * (0.7 + 0.6 * d);
        ctx.beginPath(); ctx.moveTo(prev[0], prev[1]); ctx.lineTo(q[0], q[1]); ctx.stroke();
      }
      prev = q;
    }
    if (o.ticks) {
      for (let i = 0; i < o.ticks; i++) {
        const th = (i / o.ticks) * TAU, len = (i % 5 === 0 ? 0.075 : 0.04) * (o.tickDir || 1);
        const p = point(o.R, th, o.tilt || 0, o.roll || 0, o.y || 0), p2 = point(o.R - len, th, o.tilt || 0, o.roll || 0, o.y || 0);
        const a = project(p[0], p[1], p[2], spin), b = project(p2[0], p2[1], p2[2], spin);
        const d = Math.max(0, Math.min(1, (a[2] + 1.2) / 2.4));
        ctx.globalAlpha = 0.5 * (0.2 + 0.8 * d);
        ctx.lineWidth = 0.9 * k;
        ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
      }
    }
  }

  ctx.lineCap = 'butt';
  ctx.strokeStyle = col;
  const AX = 0.41, LAT = 1.16; // axial tilt, polar circle
  const R = 0.9;
  // horizon band stays flat while the sphere turns inside it
  ring({ R: 1.24, w: 2.6, a: 0.95, spin: false, ticks: 72 });
  ring({ R: 1.14, w: 1.1, a: 0.55, spin: false });
  // meridian with a graduated scale, and the two colures
  ring({ R: 1.0, w: 3, a: 0.95, tilt: Math.PI / 2, roll: 0, ticks: 60 });
  ring({ R: R, w: 2, a: 0.8, tilt: Math.PI / 2, roll: Math.PI / 2 });
  // equator and ecliptic
  ring({ R: R, w: 3, a: 0.95, tilt: AX });
  ring({ R: R, w: 2, a: 0.8, tilt: -AX, roll: 1.05 });
  // tropics and polar circles
  ring({ R: R * Math.cos(AX), y: R * Math.sin(AX), w: 1.2, a: 0.6, tilt: AX });
  ring({ R: R * Math.cos(AX), y: -R * Math.sin(AX), w: 1.2, a: 0.6, tilt: AX });
  ring({ R: R * Math.cos(LAT), y: R * Math.sin(LAT), w: 1.2, a: 0.55, tilt: AX });
  ring({ R: R * Math.cos(LAT), y: -R * Math.sin(LAT), w: 1.2, a: 0.55, tilt: AX });
  // inner ring for depth
  ring({ R: 0.68, w: 1.6, a: 0.7, tilt: -0.9, roll: 1.3 });

  ctx.shadowBlur = 0;
  ctx.globalAlpha = 1;
  const cr = S * (0.13 + amp * 0.05);
  const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, cr * 2.2);
  g.addColorStop(0, 'rgba(190,255,250,0.95)');
  g.addColorStop(0.35, 'rgba(34,211,197,0.65)');
  g.addColorStop(1, 'rgba(14,124,134,0)');
  ctx.fillStyle = g;
  ctx.beginPath(); ctx.arc(cx, cy, cr * 2.2, 0, TAU); ctx.fill();
}

window.JARVIS_COLORS = { idle: "#0f8f95", listening: "#38bdf8", thinking: "#facc15", speaking: "#2de2c8" };
window.jarvisRingSVG = function () {
  let svg = '<circle r="96" fill="none" stroke="rgba(34,211,197,.35)" stroke-width=".6"/><circle r="88" fill="none" stroke="rgba(34,211,197,.18)" stroke-width=".4" stroke-dasharray="1.5 3"/>';
  for (let i = 0; i < 90; i++) {
    const a = (i / 90) * Math.PI * 2, big = i % 5 === 0, r1 = 96, r2 = big ? 90 : 93;
    svg += '<line x1="' + (Math.cos(a) * r1).toFixed(2) + '" y1="' + (Math.sin(a) * r1).toFixed(2) + '" x2="' + (Math.cos(a) * r2).toFixed(2) + '" y2="' + (Math.sin(a) * r2).toFixed(2) + '" stroke="rgba(34,211,197,' + (big ? ".8" : ".4") + ')" stroke-width="' + (big ? ".8" : ".5") + '"/>';
  }
  return svg;
};
