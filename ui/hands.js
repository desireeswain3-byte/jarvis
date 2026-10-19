/* Hand tracking: webcam, MediaPipe hand landmarks, on-screen cursors.
   A pinch (thumb tip to index tip) is a grab. It presses, drags and releases like a mouse by
   dispatching real pointer events, so anything that works with a mouse works with a hand.
   Pinching with both hands on the graph background zooms it. Video stays in the browser;
   only the MediaPipe library and model are downloaded, from jsdelivr.net and storage.googleapis.com. */
const HANDS_CFG = {
  vision: 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14',
  model: 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task',
  pinchOn: 0.32,     // thumb to index distance, as a fraction of palm size, that starts a grab
  pinchOff: 0.5,     // and the larger distance that lets go (the gap stops flicker)
  smooth: 0.65,       // 0 to 1, higher follows the hand faster
  margin: 0.12,      // ignore the camera edges so every screen edge is reachable
  gain: 1 + ((window.UI_SCALE || 1) - 1) * 0.8, // reach: how far a small hand movement travels. Bigger screens get more
  pollMs: 33,
  clickTravel: 14,   // px of movement under which a pinch counts as a click
  lostMs: 250        // keep a grab alive this long if the hand drops out of view
};

let _grabZ = 40;
const HAND_POINTER_MIN = 100; // pointer ids above this come from hand tracking, real mice and touch are lower

/* Anything made grabbable can be dragged by mouse or hand. Uses the CSS translate property,
   so it never fights an element's own transform. */
function makeGrabbable(el, opts) {
  opts = opts || {};
  const SKIP = 'button,input,textarea,select,a,pre,label,.x';
  let ox = 0, oy = 0, d = null, suppress = false;
  el.addEventListener('pointerdown', (e) => {
    if (e.button || e.target.closest(SKIP)) return;
    if (opts.handle && !e.target.closest(opts.handle)) return;
    d = { x: e.clientX, y: e.clientY, ox, oy, moved: false };
    // No pointer capture yet: capturing on press would redirect the click away from the row or button
    // under the pointer. Capture starts only once the pointer has really moved (a drag).
  });
  el.addEventListener('pointermove', (e) => {
    if (!d) return;
    const dx = e.clientX - d.x, dy = e.clientY - d.y;
    if (!d.moved) {
      if (Math.abs(dx) + Math.abs(dy) < 6) return;
      d.moved = true;
      if (opts.float) { floatOut(el); ox = oy = d.ox = d.oy = 0; }
      el.style.zIndex = ++_grabZ;
      try { el.setPointerCapture(e.pointerId); } catch (err) { /* synthetic pointer from hand tracking */ }
    }
    ox = d.ox + dx;
    oy = d.oy + dy;
    el.style.translate = ox + 'px ' + oy + 'px';
  });
  el.addEventListener('pointerup', () => {
    if (d && d.moved) { suppress = true; setTimeout(() => { suppress = false; }, 0); }
    d = null;
  });
  el.addEventListener('pointercancel', () => { d = null; });
  el.addEventListener('click', (e) => { if (suppress) { e.stopPropagation(); e.preventDefault(); } }, true);
}

/* Lift an element out of a clipping container so it can be carried across the screen. */
function floatOut(el) {
  if (el._floated) return;
  const r = el.getBoundingClientRect();
  el.style.position = 'fixed';
  el.style.left = r.left + 'px';
  el.style.top = r.top + 'px';
  el.style.width = r.width + 'px';
  el.style.maxWidth = 'none';
  el.style.flex = 'none';
  el.style.translate = 'none';
  document.body.appendChild(el);
  el._floated = true;
}

const HandTracker = (function () {
  const C = HANDS_CFG;
  let video = null, landmarker = null, timer = null, stream = null;
  let running = false, loading = false, lastVideoTime = -1, prevPair = 0, nextPid = 101;
  let slots = [];
  let opts = {};

  function dist(a, b, vw, vh) { return Math.hypot((a.x - b.x) * vw, (a.y - b.y) * vh); }
  function toScreen(nx, ny) {
    const span = 1 - 2 * C.margin, g = C.gain || 1;
    const sx = Math.min(1, Math.max(0, 0.5 + ((1 - nx) - 0.5) * g / span)); // camera is mirrored
    const sy = Math.min(1, Math.max(0, 0.5 + (ny - 0.5) * g / span));
    return [sx * window.innerWidth, sy * window.innerHeight];
  }
  function isBackdrop(t) { return !!t && (t.id === 'graph' || t === document.body || t === document.documentElement); }

  function fire(type, s, target, down) {
    if (!target) return;
    target.dispatchEvent(new PointerEvent(type, {
      bubbles: true, cancelable: true, composed: true, clientX: s.x, clientY: s.y,
      pointerId: s.pid, pointerType: 'mouse', isPrimary: true, button: 0, buttons: down ? 1 : 0
    }));
  }
  function newSlot(d) {
    const cursor = document.createElement('div');
    cursor.className = 'hand-cursor';
    document.body.appendChild(cursor);
    return { pid: nextPid++, x: d.x, y: d.y, sx: d.x, sy: d.y, travel: 0, pinching: false, zoom: false, target: null, seen: 0, cursor };
  }
  function assign(dets) {
    const free = slots.slice(), pairs = [];
    dets.forEach((d) => {
      let best = null, bd = 1e9;
      free.forEach((s) => { const dd = Math.hypot(s.x - d.x, s.y - d.y); if (dd < bd) { bd = dd; best = s; } });
      if (best && bd < 600) { free.splice(free.indexOf(best), 1); pairs.push([best, d]); }
      else if (slots.length < 2) { const s = newSlot(d); slots.push(s); pairs.push([s, d]); }
    });
    return pairs;
  }
  function press(s) {
    s.pinching = true; s.zoom = false; s.travel = 0; s.sx = s.x; s.sy = s.y;
    s.target = document.elementFromPoint(s.x, s.y);
    s.cursor.classList.add('pinch');
    fire('pointerdown', s, s.target, true);
  }
  function release(s, click) {
    if (!s.pinching) return;
    s.pinching = false;
    s.cursor.classList.remove('pinch');
    if (!s.zoom && s.target) {
      fire('pointerup', s, s.target, false);
      if (click && s.travel < C.clickTravel) {
        const t = s.target;
        if (t.click) t.click();
        if (t.matches && t.matches('input,textarea')) t.focus();
      }
    }
    s.target = null; s.zoom = false;
  }

  /* dets: [{x, y, ratio}] in screen px. Split out from the camera loop so it can be tested. */
  function process(dets, now) {
    assign(dets).forEach(([s, d]) => {
      s.seen = now;
      const a = s.pinching ? C.smooth * 0.7 : C.smooth;
      s.x += (d.x - s.x) * a;
      s.y += (d.y - s.y) * a;
      s.cursor.style.transform = 'translate(' + s.x + 'px,' + s.y + 'px)';
      if (!s.pinching && d.ratio < C.pinchOn) press(s);
      else if (s.pinching && d.ratio > C.pinchOff) release(s, true);
      else if (s.pinching) {
        if (!s.zoom) {
          s.travel = Math.max(s.travel, Math.hypot(s.x - s.sx, s.y - s.sy));
          fire('pointermove', s, s.target, true);
        }
      } else fire('pointermove', s, document.elementFromPoint(s.x, s.y), false);
    });

    // both hands pinching the graph background: zoom by how far apart they are
    const pin = slots.filter((s) => s.pinching);
    if (pin.length === 2 && opts.onZoom && pin.every((s) => s.zoom || isBackdrop(s.target))) {
      pin.forEach((s) => { if (!s.zoom) { fire('pointercancel', s, s.target, false); s.zoom = true; } });
      const dd = Math.hypot(pin[0].x - pin[1].x, pin[0].y - pin[1].y);
      if (prevPair > 0 && dd > 0) opts.onZoom((pin[0].x + pin[1].x) / 2, (pin[0].y + pin[1].y) / 2, dd / prevPair);
      prevPair = dd;
    } else prevPair = 0;

    slots = slots.filter((s) => {
      if (now - s.seen <= C.lostMs) return true;
      release(s, false);
      s.cursor.remove();
      return false;
    });
  }

  function frame() {
    if (!running || !video || video.readyState < 2 || video.currentTime === lastVideoTime) return;
    lastVideoTime = video.currentTime;
    const now = performance.now();
    let res;
    dbg.frames++; dbg.size = video.videoWidth + 'x' + video.videoHeight;
    try {
      // draw the frame to a canvas first: Safari can hand MediaPipe an empty picture when given the video element directly
      if (isSafari) {
        if (!cv) { cv = document.createElement('canvas'); cx = cv.getContext('2d'); }
        if (cv.width !== video.videoWidth || cv.height !== video.videoHeight) { cv.width = video.videoWidth; cv.height = video.videoHeight; }
        cx.drawImage(video, 0, 0, cv.width, cv.height);
      }
      res = landmarker.detectForVideo(isSafari ? cv : video, now);
    } catch (e) { dbg.err = String(e && e.message ? e.message : e); return; }
    if (res && res.landmarks && res.landmarks.length) dbg.seen++;
    const vw = video.videoWidth, vh = video.videoHeight;
    const dets = (res.landmarks || []).map((lm) => {
      const palm = dist(lm[0], lm[9], vw, vh) || 1;
      const p = toScreen((lm[4].x + lm[8].x) / 2, (lm[4].y + lm[8].y) / 2);
      return { x: p[0], y: p[1], ratio: dist(lm[4], lm[8], vw, vh) / palm };
    });
    process(dets, now);
  }

  function cameraError(e) {
    if (e && (e.name === 'NotAllowedError' || e.name === 'SecurityError')) return ['Camera blocked.', 'Allow the camera for this page in the browser site settings, then press Hands again.'];
    if (e && e.name === 'NotFoundError') return ['No camera found.', 'Plug one in or pick a camera in system settings.'];
    if (e && e.name === 'NotReadableError') return ['The camera is busy.', 'Another app is using it. Close that app and try again.'];
    return ['Could not open the camera.', String(e && e.message ? e.message : e)];
  }
  let cv = null, cx = null;
  const dbg = { size: '', frames: 0, seen: 0, err: '', delegate: '' };
  const isSafari = /^((?!chrome|android|crios|fxios).)*safari/i.test(navigator.userAgent);
  async function makeLandmarker(mod, files, delegate) {
    return mod.HandLandmarker.createFromOptions(files, {
      baseOptions: { modelAssetPath: C.model, delegate },
      runningMode: 'VIDEO', numHands: 2,
      minHandDetectionConfidence: 0.4, minHandPresenceConfidence: 0.4, minTrackingConfidence: 0.4
    });
  }

  async function start(o) {
    opts = o || {};
    if (running || loading) return false;
    const err = (t, d) => { if (opts.onError) opts.onError(t, d); };
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      err('Camera not available.', 'This browser cannot open a camera on this page. Use localhost or https in a current browser.');
      return false;
    }
    loading = true;
    if (opts.onStatus) opts.onStatus('Loading hand tracking', false);
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480, frameRate: { ideal: 30 }, facingMode: 'user' } });
    } catch (e) {
      loading = false;
      const t = cameraError(e);
      err(t[0], t[1]);
      if (opts.onStatus) opts.onStatus('', false);
      return false;
    }
    try {
      const mod = await import(C.vision + '/vision_bundle.mjs');
      const files = await mod.FilesetResolver.forVisionTasks(C.vision + '/wasm');
      // Safari's GPU path often returns nothing, so Safari uses the CPU path, which is slower but reliable
      const order = isSafari ? ['CPU', 'GPU'] : ['GPU', 'CPU'];
      try { landmarker = await makeLandmarker(mod, files, order[0]); dbg.delegate = order[0]; }
      catch (e) { landmarker = await makeLandmarker(mod, files, order[1]); dbg.delegate = order[1]; }
    } catch (e) {
      loading = false;
      stopStream();
      err('Hand tracking could not load.', 'It needs internet to fetch the MediaPipe library and model from jsdelivr.net and storage.googleapis.com. ' + (e && e.message ? e.message : e));
      if (opts.onStatus) opts.onStatus('', false);
      return false;
    }
    video = document.getElementById('handcam');
    video.srcObject = stream;
    try { await video.play(); } catch (e) { /* autoplay of a muted camera feed can lag, frames still arrive */ }
    running = true; loading = false; lastVideoTime = -1; dbg.frames = 0; dbg.seen = 0; dbg.err = '';
    timer = setInterval(frame, C.pollMs); // setInterval, so a background tab keeps tracking
    if (opts.onStatus) opts.onStatus('Hands on. Pinch to grab.', true);
    return true;
  }
  function stopStream() {
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }
  function stop() {
    clearInterval(timer);
    timer = null;
    slots.forEach((s) => { release(s, false); s.cursor.remove(); });
    slots = []; prevPair = 0;
    stopStream();
    if (landmarker) { try { landmarker.close(); } catch (e) { /* ignore */ } landmarker = null; }
    if (video) video.srcObject = null;
    running = false; loading = false;
    if (opts.onStatus) opts.onStatus('Hands off', false);
  }

  return { start, stop, debug: () => dbg, isOn: () => running || loading, _process: process, _slots: () => slots, _setOpts: (o) => { opts = o || {}; }, _toScreen: toScreen };
})();
